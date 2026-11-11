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


@requires_exiftool
def test_unreadable_batch_does_not_abort_the_job(tmp_path: Path):
    """Lote em que nenhum arquivo abre (rede caiu, arquivo sumiu): antes derrubava a
    conferência do destino com "execute_json expected output on stdout but got none"."""
    from photo_organizer.core.duplicates import _hash_previews

    gone = [tmp_path / "sumiu1.ARW", tmp_path / "sumiu2.ARW"]
    with MetadataReader() as reader:
        assert reader.read(gone, ["ThumbnailImage"], ["-b"]) == []
        assert _hash_previews(gone, reader) == {}
        assert reader.read([Path(__file__)], ["File:FileName"])  # a sessão segue viva


@requires_exiftool
def test_batch_that_fails_once_keeps_the_readable_files(tmp_path: Path, monkeypatch):
    from exiftool.exceptions import ExifToolOutputEmptyError

    files = [make_sidecar(tmp_path / f"f{i}.xmp", "2026-10-27T14:32:08") for i in range(5)]
    with MetadataReader() as reader:
        real = reader._et.get_tags
        calls = []

        def flaky(paths, **kw):  # a rede cai só durante o lote inteiro
            calls.append(len(paths))
            if len(calls) == 1:
                raise ExifToolOutputEmptyError(0, "", "", "")
            return real(paths, **kw)

        monkeypatch.setattr(reader._et, "get_tags", flaky)
        assert len(reader.read(files, ["XMP:CreateDate"])) == 5
    assert calls == [5, 2, 3]


@requires_exiftool
def test_unreachable_folder_stops_instead_of_retrying_file_by_file(tmp_path, monkeypatch):
    """Compartilhamento fora do ar: dividir o lote viraria centenas de esperas da rede."""
    gone = [tmp_path / "share" / f"f{i}.jpg" for i in range(50)]
    with MetadataReader() as reader:
        calls: list[int] = []
        real = reader._et.get_tags
        monkeypatch.setattr(
            reader._et, "get_tags", lambda p, **k: calls.append(len(p)) or real(p, **k)
        )
        with pytest.raises(OSError, match="inacess"):
            reader.read(gone, ["File:FileName"])
    assert calls == [50]
