"""Detecção de duplicadas potenciais (PLANO.md §1, decisões 8 e 9).

Fotos: hash perceptual (pHash, 64 bits) — pega cópias idênticas e versões
redimensionadas ou reexportadas. Duas fotos são duplicadas quando:

- são do mesmo tipo (JPEG ou HEIC entre si, RAW com RAW: o par RAW+JPEG da câmera nunca é
  duplicada);
- os hashes diferem em até ``threshold`` bits;
- foram tiradas no mesmo instante (mesmo segundo e, quando as duas têm, mesmos
  milissegundos) — isso evita marcar fotos de rajada. Uma foto sem data (ex.: cópia do
  WhatsApp, que apaga o EXIF) se liga só à foto datada mais parecida.

RAW é comparado pela imagem embutida (miniatura ou prévia), extraída pelo ExifTool.
Vídeos: só cópias idênticas (mesmo tamanho e mesmo conteúdo).

Em cada grupo fica o original (com data, depois o maior arquivo); os demais são duplicadas.

Destino: uma foto da origem que já existe no destino (mesmos critérios) vira um
``DestMatch``. A sugestão é ficar com a de maior resolução e, empatando, a maior.
"""

from __future__ import annotations

import base64
from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from photo_organizer.core.cache import HashCache
from photo_organizer.core.dates import FileDate
from photo_organizer.core.executor import hash_file
from photo_organizer.core.images import _ROTATIONS, heic_image, is_heic
from photo_organizer.core.metadata import MetadataReader
from photo_organizer.core.planner import DestAction
from photo_organizer.core.scanner import FileKind, MediaFile, path_key

THRESHOLD = 6
PHASH = "phash"
CONTENT = "blake2b"
# Imagens embutidas no RAW, da menor para a maior: basta uma para o pHash.
RAW_PREVIEW_TAGS = ("ThumbnailImage", "PreviewImage", "JpgFromRaw")
# JPEG: a miniatura do EXIF (~10 KB) dá o mesmo pHash da foto inteira (vários MB pela rede).
JPEG_PREVIEW_TAGS = ("ThumbnailImage",)
_SIZE_TAG = "Composite:ImageSize"
_LARGE_JPEG = 300_000  # bytes; acima disso decodifica em 1/4 da resolução (bem mais rápido)

Progress = Callable[[int, int], None]


@dataclass(frozen=True, slots=True)
class DuplicateGroup:
    keep: MediaFile
    duplicates: tuple[MediaFile, ...]


@dataclass(frozen=True, slots=True)
class _Entry:
    media: MediaFile
    date: datetime | None
    hash: int


def find_duplicates(
    files: Sequence[tuple[MediaFile, FileDate]],
    reader: MetadataReader,
    cache: HashCache | None = None,
    threshold: int = THRESHOLD,
    progress: Progress | None = None,
) -> list[DuplicateGroup]:
    dated = {m.path for m, d in files if d.value is not None}
    return [_keep_best(g, dated) for g in _similar(files, reader, cache, threshold, progress)]


def _similar(
    files: Sequence[tuple[MediaFile, FileDate]],
    reader: MetadataReader,
    cache: HashCache | None,
    threshold: int,
    progress: Progress | None,
) -> list[list[MediaFile]]:
    photos = [(m, d) for m, d in files if m.kind is not FileKind.VIDEO]
    hashes = image_hashes(_comparable(photos), reader, cache, progress)
    entries = [_Entry(m, d.value, hashes[m.path]) for m, d in photos if m.path in hashes]

    groups: list[list[MediaFile]] = []
    for kind in (FileKind.JPEG, FileKind.RAW):
        same_kind = [e for e in entries if e.media.kind is kind]
        groups += [[same_kind[i].media for i in g] for g in group_similar(same_kind, threshold)]
    groups += _identical_videos([m for m, _ in files if m.kind is FileKind.VIDEO], cache)
    return groups


def _comparable(photos: Sequence[tuple[MediaFile, FileDate]]) -> list[MediaFile]:
    """Só as fotos que têm com quem comparar: as datadas que dividem o segundo com outra do
    mesmo tipo e, se o tipo tiver foto sem data, todas (a sem data procura a datada mais
    parecida). Numa biblioteca sem fotos sem data, quase nenhuma foto precisa ser lida."""
    out: list[MediaFile] = []
    for kind in (FileKind.JPEG, FileKind.RAW):
        same = [(m, d.value) for m, d in photos if m.kind is kind]
        if any(v is None for _, v in same):
            out += [m for m, _ in same]
            continue
        per_second = Counter(v.replace(microsecond=0) for _, v in same if v)
        out += [m for m, v in same if v and per_second[v.replace(microsecond=0)] > 1]
    return out


