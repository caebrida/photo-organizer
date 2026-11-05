# Spec do PyInstaller. Não rode direto: use scripts/build_exe.py, que desenha a tela de
# abertura e o ícone (pasta PO_ASSETS) e depois chama este arquivo.
# Uma única análise gera as duas versões:
#   - dist/PhotoOrganizer-portable.exe: arquivo único, com tela de abertura;
#   - PhotoOrganizer/ (fora do OneDrive): pasta que o instalador (scripts/installer.iss) empacota.
import os
from pathlib import Path

ROOT = Path(SPECPATH).parent
PKG = ROOT / "photo_organizer"
RES = PKG / "resources"
ASSETS = Path(os.environ["PO_ASSETS"])
ICON = str(ASSETS / "icon.ico")

# O ExifTool acha as DLLs do Perl na própria pasta; a cópia solta na raiz é desperdício.
EXIFTOOL_DLLS = {p.name.lower() for p in (RES / "exiftool" / "exiftool_files").glob("*.dll")}
DROP_PREFIXES = (
    "opengl32sw.dll",  # OpenGL por software (21 MB): a interface não usa OpenGL
    "opencv_videoio_ffmpeg",  # vídeo no OpenCV (31 MB): o programa não abre vídeos com ele
    "libssl-3",  # OpenSSL (6 MB): só serviria ao TLS do QtNetwork, que o programa não usa
    "libcrypto-3",
)
DROP_DIRS = (
    "pyside6/plugins/tls/",
    "pyside6/plugins/networkinformation/",
    "pyside6/plugins/generic/",
    "pyside6/plugins/platforms/qdirect2d",
    "pyside6/plugins/platforms/qminimal",
    "pyside6/plugins/platforms/qoffscreen",
)
QT_TRANSLATIONS = ("qtbase_pt_br.qm", "qtbase_en.qm")  # as únicas que app.py carrega


def keep(dest: str) -> bool:
    path = dest.replace("\\", "/").lower()
    name = path.rsplit("/", 1)[-1]
    if name.startswith(DROP_PREFIXES) or path.startswith(DROP_DIRS):
        return False
    if path.startswith("pyside6/translations/"):
        return name in QT_TRANSLATIONS
    return not ("/" not in path and name in EXIFTOOL_DLLS)


a = Analysis(
    [str(PKG / "__main__.py")],
    pathex=[str(ROOT)],
    datas=[
        (str(RES), "photo_organizer/resources"),
        (str(PKG / "i18n" / "en.qm"), "photo_organizer/i18n"),
        (str(PKG / "ui" / "theme.qss"), "photo_organizer/ui"),
    ],
    excludes=["ssl", "_ssl", "_hashlib"],  # hashlib usa o blake2b embutido, sem OpenSSL
)
a.binaries = [b for b in a.binaries if keep(b[0])]
a.datas = [d for d in a.datas if keep(d[0])]
pyz = PYZ(a.pure)

splash = Splash(
    str(ASSETS / "splash.png"),
    binaries=a.binaries,
    datas=a.datas,
    text_pos=None,
)
portable = EXE(
    pyz,
    a.scripts,
    splash,
    splash.binaries,
    a.binaries,
    a.datas,
    name="PhotoOrganizer-portable",
    icon=ICON,
    console=False,
    upx=False,
)

app = EXE(
    pyz,
    a.scripts,
    exclude_binaries=True,
    name="PhotoOrganizer",
    icon=ICON,
    console=False,
    upx=False,
)
COLLECT(app, a.binaries, a.datas, name="PhotoOrganizer", upx=False)
