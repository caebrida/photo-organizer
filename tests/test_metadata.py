import threading
from pathlib import Path

import pytest
from conftest import make_sidecar, requires_exiftool

from photo_organizer.core import metadata
from photo_organizer.core.metadata import ExifToolNotFoundError, MetadataReader


def test_missing_exiftool_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata, "resources_dir", lambda: tmp_path)
    with pytest.raises(ExifToolNotFoundError, match="fetch_exiftool.py"):
        metadata.exiftool_path()


def test_resources_dir_inside_pyinstaller_bundle(tmp_path, monkeypatch):
    monkeypatch.setattr(metadata.sys, "_MEIPASS", str(tmp_path), raising=False)
    assert metadata.resources_dir() == tmp_path / "photo_organizer" / "resources"


@requires_exiftool
def test_exiftool_responds():
    with MetadataReader() as reader:
        assert float(reader.version) >= 13


@requires_exiftool
def test_reads_date_from_xmp_sidecar(tmp_path: Path):
    # Nome com acento: caminhos não ASCII são comuns no Windows.
    xmp = make_sidecar(tmp_path / "Férias" / "DSC0001.xmp", "2026-10-27T14:32:08")
    with MetadataReader() as reader:
        [meta] = reader.read([xmp], ["XMP:CreateDate"])
    assert meta["XMP:CreateDate"] == "2026:10:27 14:32:08"


@requires_exiftool
def test_read_empty_list_returns_empty():
    with MetadataReader() as reader:
        assert reader.read([]) == []


@requires_exiftool
def test_lots_of_stderr_does_not_deadlock(tmp_path: Path):
    """Com -b, avisos e erros vão para o stderr; acima de ~4 KB o ExifTool travava
    esperando o pyexiftool, que só lia o stderr depois do stdout."""

    files = []
    for i in range(150):  # cada um gera "Error: File format error - <caminho>"
        f = tmp_path / f"arquivo_corrompido_com_nome_comprido_{i:04d}.ARW"
        f.write_bytes(b"\x00garbage" * 64)
        files.append(f)
    result: list = []
    with MetadataReader() as reader:
        t = threading.Thread(
            target=lambda: result.append(reader.read(files, ["ThumbnailImage"], ["-b"])),
            daemon=True,
        )
        t.start()
        t.join(30)
        assert not t.is_alive(), "ExifTool travou com stderr cheio"
        assert float(reader.version) >= 13  # a sessão continua utilizável