@dataclass(frozen=True, slots=True)
class DestMatch:
    source: MediaFile
    existing: MediaFile  # a que já está no destino
    suggested: DestAction
    pixels: tuple[int, int] = (0, 0)  # resolução da origem e da do destino


def find_in_destination(
    source: Sequence[tuple[MediaFile, FileDate]],
    dest: Sequence[tuple[MediaFile, FileDate]],
    reader: MetadataReader,
    cache: HashCache | None = None,
    threshold: int = THRESHOLD,
    progress: Progress | None = None,
) -> tuple[list[DuplicateGroup], list[DestMatch]]:
    """Duplicadas da origem entre si e fotos da origem que já existem no destino.

    Só entram na comparação os arquivos do destino que podem bater: fotos tiradas no
    mesmo segundo de uma foto da origem e vídeos do mesmo tamanho. Assim um destino
    grande não precisa ter todas as fotos lidas e comparadas.
    """
    # shortcut: uma foto da origem sem data só acha no destino as candidatas acima; achar
    # cópia sem data em qualquer foto do destino exigiria o pHash do destino inteiro.
    seconds = {d.value.replace(microsecond=0) for _, d in source if d.value is not None}
    sizes = {_size(m) for m, _ in source if m.kind is FileKind.VIDEO}
    candidates = [
        (m, d)
        for m, d in dest
        if (m.kind is FileKind.VIDEO and _size(m) in sizes - {None})
        or (m.kind is not FileKind.VIDEO and d.value and d.value.replace(microsecond=0) in seconds)
    ]
    in_dest = {m.path for m, _ in candidates}
    files = [*source, *candidates]
    dated = {m.path for m, d in files if d.value is not None}
    groups: list[DuplicateGroup] = []
    pairs: list[tuple[MediaFile, MediaFile]] = []
    for g in _similar(files, reader, cache, threshold, progress):
        existing = [m for m in g if m.path in in_dest]
        ours = [m for m in g if m.path not in in_dest]
        if not existing:
            groups.append(_keep_best(g, dated))
        elif ours:
            best = _keep_best(existing, dated).keep if len(existing) > 1 else existing[0]
            pairs += [(m, best) for m in ours]
    return groups, _suggest(pairs, reader)


def _suggest(pairs: list[tuple[MediaFile, MediaFile]], reader: MetadataReader) -> list[DestMatch]:
    """Fica a de maior resolução; empatando, o maior arquivo; empatando, a do destino.
    Só uma foto da origem pode substituir cada foto do destino: a melhor delas."""
    paths = list({m.path: m for pair in pairs for m in pair})
    pixels = _pixels(reader, paths) if paths else {}

    def quality(m: MediaFile) -> tuple[int, int]:
        return pixels.get(path_key(m.path), 0), _size(m) or 0

    matches: list[DestMatch] = []
    replaced: set[Path] = set()
    for src, existing in sorted(pairs, key=lambda p: quality(p[0]), reverse=True):
        better = quality(src) > quality(existing) and existing.path not in replaced
        if better:
            replaced.add(existing.path)
        action = DestAction.REPLACE if better else DestAction.KEEP
        matches.append(DestMatch(src, existing, action, (quality(src)[0], quality(existing)[0])))
    order = {m.path: i for i, (m, _) in enumerate(pairs)}
    return sorted(matches, key=lambda d: order[d.source.path])


def _pixels(reader: MetadataReader, paths: list[Path]) -> dict[str, int]:
    out: dict[str, int] = {}
    results = (
        r for i in range(0, len(paths), 500) for r in reader.read(paths[i : i + 500], [_SIZE_TAG])
    )
    for r in results:
        value = str(r.get(_SIZE_TAG, ""))  # com -n: "6000 4000"
        parts = value.replace("x", " ").split()
        if len(parts) == 2 and all(p.isdigit() for p in parts):
            out[path_key(r["SourceFile"])] = int(parts[0]) * int(parts[1])
    return out


def _size(m: MediaFile) -> int | None:
    try:
        return m.path.stat().st_size
    except OSError:
        return None


def duplicate_paths(groups: Sequence[DuplicateGroup]) -> set[Path]:
    return {m.path for g in groups for m in g.duplicates}


# --- Hash perceptual ------------------------------------------------------------------


