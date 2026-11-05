"""Painel direito: prévia, dados do arquivo selecionado e destino calculado."""

from __future__ import annotations

from PySide6.QtCore import QLocale, Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from photo_organizer.core.dates import DateSource
from photo_organizer.core.images import PREVIEW
from photo_organizer.core.planner import PlanItem
from photo_organizer.core.scanner import FileKind
from photo_organizer.ui.rules_panel import section_title
from photo_organizer.ui.theme import breakable
from photo_organizer.ui.workers import ThumbnailService

PREVIEW_W, PREVIEW_H = 268, 180


class Inspector(QFrame):
    def __init__(self, service: ThumbnailService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Inspector")
        self.setFixedWidth(300)
        self._service = service
        self._item: PlanItem | None = None
        self.number_locale = QLocale()
        self.lang = "pt"
        service.thumbnailReady.connect(self._on_image)
        service.metadataReady.connect(self._on_meta)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(section_title(self.tr("Inspetor")))

        self.preview = QLabel()
        self.preview.setObjectName("Preview")
        self.preview.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview)

        head = QHBoxLayout()
        self.name = QLabel()
        self.name.setObjectName("PillPath")
        self.name.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.badge = QLabel()
        self.badge.setObjectName("Badge")
        head.addWidget(self.name, 1)
        head.addWidget(self.badge)
        layout.addLayout(head)

        self.grid = QGridLayout()
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(7)
        self.values: dict[str, QLabel] = {}
        rows = [
            ("date", self.tr("Data de captura")),
            ("camera", self.tr("Câmera")),
            ("lens", self.tr("Lente")),
            ("exposure", self.tr("Exposição")),
            ("size", self.tr("Dimensões")),
            ("sidecar", self.tr("Sidecar")),
            ("tags", self.tr("Tags")),
        ]
        for r, (key, title) in enumerate(rows):
            label = QLabel(title)
            label.setObjectName("Muted")
            value = QLabel("–")
            value.setWordWrap(True)
            value.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.grid.addWidget(label, r, 0, Qt.AlignmentFlag.AlignTop)
            self.grid.addWidget(value, r, 1)
            self.values[key] = value
        self.source_chip = QLabel()
        self.source_chip.setObjectName("SourceChip")
        self.grid.addWidget(self.source_chip, 0, 2, Qt.AlignmentFlag.AlignTop)
        self.grid.setColumnStretch(1, 1)
        layout.addLayout(self.grid)

        dest = QFrame()
        dest.setObjectName("DestBox")
        dest_layout = QVBoxLayout(dest)
        dest_layout.setContentsMargins(12, 10, 12, 10)
        dest_layout.setSpacing(4)
        self.dest_title = section_title(self.tr("Destino"))
        dest_layout.addWidget(self.dest_title)
        self.dest = QLabel()
        self.dest.setObjectName("DestPath")
        self.dest.setWordWrap(True)
        self.dest.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        dest_layout.addWidget(self.dest)
        layout.addWidget(dest)
        layout.addStretch()

        self.empty = QLabel(self.tr("Selecione um arquivo na grade para ver os detalhes."))
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        layout.insertWidget(1, self.empty)
        self.show_item(None)

    def show_item(self, item: PlanItem | None) -> None:
        self._item = item
        widgets = [self.preview, self.name, self.badge, self.dest.parentWidget(), self.source_chip]
        for w in widgets:
            w.setVisible(item is not None)
        for i in range(self.grid.count()):
            self.grid.itemAt(i).widget().setVisible(item is not None)
        self.empty.setVisible(item is None)
        if item is None:
            return

        media = item.media
        self.name.setText(media.path.name)
        self.name.setToolTip(str(media.path))
        try:
            size_mb = media.path.stat().st_size / 1_000_000
        except OSError:
            size_mb = 0
        kind = {FileKind.RAW: "RAW", FileKind.VIDEO: self.tr("Vídeo"), FileKind.JPEG: "JPEG"}
        mb = self.number_locale.toString(size_mb, "f", 1)
        self.badge.setText(f"{kind[media.kind]} · {mb} MB")

        when = item.date.value
        fmt = "%d/%m/%Y %H:%M:%S" if self.lang == "pt" else "%Y-%m-%d %H:%M:%S"
        self.values["date"].setText(when.strftime(fmt) if when else self.tr("sem data"))
        chip = {
            DateSource.EXIF: "EXIF",
            DateSource.XMP_SIDECAR: "XMP",
            DateSource.XMP_EMBEDDED: "XMP",
            DateSource.VIDEO: self.tr("VÍDEO"),
        }.get(item.date.source)
        self.source_chip.setText(chip or "")
        self.source_chip.setVisible(chip is not None)
        for key in ("camera", "lens", "exposure", "size", "tags"):
            self.values[key].setText("…")
        self.values["sidecar"].setText(media.sidecar.name if media.sidecar else "–")
        self.dest_title.setText(
            (self.tr("Fica onde está") if item.skip else self.tr("Destino")).upper()
        )
        self.dest.setText(breakable(item.dest))
        if item.duplicate:
            self.dest.setToolTip(self.tr("Duplicada potencial: vai para a pasta de validação."))

        self.preview.setPixmap(QPixmap())
        self.preview.setText(self.tr("Vídeo") if media.kind is FileKind.VIDEO else "")
        if media.kind is not FileKind.VIDEO:
            self._service.request_thumbnail(media.path, media.kind, PREVIEW)
        self._service.request_metadata(media.path, media.kind, media.sidecar)

    def _on_image(self, path: str, image: QImage, size: int) -> None:
        if size != PREVIEW or self._item is None or str(self._item.media.path) != path:
            return
        pm = QPixmap.fromImage(image)
        ratio = self.devicePixelRatioF()
        scaled = pm.scaled(
            int(PREVIEW_W * ratio),
            int(PREVIEW_H * ratio),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        scaled.setDevicePixelRatio(ratio)
        self.preview.setPixmap(scaled)

    def _on_meta(self, path: str, meta: dict) -> None:
        if self._item is None or str(self._item.media.path) != path:
            return
        make = str(meta.get("EXIF:Make", "")).strip()
        model = str(meta.get("EXIF:Model", "")).strip()
        brand = make.split()[0].lower() if make else ""
        # "Canon" + "Canon EOS R5" vira "Canon EOS R5"; "SONY" + "ILCE-6700" fica junto.
        camera = model if brand and model.lower().startswith(brand) else f"{make} {model}".strip()
        self.values["camera"].setText(camera or "–")
        self.values["lens"].setText(
            str(meta.get("EXIF:LensModel") or meta.get("Composite:LensID") or "–")
        )
        self.values["exposure"].setText(self._exposure(meta) or "–")
        size = str(meta.get("Composite:ImageSize", "")).replace("x", " ").split()
        self.values["size"].setText(" × ".join(size) if len(size) == 2 else "–")
        self.values["tags"].setText(", ".join(meta.get("Tags", [])) or "–")

    def _exposure(self, meta: dict) -> str:
        parts = []
        t = meta.get("EXIF:ExposureTime")
        if isinstance(t, int | float) and t > 0:
            parts.append(f"1/{round(1 / t)} s" if t < 1 else f"{t:g} s")
        f = meta.get("EXIF:FNumber")
        if isinstance(f, int | float):
            parts.append(f"f/{f:g}")
        iso = meta.get("EXIF:ISO")
        if iso:
            parts.append(f"ISO {iso}")
        duration = meta.get("QuickTime:Duration")
        if isinstance(duration, int | float):
            minutes, seconds = divmod(round(duration), 60)
            parts.append(f"{minutes}:{seconds:02d}")
        return " · ".join(parts)
