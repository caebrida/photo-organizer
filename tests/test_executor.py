import errno
import os
import threading
from datetime import datetime
from pathlib import Path

import pytest

from photo_organizer.core import executor
from photo_organizer.core.dates import DateSource, FileDate
from photo_organizer.core.executor import Mode, Status, execute
from photo_organizer.core.pattern import FolderPattern
from photo_organizer.core.planner import build_plan
from photo_organizer.core.rules import RuleSettings
from photo_organizer.core.scanner import scan

SETTINGS = RuleSettings(FolderPattern.parse("aaaa > mm > dd"))
DATE = FileDate(datetime(2026, 10, 27), DateSource.EXIF, "EXIF:DateTimeOriginal")


def make_source(root: Path) -> None:
    for name, data in {
        "DSC0001.JPG": b"jpeg-1",
        "DSC0001.ARW": b"raw-1" * 1000,
        "DSC0001.xmp": b"<xmp/>",
        "sub/C0031.MP4": b"video",
    }.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def run(src: Path, dst: Path, mode: Mode, **kwargs):
    plan = build_plan(((f, DATE) for f in scan(src)), dst, SETTINGS)
    return plan, list(execute(plan, mode, **kwargs))


def day(dst: Path) -> Path:
    return dst / "2026" / "10" / "27"


