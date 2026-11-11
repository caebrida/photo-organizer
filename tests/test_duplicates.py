import os
import shutil
import time
from datetime import datetime, timedelta
from pathlib import Path

import cv2
import numpy as np
import pytest
from conftest import SAMPLES, exiftool, make_mp4, requires_exiftool

from photo_organizer.core import duplicates
from photo_organizer.core.cache import HashCache
from photo_organizer.core.dates import NO_DATE, FileDate, read_dates
from photo_organizer.core.duplicates import (
    _Entry,
    duplicate_paths,
    find_duplicates,
    group_similar,
)
from photo_organizer.core.metadata import MetadataReader
from photo_organizer.core.scanner import FileKind, MediaFile, scan


def photo(seed: int, w: int = 1200, h: int = 800) -> np.ndarray:
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0:h, 0:w]
    img = np.zeros((h, w, 3), np.uint8)
    for c in range(3):
        img[..., c] = (xx * rng.uniform(0.05, 0.3) + yy * rng.uniform(0.05, 0.3)) % 255
    for _ in range(25):
        center = (int(rng.integers(w)), int(rng.integers(h)))
        color = tuple(int(v) for v in rng.integers(0, 255, 3))
        cv2.circle(img, center, int(rng.integers(20, 200)), color, -1)
    return img


def save(
    path: Path,
    img: np.ndarray,
    quality: int = 92,
    date: str | None = None,
    subsec: str | None = None,
    mtime: int | None = None,
) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tobytes())
    if date:
        args = [f"-EXIF:DateTimeOriginal={date}"]
        if subsec:
            args.append(f"-EXIF:SubSecTimeOriginal={subsec}")
        exiftool(*args, path)
    if mtime:
        os.utime(path, (mtime, mtime))
    return path


def detect(root: Path, cache: HashCache | None = None):
    with MetadataReader() as reader:
        files = list(read_dates(reader, scan(root)))
        return find_duplicates(files, reader, cache)


def names(groups) -> set[tuple[str, frozenset[str]]]:
    return {(g.keep.path.name, frozenset(m.path.name for m in g.duplicates)) for g in groups}


@requires_exiftool
def test_finds_copies_resized_and_stripped_versions(tmp_path):
    base = photo(1)
    d = "2025:04:20 07:16:07"
    save(tmp_path / "a" / "original.jpg", base, date=d, subsec="887", mtime=1_600_000_000)
    small = cv2.resize(base, (600, 400), interpolation=cv2.INTER_AREA)
    save(tmp_path / "b" / "exportada.jpg", small, 70, d, "887", mtime=1_700_000_000)
    whats = cv2.resize(base, (800, 533), interpolation=cv2.INTER_AREA)
    save(tmp_path / "c" / "whatsapp.jpg", whats, 60, mtime=1_710_000_000)  # sem EXIF
    # Mesma cena, mesmo segundo, outros milissegundos: rajada, não duplicada.
    save(tmp_path / "rajada.jpg", base, 90, d, "912", mtime=1_600_000_001)
    # Outra foto no mesmo instante exato: conteúdo diferente, não duplicada.
    save(tmp_path / "outra.jpg", photo(2), date=d, subsec="887")

    groups = detect(tmp_path)
    assert names(groups) == {("original.jpg", frozenset({"exportada.jpg", "whatsapp.jpg"}))}
    assert {p.name for p in duplicate_paths(groups)} == {"exportada.jpg", "whatsapp.jpg"}


@requires_exiftool
def test_keeps_the_dated_original_even_if_the_copy_is_older(tmp_path):
    base = photo(5)
    save(tmp_path / "camera.jpg", base, date="2025:04:20 07:16:07", mtime=1_700_000_000)
    whats = cv2.resize(base, (800, 533), interpolation=cv2.INTER_AREA)
    save(tmp_path / "whatsapp.jpg", whats, 60, mtime=1_600_000_000)  # sem EXIF, mais antiga
    assert names(detect(tmp_path)) == {("camera.jpg", frozenset({"whatsapp.jpg"}))}


