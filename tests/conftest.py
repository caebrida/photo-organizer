"""Fixtures compartilhadas: arquivos sintéticos com datas conhecidas.

Os testes não dependem das fotos pessoais em ``tests/samples`` (fora do git); os que
usam essas amostras são pulados quando a pasta não existe.
"""

from __future__ import annotations

import os

# Testes de interface sem abrir janelas (precisa vir antes de criar o QApplication).
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import struct
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest
from PIL import Image

from photo_organizer.core import metadata

SAMPLES = Path(__file__).parent / "samples"

requires_exiftool = pytest.mark.skipif(
    not (metadata.resources_dir() / "exiftool" / "exiftool.exe").is_file(),
    reason="ExifTool não instalado; rode scripts/fetch_exiftool.py",
)


def _models_installed() -> bool:
    from photo_organizer.tagging.tagger import MODEL_FILES, models_dir

    return all((models_dir() / f).is_file() for f in MODEL_FILES)


requires_models = pytest.mark.skipif(
    not _models_installed(), reason="modelos ausentes (rode scripts/fetch_models.py)"
)


def exiftool(*args: str | Path) -> None:
    exe = metadata.exiftool_path()
    cmd = [str(exe), "-charset", "filename=utf8", "-overwrite_original", *map(str, args)]
    subprocess.run(cmd, check=True, capture_output=True, encoding="utf-8")


def make_jpeg(path: Path, exif_date: str | None = None) -> Path:
    """JPEG 8×8 sem metadados; com ``exif_date`` ("2025:04:20 07:16:07") grava o EXIF."""
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (8, 8), (200, 120, 40)).save(path, "JPEG")
    if exif_date:
        exiftool(f"-EXIF:DateTimeOriginal={exif_date}", path)
    return path


def make_sidecar(path: Path, create_date: str) -> Path:
    """Sidecar XMP com ``xmp:CreateDate`` no formato ISO ("2026-10-27T14:32:08")."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "<?xpacket begin='' id='W5M0MpCehiHzreSzNTczkc9d'?>\n"
        "<x:xmpmeta xmlns:x='adobe:ns:meta/'>\n"
        " <rdf:RDF xmlns:rdf='http://www.w3.org/1999/02/22-rdf-syntax-ns#'>\n"
        "  <rdf:Description rdf:about='' xmlns:xmp='http://ns.adobe.com/xap/1.0/'>\n"
        f"   <xmp:CreateDate>{create_date}</xmp:CreateDate>\n"
        "  </rdf:Description>\n"
        " </rdf:RDF>\n"
        "</x:xmpmeta>\n"
        "<?xpacket end='w'?>\n",
        encoding="utf-8",
    )
    return path


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def make_mp4(path: Path, created_utc: datetime) -> Path:
    """MP4 mínimo (ftyp + moov/mvhd) cujo ``QuickTime:CreateDate`` é ``created_utc``."""
    secs = int((created_utc - datetime(1904, 1, 1, tzinfo=UTC)).total_seconds())
    matrix = struct.pack(">9I", 0x10000, 0, 0, 0, 0x10000, 0, 0, 0, 0x40000000)
    mvhd = (
        struct.pack(">I", 0)  # versão 0, flags
        + struct.pack(">IIII", secs, secs, 1000, 0)  # criação, modificação, escala, duração
        + struct.pack(">IH", 0x10000, 0x100)  # taxa 1.0, volume 1.0
        + bytes(10)
        + matrix
        + bytes(24)
        + struct.pack(">I", 2)  # próximo track id
    )
    ftyp = _box(b"ftyp", b"isom" + struct.pack(">I", 512) + b"isomiso2mp41")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(ftyp + _box(b"moov", _box(b"mvhd", mvhd)))
    return path
