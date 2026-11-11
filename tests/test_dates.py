import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import SAMPLES, make_jpeg, make_mp4, make_sidecar, requires_exiftool

from photo_organizer.core.cache import HashCache
from photo_organizer.core.dates import (
    NO_DATE,
    DateSource,
    FileDate,
    date_from_name,
    parse_date,
    read_dates,
    resolve_date,
)
from photo_organizer.core.metadata import MetadataReader
from photo_organizer.core.pattern import FolderPattern
from photo_organizer.core.rules import RuleSettings, destination_dir
from photo_organizer.core.scanner import FileKind, MediaFile, scan

# --- parse_date / resolve_date: sem ExifTool ------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("2025:04:20 07:16:07", datetime(2025, 4, 20, 7, 16, 7)),
        ("2025:04:20 07:08:48.791-03:00", datetime(2025, 4, 20, 7, 8, 48, 791000)),
        ("2025:04:20 07:08:48.5", datetime(2025, 4, 20, 7, 8, 48, 500000)),
        ("2025-04-20T07:08:48Z", datetime(2025, 4, 20, 7, 8, 48)),
        ("2025:04:20", datetime(2025, 4, 20)),
        ("2025:04:20 07:08", datetime(2025, 4, 20, 7, 8)),
    ],
)
def test_parse_date_keeps_local_wall_clock(value, expected):
    assert parse_date(value) == expected


@pytest.mark.parametrize(
    "value",
    [None, "", "0000:00:00 00:00:00", "    :  :     :  :  ", "2025:13:01", 20250420, "1800:01:01"],
)
def test_parse_date_rejects_empty_or_invalid(value):
    assert parse_date(value) is None


def test_parse_date_converts_utc_only_without_offset():
    utc = datetime(2025, 7, 13, 6, 37, 14, tzinfo=UTC)
    local = utc.astimezone().replace(tzinfo=None)
    assert parse_date("2025:07:13 06:37:14", assume_utc=True) == local
    assert parse_date("2025:07:13 03:37:14-03:00", assume_utc=True) == datetime(
        2025, 7, 13, 3, 37, 14
    )


def test_exif_wins_over_sidecar_and_embedded_xmp():
    meta = {"EXIF:DateTimeOriginal": "2025:04:20 07:16:07", "XMP:CreateDate": "2020:01:01 00:00:00"}
    got = resolve_date(meta, {"XMP:CreateDate": "2019:01:01 00:00:00"})
    assert got == FileDate(
        datetime(2025, 4, 20, 7, 16, 7), DateSource.EXIF, "EXIF:DateTimeOriginal"
    )


def test_invalid_exif_falls_through_to_sidecar():
    meta = {"EXIF:DateTimeOriginal": "0000:00:00 00:00:00"}
    got = resolve_date(meta, {"XMP:CreateDate": "2026:10:27 14:32:08"})
    assert got.source is DateSource.XMP_SIDECAR
    assert got.value == datetime(2026, 10, 27, 14, 32, 8)


def test_sidecar_wins_over_embedded_xmp_and_video():
    meta = {"XMP:CreateDate": "2020:01:01 00:00:00", "QuickTime:CreateDate": "2018:01:01 00:00:00"}
    assert resolve_date(meta, {"XMP:DateCreated": "2026:10:27"}).source is DateSource.XMP_SIDECAR
    assert resolve_date(meta).source is DateSource.XMP_EMBEDDED


def test_crw_date_from_makernotes():
    got = resolve_date({"MakerNotes:DateTimeOriginal": "2004:08:01 10:00:00"})
    assert got.source is DateSource.EXIF


def test_video_prefers_creation_date_with_offset():
    meta = {
        "QuickTime:CreationDate": "2025:07:13 03:37:14-03:00",
        "QuickTime:CreateDate": "2025:07:13 06:37:14",
    }
    assert resolve_date(meta).value == datetime(2025, 7, 13, 3, 37, 14)
    assert resolve_date({"RIFF:DateTimeOriginal": "2005:08:19 14:22:13"}).source is DateSource.VIDEO


def test_nothing_found_means_no_date():
    assert resolve_date({"File:FileModifyDate": "2025:01:01 00:00:00-03:00"}) is NO_DATE


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("IMG_20261027_143208.jpg", datetime(2026, 10, 27, 14, 32, 8)),
        ("IMG-20261027-WA0003.jpg", datetime(2026, 10, 27)),  # WhatsApp: só o dia
        ("PXL_20261027_143208123.jpg", datetime(2026, 10, 27, 14, 32, 8)),
        ("Screenshot_2026-10-27-14-32-08.png", datetime(2026, 10, 27, 14, 32, 8)),
        ("2026-10-27 14.32.08.jpg", datetime(2026, 10, 27, 14, 32, 8)),
        ("DSC01234.JPG", None),
        ("IMG_20261327.jpg", None),  # mês 13
        ("VID_20240230.mp4", None),  # 30 de fevereiro
        ("1698412345678.jpg", None),  # número colado: não é data
        ("x120261027.jpg", None),
    ],
)
def test_date_from_file_name(name, expected):
    got = date_from_name(name)
    assert got.value == expected
    assert got.source is (DateSource.FILENAME if expected else None)


