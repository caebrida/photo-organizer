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
from photo_organizer.core.dates import read_dates
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
