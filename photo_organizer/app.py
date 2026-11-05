"""Ponto de entrada: ``python -m photo_organizer`` ou o executável."""

from __future__ import annotations

import faulthandler
import logging
import os
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QLibraryInfo, QLocale, QSettings, QStandardPaths, QTranslator
from PySide6.QtWidgets import QApplication

from photo_organizer import __version__
from photo_organizer.ui import icons, theme
from photo_organizer.ui.main_window import MainWindow

I18N_DIR = Path(__file__).parent / "i18n"


def default_language() -> str:
    return "pt" if QLocale.system().language() == QLocale.Language.Portuguese else "en"


def install_translators(app: QApplication, lang: str) -> list[QTranslator]:
    """O código-fonte está em português; em inglês carrega i18n/en.qm."""
    translators = []
    qt = QTranslator(app)
    qt_name = "qtbase_pt_BR" if lang == "pt" else "qtbase_en"
    if qt.load(qt_name, QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(qt)
        translators.append(qt)
    if lang != "pt":
        own = QTranslator(app)
        if own.load(str(I18N_DIR / f"{lang}.qm")):
            app.installTranslator(own)
            translators.append(own)
    return translators


def create_window(app: QApplication, settings: QSettings | None = None) -> MainWindow:
    settings = settings or QSettings("PhotoOrganizer", "PhotoOrganizer")
    lang = str(settings.value("lang", default_language()))
    install_translators(app, lang)
    app.setStyleSheet(theme.stylesheet())
    app.setWindowIcon(icons.app_icon())
    return MainWindow(settings, lang)


def log_path() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppLocalDataLocation)
    return Path(base) / "photo-organizer.log"


def setup_logging(path: Path) -> None:
    """Log em arquivo, para que um fechamento inesperado deixe rastro: exceções não
    tratadas (em qualquer thread) e quedas nativas do Qt/OpenCV (faulthandler)."""
    global _fault_log
    path.parent.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.FileHandler(path, encoding="utf-8")]
    if sys.stderr is not None:  # no .exe sem console não há stderr
        handlers.append(logging.StreamHandler())
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    log = logging.getLogger("photo_organizer")

    def excepthook(exc_type, exc, tb) -> None:
        log.critical("Exceção não tratada", exc_info=(exc_type, exc, tb))

    sys.excepthook = excepthook
    threading.excepthook = lambda a: excepthook(a.exc_type, a.exc_value, a.exc_traceback)
    _fault_log = path.with_suffix(".crash.log").open("a", encoding="utf-8")
    faulthandler.enable(_fault_log)
    log.info("Photo Organizer %s iniciado", __version__)


_fault_log = None  # precisa ficar aberto enquanto o programa roda


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Photo Organizer")
    app.setOrganizationName("PhotoOrganizer")
    setup_logging(log_path())
    app.aboutToQuit.connect(lambda: logging.getLogger("photo_organizer").info("Encerrado"))
    window = create_window(app)
    window.show()
    close_splash()
    return app.exec()


def close_splash() -> None:
    """Fecha a tela de abertura do PyInstaller (só existe na versão portátil)."""
    # O módulo também vai na versão instalada (as duas compartilham o código), mas lá não
    # há splash e importá-lo deixa um aviso no log. O bootloader define esta variável.
    if "_PYI_SPLASH_IPC" not in os.environ:
        return
    import pyi_splash

    pyi_splash.close()


if __name__ == "__main__":
    sys.exit(main())
