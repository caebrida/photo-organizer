"""Cores e fontes do tema escuro "Estúdio Pro" (Conceito C)."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from PySide6.QtGui import QColor, QFont

BG = "#141414"
PANEL = "#1C1C1C"
CARD = "#252525"
CARD_HOVER = "#2C2C2C"
BORDER = "#2E2E2E"
TEXT = "#EDEDED"
MUTED = "#8A8A8A"
FAINT = "#5C5C5C"
ACCENT = "#F5A623"
ACCENT_TEXT = "#1A1206"
RED = "#FF5C5C"
VIOLET = "#A78BFA"
GREEN = "#4ADE80"

FONT_UI = "Segoe UI"
FONT_MONO = '"Cascadia Mono", Consolas'


def color(hex_value: str, alpha: int = 255) -> QColor:
    c = QColor(hex_value)
    c.setAlpha(alpha)
    return c


def mono_font(point_size: float = 9) -> QFont:
    font = QFont()
    font.setFamilies([f.strip().strip('"') for f in FONT_MONO.split(",")])
    font.setPointSizeF(point_size)
    return font


def breakable(path: object) -> str:
    """Caminho que pode quebrar linha depois de cada barra (espaço de largura zero)."""
    return str(path).replace("\\", "\\\N{ZERO WIDTH SPACE}")


def _check_icon() -> str:
    """O QSS só aceita imagem por arquivo: grava o ✓ numa pasta temporária."""
    path = Path(tempfile.gettempdir()) / "photo-organizer-check.svg"
    data = (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{ACCENT_TEXT}" stroke-width="3.5" stroke-linecap="round" '
        'stroke-linejoin="round"><path d="M20 6L9 17l-5-5"/></svg>'
    )
    if not path.exists() or path.read_text() != data:
        path.write_text(data)
    return path.as_posix()


def stylesheet() -> str:
    qss = (Path(__file__).parent / "theme.qss").read_text(encoding="utf-8")
    qss = qss.replace("@CHECK_ICON", _check_icon())
    tokens = {k: v for k, v in globals().items() if k.isupper() and isinstance(v, str)}
    for key in sorted(tokens, key=len, reverse=True):  # ACCENT_TEXT antes de ACCENT
        qss = qss.replace(f"@{key}", tokens[key])
    return qss


def use_dark_title_bar(win_id: int) -> None:
    """Barra de título escura no Windows 10/11 (sem efeito em outros sistemas)."""
    if sys.platform != "win32":
        return
    import ctypes

    value = ctypes.c_int(1)
    for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (novo e antigo)
        if not ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(win_id), attribute, ctypes.byref(value), ctypes.sizeof(value)
        ):
            break