def test_copy_keeps_source_and_content(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    _, results = run(src, dst, Mode.COPY)
    assert {r.status for r in results} == {Status.DONE}
    assert (day(dst) / "DSC0001.JPG").read_bytes() == b"jpeg-1"
    assert (day(dst) / "RAW" / "DSC0001.ARW").read_bytes() == b"raw-1" * 1000
    assert (day(dst) / "RAW" / "DSC0001.xmp").read_bytes() == b"<xmp/>"
    assert (day(dst) / "Video" / "C0031.MP4").exists()
    assert (src / "DSC0001.ARW").exists() and (src / "DSC0001.xmp").exists()
    assert not list(dst.rglob("*.tmp"))


def test_copy_preserves_modification_time(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    f = src / "DSC0001.JPG"
    os.utime(f, (1_600_000_000, 1_600_000_000))
    run(src, dst, Mode.COPY)
    assert (day(dst) / "DSC0001.JPG").stat().st_mtime == 1_600_000_000


def test_move_same_volume(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    _, results = run(src, dst, Mode.MOVE)
    assert {r.status for r in results} == {Status.DONE}
    assert not any(p.is_file() for p in src.rglob("*"))
    assert (day(dst) / "RAW" / "DSC0001.xmp").exists()


def cross_device_rename(monkeypatch):
    real_rename = executor.os.rename

    def rename(a, b):
        if "~" not in Path(a).name:  # o rename do temporário (mesma pasta) funciona
            raise OSError(errno.EXDEV, "Invalid cross-device link")
        real_rename(a, b)

    monkeypatch.setattr(executor.os, "rename", rename)


def test_move_across_disks_copies_verifies_and_deletes(tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    cross_device_rename(monkeypatch)
    _, results = run(src, dst, Mode.MOVE)
    assert {r.status for r in results} == {Status.DONE}
    assert (day(dst) / "RAW" / "DSC0001.ARW").read_bytes() == b"raw-1" * 1000
    assert not (src / "DSC0001.ARW").exists()


def test_failed_verification_keeps_source_and_leaves_no_partial_file(tmp_path, monkeypatch):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    cross_device_rename(monkeypatch)
    monkeypatch.setattr(executor, "hash_file", lambda p: b"corrompido")
    _, results = run(src, dst, Mode.MOVE)
    assert {r.status for r in results} == {Status.FAILED}
    assert all("não confere" in r.error for r in results)
    assert (src / "DSC0001.ARW").read_bytes() == b"raw-1" * 1000
    assert not [p for p in dst.rglob("*") if p.is_file()]


def test_never_overwrites_file_created_after_planning(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    plan = build_plan(((f, DATE) for f in scan(src)), dst, SETTINGS)
    intruder = day(dst) / "DSC0001.JPG"
    intruder.parent.mkdir(parents=True)
    intruder.write_bytes(b"nao mexer")
    results = {r.item.media.path.name: r for r in execute(plan, Mode.COPY)}
    assert results["DSC0001.JPG"].status is Status.FAILED
    assert "nada foi sobrescrito" in results["DSC0001.JPG"].error
    assert intruder.read_bytes() == b"nao mexer"
    assert results["DSC0001.ARW"].status is Status.DONE


def test_sidecar_failure_is_partial(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    plan = build_plan(((f, DATE) for f in scan(src)), dst, SETTINGS)
    (src / "DSC0001.xmp").unlink()  # some depois do plano
    results = {r.item.media.path.name: r for r in execute(plan, Mode.COPY)}
    assert results["DSC0001.ARW"].status is Status.PARTIAL
    assert results["DSC0001.ARW"].error.startswith("Sidecar:")
    assert (day(dst) / "RAW" / "DSC0001.ARW").exists()


def test_cancel_stops_remaining_items(tmp_path):
    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    cancel = threading.Event()
    seen = []

    def progress(done, total, result):
        seen.append((done, total))
        cancel.set()

    _, results = run(src, dst, Mode.COPY, progress=progress, cancel=cancel)
    assert [r.status for r in results] == [Status.DONE, Status.CANCELLED, Status.CANCELLED]
    assert seen == [(1, 3), (2, 3), (3, 3)]


def test_skipped_items_are_reported(tmp_path):
    dst = tmp_path / "dst"
    make_source(day(dst))
    plan = build_plan(((f, DATE) for f in scan(dst)), dst, SETTINGS)
    statuses = {r.item.media.path.name: r.status for r in execute(plan, Mode.MOVE)}
    assert statuses["DSC0001.JPG"] is Status.SKIPPED
    assert statuses["DSC0001.ARW"] is Status.DONE  # vai para a subpasta RAW


@pytest.mark.skipif(executor.sys.platform != "win32", reason="prefixo só no Windows")
def test_long_paths(tmp_path):
    src, dst = tmp_path / "src", tmp_path / ("x" * 120) / ("y" * 120)
    make_source(src)
    _, results = run(src, dst, Mode.COPY)
    assert {r.status for r in results} == {Status.DONE}
    target = executor._fs(day(dst) / "RAW" / "DSC0001.ARW")
    assert target.startswith("\\\\?\\")
    with open(target, "rb") as f:  # noqa: PTH123 (str com prefixo \?\)
        assert f.read() == b"raw-1" * 1000


# --- Deixados de fora, Lixeira e substituição -----------------------------------------


@pytest.fixture
def fake_trash(tmp_path, monkeypatch):
    """Lixeira de mentira: os testes não enchem a Lixeira de verdade do Windows."""
    bin_ = tmp_path / "lixeira"
    bin_.mkdir()

    def move(path):
        Path(path).replace(bin_ / Path(path).name)

    monkeypatch.setattr(executor, "move_to_trash", move)
    return bin_


def test_left_out_files_stay_or_go_to_the_trash_only_when_moving(tmp_path, fake_trash):
    from photo_organizer.core.planner import Skip

    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    files = [(f, DATE) for f in scan(src)]
    out = [f.path for f, _ in files if f.path.suffix == ".ARW"]
    copy_plan = build_plan(files, dst, SETTINGS, excluded=out, trash_excluded=True)
    results = {r.item.media.path.suffix: r.status for r in execute(copy_plan, Mode.COPY)}
    assert results[".ARW"] is Status.SKIPPED  # copiando, a origem nunca muda
    assert (src / "DSC0001.ARW").exists()

    plan = build_plan(files, tmp_path / "dst2", SETTINGS, excluded=out, trash_excluded=True)
    assert [i.skip for i in plan.items if i.trash] == [Skip.EXCLUDED]
    results = {r.item.media.path.suffix: r.status for r in execute(plan, Mode.MOVE)}
    assert results[".ARW"] is Status.DONE
    assert not (src / "DSC0001.ARW").exists()
    assert {p.name for p in fake_trash.iterdir()} == {"DSC0001.ARW", "DSC0001.xmp"}
    assert not (tmp_path / "dst2" / "2026" / "10" / "27" / "RAW").exists()


def _existing(dst: Path, data: bytes):
    from photo_organizer.core.scanner import FileKind, MediaFile

    old = day(dst) / "DSC0001.JPG"
    old.parent.mkdir(parents=True)
    old.write_bytes(data)
    return MediaFile(old, FileKind.JPEG)


@pytest.mark.parametrize("mode", [Mode.COPY, Mode.MOVE])
def test_replace_sends_the_old_destination_file_to_the_trash(tmp_path, fake_trash, mode):
    from photo_organizer.core.planner import DestAction

    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    old = _existing(dst, b"menor")
    files = [(f, DATE) for f in scan(src)]
    jpg = next(f for f, _ in files if f.path.suffix == ".JPG")
    plan = build_plan(files, dst, SETTINGS, in_dest={jpg.path: (DestAction.REPLACE, old)})
    item = next(i for i in plan.items if i.media == jpg)
    assert item.dest == old.path and item.replaces == old
    results = {r.item.media.path.suffix: r for r in execute(plan, mode)}
    assert results[".JPG"].status is Status.DONE, results[".JPG"].error
    assert old.path.read_bytes() == b"jpeg-1"
    assert (fake_trash / "DSC0001.JPG").read_bytes() == b"menor"
    assert (src / "DSC0001.JPG").exists() == (mode is Mode.COPY)
    assert list(day(dst).glob("~*")) == []  # nenhum temporário sobrando


def test_replace_changes_nothing_when_the_old_file_cannot_go_to_the_trash(tmp_path, monkeypatch):
    from photo_organizer.core.planner import DestAction

    def refuse(path):
        raise OSError(errno.EPERM, "Esta unidade não tem Lixeira", str(path))

    monkeypatch.setattr(executor, "move_to_trash", refuse)
    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    old = _existing(dst, b"menor")
    files = [(f, DATE) for f in scan(src)]
    jpg = next(f for f, _ in files if f.path.suffix == ".JPG")
    plan = build_plan(files, dst, SETTINGS, in_dest={jpg.path: (DestAction.REPLACE, old)})
    result = next(r for r in execute(plan, Mode.MOVE) if r.item.media == jpg)
    assert result.status is Status.FAILED
    assert "Nada foi trocado" in result.error
    assert old.path.read_bytes() == b"menor"
    assert (src / "DSC0001.JPG").read_bytes() == b"jpeg-1"  # voltou para a origem
    assert list(day(dst).glob("~*")) == []


def test_keep_destination_and_duplicate_actions(tmp_path):
    from photo_organizer.core.planner import DestAction, Skip

    src, dst = tmp_path / "src", tmp_path / "dst"
    make_source(src)
    old = _existing(dst, b"maior")
    files = [(f, DATE) for f in scan(src)]
    jpg = next(f for f, _ in files if f.path.suffix == ".JPG")
    keep = build_plan(files, dst, SETTINGS, in_dest={jpg.path: (DestAction.KEEP, old)})
    item = next(i for i in keep.items if i.media == jpg)
    assert item.skip is Skip.KEPT and item.dest == old.path
    dup = build_plan(files, dst, SETTINGS, in_dest={jpg.path: (DestAction.DUPLICATE, old)})
    item = next(i for i in dup.items if i.media == jpg)
    assert item.duplicate and "Duplicadas - Validar" in str(item.dest)


def test_move_to_trash_refuses_drives_without_a_recycle_bin(tmp_path, monkeypatch):
    if os.name != "nt":
        pytest.skip("só Windows")
    import ctypes

    f = tmp_path / "foto.jpg"
    f.write_bytes(b"x")
    monkeypatch.setattr(ctypes.windll.kernel32, "GetDriveTypeW", lambda root: 4)  # rede
    with pytest.raises(OSError, match="não tem Lixeira"):
        executor.move_to_trash(f)
    assert f.exists()