def test_undated_copies_do_not_join_photos_from_different_moments():
    def entry(name, second, bits):
        date = datetime(2026, 1, 1, 10, 0, second) if second is not None else None
        return _Entry(MediaFile(Path(name), FileKind.JPEG), date, bits)

    entries = [
        entry("rajada1.jpg", 1, 0),  # 10:00:01
        entry("rajada2.jpg", 2, 0b111111111),  # 10:00:02, 9 bits diferente
        entry("copia1.jpg", None, 0b000000111),  # mais perto da rajada1
        entry("copia2.jpg", None, 0b000111111),  # mais perto da rajada2; 3 bits da copia1
    ]
    assert sorted(group_similar(entries)) == [[0, 2], [1, 3]]


@requires_exiftool
def test_different_dates_are_never_duplicates(tmp_path):
    save(tmp_path / "um.jpg", photo(3), date="2025:01:01 10:00:00")
    save(tmp_path / "dois.jpg", photo(3), date="2025:01:01 10:00:01")
    assert detect(tmp_path) == []


@requires_exiftool
def test_identical_videos_only(tmp_path):
    when = datetime(2025, 7, 13, 6, 0).astimezone()
    original = make_mp4(tmp_path / "C0001.MP4", when)
    os.utime(original, (1_600_000_000, 1_600_000_000))
    copy = tmp_path / "copia" / "C0001.MP4"
    copy.parent.mkdir()
    shutil.copy2(original, copy)
    os.utime(copy, (1_800_000_000, 1_800_000_000))
    make_mp4(tmp_path / "C0002.MP4", when + timedelta(seconds=5))  # mesmo tamanho, outro conteúdo

    [group] = detect(tmp_path)
    assert group.keep.path == original
    assert [m.path for m in group.duplicates] == [copy]


@requires_exiftool
def test_cache_avoids_recomputing(tmp_path, monkeypatch):
    src = tmp_path / "fotos"
    save(src / "x.jpg", photo(4), date="2025:01:01 10:00:00", mtime=1_600_000_000)
    save(src / "y.jpg", photo(4), 80, "2025:01:01 10:00:00", mtime=1_700_000_000)
    db = tmp_path / "cache" / "hashes.sqlite"
    with HashCache(db) as cache:
        first = names(detect(src, cache))

    def boom(*args):
        raise AssertionError("não deveria recalcular")

    monkeypatch.setattr(duplicates, "_hash_jpeg_file", boom)
    with HashCache(db) as cache:
        assert names(detect(src, cache)) == first == {("x.jpg", frozenset({"y.jpg"}))}


def test_group_similar_50k_hashes_in_seconds():
    rng = np.random.default_rng(0)
    n = 50_000
    hashes = rng.integers(0, 2**63, n, dtype=np.uint64) | (
        rng.integers(0, 2, n, dtype=np.uint64) << np.uint64(63)
    )
    start = datetime(2020, 1, 1)
    dates = [start + timedelta(seconds=int(s)) for s in rng.integers(0, 3 * 10**7, n)]
    for i in range(0, n, 10):  # 10% sem data
        dates[i] = None
    media = MediaFile(Path("x.jpg"), FileKind.JPEG)
    entries = [_Entry(media, d, int(h)) for d, h in zip(dates, hashes, strict=True)]
    # Duplicadas plantadas: cópia com 3 bits trocados e mesma data; e uma sem data.
    entries.append(_Entry(media, entries[1].date, entries[1].hash ^ 0b10101))
    entries.append(_Entry(media, None, entries[2].hash ^ 0b11))

    t = time.perf_counter()
    groups = group_similar(entries)
    elapsed = time.perf_counter() - t
    assert sorted(sorted(g) for g in groups) == [[1, n], [2, n + 1]]
    assert elapsed < 15, f"{elapsed:.1f}s"


# --- Amostras reais -------------------------------------------------------------------

raw_samples = sorted(SAMPLES.glob("*.ARW")) if SAMPLES.is_dir() else []


@requires_exiftool
@pytest.mark.skipif(not raw_samples, reason="sem ARW em tests/samples")
def test_real_samples(tmp_path):
    for f in SAMPLES.iterdir():
        shutil.copy2(f, tmp_path / f.name)
    assert detect(tmp_path) == []  # fotos diferentes entre si

    copy = tmp_path / "copia" / raw_samples[0].name
    copy.parent.mkdir()
    shutil.copy2(raw_samples[0], copy)
    os.utime(copy, (2_000_000_000, 2_000_000_000))
    [group] = detect(tmp_path)
    assert group.keep.path == tmp_path / raw_samples[0].name
    assert [m.path for m in group.duplicates] == [copy]


