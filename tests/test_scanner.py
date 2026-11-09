import os
from pathlib import Path

from photo_organizer.core.scanner import FileKind, MediaFile, kind_of, scan


def touch(root: Path, *names: str) -> None:
    for name in names:
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"")


def by_name(files: list[MediaFile]) -> dict[str, MediaFile]:
    return {f.path.name: f for f in files}


def test_kind_of_is_case_insensitive():
    assert kind_of("a.JPG") is FileKind.JPEG
    assert kind_of("a.jpeg") is FileKind.JPEG
    assert kind_of("IMG_0001.HEIC") is FileKind.JPEG  # foto comum, não RAW
    assert kind_of("a.Cr3") is FileKind.RAW
    assert kind_of("a.dng") is FileKind.RAW
    assert kind_of("a.MOV") is FileKind.VIDEO
    assert kind_of("a.xmp") is None
    assert kind_of("semextensao") is None


def test_scan_is_recursive_and_ignores_other_files(tmp_path):
    touch(tmp_path, "a.JPG", "sub/b.ARW", "sub/deep/c.mp4", "notas.txt", "sub/d.xmp")
    files = by_name(list(scan(tmp_path)))
    assert set(files) == {"a.JPG", "b.ARW", "c.mp4"}
    assert files["c.mp4"].kind is FileKind.VIDEO


def test_scan_filters_kinds(tmp_path):
    touch(tmp_path, "a.JPG", "b.ARW", "c.mp4")
    files = by_name(list(scan(tmp_path, kinds=[FileKind.JPEG, FileKind.RAW])))
    assert set(files) == {"a.JPG", "b.ARW"}


def test_stem_sidecar_goes_to_raw_not_jpeg(tmp_path):
    touch(tmp_path, "DSC0001.JPG", "DSC0001.ARW", "DSC0001.xmp")
    files = by_name(list(scan(tmp_path)))
    assert files["DSC0001.ARW"].sidecar == tmp_path / "DSC0001.xmp"
    assert files["DSC0001.JPG"].sidecar is None


def test_full_name_sidecar_belongs_to_that_file(tmp_path):
    touch(tmp_path, "DSC0001.JPG", "DSC0001.ARW", "DSC0001.xmp", "DSC0001.JPG.xmp")
    files = by_name(list(scan(tmp_path)))
    assert files["DSC0001.JPG"].sidecar == tmp_path / "DSC0001.JPG.xmp"
    assert files["DSC0001.ARW"].sidecar == tmp_path / "DSC0001.xmp"


def test_stem_sidecar_without_raw_goes_to_jpeg(tmp_path):
    touch(tmp_path, "IMG_5.jpg", "IMG_5.XMP")
    [f] = scan(tmp_path)
    assert f.sidecar == tmp_path / "IMG_5.XMP"


def test_sidecar_in_other_folder_is_not_matched(tmp_path):
    touch(tmp_path, "a/DSC0001.ARW", "b/DSC0001.xmp")
    [f] = scan(tmp_path)
    assert f.sidecar is None


def test_scan_skips_excluded_folder(tmp_path):
    touch(tmp_path, "a.jpg", "Organizadas/2026/b.jpg", "outra/c.jpg")
    files = by_name(list(scan(tmp_path, exclude=tmp_path / "organizadas")))
    assert set(files) == {"a.jpg", "c.jpg"}


def test_unreadable_folders_are_reported_and_skipped(tmp_path, monkeypatch):
    touch(tmp_path, "a.jpg", "bloqueada/b.jpg", "outra/c.jpg")
    real_scandir = os.scandir

    def scandir(path="."):
        if Path(path).name == "bloqueada":
            raise PermissionError(13, "Acesso negado", str(path))
        return real_scandir(path)

    monkeypatch.setattr(os, "scandir", scandir)
    errors: list[OSError] = []
    files = by_name(list(scan(tmp_path, on_error=errors.append)))
    assert set(files) == {"a.jpg", "c.jpg"}
    assert [Path(e.filename).name for e in errors] == ["bloqueada"]


def test_scan_returns_absolute_paths(tmp_path, monkeypatch):
    touch(tmp_path, "a.jpg")
    monkeypatch.chdir(tmp_path)
    [f] = scan(".")
    assert f.path.is_absolute()
    assert f.path == tmp_path / "a.jpg"


def test_scan_handles_non_ascii_folders(tmp_path):
    touch(tmp_path, "Łódź 東京/foto.jpg")
    [f] = scan(tmp_path)
    assert f.path == tmp_path / "Łódź 東京" / "foto.jpg"
