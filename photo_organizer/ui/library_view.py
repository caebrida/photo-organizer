"""Grade de miniaturas agrupada por data (centro do Conceito C).

O modelo é uma lista plana com linhas de cabeçalho (uma por dia) e linhas de arquivo. A
``QListView`` em modo ícone quebra a linha antes de cada cabeçalho porque ele ocupa a
largura inteira. As miniaturas são pedidas só quando a célula é desenhada.

Cada miniatura e cada dia têm uma caixa de marcação: desmarcado fica de fora (não é
copiado nem movido). Espaço e o menu do botão direito valem para a seleção.
"""

from __future__ import annotations

from collections import OrderedDict, defaultdict
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from PySide6.QtCore import (
    QAbstractListModel,
    QCoreApplication,
    QDate,
    QLocale,
    QModelIndex,
    QPersistentModelIndex,
    QRect,
    QRectF,
    QSize,
    Qt,
    Signal,
)
from PySide6.QtGui import QAction, QFont, QImage, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QListView,
    QMenu,
    QStyle,
    QStyledItemDelegate,
)

from photo_organizer.core.images import THUMB
from photo_organizer.core.planner import Plan, PlanItem, Skip
from photo_organizer.core.rules import RuleSettings
from photo_organizer.core.scanner import FileKind
from photo_organizer.ui import icons, theme
from photo_organizer.ui.workers import ThumbnailService

CARD_W, THUMB_H, CARD_H = 132, 92, 116
CHECK = 16
ItemRole = Qt.ItemDataRole.UserRole + 1


def card_check_rect(card: QRect) -> QRect:
    return QRect(card.x() + 8, card.y() + 8, CHECK, CHECK)


def header_check_rect(header: QRect) -> QRect:
    return QRect(header.x() + 2, header.y() + 14, CHECK, CHECK)


def excluded(item: PlanItem) -> bool:
    return item.skip is Skip.EXCLUDED


class Filter(StrEnum):
    ALL = "all"
    PHOTOS = "photos"
    RAW = "raw"
    VIDEO = "video"
    DUPLICATES = "dup"


@dataclass(frozen=True, slots=True)
class Header:
    title: str
    count: int
    folder: str  # pasta relativa ao destino, ex.: 2026\10\27


Row = Header | PlanItem


class LibraryModel(QAbstractListModel):
    def __init__(self, thumbnails: ThumbnailService, parent=None) -> None:
        super().__init__(parent)
        self._rows: list[Row] = []
        self._row_of: dict[str, int] = {}
        self._pixmaps: OrderedDict[str, QPixmap] = OrderedDict()
        self._service = thumbnails
        self._service.thumbnailReady.connect(self._on_thumbnail)
        self.plan: Plan | None = None
        self.filter = Filter.ALL
        self.lang = "pt"
        self._settings: RuleSettings | None = None

    MAX_PIXMAPS = 1500

    def set_plan(self, plan: Plan | None, settings: RuleSettings | None = None) -> None:
        self.beginResetModel()
        self.plan = plan
        self._rows = _build_rows(plan, self.filter, settings, self.lang) if plan else []
        self._row_of = {
            str(r.media.path): i for i, r in enumerate(self._rows) if isinstance(r, PlanItem)
        }
        self._settings = settings
        self.endResetModel()

    def set_filter(self, value: Filter) -> None:
        self.filter = value
        self.set_plan(self.plan, self._settings)

    def file_count(self) -> int:
        return len(self._row_of)

    def row_of(self, path: object) -> int | None:  # Path do arquivo
        return self._row_of.get(str(path))

    def items(self) -> list[PlanItem]:
        """Arquivos mostrados (respeita o filtro)."""
        return [r for r in self._rows if isinstance(r, PlanItem)]

    def items_of_day(self, header_row: int) -> list[PlanItem]:
        out: list[PlanItem] = []
        for r in self._rows[header_row + 1 :]:
            if isinstance(r, Header):
                break
            out.append(r)
        return out

    def rowCount(self, parent: QModelIndex | QPersistentModelIndex = QModelIndex()) -> int:  # noqa: B008, N802
        return 0 if parent.isValid() else len(self._rows)

    def flags(self, index):
        row = self._rows[index.row()]
        if isinstance(row, Header):
            return Qt.ItemFlag.ItemIsEnabled
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        row = self._rows[index.row()]
        if role == ItemRole:
            return row
        if role == Qt.ItemDataRole.DisplayRole:
            return row.title if isinstance(row, Header) else row.media.path.name
        if role == Qt.ItemDataRole.DecorationRole and isinstance(row, PlanItem):
            return self.thumbnail(row)
        return None

    def thumbnail(self, item: PlanItem) -> QPixmap | None:
        key = str(item.media.path)
        pm = self._pixmaps.get(key)
        if pm is not None:
            self._pixmaps.move_to_end(key)
            return pm
        if item.media.kind is not FileKind.VIDEO:
            self._service.request_thumbnail(item.media.path, item.media.kind, THUMB)
        return None

    def _on_thumbnail(self, path: str, image: QImage, size: int) -> None:
        if size != THUMB:
            return
        self._pixmaps[path] = QPixmap.fromImage(image)
        while len(self._pixmaps) > self.MAX_PIXMAPS:
            self._pixmaps.popitem(last=False)
        row = self._row_of.get(path)
        if row is not None:
            idx = self.index(row)
            self.dataChanged.emit(idx, idx, [Qt.ItemDataRole.DecorationRole])