# --- read_dates: com ExifTool e arquivos sintéticos -----------------------------------


@requires_exiftool
def test_read_dates_end_to_end(tmp_path):
    utc = datetime(2025, 7, 13, 6, 37, 14, tzinfo=UTC)
    src = tmp_path / "origem"
    make_jpeg(src / "exif.jpg", "2025:04:20 07:16:07")
    make_sidecar(src / "exif.jpg.xmp", "2019-01-01T00:00:00")  # perde para o EXIF
    make_jpeg(src / "so_xmp.JPG")
    make_sidecar(src / "so_xmp.JPG.xmp", "2026-10-27T14:32:08")
    make_jpeg(src / "raw_com_xmp.ARW")  # conteúdo JPEG sem EXIF, mas com extensão RAW
    make_sidecar(src / "raw_com_xmp.xmp", "2024-12-25T09:00:00")
    make_jpeg(src / "sem_data.jpeg")
    (src / "corrompido.jpg").write_bytes(b"isto nao e uma imagem")
    make_mp4(src / "Łódź 東京" / "clip.MP4", utc)

    with MetadataReader() as reader:
        got = {f.path.name: d for f, d in read_dates(reader, scan(src), batch_size=3)}

    assert got["exif.jpg"].value == datetime(2025, 4, 20, 7, 16, 7)
    assert got["exif.jpg"].source is DateSource.EXIF
    assert got["so_xmp.JPG"] == FileDate(
        datetime(2026, 10, 27, 14, 32, 8), DateSource.XMP_SIDECAR, "XMP:CreateDate"
    )
    assert got["raw_com_xmp.ARW"].value == datetime(2024, 12, 25, 9, 0)
    assert got["sem_data.jpeg"] is NO_DATE
    assert got["corrompido.jpg"] is NO_DATE
    assert got["clip.MP4"].value == utc.astimezone().replace(tzinfo=None)
    assert got["clip.MP4"].source is DateSource.VIDEO


@requires_exiftool
def test_read_dates_empty_input():
    with MetadataReader() as reader:
        assert list(read_dates(reader, [])) == []


# --- Amostras reais (tests/samples, fora do git) --------------------------------------

sample_files = list(scan(SAMPLES)) if SAMPLES.is_dir() else []


@requires_exiftool
@pytest.mark.skipif(not sample_files, reason="sem amostras em tests/samples")
def test_real_samples_have_exif_date_and_expected_folder(tmp_path):
    settings = RuleSettings(FolderPattern.parse("aaaa > mm > dd"))
    with MetadataReader() as reader:
        results = list(read_dates(reader, sample_files))
    for f, d in results:
        assert d.source is DateSource.EXIF, f.path.name
        folder = destination_dir(tmp_path, f.kind, d.value, settings)
        expected = tmp_path / f"{d.value:%Y}" / f"{d.value:%m}" / f"{d.value:%d}"
        expected /= {FileKind.JPEG: "", FileKind.RAW: "RAW", FileKind.VIDEO: "Video"}[f.kind]
        assert folder == expected, f.path.name


@requires_exiftool
def test_unreadable_files_are_reported_not_undated(tmp_path):
    """Arquivo que o ExifTool não abre (sumiu, rede caiu) não pode virar "sem data": iria
    para a pasta Sem data ao organizar."""
    ok = MediaFile(make_jpeg(tmp_path / "ok.jpg", "2025:04:20 07:16:07"), FileKind.JPEG)
    gone = MediaFile(tmp_path / "sumiu.jpg", FileKind.JPEG)
    failed: list[MediaFile] = []
    with MetadataReader() as reader:
        got = list(read_dates(reader, [ok, gone], unreadable=failed))
    assert [f.path.name for f, _ in got] == ["ok.jpg"]
    assert failed == [gone]


@requires_exiftool
def test_date_cache_skips_exiftool_until_the_sidecar_changes(tmp_path, monkeypatch):
    src = tmp_path / "src"
    make_jpeg(src / "a.jpg")
    side = make_sidecar(src / "a.jpg.xmp", "2026-10-27T14:32:08")
    make_jpeg(src / "b.jpg", "2025:04:20 07:16:07")
    make_jpeg(src / "c.jpg")  # sem data também vai para o cache
    with MetadataReader() as reader, HashCache(tmp_path / "cache.sqlite") as cache:
        first = {f.path.name: d for f, d in read_dates(reader, scan(src), cache=cache)}
        calls: list[list] = []
        real = reader.read
        monkeypatch.setattr(
            reader, "read", lambda files, *a, **k: calls.append(list(files)) or real(files, *a, **k)
        )
        again = {f.path.name: d for f, d in read_dates(reader, scan(src), cache=cache)}
        assert again == first
        assert first["c.jpg"] is NO_DATE
        assert calls == []  # nada voltou ao ExifTool

        make_sidecar(side, "2020-01-01T00:00:00")  # editado no Lightroom
        os.utime(side, ns=(1_700_000_000_000_000_000, 1_700_000_000_000_000_000))
        third = {f.path.name: d for f, d in read_dates(reader, scan(src), cache=cache)}
    assert third["a.jpg"].value == datetime(2020, 1, 1)
    assert [Path(p).name for p in calls[0]] == ["a.jpg"]  # só o que mudou foi relido
