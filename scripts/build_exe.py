"""Gera as duas versões do programa para Windows (fase 6):

- dist/PhotoOrganizer-portable.exe: arquivo único, roda de qualquer pasta ou pendrive;
- dist/PhotoOrganizer-Setup-<versão>.exe: instalador (Inno Setup), abre mais rápido.

Roda num ambiente de build limpo, fora do OneDrive, só com as dependências do programa
e o PyInstaller (sem pacotes de desenvolvimento, que inchariam o .exe):

    $env:UV_PROJECT_ENVIRONMENT = "$env:LOCALAPPDATA\\photo-organizer\\build-venv"
    uv run --no-dev --group build python scripts/build_exe.py

Antes, uma vez: scripts/fetch_exiftool.py, scripts/fetch_models.py e o Inno Setup 6
(winget install JRSoftware.InnoSetup). Sem o Inno Setup, só a versão portátil sai.
``--preview`` só desenha a tela de abertura e o ícone, para revisar.
"""

from __future__ import annotations

import os
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
# Sem isto o modo offscreen não acha fontes e o texto do splash sai como quadradinhos.
os.environ.setdefault("QT_QPA_FONTDIR", str(Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"))

from PySide6.QtCore import QBuffer, QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from photo_organizer import __version__  # noqa: E402
from photo_organizer.core.metadata import exiftool_path  # noqa: E402
from photo_organizer.tagging.tagger import MODEL_FILES, models_dir  # noqa: E402
from photo_organizer.ui import icons, theme  # noqa: E402

WORK = Path(os.environ.get("LOCALAPPDATA", ROOT)) / "photo-organizer" / "pyinstaller"
DIST = ROOT / "dist"  # só os dois .exe finais
BUILD_DIST = WORK / "dist"  # pasta intermediária, fora do OneDrive (que trava arquivos)
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def splash_image(path: Path) -> None:
    """Tela de abertura da versão portátil: aparece enquanto o .exe se descompacta."""
    w, h = 560, 300
    image = QImage(w, h, QImage.Format.Format_RGB32)
    image.fill(QColor(theme.BG))
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    p.setPen(QColor(theme.BORDER))
    p.drawRect(0, 0, w - 1, h - 1)
    p.fillRect(0, h - 4, w, 4, QColor(theme.ACCENT))

    p.drawImage(48, 84, icons.app_icon_image(104))
    left = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
    p.setPen(QColor(theme.TEXT))
    p.setFont(QFont(theme.FONT_UI, 24, QFont.Weight.DemiBold))
    p.drawText(QRectF(176, 92, 360, 48), left, "Photo Organizer")
    p.setPen(QColor(theme.MUTED))
    p.setFont(QFont(theme.FONT_UI, 10))
    tagline = "Open-source Photo Organizer Tool with AI Tag detection"
    p.drawText(QRectF(178, 142, 370, 24), left, tagline)

    p.setFont(QFont(theme.FONT_UI, 9))
    p.drawText(QRectF(24, h - 40, 300, 24), left, "Carregando…  /  Loading…")
    p.setPen(QColor(theme.FAINT))
    right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
    p.drawText(QRectF(w - 224, h - 40, 200, 24), right, f"versão {__version__}")
    p.end()
    if not image.save(str(path)):
        raise OSError(f"Não foi possível salvar {path}")


def write_ico(path: Path) -> None:
    """ICO com um PNG desenhado em cada tamanho (nítido de 16 a 256 px)."""
    pngs = []
    for size in ICO_SIZES:
        buffer = QBuffer()
        buffer.open(QBuffer.OpenModeFlag.WriteOnly)
        icons.app_icon_image(size).save(buffer, "PNG")
        pngs.append((size, bytes(buffer.data())))
    offset = 6 + 16 * len(pngs)
    header = struct.pack("<HHH", 0, 1, len(pngs))
    entries = data = b""
    for size, png in pngs:
        side = size % 256  # 0 significa 256
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset + len(data))
        data += png
    path.write_bytes(header + entries + data)


def check_resources() -> None:
    exiftool_path()  # levanta erro com a instrução de como baixar
    missing = [f for f in MODEL_FILES if not (models_dir() / f).is_file()]
    if missing:
        raise SystemExit(f"Faltam modelos {missing}. Rode scripts/fetch_models.py.")


def inno_compiler() -> Path | None:
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    roots = [os.environ.get(v) for v in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA")]
    for root in filter(None, roots):
        for sub in ("Inno Setup 6", "Programs/Inno Setup 6"):
            exe = Path(root) / sub / "ISCC.exe"
            if exe.is_file():
                return exe
    return None


def draw_assets(folder: Path) -> None:
    QApplication.instance() or QApplication([])
    folder.mkdir(parents=True, exist_ok=True)
    splash_image(folder / "splash.png")
    write_ico(folder / "icon.ico")
    icons.app_icon_image(256).save(str(folder / "icon.png"))


def main(argv: list[str]) -> int:
    assets = WORK / "assets"
    draw_assets(assets)
    if "--preview" in argv:
        print(assets)
        return 0

    import PyInstaller.__main__

    check_resources()
    os.environ["PO_ASSETS"] = str(assets)
    PyInstaller.__main__.run([
        str(ROOT / "scripts" / "PhotoOrganizer.spec"),
        "--noconfirm",
        "--clean",
        "--distpath", str(BUILD_DIST),
        "--workpath", str(WORK / "build"),
    ])  # fmt: skip
    DIST.mkdir(exist_ok=True)
    portable = DIST / "PhotoOrganizer-portable.exe"
    shutil.copy2(BUILD_DIST / portable.name, portable)
    outputs = [portable]
    folder = BUILD_DIST / "PhotoOrganizer"

    compiler = inno_compiler()
    if compiler:
        subprocess.run(
            [
                str(compiler),
                "/Q",
                f"/DAppVersion={__version__}",
                f"/DSourceDir={folder}",
                f"/DIconFile={assets / 'icon.ico'}",
                f"/O{DIST}",
                str(ROOT / "scripts" / "installer.iss"),
            ],
            check=True,
        )
        outputs.append(DIST / f"PhotoOrganizer-Setup-{__version__}.exe")
    else:
        print("\nInno Setup não encontrado: o instalador não foi gerado.")
        print("Instale com `winget install JRSoftware.InnoSetup` e rode de novo.")

    installed = sum(f.stat().st_size for f in folder.rglob("*") if f.is_file())
    print(f"\n{folder}  (pasta instalada, {installed / 1e6:.0f} MB)")
    for exe in outputs:
        print(f"{exe}  ({exe.stat().st_size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