def _matches(item: PlanItem, f: Filter) -> bool:
    kind = item.media.kind
    match f:
        case Filter.ALL:
            return True
        case Filter.PHOTOS:
            return kind is not FileKind.VIDEO
        case Filter.RAW:
            return kind is FileKind.RAW
        case Filter.VIDEO:
            return kind is FileKind.VIDEO
        case Filter.DUPLICATES:  # inclui as que já existem no destino
            return item.duplicate or item.skip is Skip.KEPT or item.replaces is not None


def _build_rows(plan: Plan, f: Filter, settings: RuleSettings | None, lang: str) -> list[Row]:
    by_day: dict[date | None, list[PlanItem]] = defaultdict(list)
    for item in plan.items:
        if _matches(item, f):
            by_day[item.date.value.date() if item.date.value else None].append(item)
    locale = QLocale(QLocale.Language.Portuguese if lang == "pt" else QLocale.Language.English)
    fmt = "d 'de' MMMM 'de' yyyy" if lang == "pt" else "MMMM d, yyyy"
    rows: list[Row] = []
    days = sorted((d for d in by_day if d is not None), reverse=True)
    for day in [*days, None] if None in by_day else days:
        items = sorted(by_day[day], key=lambda i: (i.date.value or 0, i.media.path.name.lower()))
        if day is None:
            title = settings.no_date_folder if settings else "—"
            folder = title
        else:
            title = locale.toString(QDate(day.year, day.month, day.day), fmt)
            folder = (
                "\\".join(settings.pattern.render(items[0].date.value, lang)) if settings else ""
            )
        rows.append(Header(title, len(items), folder))
        rows.extend(items)
    return rows


# --- Desenho ----------------------------------------------------------------------------


