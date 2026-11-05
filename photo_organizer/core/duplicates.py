"""Detecção de duplicadas potenciais (PLANO.md §1, decisões 8 e 9).

Fotos: hash perceptual (pHash, 64 bits) — pega cópias idênticas e versões
redimensionadas ou reexportadas. Duas fotos são duplicadas quando:

- são do mesmo tipo (JPEG com JPEG, RAW com RAW: o par RAW+JPEG da câmera nunca é
  duplicada);
- os hashes diferem em até ``threshold`` bits;
- foram tiradas no mesmo instante (mesmo segundo e, quando as duas têm, mesmos
  milissegundos) — isso evita marcar fotos de rajada. Uma foto sem data (ex.: cópia do
  WhatsApp, que apaga o EXIF) se liga só à foto datada mais parecida.

RAW é comparado pela imagem embutida (miniatura ou prévia), extraída pelo ExifTool.
Vídeos: só cópias idênticas (mesmo tamanho e mesmo conteúdo).

Em cada grupo fica o arquivo mais antigo (data de modificação); os demais são duplicadas.
"""

from __future__ import annotations

import base64
from collections import defaultdict
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
from photo_organizer.core.metadata import MetadataReader
from photo_organizer.core.scanner import FileKind, MediaFile, path_key

THRESHOLD = 6
PHASH = "phash"
CONTENT = "blake2b"
# Imagens embutidas no RAW, da menor para a maior: basta uma para o pHash.
RAW_PREVIEW_TAGS = ("ThumbnailImage", "PreviewImage", "JpgFromRaw")
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
    photos = [(m, d) for m, d in files if m.kind is not FileKind.VIDEO]
    hashes = image_hashes([m for m, _ in photos], reader, cache, progress)
    entries = [_Entry(m, d.value, hashes[m.path]) for m, d in photos if m.path in hashes]

    groups: list[list[MediaFile]] = []
    for kind in (FileKind.JPEG, FileKind.RAW):
        same_kind = [e for e in entries if e.media.kind is kind]
        groups += [[same_kind[i].media for i in g] for g in group_similar(same_kind, threshold)]
    groups += _identical_videos([m for m, _ in files if m.kind is FileKind.VIDEO], cache)
    dated = {m.path for m, d in files if d.value is not None}
    return [_keep_best(g, dated) for g in groups]


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
        new.update(_hash_raw_previews(chunk, reader))
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
    try:
        data = path.read_bytes()  # np.fromfile/imread falham com acentos no Windows
    except OSError:
        return None
    return phash_bytes(data, reduced=len(data) > _LARGE_JPEG)


def _hash_raw_previews(paths: list[Path], reader: MetadataReader) -> dict[Path, int]:
    out: dict[Path, int] = {}
    missing = list(paths)
    for tag in RAW_PREVIEW_TAGS:  # uma tag por vez: não transfere prévias grandes à toa
        if not missing:
            break
        by_path = {path_key(r["SourceFile"]): r for r in reader.read(missing, [tag], ["-b"])}
        still = []
        for p in missing:
            h = _decode_b64_hash(_any_tag(by_path.get(path_key(p), {}), tag))
            if h is None:
                still.append(p)
            else:
                out[p] = h
        missing = still
    return out


def _any_tag(meta: dict, tag: str) -> object:
    return next((v for k, v in meta.items() if k.endswith(f":{tag}")), None)


def _decode_b64_hash(value: object) -> int | None:
    if not isinstance(value, str) or not value.startswith("base64:"):
        return None
    data = base64.b64decode(value[7:])
    return phash_bytes(data, reduced=len(data) > _LARGE_JPEG)


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