def image_hashes(
    files: Sequence[MediaFile],
    reader: MetadataReader,
    cache: HashCache | None = None,
    progress: Progress | None = None,
) -> dict[Path, int]:
    """pHash de cada foto; arquivos que não puderam ser lidos ficam de fora."""
    result: dict[Path, int] = {}
    pending: list[MediaFile] = []
    for f in files:
        cached = cache.get(f.path, PHASH) if cache else None
        if cached is not None:
            result[f.path] = int.from_bytes(cached, "big")
        else:
            pending.append(f)
    done, total = len(result), len(files)
    if progress:
        progress(done, total)

    new: dict[Path, int] = {}
    jpegs = [f.path for f in pending if f.kind is FileKind.JPEG]
    with_thumb = [p for p in jpegs if not is_heic(p)]
    for start in range(0, len(with_thumb), 100):
        chunk = with_thumb[start : start + 100]
        found = _hash_previews(chunk, reader, JPEG_PREVIEW_TAGS, upright=True)
        new.update(found)
        done += len(found)
        if progress:
            progress(done, total)
    jpegs = [p for p in jpegs if p not in new]  # sem miniatura (ex.: WhatsApp) ou HEIC
    with ThreadPoolExecutor() as pool:  # o OpenCV libera o GIL ao decodificar
        for path, h in zip(jpegs, pool.map(_hash_jpeg_file, jpegs), strict=True):
            done += 1
            if h is not None:
                new[path] = h
            if progress and done % 50 == 0:
                progress(done, total)
    raws = [f.path for f in pending if f.kind is FileKind.RAW]
    for start in range(0, len(raws), 100):
        chunk = raws[start : start + 100]
        new.update(_hash_previews(chunk, reader))
        done += len(chunk)
        if progress:
            progress(done, total)

    if cache and new:
        cache.put_many(PHASH, ((p, h.to_bytes(8, "big")) for p, h in new.items()))
    result.update(new)
    if progress:
        progress(total, total)
    return result


def phash_bytes(data: bytes, reduced: bool = False) -> int | None:
    """pHash de uma imagem codificada (JPEG etc.), ou ``None`` se não decodificar."""
    flag = cv2.IMREAD_REDUCED_GRAYSCALE_4 if reduced else cv2.IMREAD_GRAYSCALE
    img = cv2.imdecode(np.frombuffer(data, np.uint8), flag)
    if img is None or img.size == 0:
        return None
    return int.from_bytes(phash(_trim_dark_borders(img)).tobytes(), "big")


def phash(gray: np.ndarray) -> np.ndarray:
    """pHash idêntico ao ``cv2.img_hash.pHash`` (8 bytes), sem precisar do OpenCV contrib,
    que deixaria o .exe ~10 MB maior. Mudar o cálculo invalidaria os hashes em cache."""
    small = cv2.resize(gray, (32, 32), interpolation=cv2.INTER_LINEAR_EXACT)
    low = cv2.dct(small.astype(np.float32))[:8, :8].copy()
    low[0, 0] = 0
    return np.packbits(low > low.mean(), axis=1, bitorder="little").reshape(-1)


def _hash_jpeg_file(path: Path) -> int | None:
    if is_heic(path):
        img = heic_image(path, 256)
        if img is None:
            return None
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return int.from_bytes(phash(_trim_dark_borders(gray)).tobytes(), "big")
    try:
        data = path.read_bytes()  # np.fromfile/imread falham com acentos no Windows
    except OSError:
        return None
    return phash_bytes(data, reduced=len(data) > _LARGE_JPEG)


def _hash_previews(
    paths: list[Path],
    reader: MetadataReader,
    tags: Sequence[str] = RAW_PREVIEW_TAGS,
    upright: bool = False,
) -> dict[Path, int]:
    """pHash da imagem embutida (lida pelo ExifTool, sem ler o arquivo inteiro).

    ``upright``: gira pela tag Orientation. A miniatura de uma foto em pé fica deitada, mas
    o OpenCV desvira o JPEG inteiro; sem girar, ela não bateria com a cópia do WhatsApp nem
    com os hashes já no cache. RAW não gira: só compara com RAW, todos deitados.
    """
    out: dict[Path, int] = {}
    missing = list(paths)
    for tag in tags:  # uma tag por vez: não transfere prévias grandes à toa
        if not missing:
            break
        fields = [tag, "EXIF:Orientation"] if upright else [tag]
        by_path = {path_key(r["SourceFile"]): r for r in reader.read(missing, fields, ["-b"])}
        still = []
        for p in missing:
            meta = by_path.get(path_key(p), {})
            rotation = _ROTATIONS.get(meta.get("EXIF:Orientation")) if upright else None
            h = _decode_b64_hash(_any_tag(meta, tag), rotation)
            if h is None:
                still.append(p)
            else:
                out[p] = h
        missing = still
    return out


def _any_tag(meta: dict, tag: str) -> object:
    return next((v for k, v in meta.items() if k.endswith(f":{tag}")), None)