class LibraryDelegate(QStyledItemDelegate):
    def __init__(self, view: LibraryView) -> None:
        super().__init__(view)
        self._view = view
        self._mono = theme.mono_font(8)
        self._badge = theme.mono_font(7)
        self._title = QFont(theme.FONT_UI, 11)
        self._title.setWeight(QFont.Weight.DemiBold)

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        if isinstance(index.data(ItemRole), Header):
            return QSize(self._view.header_width(), 40)
        return QSize(CARD_W, CARD_H)

    def paint(self, painter: QPainter, option, index) -> None:
        row = index.data(ItemRole)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if isinstance(row, Header):
            day = index.model().items_of_day(index.row())
            out = sum(1 for i in day if excluded(i))
            state = True if out == 0 else False if out == len(day) else None
            self._paint_header(painter, option.rect, row, state)
        else:
            selected = bool(option.state & QStyle.StateFlag.State_Selected)
            hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
            self._paint_card(
                painter,
                option.rect,
                row,
                index.data(Qt.ItemDataRole.DecorationRole),
                selected,
                hover,
            )
        painter.restore()

    def _paint_header(self, p: QPainter, rect: QRect, h: Header, state: bool | None) -> None:
        self._paint_check(p, header_check_rect(rect), state)
        x, y = rect.x() + 2 + CHECK + 10, rect.y() + 12
        p.drawPixmap(x, y + 2, icons.pixmap("folder", theme.MUTED, 16))
        x += 26
        p.setFont(self._title)
        p.setPen(theme.color(theme.TEXT))
        fm = p.fontMetrics()
        p.drawText(x, y + 15, h.title)
        x += fm.horizontalAdvance(h.title) + 14
        p.setFont(self._mono)
        p.setPen(theme.color(theme.MUTED))
        n = self._view.number_locale.toString(h.count)
        count = (
            QCoreApplication.translate("LibraryView", "{n} itens").format(n=n)
            if h.count != 1
            else QCoreApplication.translate("LibraryView", "1 item")
        )
        p.drawText(x, y + 15, count)
        x += p.fontMetrics().horizontalAdvance(count) + 12
        p.drawPixmap(x, y + 4, icons.pixmap("arrow-right", theme.FAINT, 12))
        p.drawText(x + 20, y + 15, h.folder)

    def _paint_card(self, p: QPainter, rect: QRect, item: PlanItem, pm: QPixmap | None,
                    selected: bool, hover: bool) -> None:  # fmt: skip
        thumb = QRectF(rect.x() + 2, rect.y() + 2, CARD_W - 4, THUMB_H)
        left_out = excluded(item)
        if left_out:
            p.setOpacity(0.35)
        clip = QPainterPath()
        clip.addRoundedRect(thumb, 6, 6)
        p.fillPath(clip, theme.color(theme.CARD_HOVER if hover else theme.CARD))
        kind = item.media.kind
        if pm is not None and not pm.isNull():
            p.save()
            p.setClipPath(clip)
            scaled = pm.scaled(thumb.size().toSize() * pm.devicePixelRatio(),
                               Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                               Qt.TransformationMode.SmoothTransformation)  # fmt: skip
            scaled.setDevicePixelRatio(pm.devicePixelRatio())
            sw, sh = (
                scaled.width() / scaled.devicePixelRatio(),
                scaled.height() / scaled.devicePixelRatio(),
            )
            p.drawPixmap(int(thumb.center().x() - sw / 2), int(thumb.center().y() - sh / 2), scaled)
            p.restore()
        else:
            name = "film" if kind is FileKind.VIDEO else "image"
            p.drawPixmap(
                int(thumb.center().x() - 12),
                int(thumb.center().y() - 12),
                icons.pixmap(name, theme.FAINT, 24),
            )
        if kind is FileKind.VIDEO:
            c = thumb.center()
            p.setBrush(theme.color("#000000", 140))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(c, 14, 14)
            p.drawPixmap(int(c.x() - 6), int(c.y() - 6), icons.pixmap("play", theme.TEXT, 12))

        ext = item.media.path.suffix.lstrip(".").upper()
        color = {FileKind.RAW: theme.ACCENT, FileKind.VIDEO: theme.VIOLET}.get(kind, theme.TEXT)
        self._badge_at(p, ext, thumb.left() + 6, thumb.bottom() - 20, color, "#000000", 170)
        p.setOpacity(1.0)
        badge = None
        if item.trash:
            badge = (QCoreApplication.translate("LibraryView", "LIXEIRA"), "#FFFFFF", theme.RED)
        elif item.skip is Skip.KEPT:
            badge = (
                QCoreApplication.translate("LibraryView", "NO DESTINO"),
                theme.ACCENT_TEXT,
                theme.VIOLET,
            )
        elif item.replaces is not None:
            badge = (
                QCoreApplication.translate("LibraryView", "SUBSTITUI"),
                theme.ACCENT_TEXT,
                theme.VIOLET,
            )
        elif item.duplicate:
            badge = ("DUP", "#FFFFFF", theme.RED)
        if badge:
            p.setFont(self._badge)
            w = p.fontMetrics().horizontalAdvance(badge[0]) + 8
            self._badge_at(p, badge[0], thumb.right() - 6 - w, thumb.top() + 6, badge[1],
                           badge[2], 255)  # fmt: skip
        elif item.skip is Skip.IN_PLACE:
            p.drawPixmap(
                int(thumb.right() - 22),
                int(thumb.top() + 6),
                icons.pixmap("check", theme.GREEN, 16),
            )
        self._paint_check(p, card_check_rect(rect), not left_out)

        if selected:
            p.setPen(theme.color(theme.ACCENT))
            p.setBrush(Qt.BrushStyle.NoBrush)
            pen = p.pen()
            pen.setWidthF(2)
            p.setPen(pen)
            p.drawRoundedRect(thumb.adjusted(1, 1, -1, -1), 6, 6)
        p.setFont(self._mono)
        p.setPen(theme.color(theme.TEXT if selected else theme.MUTED))
        name = p.fontMetrics().elidedText(
            item.media.path.name, Qt.TextElideMode.ElideMiddle, CARD_W - 4
        )
        p.drawText(QRectF(rect.x() + 2, thumb.bottom() + 6, CARD_W - 4, 16),
                   Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, name)  # fmt: skip

    def _paint_check(self, p: QPainter, r: QRect, state: bool | None) -> None:
        """Marcado (vai), desmarcado (fica de fora) ou misto (só parte do dia)."""
        box = QRectF(r)
        p.setPen(theme.color(theme.ACCENT if state is not False else theme.MUTED))
        p.setBrush(theme.color(theme.ACCENT) if state else theme.color("#000000", 150))
        p.drawRoundedRect(box.adjusted(0.5, 0.5, -0.5, -0.5), 4, 4)
        if state:
            p.drawPixmap(r.x() + 2, r.y() + 2, icons.pixmap("check", theme.ACCENT_TEXT, 12))
        elif state is None:
            p.fillRect(QRectF(r.x() + 4, r.center().y() - 1, CHECK - 8, 2),
                       theme.color(theme.ACCENT))  # fmt: skip

    def _badge_at(
        self, p: QPainter, text: str, x: float, y: float, fg: str, bg: str, alpha: int
    ) -> None:
        p.setFont(self._badge)
        w = p.fontMetrics().horizontalAdvance(text) + 8
        r = QRectF(x, y, w, 14)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(theme.color(bg, alpha))
        p.drawRoundedRect(r, 3, 3)
        p.setPen(theme.color(fg))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)


