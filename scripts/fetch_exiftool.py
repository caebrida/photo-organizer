"""Baixa o ExifTool para Windows (64 bits) e instala em photo_organizer/resources/exiftool.

A versão e o SHA-256 ficam fixados aqui para builds reproduzíveis. Para atualizar, troque
VERSION e SHA256 pelos valores de https://exiftool.org/checksums.txt.

Uso:  uv run python scripts/fetch_exiftool.py [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

VERSION = "13.59"
SHA256 = "44b512b25af500724ba579d0a53c8fc5851628b692dd5e5d94ae4a15c2cba9ec"
ARCHIVE = f"exiftool-{VERSION}_64.zip"
# Os pacotes são hospedados no SourceForge (exiftool.org publica só os checksums);
# o SHA-256 acima garante a integridade independentemente da fonte.
URLS = [
    f"https://sourceforge.net/projects/exiftool/files/{ARCHIVE}/download",
    f"https://exiftool.org/{ARCHIVE}",
]

TARGET = Path(__file__).resolve().parent.parent / "photo_organizer" / "resources" / "exiftool"


def download() -> bytes:
    for url in URLS:
        try:
            print(f"Baixando {url} ...")
            with urllib.request.urlopen(url, timeout=60) as resp:
                data = resp.read()
        except OSError as exc:
            print(f"  falhou: {exc}")
            continue
        digest = hashlib.sha256(data).hexdigest()
        if digest != SHA256:
            print(f"  SHA-256 não confere ({digest}); ignorando esta fonte.")
            continue
        return data
    sys.exit("Não foi possível baixar o ExifTool com o checksum esperado.")


def install(data: bytes) -> None:
    root = f"exiftool-{VERSION}_64/"
    staging = TARGET.with_name("exiftool.tmp")
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True)
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for member in zf.infolist():
            if not member.filename.startswith(root) or member.is_dir():
                continue
            rel = member.filename[len(root) :]
            if rel == "exiftool(-k).exe":
                rel = "exiftool.exe"  # sem "(-k)" o executável não pausa ao terminar
            dest = (staging / rel).resolve()
            if not dest.is_relative_to(staging.resolve()):
                sys.exit(f"Caminho inválido no zip: {member.filename}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(zf.read(member))
    if not (staging / "exiftool.exe").is_file():
        sys.exit("exiftool.exe não encontrado no pacote baixado.")
    shutil.rmtree(TARGET, ignore_errors=True)
    staging.rename(TARGET)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--force", action="store_true", help="reinstala mesmo se já existir")
    args = parser.parse_args()

    if (TARGET / "exiftool.exe").is_file() and not args.force:
        print(f"ExifTool já instalado em {TARGET} (use --force para reinstalar).")
        return
    install(download())
    print(f"ExifTool {VERSION} instalado em {TARGET}")


if __name__ == "__main__":
    main()