def _decode_b64_hash(value: object, rotation: int | None = None) -> int | None:
    if not isinstance(value, str) or not value.startswith("base64:"):
        return None
    data = base64.b64decode(value[7:])
    if rotation is None:
        return phash_bytes(data, reduced=len(data) > _LARGE_JPEG)
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_GRAYSCALE)
    if img is None or img.size == 0:
        return None
    return int.from_bytes(phash(_trim_dark_borders(cv2.rotate(img, rotation))).tobytes(), "big")


def _trim_dark_borders(img: np.ndarray) -> np.ndarray:
    """Corta faixas pretas (ex.: miniatura 4:3 da Sony com foto 3:2) para comparar a mesma
    área da foto em imagens com e sem tarja."""
    rows = np.flatnonzero(img.mean(axis=1) > 12)
    cols = np.flatnonzero(img.mean(axis=0) > 12)
    if rows.size == 0 or cols.size == 0:
        return img
    crop = img[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]
    return crop if min(crop.shape) >= 8 else img


# --- Agrupamento ----------------------------------------------------------------------


def group_similar(entries: Sequence[_Entry], threshold: int = THRESHOLD) -> list[list[int]]:
    """Índices dos grupos de duplicadas (2 ou mais itens) entre ``entries``."""
    n = len(entries)
    if n < 2:
        return []
    hashes = np.array([e.hash for e in entries], dtype=np.uint64)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    buckets: dict[datetime, list[int]] = defaultdict(list)
    undated: list[int] = []
    for i, e in enumerate(entries):
        if e.date is None:
            undated.append(i)
        else:
            buckets[e.date.replace(microsecond=0)].append(i)

    # Datadas: só compara fotos do mesmo segundo.
    for idxs in buckets.values():
        for pos, a in enumerate(idxs[:-1]):
            rest = np.array(idxs[pos + 1 :])
            close = rest[np.bitwise_count(hashes[rest] ^ hashes[a]) <= threshold]
            for b in close:
                if _same_moment(entries[a].date, entries[int(b)].date):
                    union(a, int(b))

    # Sem data: liga à datada mais parecida. As que não acharam datada se ligam entre si;
    # ligar também as que acharam juntaria fotos de momentos diferentes (rajada A + cópia
    # de A ~ cópia de C + rajada C viraria um grupo só).
    dated = np.array([i for i in range(n) if entries[i].date is not None], dtype=np.intp)
    alone: list[int] = []
    for u in undated:
        if dated.size:
            dist = np.bitwise_count(hashes[dated] ^ hashes[u])
            j = int(dist.argmin())
            if dist[j] <= threshold:
                union(u, int(dated[j]))
                continue
        alone.append(u)
    rest = np.array(alone, dtype=np.intp)
    for k, u in enumerate(alone):
        later = rest[k + 1 :]
        if later.size:
            for b in later[np.bitwise_count(hashes[later] ^ hashes[u]) <= threshold]:
                union(u, int(b))

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    return [g for g in groups.values() if len(g) > 1]


def _same_moment(a: datetime | None, b: datetime | None) -> bool:
    if a is None or b is None:
        return True
    if a.replace(microsecond=0) != b.replace(microsecond=0):
        return False
    return a.microsecond == b.microsecond or 0 in (a.microsecond, b.microsecond)


# --- Vídeos: só cópias idênticas ------------------------------------------------------


def _identical_videos(
    videos: Sequence[MediaFile], cache: HashCache | None
) -> list[list[MediaFile]]:
    by_size: dict[int, list[MediaFile]] = defaultdict(list)
    for v in videos:
        try:
            by_size[v.path.stat().st_size].append(v)
        except OSError:
            continue
    groups: list[list[MediaFile]] = []
    for same_size in by_size.values():
        if len(same_size) < 2:
            continue
        by_digest: dict[bytes, list[MediaFile]] = defaultdict(list)
        new = []
        for v in same_size:
            digest = cache.get(v.path, CONTENT) if cache else None
            if digest is None:
                try:
                    digest = hash_file(v.path)
                except OSError:
                    continue
                new.append((v.path, digest))
            by_digest[digest].append(v)
        if cache and new:
            cache.put_many(CONTENT, new)
        groups += [g for g in by_digest.values() if len(g) > 1]
    return groups


def _keep_best(group: list[MediaFile], dated: set[Path]) -> DuplicateGroup:
    """Fica o original: com data (a cópia do WhatsApp perde o EXIF), depois o maior
    arquivo (mais resolução), depois o mais antigo."""

    def rank(m: MediaFile) -> tuple[bool, int, float, str]:
        try:
            st = m.path.stat()
            size, mtime = st.st_size, st.st_mtime
        except OSError:
            size, mtime = 0, float("inf")
        return m.path not in dated, -size, mtime, str(m.path).lower()

    ordered = sorted(group, key=rank)
    return DuplicateGroup(ordered[0], tuple(ordered[1:]))
