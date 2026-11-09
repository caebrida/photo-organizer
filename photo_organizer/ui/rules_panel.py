"""Painel esquerdo: padrão de pastas, tipos de arquivo, duplicadas, sem data e operação."""

from __future__ import annotations

from collections import Counter
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from photo_organizer.core.executor import Mode
from photo_organizer.core.pattern import PRESETS, FolderPattern, PatternError, validate_folder_name
from photo_organizer.core.rules import destination_dir
from photo_organizer.core.scanner import EXTENSIONS, FileKind
from photo_organizer.ui.theme import breakable
from photo_organizer.ui.workers import PlanOptions

# Extensões exibidas, na ordem da tela (.jpeg conta como jpg).
EXTENSION_ORDER = ["jpg", "heic", "arw", "cr2", "cr3", "crw", "dng", "mp4", "mov", "avi"]
KIND_COLOR = {FileKind.JPEG: "#EDEDED", FileKind.RAW: "#F5A623", FileKind.VIDEO: "#A78BFA"}


def section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("SectionTitle")
    return label


class RulesPanel(QScrollArea):
    changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("SidePanel")
        self.setWidgetResizable(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFixedWidth(288)
        self.lang = "pt"
        self.dest: Path | None = None
        self._sample: tuple[str, FileKind, datetime] = (
            "DSC09812.ARW",
            FileKind.RAW,
            datetime(2026, 10, 27),
        )

        body = QWidget()
        body.setObjectName("SidePanel")
        layout = QVBoxLayout(body)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(8)
        self.setWidget(body)

        # Estrutura de pastas
        layout.addWidget(section_title(self.tr("Estrutura de pastas")))
        self.preset = QComboBox()
        self.preset.addItem(self.tr("Predefinições…"), "")
        for text in PRESETS:
            self.preset.addItem(text, text)
        self.preset.activated.connect(self._apply_preset)
        layout.addWidget(self.preset)
        self.pattern = QLineEdit(self.tr("aaaa > mm > dd"))
        self.pattern.setObjectName("PatternEdit")
        self.pattern.setToolTip(
            self.tr(
                "aaaa = ano (2026) · aa = 26 · mm = mês (10) · month = Outubro · "
                "mon = Out · dd = dia\n'>' separa as pastas · texto entre aspas é literal"
            )
        )
        self.pattern.textChanged.connect(self._on_changed)
        layout.addWidget(self.pattern)
        hint = QLabel(self.tr("aaaa · aa · mm · month · mon · dd   ·   > nova pasta"))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.preview = QLabel()
        self.preview.setObjectName("Mono")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.preview)
        layout.addSpacing(10)

        # Tipos de arquivo
        layout.addWidget(section_title(self.tr("Tipos de arquivo")))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.type_boxes: dict[str, QCheckBox] = {}
        self.type_counts: dict[str, QLabel] = {}
        for row, ext in enumerate(EXTENSION_ORDER):
            box = QCheckBox(ext.upper().replace("JPG", "JPEG"))
            box.setChecked(True)
            box.toggled.connect(self._on_changed)
            dot = QLabel("●")
            dot.setStyleSheet(f"color: {KIND_COLOR[EXTENSIONS['.' + ext]]}; font-size: 7pt;")
            count = QLabel("–")
            count.setObjectName("Count")
            count.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            grid.addWidget(box, row, 0)
            grid.addWidget(dot, row, 1)
            grid.addWidget(count, row, 2)
            self.type_boxes[ext] = box
            self.type_counts[ext] = count
        grid.setColumnStretch(1, 1)
        layout.addLayout(grid)
        layout.addSpacing(10)

        # Duplicadas
        layout.addWidget(section_title(self.tr("Duplicadas")))
        self.separate = QCheckBox(self.tr("Separar em pasta"))
        self.separate.setObjectName("Toggle")
        self.separate.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
        self.separate.setChecked(True)
        self.separate.toggled.connect(self._on_changed)
        layout.addWidget(self.separate)
        self.dup_folder = QLineEdit(self.tr("Duplicadas - Validar"))
        self.dup_folder.textChanged.connect(self._on_changed)
        layout.addWidget(self.dup_folder)
        caption = QLabel(self.tr("Critério: imagem parecida tirada no mesmo instante"))
        caption.setObjectName("Muted")
        caption.setWordWrap(True)
        layout.addWidget(caption)
        layout.addSpacing(10)

        # Sem data
        layout.addWidget(section_title(self.tr("Arquivos sem data")))
        self.no_date = QLineEdit(self.tr("Sem data"))
        self.no_date.textChanged.connect(self._on_changed)
        layout.addWidget(self.no_date)
        layout.addSpacing(10)

        # Operação
        layout.addWidget(section_title(self.tr("Operação")))
        ops = QHBoxLayout()
        self.move_radio = QRadioButton(self.tr("Mover"))
        self.copy_radio = QRadioButton(self.tr("Copiar"))
        self.copy_radio.setChecked(True)
        group = QButtonGroup(self)
        group.addButton(self.move_radio)
        group.addButton(self.copy_radio)
        group.buttonToggled.connect(lambda *_: self.changed.emit())
        ops.addWidget(self.move_radio)
        ops.addWidget(self.copy_radio)
        ops.addStretch()
        layout.addLayout(ops)
        self.trash_excluded = QCheckBox(self.tr("Mandar os desmarcados para a Lixeira"))
        self.trash_excluded.setToolTip(
            self.tr("Só ao mover: os arquivos que você desmarcou na lista saem da origem e vão "
                    "para a Lixeira do Windows. Em pendrive ou rede não há Lixeira e eles ficam.")
        )  # fmt: skip
        self.trash_excluded.toggled.connect(self._on_changed)
        self.move_radio.toggled.connect(self.trash_excluded.setEnabled)
        self.trash_excluded.setEnabled(False)
        layout.addWidget(self.trash_excluded)
        note = QLabel(self.tr("Não há desfazer: cada execução gera um relatório CSV."))
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addSpacing(10)

        # Prioridade da data (informativa)
        layout.addWidget(section_title(self.tr("Prioridade da data")))
        for i, text in enumerate(
            [
                self.tr("EXIF DateTimeOriginal"),
                self.tr("XMP do sidecar (.xmp)"),
                self.tr("XMP embutido no arquivo"),
                self.tr("Data do vídeo (QuickTime)"),
            ],
            1,
        ):
            row = QLabel(f"<span style='color:#F5A623'>{i}</span>&nbsp;&nbsp;{text}")
            row.setObjectName("PriorityRow")
            layout.addWidget(row)
        self.name_dates = QCheckBox(self.tr("5  Data no nome do arquivo"))
        self.name_dates.setChecked(True)
        self.name_dates.setToolTip(
            self.tr("Ex.: IMG_20261027_143208.jpg. Só para arquivos sem nenhuma das datas acima; "
                    "sem data no nome, vão para a pasta de arquivos sem data.")
        )  # fmt: skip
        self.name_dates.toggled.connect(self._on_changed)
        layout.addWidget(self.name_dates)
        layout.addStretch()

        self.error: str | None = None
        self._refresh_preview()

    # --- API --------------------------------------------------------------------------

    def mode(self) -> Mode:
        return Mode.MOVE if self.move_radio.isChecked() else Mode.COPY

    def options(self, dest: Path) -> PlanOptions | None:
        """Opções do plano, ou ``None`` se algo digitado é inválido (ver ``self.error``)."""
        try:
            pattern = FolderPattern.parse(self.pattern.text())
            for name in (self.dup_folder.text().strip(), self.no_date.text().strip()):
                if not name:
                    raise PatternError("empty_level", "")
                validate_folder_name(name)
        except PatternError as exc:
            self.error = self._message(exc.code)
            return None
        self.error = None
        exts = {e for e, box in self.type_boxes.items() if box.isChecked()}
        if "jpg" in exts:
            exts.add("jpeg")
        return PlanOptions(
            dest=dest,
            pattern=pattern,
            lang=self.lang,
            extensions=frozenset(exts),
            separate_duplicates=self.separate.isChecked(),
            duplicates_folder=self.dup_folder.text().strip(),
            no_date_folder=self.no_date.text().strip(),
            name_dates=self.name_dates.isChecked(),
            trash_excluded=self.trash_excluded.isChecked() and self.mode() is Mode.MOVE,
        )

    def set_counts(self, counts: Counter[str]) -> None:
        merged = Counter(counts)
        merged["jpg"] += merged.pop("jpeg", 0)
        for ext, label in self.type_counts.items():
            n = merged.get(ext, 0)
            label.setText(f"{n:,}".replace(",", ".") if self.lang == "pt" else f"{n:,}")
            self.type_boxes[ext].setEnabled(n > 0)

    def set_sample(self, name: str, kind: FileKind, when: datetime) -> None:
        self._sample = (name, kind, when)
        self._refresh_preview()

    def set_dest(self, dest: Path | None) -> None:
        self.dest = dest
        self._refresh_preview()

    def save(self, settings: QSettings) -> None:
        settings.setValue("rules/pattern", self.pattern.text())
        settings.setValue("rules/separate", self.separate.isChecked())
        settings.setValue("rules/dup_folder", self.dup_folder.text())
        settings.setValue("rules/no_date", self.no_date.text())
        settings.setValue("rules/mode", self.mode().value)
        settings.setValue("rules/name_dates", self.name_dates.isChecked())
        settings.setValue("rules/trash_excluded", self.trash_excluded.isChecked())
        off = [e for e, b in self.type_boxes.items() if not b.isChecked()]
        settings.setValue("rules/off_types", ",".join(off))

    def load(self, settings: QSettings) -> None:
        self.pattern.setText(settings.value("rules/pattern", self.pattern.text()))
        self.separate.setChecked(settings.value("rules/separate", True, type=bool))
        self.dup_folder.setText(settings.value("rules/dup_folder", self.dup_folder.text()))
        self.no_date.setText(settings.value("rules/no_date", self.no_date.text()))
        self.name_dates.setChecked(settings.value("rules/name_dates", True, type=bool))
        self.trash_excluded.setChecked(settings.value("rules/trash_excluded", False, type=bool))
        mode = settings.value("rules/mode", Mode.COPY.value)
        (self.move_radio if mode == Mode.MOVE.value else self.copy_radio).setChecked(True)
        off = set(filter(None, str(settings.value("rules/off_types", "")).split(",")))
        for ext, box in self.type_boxes.items():
            box.setChecked(ext not in off)

    # --- Interno ----------------------------------------------------------------------

    def _apply_preset(self, index: int) -> None:
        text = self.preset.itemData(index)
        if text:
            self.pattern.setText(text)
        self.preset.setCurrentIndex(0)

    def _on_changed(self) -> None:
        self._refresh_preview()
        self.changed.emit()

    def _refresh_preview(self) -> None:
        options = self.options(self.dest or Path(self.tr("Destino")))
        self.pattern.setStyleSheet("border-color: #FF5C5C;" if self.error else "")
        if options is None:
            self.preview.setObjectName("Error")
            self.preview.setText(self.error or "")
        else:
            name, kind, when = self._sample
            folder = destination_dir(
                options.dest, kind, when, options.rule_settings(), duplicate=False
            )
            self.preview.setObjectName("Mono")
            self.preview.setText(breakable(folder / name))
        self.preview.style().unpolish(self.preview)
        self.preview.style().polish(self.preview)

    def _message(self, code: str) -> str:
        return {
            "empty": self.tr("Digite um padrão, por exemplo: aaaa > mm > dd"),
            "empty_level": self.tr("Há um nome de pasta vazio."),
            "unclosed_quote": self.tr("Há uma aspa sem fechamento."),
            "invalid_char": self.tr('Nomes de pasta não podem ter \\ / : * ? " < > |'),
            "trailing_dot": self.tr("Nome de pasta não pode terminar com ponto."),
            "reserved_name": self.tr("Nome reservado pelo Windows (CON, NUL, COM1…)."),
        }.get(code, self.tr("Padrão inválido."))
