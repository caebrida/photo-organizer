"""Aba Tags IA: escolher a pasta, analisar, revisar as tags sugeridas e gravar nos sidecars.

O trabalho pesado roda na MainWindow (Task), que liga os sinais desta aba.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from photo_organizer.core.images import PREVIEW
from photo_organizer.core.scanner import MediaFile
from photo_organizer.ui import icons, theme
from photo_organizer.ui.rules_panel import section_title
from photo_organizer.ui.workers import TagItem, ThumbnailService

PREVIEW_W, PREVIEW_H = 360, 260
COL_FILE, COL_SUGGESTED, COL_CURRENT = range(3)


def split_tags(text: str) -> list[str]:
    return list(dict.fromkeys(t.strip() for t in text.split(",") if t.strip()))


class TaggingView(QWidget):
    analyzeRequested = Signal(Path, str)  # pasta, hemisfério ("south" | "north")
    writeRequested = Signal(list)  # [(MediaFile, [tags])]

    def __init__(self, service: ThumbnailService, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Center")
        self._service = service
        self.folder: Path | None = None
        self.items: list[TagItem] = []
        self.number_locale = QLocale()
        service.thumbnailReady.connect(self._on_image)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 12)
        layout.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(10)
        title_box = QVBoxLayout()
        title_box.setSpacing(2)
        title_box.addWidget(section_title(self.tr("Tags IA")))
        self.folder_label = QLabel(self.tr("Nenhuma pasta escolhida"))
        self.folder_label.setObjectName("PillPath")
        title_box.addWidget(self.folder_label)
        head.addLayout(title_box, 1)
        self.choose_button = QPushButton(
            icons.icon("folder-open", theme.TEXT), " " + self.tr("Escolher pasta…")
        )
        self.choose_button.setObjectName("Secondary")
        self.choose_button.clicked.connect(self.choose_folder)
        self.hemisphere = QComboBox()
        self.hemisphere.addItem(self.tr("Hemisfério Sul"), "south")
        self.hemisphere.addItem(self.tr("Hemisfério Norte"), "north")
        self.hemisphere.setToolTip(self.tr("Define a estação do ano a partir da data da foto."))
        self.analyze_button = QPushButton(
            icons.icon("play", theme.ACCENT_TEXT), " " + self.tr("Analisar")
        )
        self.analyze_button.setObjectName("Primary")
        self.analyze_button.clicked.connect(self._analyze)
        for w in (self.choose_button, self.hemisphere, self.analyze_button):
            w.setFixedHeight(36)
            head.addWidget(w)
        layout.addLayout(head)

        self.body = QSplitter(Qt.Orientation.Horizontal)
        self.body.setChildrenCollapsible(False)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(
            [self.tr("Arquivo"), self.tr("Tags sugeridas (editáveis)"), self.tr("Já gravadas")]
        )
        self.table.verticalHeader().hide()
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
            | QAbstractItemView.EditTrigger.AnyKeyPressed
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(COL_FILE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(COL_SUGGESTED, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(COL_CURRENT, QHeaderView.ResizeMode.Interactive)
        header.resizeSection(COL_CURRENT, 220)
        self.table.currentCellChanged.connect(lambda row, *_: self._show_row(row))
        self.table.itemChanged.connect(lambda _: self._update_footer())
        self.body.addWidget(self.table)

        side = QFrame()
        side.setObjectName("SidePanel")
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 14, 14, 14)
        self.preview = QLabel()
        self.preview.setObjectName("Preview")
        self.preview.setFixedSize(PREVIEW_W, PREVIEW_H)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview_name = QLabel()
        self.preview_name.setObjectName("Muted")
        self.preview_name.setWordWrap(True)
        side_layout.addWidget(self.preview)
        side_layout.addWidget(self.preview_name)
        hint = QLabel(
            self.tr(
                "Separe as tags por vírgula; apague o texto para não gravar nada nessa foto. "
                "As tags vão para o sidecar .xmp (o arquivo original não muda) e somam-se às "
                "que já existem."
            )
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        side_layout.addWidget(hint)
        side_layout.addStretch()
        self.body.addWidget(side)
        self.body.setStretchFactor(0, 1)
        layout.addWidget(self.body, 1)

        self.empty = QLabel(
            self.tr(
                "Escolha uma pasta e clique em Analisar. Cena, objetos, estação e sol são "
                "detectados no computador, sem enviar fotos para a internet."
            )
        )
        self.empty.setObjectName("Muted")
        self.empty.setWordWrap(True)
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty, 1)

        foot = QHBoxLayout()
        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        foot.addWidget(self.summary, 1)
        self.write_button = QPushButton(
            icons.icon("check", theme.ACCENT_TEXT), " " + self.tr("Gravar tags")
        )
        self.write_button.setObjectName("Primary")
        self.write_button.setFixedHeight(36)
        self.write_button.clicked.connect(self._write)
        foot.addWidget(self.write_button)
        layout.addLayout(foot)

        self._busy = False
        self.set_results([])

    # --- API usada pela MainWindow --------------------------------------------------

    def set_folder(self, folder: Path | None) -> None:
        self.folder = folder
        self.folder_label.setText(str(folder) if folder else self.tr("Nenhuma pasta escolhida"))
        self.folder_label.setToolTip(str(folder) if folder else "")
        self._update_buttons()

    def set_hemisphere(self, value: str) -> None:
        self.hemisphere.setCurrentIndex(max(0, self.hemisphere.findData(value)))

    def set_busy(self, busy: bool) -> None:
        self._busy = busy
        self._update_buttons()

    def set_results(self, items: list[TagItem]) -> None:
        self.items = items
        self.table.blockSignals(True)
        self.table.setRowCount(len(items))
        for row, item in enumerate(items):
            name = QTableWidgetItem(item.media.path.name)
            name.setFlags(name.flags() & ~Qt.ItemFlag.ItemIsEditable)
            name.setToolTip(str(item.media.path))
            current = QTableWidgetItem(", ".join(item.current))
            current.setFlags(current.flags() & ~Qt.ItemFlag.ItemIsEditable)
            current.setForeground(Qt.GlobalColor.gray)
            self.table.setItem(row, COL_FILE, name)
            self.table.setItem(row, COL_SUGGESTED, QTableWidgetItem(", ".join(item.suggested)))
            self.table.setItem(row, COL_CURRENT, current)
        self.table.blockSignals(False)
        has = bool(items)
        self.body.setVisible(has)
        self.empty.setVisible(not has)
        if has:
            self.table.selectRow(0)
        self._update_footer()

    def pending(self) -> list[tuple[MediaFile, list[str]]]:
        """Fotos com tags novas (que a foto ainda não tem) e as tags a gravar."""
        out = []
        for row, item in enumerate(self.items):
            tags = split_tags(self.table.item(row, COL_SUGGESTED).text())
            if any(t not in item.current for t in tags):
                out.append((item.media, tags))
        return out

    def mark_written(self, written: list[tuple[MediaFile, list[str]]]) -> None:
        done = {m.path: tags for m, tags in written}
        self.table.blockSignals(True)
        for row, item in enumerate(self.items):
            if item.media.path in done:
                item.current = list(dict.fromkeys(item.current + done[item.media.path]))
                self.table.item(row, COL_CURRENT).setText(", ".join(item.current))
        self.table.blockSignals(False)
        self._update_footer()

    # --- Interno ----------------------------------------------------------------------

    def choose_folder(self) -> None:
        start = str(self.folder) if self.folder else ""
        path = QFileDialog.getExistingDirectory(self, self.tr("Pasta das fotos"), start)
        if path:
            self.set_folder(Path(path))

    def _analyze(self) -> None:
        if self.folder is not None:
            self.analyzeRequested.emit(self.folder, self.hemisphere.currentData())

    def _write(self) -> None:
        if items := self.pending():
            self.writeRequested.emit(items)

    def _update_buttons(self) -> None:
        self.analyze_button.setEnabled(not self._busy and self.folder is not None)
        self.choose_button.setEnabled(not self._busy)
        self.write_button.setEnabled(not self._busy and bool(self.items) and bool(self.pending()))

    def _update_footer(self) -> None:
        if not self.items:
            self.summary.setText("")
        else:
            n = self.number_locale.toString(len(self.items))
            k = self.number_locale.toString(len(self.pending()))
            self.summary.setText(
                self.tr("{n} fotos analisadas · {k} com tags novas para gravar").format(n=n, k=k)
            )
        self._update_buttons()

    def _show_row(self, row: int) -> None:
        self.preview.setPixmap(QPixmap())
        if not 0 <= row < len(self.items):
            self.preview_name.setText("")
            return
        media = self.items[row].media
        self.preview_name.setText(theme.breakable(media.path))
        self._service.request_thumbnail(media.path, media.kind, PREVIEW)

    def _on_image(self, path: str, image: QImage, size: int) -> None:
        row = self.table.currentRow()
        if size != PREVIEW or not 0 <= row < len(self.items):
            return
        if str(self.items[row].media.path) != path:
            return
        ratio = self.devicePixelRatioF()
        pm = QPixmap.fromImage(image).scaled(
            int(PREVIEW_W * ratio),
            int(PREVIEW_H * ratio),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        pm.setDevicePixelRatio(ratio)
        self.preview.setPixmap(pm)
