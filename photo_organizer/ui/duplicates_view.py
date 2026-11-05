"""Aba Duplicadas: grupos à esquerda, comparação lado a lado à direita.

O usuário pode desmarcar um arquivo que não é duplicada; ele então segue a regra normal.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from photo_organizer.core.dates import FileDate
from photo_organizer.core.duplicates import DuplicateGroup
from photo_organizer.core.scanner import FileKind, MediaFile
from photo_organizer.ui import icons, theme
from photo_organizer.ui.rules_panel import section_title
from photo_organizer.ui.workers import ThumbnailService

COMPARE = 320
CARD_W = 240


class DuplicatesView(QSplitter):
    notDuplicatesChanged = Signal(frozenset)

    def __init__(self, service: ThumbnailService, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._service = service
        self._groups: list[DuplicateGroup] = []
        self._dates: dict[Path, FileDate] = {}
        self._not_dups: set[Path] = set()
        self._images: dict[str, QLabel] = {}
        self.folder_name = ""
        self.number_locale = QLocale()
        service.thumbnailReady.connect(self._on_image)

        left = QFrame()
        left.setObjectName("SidePanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 16, 12, 12)
        left_layout.addWidget(section_title(self.tr("Grupos de duplicadas")))
        self.list = QListWidget()
        self.list.setObjectName("SidePanel")
        self.list.currentRowChanged.connect(self._show_group)
        left_layout.addWidget(self.list)
        self.addWidget(left)

        right = QWidget()
        right.setObjectName("Center")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(20, 16, 20, 16)
        self.title = QLabel()
        self.title.setObjectName("BigCount")
        self.subtitle = QLabel(
            self.tr(
                "Fica no destino normal o arquivo mais antigo. Desmarque o que não for duplicada."
            )
        )
        self.subtitle.setObjectName("Muted")
        right_layout.addWidget(self.title)
        right_layout.addWidget(self.subtitle)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        right_layout.addWidget(self.scroll, 1)
        self.empty = QLabel(self.tr("Nenhuma duplicada encontrada."))
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        right_layout.addWidget(self.empty, 1)
        self.addWidget(right)
        self.setHandleWidth(1)
        self.setSizes([280, 900])
        self.setStretchFactor(1, 1)
        self.set_groups([], {})

    def set_groups(self, groups: list[DuplicateGroup], dates: dict[Path, FileDate]) -> None:
        self._groups, self._dates = groups, dates
        self._not_dups.clear()
        self.list.clear()
        for g in groups:
            n = len(g.duplicates)
            text = self.tr("{n} cópias").format(n=n) if n != 1 else self.tr("1 cópia")
            item = QListWidgetItem(f"{g.keep.path.name}\n{text}")
            kind_icon = "film" if g.keep.kind is FileKind.VIDEO else "image"
            item.setIcon(icons.icon(kind_icon, theme.MUTED, 16))
            self.list.addItem(item)
        has = bool(groups)
        for w in (self.title, self.subtitle, self.scroll):
            w.setVisible(has)
        self.empty.setVisible(not has)
        if has:
            self.list.setCurrentRow(0)

    def not_duplicates(self) -> frozenset[Path]:
        return frozenset(self._not_dups)

    def _show_group(self, row: int) -> None:
        self._images.clear()
        if not 0 <= row < len(self._groups):
            return
        group = self._groups[row]
        total = 1 + len(group.duplicates)
        self.title.setText(self.tr("Grupo {i} de {n} · {k} arquivos").format(
            i=row + 1, n=len(self._groups), k=total))  # fmt: skip
        body = QWidget()
        body.setObjectName("Center")
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self._card(group.keep, keep=True), 0, Qt.AlignmentFlag.AlignTop)
        for media in group.duplicates:
            layout.addWidget(self._card(media, keep=False), 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch()
        self.scroll.setWidget(body)

    def _card(self, media: MediaFile, keep: bool) -> QFrame:
        card = QFrame()
        card.setObjectName("DupCard")
        card.setProperty("keep", keep)
        card.setFixedWidth(CARD_W)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 12)
        layout.setSpacing(6)
        image = QLabel(self.tr("Vídeo") if media.kind is FileKind.VIDEO else "")
        image.setObjectName("Preview")
        image.setFixedSize(CARD_W - 20, 150)
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(image)
        if media.kind is not FileKind.VIDEO:
            self._images[str(media.path)] = image
            self._service.request_thumbnail(media.path, media.kind, COMPARE)

        name = QLabel(media.path.name)
        name.setObjectName("PillPath")
        layout.addWidget(name)
        folder = QLabel(theme.breakable(media.path.parent))
        folder.setObjectName("Mono")
        folder.setWordWrap(True)
        folder.setToolTip(str(media.path))
        layout.addWidget(folder)
        info = QLabel(self._info(media))
        info.setObjectName("Muted")
        info.setWordWrap(True)
        layout.addWidget(info)
        if keep:
            chip = QLabel("✓ " + self.tr("Fica no destino normal (mais antigo)"))
            chip.setObjectName("KeepChip")
            chip.setWordWrap(True)
            layout.addWidget(chip)
        else:
            box = QCheckBox(self.tr("Mover para «{folder}»").format(folder=self.folder_name))
            box.setChecked(media.path not in self._not_dups)
            box.toggled.connect(lambda checked, p=media.path: self._toggle(p, checked))
            layout.addWidget(box)
        return card

    def _info(self, media: MediaFile) -> str:
        try:
            st = media.path.stat()
        except OSError:
            return ""
        mb = self.number_locale.toString(st.st_size / 1_000_000, "f", 1)
        modified = datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M")
        taken = self._dates.get(media.path)
        lines = [f"{mb} MB", self.tr("Modificado: {d}").format(d=modified)]
        if taken and taken.value:
            lines.append(
                self.tr("Captura: {d}").format(d=taken.value.strftime("%d/%m/%Y %H:%M:%S"))
            )
        return "\n".join(lines)

    def _toggle(self, path: Path, is_duplicate: bool) -> None:
        if is_duplicate:
            self._not_dups.discard(path)
        else:
            self._not_dups.add(path)
        self.notDuplicatesChanged.emit(self.not_duplicates())

    def _on_image(self, path: str, image: QImage, size: int) -> None:
        label = self._images.get(path)
        if size != COMPARE or label is None:
            return
        ratio = self.devicePixelRatioF()
        pm = QPixmap.fromImage(image).scaled(
            int(label.width() * ratio),
            int(label.height() * ratio),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pm.setDevicePixelRatio(ratio)
        label.setPixmap(pm)
