"""Aba Duplicadas: grupos à esquerda, comparação lado a lado à direita.

Dois tipos de item na lista:

- **Cópias na origem**: o original segue a regra normal; cada cópia pode ir para a pasta
  de duplicadas (marcada) ou seguir a regra normal (desmarcada).
- **Já no destino** (marcador violeta): a foto da origem já existe no destino. O usuário
  escolhe manter a do destino, mandar a da origem para duplicadas ou substituir a do
  destino. A sugestão vem de ``core.duplicates`` (maior resolução, depois maior arquivo).

"Marcar todas" aplica uma escolha a todos os itens de uma vez.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QAction, QImage, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from photo_organizer.core.dates import FileDate
from photo_organizer.core.duplicates import DestMatch, DuplicateGroup
from photo_organizer.core.planner import DestAction
from photo_organizer.core.scanner import FileKind, MediaFile
from photo_organizer.ui import icons, theme
from photo_organizer.ui.rules_panel import section_title
from photo_organizer.ui.workers import ThumbnailService

COMPARE = 320
CARD_W = 240


class DuplicatesView(QSplitter):
    changed = Signal()  # alguma escolha mudou: o plano precisa ser refeito

    def __init__(self, service: ThumbnailService, parent: QWidget | None = None) -> None:
        super().__init__(Qt.Orientation.Horizontal, parent)
        self._service = service
        self._groups: list[DuplicateGroup] = []
        self._matches: list[DestMatch] = []
        self._dates: dict[Path, FileDate] = {}
        self._not_dups: set[Path] = set()
        self._actions: dict[Path, DestAction] = {}  # só as que o usuário mudou
        self._images: dict[str, QLabel] = {}
        self.folder_name = ""
        self.number_locale = QLocale()
        service.thumbnailReady.connect(self._on_image)

        left = QFrame()
        left.setObjectName("SidePanel")
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(12, 16, 12, 12)
        left_layout.addWidget(section_title(self.tr("Grupos de duplicadas")))
        self.bulk = QPushButton(self.tr("Marcar todas"))
        self.bulk.setToolTip(self.tr("Aplica uma escolha a todos os grupos de uma vez."))
        menu = QMenu(self.bulk)
        self.act_suggested = QAction(self.tr("Só as sugeridas"), menu)
        self.act_suggested.setToolTip(
            self.tr("Volta tudo à sugestão: cópias para a pasta de duplicadas; no destino, "
                    "fica a de maior resolução.")
        )  # fmt: skip
        self.act_all = QAction(self.tr("Selecionar todas (tudo para duplicadas)"), menu)
        self.act_none = QAction(self.tr("Nenhuma (não mover; manter as do destino)"), menu)
        for act, fn in (
            (self.act_suggested, self.mark_suggested),
            (self.act_all, self.mark_all),
            (self.act_none, self.mark_none),
        ):
            act.triggered.connect(fn)
            menu.addAction(act)
        menu.setToolTipsVisible(True)
        self.bulk.setMenu(menu)
        left_layout.addWidget(self.bulk)
        self.list = QListWidget()
        self.list.setObjectName("SidePanel")
        self.list.currentRowChanged.connect(self._show_entry)
        left_layout.addWidget(self.list)
        self.addWidget(left)

        right = QWidget()
        right.setObjectName("Center")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(20, 16, 20, 16)
        self.title = QLabel()
        self.title.setObjectName("BigCount")
        self.subtitle = QLabel()
        self.subtitle.setObjectName("Muted")
        self.subtitle.setWordWrap(True)
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

    # --- API --------------------------------------------------------------------------

    def set_groups(
        self,
        groups: list[DuplicateGroup],
        dates: dict[Path, FileDate],
        matches: list[DestMatch] | None = None,
    ) -> None:
        self._groups, self._dates, self._matches = groups, dates, list(matches or [])
        self._not_dups.clear()
        self._actions.clear()
        self.list.clear()
        for g in groups:
            n = len(g.duplicates)
            text = self.tr("{n} cópias").format(n=n) if n != 1 else self.tr("1 cópia")
            item = QListWidgetItem(f"{g.keep.path.name}\n{text}")
            kind_icon = "film" if g.keep.kind is FileKind.VIDEO else "image"
            item.setIcon(icons.icon(kind_icon, theme.MUTED, 16))
            self.list.addItem(item)
        for _ in self._matches:
            item = QListWidgetItem()
            item.setIcon(icons.icon("folder", theme.VIOLET, 16))
            self.list.addItem(item)
        self._refresh_list_texts()
        has = bool(groups or self._matches)
        for w in (self.title, self.subtitle, self.scroll):
            w.setVisible(has)
        self.empty.setVisible(not has)
        self.bulk.setEnabled(has)
        if has:
            self.list.setCurrentRow(0)

    def count(self) -> int:
        """Arquivos da origem com decisão a tomar (cópias e fotos que já estão no destino)."""
        return sum(len(g.duplicates) for g in self._groups) + len(self._matches)

    def not_duplicates(self) -> frozenset[Path]:
        return frozenset(self._not_dups)

    def in_dest(self) -> dict[Path, tuple[DestAction, MediaFile]]:
        return {m.source.path: (self.action(m), m.existing) for m in self._matches}

    def action(self, match: DestMatch) -> DestAction:
        return self._actions.get(match.source.path, match.suggested)

    def mark_suggested(self) -> None:
        self._not_dups.clear()
        self._actions.clear()
        self._after_bulk()

    def mark_all(self) -> None:
        self._not_dups.clear()
        self._actions = {m.source.path: DestAction.DUPLICATE for m in self._matches}
        self._after_bulk()

    def mark_none(self) -> None:
        self._not_dups = {m.path for g in self._groups for m in g.duplicates}
        self._actions = {m.source.path: DestAction.KEEP for m in self._matches}
        self._after_bulk()

    # --- Interno ----------------------------------------------------------------------

    def _after_bulk(self) -> None:
        self._refresh_list_texts()
        self._show_entry(self.list.currentRow())
        self.changed.emit()

    def _action_label(self, action: DestAction) -> str:
        return {
            DestAction.KEEP: self.tr("Manter a do destino (não copiar nem mover)"),
            DestAction.DUPLICATE: self.tr("Mover para «{folder}»").format(folder=self.folder_name),
            DestAction.REPLACE: self.tr("Substituir a do destino (a antiga vai para a Lixeira)"),
        }[action]

    def _refresh_list_texts(self) -> None:
        short = {
            DestAction.KEEP: self.tr("manter a do destino"),
            DestAction.DUPLICATE: self.tr("para duplicadas"),
            DestAction.REPLACE: self.tr("substituir"),
        }
        start = len(self._groups)
        for i, m in enumerate(self._matches):
            item = self.list.item(start + i)
            if item is not None:
                label = self.tr("Já no destino · {action}").format(action=short[self.action(m)])
                item.setText(f"{m.source.path.name}\n{label}")

    def _show_entry(self, row: int) -> None:
        self._images.clear()
        total = len(self._groups) + len(self._matches)
        if not 0 <= row < total:
            return
        body = QWidget()
        body.setObjectName("Center")
        layout = QHBoxLayout(body)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(14)
        if row < len(self._groups):
            group = self._groups[row]
            self.title.setText(self.tr("Grupo {i} de {n} · {k} arquivos").format(
                i=row + 1, n=total, k=1 + len(group.duplicates)))  # fmt: skip
            self.subtitle.setText(
                self.tr("Fica no destino normal o original (com data e maior). Desmarque o "
                        "que não for duplicada.")
            )  # fmt: skip
            layout.addWidget(self._card(group.keep, keep=True), 0, Qt.AlignmentFlag.AlignTop)
            for media in group.duplicates:
                layout.addWidget(self._copy_card(media), 0, Qt.AlignmentFlag.AlignTop)
        else:
            match = self._matches[row - len(self._groups)]
            self.title.setText(self.tr("Grupo {i} de {n} · já no destino").format(
                i=row + 1, n=total))  # fmt: skip
            self.subtitle.setText(
                self.tr("Esta foto da origem já existe no destino. Sugestão: ficar com a de "
                        "maior resolução e, empatando, a maior.")
            )  # fmt: skip
            existing = self._card(match.existing, dest=True, pixels=match.pixels[1])
            layout.addWidget(existing, 0, Qt.AlignmentFlag.AlignTop)
            layout.addWidget(self._match_card(match), 0, Qt.AlignmentFlag.AlignTop)
        layout.addStretch()
        self.scroll.setWidget(body)

    def _card(
        self, media: MediaFile, keep: bool = False, dest: bool = False, pixels: int = 0
    ) -> QFrame:
        card = QFrame()
        card.setObjectName("DupCard")
        card.setProperty("keep", keep)
        card.setProperty("dest", dest)
        card.setFixedWidth(CARD_W)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(10, 10, 10, 12)
        layout.setSpacing(6)
        if dest:
            chip = QLabel("● " + self.tr("JÁ NO DESTINO"))
            chip.setObjectName("DestChip")
            layout.addWidget(chip)
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
        info = QLabel(self._info(media, pixels))
        info.setObjectName("Muted")
        info.setWordWrap(True)
        layout.addWidget(info)
        if keep:
            chip = QLabel("✓ " + self.tr("Fica no destino normal (original)"))
            chip.setObjectName("KeepChip")
            chip.setWordWrap(True)
            layout.addWidget(chip)
        return card

    def _copy_card(self, media: MediaFile) -> QFrame:
        card = self._card(media)
        box = QCheckBox(self.tr("Mover para «{folder}»").format(folder=self.folder_name))
        box.setChecked(media.path not in self._not_dups)
        box.toggled.connect(lambda checked, p=media.path: self._toggle(p, checked))
        card.layout().addWidget(box)
        return card

    def _match_card(self, match: DestMatch) -> QFrame:
        card = self._card(match.source, pixels=match.pixels[0])
        group = QButtonGroup(card)
        current = self.action(match)
        for action in DestAction:
            label = self._action_label(action)
            if action is match.suggested:
                label += " · " + self.tr("sugerido")
            radio = QRadioButton(label)
            radio.setChecked(action is current)
            radio.toggled.connect(lambda on, a=action, m=match: on and self._set_action(m, a))
            group.addButton(radio)
            card.layout().addWidget(radio)
        return card

    def _info(self, media: MediaFile, pixels: int = 0) -> str:
        try:
            st = media.path.stat()
        except OSError:
            return ""
        mb = self.number_locale.toString(st.st_size / 1_000_000, "f", 1)
        modified = datetime.fromtimestamp(st.st_mtime).strftime("%d/%m/%Y %H:%M")
        first = f"{mb} MB"
        if pixels:
            mp = self.number_locale.toString(pixels / 1_000_000, "f", 1)
            first += " · " + self.tr("{mp} MP").format(mp=mp)
        lines = [first, self.tr("Modificado: {d}").format(d=modified)]
        taken = self._dates.get(media.path)
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
        self.changed.emit()

    def _set_action(self, match: DestMatch, action: DestAction) -> None:
        if action is match.suggested:
            self._actions.pop(match.source.path, None)
        else:
            self._actions[match.source.path] = action
        self._refresh_list_texts()
        self.changed.emit()

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