class LibraryView(QListView):
    currentItemChanged = Signal(object)  # PlanItem | None
    includeRequested = Signal(list, bool)  # caminhos, True = incluir / False = deixar de fora

    SPACING = 10

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setViewMode(QListView.ViewMode.IconMode)
        self.setFlow(QListView.Flow.LeftToRight)
        self.setWrapping(True)
        self.setResizeMode(QListView.ResizeMode.Adjust)
        self.setMovement(QListView.Movement.Static)
        self.setUniformItemSizes(False)
        self.setLayoutMode(QListView.LayoutMode.Batched)
        self.setBatchSize(400)
        self.setSpacing(self.SPACING // 2)
        self.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.verticalScrollBar().setSingleStep(24)
        self.setMouseTracking(True)
        self.setItemDelegate(LibraryDelegate(self))
        self.setContentsMargins(0, 0, 0, 0)
        self.setViewportMargins(14, 4, 6, 4)
        self.number_locale = QLocale()

    def setModel(self, model) -> None:  # noqa: N802
        super().setModel(model)
        self.selectionModel().currentChanged.connect(
            lambda cur, _prev: self.currentItemChanged.emit(
                cur.data(ItemRole) if isinstance(cur.data(ItemRole), PlanItem) else None
            )
        )

    def header_width(self) -> int:
        return max(200, self.viewport().width() - self.SPACING - 2)

    def selected_items(self) -> list[PlanItem]:
        rows = (i.data(ItemRole) for i in self.selectionModel().selectedIndexes())
        return [r for r in rows if isinstance(r, PlanItem)]

    def _request(self, items: list[PlanItem], include: bool | None = None) -> None:
        """Sem ``include``: se algum está de fora, inclui todos; senão deixa todos de fora."""
        if not items:
            return
        if include is None:
            include = any(excluded(i) for i in items)
        self.includeRequested.emit([i.media.path for i in items], include)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position().toPoint()
        idx = self.indexAt(pos)
        row = idx.data(ItemRole) if idx.isValid() else None
        if event.button() == Qt.MouseButton.LeftButton and row is not None:
            rect = self.visualRect(idx)
            if isinstance(row, PlanItem) and card_check_rect(rect).contains(pos):
                self._request([row])
                return
            if isinstance(row, Header) and header_check_rect(rect).contains(pos):
                self._request(self.model().items_of_day(idx.row()))
                return
        super().mousePressEvent(event)

    def keyPressEvent(self, event) -> None:  # noqa: N802
        if event.key() == Qt.Key.Key_Space:
            self._request(self.selected_items())
            return
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        chosen = self.selected_items()
        shown = self.model().items()
        for text, items, include in (
            (QCoreApplication.translate("LibraryView", "Incluir selecionados"), chosen, True),
            (
                QCoreApplication.translate("LibraryView", "Deixar selecionados de fora"),
                chosen,
                False,
            ),
            (None, None, None),
            (QCoreApplication.translate("LibraryView", "Incluir todos os mostrados"), shown, True),
            (
                QCoreApplication.translate("LibraryView", "Deixar todos os mostrados de fora"),
                shown,
                False,
            ),
        ):
            if text is None:
                menu.addSeparator()
                continue
            act = QAction(text, menu)
            act.setEnabled(bool(items))
            act.triggered.connect(lambda _=False, i=items, inc=include: self._request(i, inc))
            menu.addAction(act)
        menu.exec(event.globalPos())

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if event.size().width() != event.oldSize().width():
            self.scheduleDelayedItemsLayout()
