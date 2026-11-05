"""Ícones Lucide (licença ISC) desenhados na cor pedida."""

from __future__ import annotations

from functools import cache

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from photo_organizer.ui import theme

_PATHS = {
    "folder": '<path d="M20 20a2 2 0 0 0 2-2V8a2 2 0 0 0-2-2h-7.9a2 2 0 0 1-1.69-.9L9.6 3.9A2 2 0 0 0 7.93 3H4a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2Z"/>',
    "folder-open": '<path d="m6 14l1.5-2.9A2 2 0 0 1 9.24 10H20a2 2 0 0 1 1.94 2.5l-1.54 6a2 2 0 0 1-1.95 1.5H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h3.9a2 2 0 0 1 1.69.9l.81 1.2a2 2 0 0 0 1.67.9H18a2 2 0 0 1 2 2v2"/>',
    "arrow-right": '<path d="M5 12h14m-7-7l7 7l-7 7"/>',
    "refresh": '<path d="M3 12a9 9 0 0 1 9-9a9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5m5 4a9 9 0 0 1-9 9a9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
    "play": '<path d="M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z"/>',
    "square": '<rect width="18" height="18" x="3" y="3" rx="2"/>',
    "copy": '<rect width="14" height="14" x="8" y="8" rx="2" ry="2"/><path d="M4 16c-1.1 0-2-.9-2-2V4c0-1.1.9-2 2-2h10c1.1 0 2 .9 2 2"/>',
    "film": '<rect width="18" height="18" x="3" y="3" rx="2"/><path d="M7 3v18M3 7.5h4M3 12h18M3 16.5h4M17 3v18m0-13.5h4m-4 9h4"/>',
    "image": '<rect width="18" height="18" x="3" y="3" rx="2" ry="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15l-3.086-3.086a2 2 0 0 0-2.828 0L6 21"/>',
    "alert": '<path d="m21.73 18l-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3M12 9v4m0 4h.01"/>',
    "check": '<path d="M20 6L9 17l-5-5"/>',
    "file-text": '<path d="M6 22a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h8a2.4 2.4 0 0 1 1.704.706l3.588 3.588A2.4 2.4 0 0 1 20 8v12a2 2 0 0 1-2 2z"/><path d="M14 2v5a1 1 0 0 0 1 1h5M10 9H8m8 4H8m8 4H8"/>',
    "chevron-down": '<path d="m6 9l6 6l6-6"/>',
    "camera": '<path d="M13.997 4a2 2 0 0 1 1.76 1.05l.486.9A2 2 0 0 0 18.003 7H20a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V9a2 2 0 0 1 2-2h1.997a2 2 0 0 0 1.759-1.048l.489-.904A2 2 0 0 1 10.004 4z"/><circle cx="12" cy="13" r="3"/>',
}  # fmt: skip


def svg(name: str, color: str) -> bytes:
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">'
        f"{_PATHS[name]}</svg>"
    ).encode()


@cache
def pixmap(name: str, color: str, size: int = 16, ratio: float = 2.0) -> QPixmap:
    pm = QPixmap(int(size * ratio), int(size * ratio))
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    QSvgRenderer(QByteArray(svg(name, QColor(color).name()))).render(
        painter, QRectF(0, 0, pm.width(), pm.height())
    )
    painter.end()
    pm.setDevicePixelRatio(ratio)
    return pm


def icon(name: str, color: str, size: int = 16) -> QIcon:
    return QIcon(pixmap(name, color, size))


def app_icon() -> QIcon:
    result = QIcon()
    for size in (16, 24, 32, 48, 256):
        result.addPixmap(QPixmap.fromImage(app_icon_image(size)))
    return result


def app_icon_image(size: int) -> QImage:
    """Ícone do programa: quadrado arredondado em degradê com a câmera por cima.
    Usado na janela e, via scripts/build_exe.py, no .exe e na tela de abertura."""
    image = QImage(size, size, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    p = QPainter(image)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(0, 0, 0, size)
    gradient.setColorAt(0, QColor("#FFC85A"))
    gradient.setColorAt(1, QColor(theme.ACCENT))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(gradient)
    p.drawRoundedRect(QRectF(0, 0, size, size), size * 0.22, size * 0.22)
    small = size <= 24  # em 16-24 px a câmera ocupa mais o quadrado e tem traço grosso
    stroke = "2.8" if small else "2.1"
    data = svg("camera", theme.ACCENT_TEXT).replace(
        b'stroke-width="2"', f'stroke-width="{stroke}"'.encode()
    )
    m = size * (0.1 if small else 0.18)
    QSvgRenderer(QByteArray(data)).render(p, QRectF(m, m, size - 2 * m, size - 2 * m))
    p.end()
    return image