@pytest.mark.skipif(
    not hasattr(getattr(cv2, "img_hash", None), "pHash"), reason="OpenCV contrib não instalado"
)
def test_phash_matches_opencv_contrib():
    rng = np.random.default_rng(7)
    images = [
        cv2.cvtColor(photo(s, 300 + 37 * s, 200 + 23 * s), cv2.COLOR_BGR2GRAY) for s in range(8)
    ]
    images += [
        rng.integers(0, 256, (int(h), int(w)), np.uint8) for h, w in rng.integers(9, 700, (40, 2))
    ]
    for img in images:
        assert np.array_equal(duplicates.phash(img), cv2.img_hash.pHash(img).reshape(-1))


@requires_exiftool
def test_finds_photos_already_in_the_destination_and_suggests_the_better_one(tmp_path):
    from photo_organizer.core.duplicates import find_in_destination
    from photo_organizer.core.planner import DestAction

    src, dst = tmp_path / "origem", tmp_path / "destino"
    d1, d2 = "2025:04:20 07:16:07", "2025:05:01 10:00:00"
    base, other = photo(1), photo(2)
    small = cv2.resize(base, (600, 400), interpolation=cv2.INTER_AREA)
    save(src / "grande.jpg", base, date=d1)  # a da origem tem mais resolução
    save(dst / "2025" / "pequena.jpg", small, date=d1)
    save(src / "igual.jpg", other, date=d2)
    save(dst / "2025" / "melhor.jpg", other, quality=98, date=d2)  # o destino é maior
    save(src / "nova.jpg", photo(3), date="2025:06:01 08:00:00")  # não está no destino
    save(dst / "outra_hora.jpg", base, date="2025:04:20 09:00:00")  # outro momento

    with MetadataReader() as reader:
        source = list(read_dates(reader, scan(src)))
        dest = list(read_dates(reader, scan(dst)))
        groups, matches = find_in_destination(source, dest, reader)
    assert groups == []
    got = {m.source.path.name: (m.existing.path.name, m.suggested) for m in matches}
    assert got == {
        "grande.jpg": ("pequena.jpg", DestAction.REPLACE),
        "igual.jpg": ("melhor.jpg", DestAction.KEEP),
    }


def save_heic(path: Path, img: np.ndarray, date: str | None = None) -> Path:
    import pillow_heif  # só nos testes: o programa usa o pi-heif, que não grava HEIC
    from PIL import Image

    path.parent.mkdir(parents=True, exist_ok=True)
    rgb = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    pillow_heif.from_pillow(rgb).save(path, quality=90)
    if date:
        exiftool(f"-EXIF:DateTimeOriginal={date}", path)
    return path


@requires_exiftool
def test_heic_from_iphone_is_read_dated_and_matched_with_its_jpeg_copy(tmp_path):
    from photo_organizer.core.images import load_image

    base = photo(7)
    d = "2025:04:20 07:16:07"
    heic = save_heic(tmp_path / "IMG_0001.HEIC", base, d)
    save(tmp_path / "IMG_0001.jpg", cv2.resize(base, (600, 400)), 80, d)  # exportada
    save_heic(tmp_path / "IMG_0002.HEIC", photo(8), d)  # outra foto, mesmo instante

    img = load_image(heic, FileKind.JPEG, 256, None)
    assert img is not None and img.shape[:2] == (341, 512)  # 1200×800 reduzida, proporção mantida
    with MetadataReader() as reader:
        files = list(read_dates(reader, scan(tmp_path)))
        assert {f.path.name: d.value for f, d in files}["IMG_0001.HEIC"] == datetime(
            2025, 4, 20, 7, 16, 7
        )
        groups = find_duplicates(files, reader)
    [group] = groups
    assert {group.keep.path.name, *(m.path.name for m in group.duplicates)} == {
        "IMG_0001.HEIC",
        "IMG_0001.jpg",
    }


