from datetime import datetime
from pathlib import Path

from photo_organizer.core.dates import NO_DATE, DateSource, FileDate
from photo_organizer.core.pattern import FolderPattern
from photo_organizer.core.planner import build_plan
from photo_organizer.core.rules import RuleSettings
from photo_organizer.core.scanner import FileKind, MediaFile, scan

SETTINGS = RuleSettings(FolderPattern.parse("aaaa > mm > dd"))
DATE = FileDate(datetime(2026, 10, 27, 14, 32), DateSource.EXIF, "EXIF:DateTimeOriginal")


def touch(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path


def media(path: Path, kind: FileKind, sidecar: Path | None = None) -> MediaFile:
    return MediaFile(touch(path), kind, touch(sidecar) if sidecar else None)


def test_basic_destinations(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    jpg = media(src / "a.JPG", FileKind.JPEG)
    raw = media(src / "a.ARW", FileKind.RAW, src / "a.xmp")
    vid = media(src / "c.mp4", FileKind.VIDEO)
    old = media(src / "x.jpg", FileKind.JPEG)
    plan = build_plan([(jpg, DATE), (raw, DATE), (vid, DATE), (old, NO_DATE)], dst, SETTINGS)
    day = dst / "2026" / "10" / "27"
    assert [i.dest for i in plan.items] == [
        day / "a.JPG",
        day / "RAW" / "a.ARW",
        day / "Video" / "c.mp4",
        dst / "Sem data" / "x.jpg",
    ]
    assert plan.items[1].sidecar_dest == day / "RAW" / "a.xmp"


def test_conflict_with_existing_file_gets_suffix(tmp_path):
    day = tmp_path / "dst" / "2026" / "10" / "27"
    touch(day / "DSC0001.jpg")  # já existe, com outra caixa
    touch(day / "DSC0001_1.JPG")
    f = media(tmp_path / "src" / "DSC0001.JPG", FileKind.JPEG)
    [item] = build_plan([(f, DATE)], tmp_path / "dst", SETTINGS).items
    assert item.dest == day / "DSC0001_2.JPG"


def test_conflict_inside_the_plan(tmp_path):
    a = media(tmp_path / "src" / "cam1" / "IMG.jpg", FileKind.JPEG)
    b = media(tmp_path / "src" / "cam2" / "IMG.jpg", FileKind.JPEG)
    plan = build_plan([(a, DATE), (b, DATE)], tmp_path / "dst", SETTINGS)
    assert [i.dest.name for i in plan.items] == ["IMG.jpg", "IMG_1.jpg"]


def test_raw_and_sidecar_get_the_same_suffix(tmp_path):
    raw_dir = tmp_path / "dst" / "2026" / "10" / "27" / "RAW"
    touch(raw_dir / "DSC0001.xmp")  # só o sidecar colide: o par inteiro muda de nome
    f = media(tmp_path / "src" / "DSC0001.ARW", FileKind.RAW, tmp_path / "src" / "DSC0001.xmp")
    [item] = build_plan([(f, DATE)], tmp_path / "dst", SETTINGS).items
    assert item.dest == raw_dir / "DSC0001_1.ARW"
    assert item.sidecar_dest == raw_dir / "DSC0001_1.xmp"


def test_jpeg_full_name_sidecar_follows_suffix(tmp_path):
    day = tmp_path / "dst" / "2026" / "10" / "27"
    touch(day / "DSC0001.JPG")
    f = media(tmp_path / "src" / "DSC0001.JPG", FileKind.JPEG, tmp_path / "src" / "DSC0001.JPG.xmp")
    [item] = build_plan([(f, DATE)], tmp_path / "dst", SETTINGS).items
    assert item.dest == day / "DSC0001_1.JPG"
    assert item.sidecar_dest == day / "DSC0001_1.JPG.xmp"


def test_unreadable_destination_does_not_break_the_plan(tmp_path, monkeypatch):
    def denied(_path):
        raise PermissionError(13, "Acesso negado")

    monkeypatch.setattr("photo_organizer.core.planner.os.listdir", denied)
    f = media(tmp_path / "src" / "a.jpg", FileKind.JPEG)
    [item] = build_plan([(f, DATE)], tmp_path / "dst", SETTINGS).items
    assert item.dest == tmp_path / "dst" / "2026" / "10" / "27" / "a.jpg"


def test_file_already_in_place_is_skipped(tmp_path):
    dst = tmp_path / "dst"
    touch(dst / "2026" / "10" / "27" / "a.jpg")
    [f] = scan(dst)
    [item] = build_plan([(f, DATE)], dst, SETTINGS).items
    assert item.skip
    assert item.dest == f.path


def test_duplicates_go_to_their_folder(tmp_path):
    a = media(tmp_path / "src" / "a.jpg", FileKind.JPEG)
    b = media(tmp_path / "src" / "b.jpg", FileKind.JPEG)
    plan = build_plan([(a, DATE), (b, DATE)], tmp_path / "dst", SETTINGS, duplicates=[b.path])
    assert plan.items[1].duplicate
    assert plan.items[1].dest == tmp_path / "dst/Duplicadas - Validar/2026/10/27/b.jpg"
    assert not plan.items[0].duplicate


def test_destination_folders_are_listed_once_across_plans(tmp_path, monkeypatch):
    """Cada ajuste nas regras refaz o plano; numa rede, relistar as pastas a cada clique
    demora. As listagens passadas em ``listings`` valem para os próximos planos."""
    import os

    from photo_organizer.core import planner

    dst = tmp_path / "dst"
    touch(dst / "2026" / "10" / "27" / "a.JPG")  # já existe lá
    f = media(tmp_path / "src" / "a.JPG", FileKind.JPEG)
    calls: list[str] = []
    real = os.listdir
    monkeypatch.setattr(planner.os, "listdir", lambda p: calls.append(p) or real(p))
    listings: dict = {}
    for _ in range(3):
        [item] = build_plan([(f, DATE)], dst, SETTINGS, listings=listings).items
        assert item.dest.name == "a_1.JPG"  # o nome reservado num plano não vaza para o outro
    assert len(calls) == 1