def test_unreadable_heic_has_no_image(tmp_path):
    from photo_organizer.core.images import load_image

    bad = tmp_path / "corrompida.heic"
    bad.write_bytes(b"\x00\x00\x00\x18ftypheic" + b"lixo" * 10)
    assert load_image(bad, FileKind.JPEG, 256, None) is None
    assert duplicates._hash_jpeg_file(bad) is None


def test_only_photos_that_can_match_are_hashed():
    from photo_organizer.core.duplicates import _comparable

    def m(name: str, kind: FileKind = FileKind.JPEG) -> MediaFile:
        return MediaFile(Path(name), kind)

    t = datetime(2025, 1, 1, 10, 0, 0)
    a, b, c, r = m("a.jpg"), m("b.jpg"), m("c.jpg"), m("r.arw", FileKind.RAW)
    photos = [
        (a, FileDate(t)),
        (b, FileDate(t.replace(microsecond=5000))),
        (c, FileDate(t + timedelta(seconds=1))),  # sozinha no segundo: não precisa ser lida
        (r, FileDate(t)),  # RAW não compara com JPEG
    ]
    assert _comparable(photos) == [a, b]
    whats = m("whats.jpg")  # sem data: procura a datada mais parecida, então todas entram
    assert set(_comparable([*photos, (whats, NO_DATE)])) == {a, b, c, whats}


@requires_exiftool
def test_jpeg_hash_comes_from_the_exif_thumbnail(tmp_path, monkeypatch):
    """A miniatura do EXIF (~10 KB) substitui a leitura da foto inteira pela rede."""
    base = photo(9)
    d = "2025:04:20 07:16:07"
    big = save(tmp_path / "a.jpg", base, date=d)
    thumb = tmp_path / "t.bin"
    thumb.write_bytes(cv2.imencode(".jpg", cv2.resize(base, (160, 107)))[1].tobytes())
    exiftool(f"-ThumbnailImage<={thumb}", big)
    thumb.unlink()
    full = duplicates._hash_jpeg_file(big)
    save(tmp_path / "b.jpg", base, 70, d)  # cópia sem miniatura: lê o arquivo inteiro

    read_whole: list[str] = []
    real = duplicates._hash_jpeg_file
    monkeypatch.setattr(
        duplicates, "_hash_jpeg_file", lambda p: read_whole.append(p.name) or real(p)
    )
    with MetadataReader() as reader:
        files = list(read_dates(reader, scan(tmp_path)))
        hashes = duplicates.image_hashes([m for m, _ in files], reader)
        groups = find_duplicates(files, reader)
    assert read_whole == ["b.jpg", "b.jpg"]
    assert bin(hashes[big] ^ full).count("1") <= duplicates.THRESHOLD
    [group] = groups
    assert {group.keep.path.name, *(m.path.name for m in group.duplicates)} == {"a.jpg", "b.jpg"}


@requires_exiftool
def test_thumbnail_of_a_portrait_photo_still_matches_its_upright_copy(tmp_path):
    """Foto em pé: a câmera grava os pixels deitados (Orientation 6), inclusive na miniatura,
    e o OpenCV desvira o JPEG inteiro. A cópia do WhatsApp já vem em pé."""
    base = photo(11)
    d = "2025:04:20 07:16:07"
    camera = save(tmp_path / "camera.jpg", base, date=d)
    thumb = tmp_path / "t.bin"
    thumb.write_bytes(cv2.imencode(".jpg", cv2.resize(base, (160, 107)))[1].tobytes())
    exiftool(f"-ThumbnailImage<={thumb}", "-Orientation#=6", camera)
    thumb.unlink()
    save(tmp_path / "whats.jpg", cv2.rotate(base, cv2.ROTATE_90_CLOCKWISE), 70, d)
    with MetadataReader() as reader:
        files = list(read_dates(reader, scan(tmp_path)))
        hashes = duplicates.image_hashes([m for m, _ in files], reader)
        groups = find_duplicates(files, reader)
    assert bin(hashes[camera] ^ duplicates._hash_jpeg_file(camera)).count("1") <= 6
    assert names(groups) == {("camera.jpg", frozenset({"whats.jpg"}))}
