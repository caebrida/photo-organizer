"""Janela principal (Conceito C, "Estúdio Pro").

Fluxo: escolher origem e destino → Escanear (thread) → o plano é recalculado a cada
mudança de regra (thread, com atraso curto) → a grade mostra o destino de cada arquivo →
Organizar (thread, com confirmação) → relatório CSV.
"""

from __future__ import annotations

import os
from collections import Counter
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import (
    QItemSelectionModel,
    QLocale,
    QSettings,
    QStandardPaths,
    Qt,
    QThreadPool,
    QTimer,
    QUrl,
)
from PySide6.QtGui import QAction, QActionGroup, QDesktopServices, QKeySequence
from PySide6.QtWidgets import (
    QButtonGroup,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from photo_organizer import __version__
from photo_organizer.core.dates import DateSource, date_from_name
from photo_organizer.core.executor import Mode, Status
from photo_organizer.core.planner import Plan
from photo_organizer.core.report import default_report_path
from photo_organizer.ui import icons, theme
from photo_organizer.ui.duplicates_view import DuplicatesView
from photo_organizer.ui.inspector import Inspector
from photo_organizer.ui.library_view import Filter, LibraryModel, LibraryView
from photo_organizer.ui.rules_panel import RulesPanel
from photo_organizer.ui.tagging_view import TaggingView
from photo_organizer.ui.workers import (
    DestCheck,
    ExecutionSummary,
    PlanOptions,
    ScanResult,
    TagItem,
    TagWriteSummary,
    Task,
    ThumbnailService,
    dest_check_job,
    execute_job,
    plan_job,
    scan_job,
    tag_job,
    write_tags_job,
)


class PathPill(QPushButton):
    def __init__(self, caption: str, icon_name: str, placeholder: str) -> None:
        super().__init__()
        self.setObjectName("PathPill")
        self.setFixedHeight(46)
        self.setMinimumWidth(230)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._placeholder = placeholder
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 4, 10, 4)
        layout.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(icons.pixmap(icon_name, theme.MUTED, 18))
        texts = QVBoxLayout()
        texts.setSpacing(0)
        cap = QLabel(caption.upper())
        cap.setObjectName("PillCaption")
        self.path_label = QLabel(placeholder)
        self.path_label.setObjectName("PillPath")
        texts.addWidget(cap)
        texts.addWidget(self.path_label)
        chevron = QLabel()
        chevron.setPixmap(icons.pixmap("chevron-down", theme.MUTED, 14))
        layout.addWidget(ic)
        layout.addLayout(texts, 1)
        layout.addWidget(chevron)
        for w in (ic, cap, self.path_label, chevron):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

    def set_path(self, path: Path | None) -> None:
        text = str(path) if path else self._placeholder
        if len(text) > 34:
            text = text[:12] + "…" + text[-21:]
        self.path_label.setText(text)
        self.setToolTip(str(path) if path else "")


class SegmentButton(QPushButton):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.setObjectName("SegmentButton")
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(6)
        self.label = QLabel(text)
        self.badge = QLabel()
        self.badge.setObjectName("CountBadge")
        self.badge.hide()
        layout.addWidget(self.label)
        layout.addWidget(self.badge)
        for w in (self.label, self.badge):
            w.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedHeight(30)
        self.toggled.connect(self._restyle)
        self._restyle(False)

    def set_count(self, n: int) -> None:
        self.badge.setText(str(n))
        self.badge.setVisible(n > 0)

    def sizeHint(self):  # noqa: N802
        hint = self.layout().sizeHint()
        hint.setHeight(30)
        return hint

    def _restyle(self, checked: bool) -> None:
        color = theme.TEXT if checked else theme.MUTED
        weight = 600 if checked else 400
        self.label.setStyleSheet(f"color: {color}; font-weight: {weight};")


class MainWindow(QMainWindow):
    def __init__(self, settings: QSettings, lang: str = "pt") -> None:
        super().__init__()
        self.settings = settings
        self.lang = lang
        self.setWindowTitle("Photo Organizer")
        self.resize(1480, 900)
        self.setMinimumSize(1100, 640)
        self.pool = QThreadPool.globalInstance()
        self.locale_ = (
            QLocale(QLocale.Language.Portuguese, QLocale.Country.Brazil)
            if lang == "pt"
            else QLocale(QLocale.Language.English, QLocale.Country.UnitedStates)
        )

        self.source: Path | None = None
        self.dest: Path | None = None
        self.scan_result: ScanResult | None = None
        self.dest_check: DestCheck | None = None  # o que o destino já tem
        self.excluded: set[Path] = set()  # desmarcados na lista: ficam de fora
        # Conteúdo das pastas do destino, reaproveitado entre planos; um dict novo (e não
        # clear()) quando o destino muda, porque um plano em andamento ainda usa o velho.
        self._listings: dict[str, frozenset[str]] = {}
        self.plan: Plan | None = None
        self._task: Task | None = None
        self.last_summary: ExecutionSummary | None = None
        self._plan_tasks: list[Task] = []
        self._plan_gen = self._done_gen = 0  # plano pedido / plano que chegou
        self._plan_timer = QTimer(self, singleShot=True, interval=250)
        self._plan_timer.timeout.connect(self._start_plan)

        self.thumbnails = ThumbnailService(self)
        self._build_menu()
        self._build_ui()
        self._load_settings()
        self._show_default_empty()
        self._update_state()

    # --- Construção -------------------------------------------------------------------

    def _build_menu(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu(self.tr("&Arquivo"))
        self.act_source = file_menu.addAction(self.tr("Escolher origem…"), self.choose_source)
        self.act_source.setShortcut(QKeySequence("Ctrl+O"))
        self.act_dest = file_menu.addAction(self.tr("Escolher destino…"), self.choose_dest)
        self.act_dest.setShortcut(QKeySequence("Ctrl+D"))
        file_menu.addSeparator()
        self.act_scan = file_menu.addAction(self.tr("Escanear"), self.start_scan)
        self.act_scan.setShortcut(QKeySequence("F5"))
        self.act_organize = file_menu.addAction(self.tr("Organizar"), self.start_organize)
        self.act_organize.setShortcut(QKeySequence("Ctrl+Return"))
        file_menu.addSeparator()
        file_menu.addAction(self.tr("Sair"), self.close).setShortcut(QKeySequence("Alt+F4"))

        view_menu = bar.addMenu(self.tr("&Exibir"))
        lang_menu = view_menu.addMenu(self.tr("Idioma"))
        group = QActionGroup(self)
        for code, name in (("pt", "Português"), ("en", "English")):
            act = QAction(name, self, checkable=True, checked=code == self.lang)
            act.triggered.connect(lambda _=False, c=code: self._set_language(c))
            group.addAction(act)
            lang_menu.addAction(act)

        help_menu = bar.addMenu(self.tr("A&juda"))
        help_menu.addAction(self.tr("Sobre o Photo Organizer"), self._about)

    def _build_ui(self) -> None:
        central = QWidget()
        central.setObjectName("Central")
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_top_bar())

        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_organize_page())
        self.duplicates = DuplicatesView(self.thumbnails)
        self.duplicates.changed.connect(self._on_duplicates_changed)
        self.pages.addWidget(self.duplicates)
        self.tagging = TaggingView(self.thumbnails)
        self.tagging.number_locale = self.locale_
        self.tagging.analyzeRequested.connect(self.start_tagging)
        self.tagging.writeRequested.connect(self.start_write_tags)
        self.pages.addWidget(self.tagging)
        root.addWidget(self.pages, 1)
        self.setCentralWidget(central)
        self._build_status_bar()

    def _build_top_bar(self) -> QWidget:
        bar = QFrame()
        bar.setObjectName("TopBar")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)
        self.source_pill = PathPill(self.tr("Origem"), "camera", self.tr("Escolher pasta…"))
        self.source_pill.clicked.connect(self.choose_source)
        self.dest_pill = PathPill(self.tr("Destino"), "folder", self.tr("Escolher pasta…"))
        self.dest_pill.clicked.connect(self.choose_dest)
        arrow = QLabel()
        arrow.setPixmap(icons.pixmap("arrow-right", theme.MUTED, 16))
        layout.addWidget(self.source_pill)
        layout.addWidget(arrow)
        layout.addWidget(self.dest_pill)
        layout.addStretch()

        segment = QFrame()
        segment.setObjectName("Segment")
        seg_layout = QHBoxLayout(segment)
        seg_layout.setContentsMargins(3, 3, 3, 3)
        seg_layout.setSpacing(2)
        self.tab_organize = SegmentButton(self.tr("Organizar"))
        self.tab_duplicates = SegmentButton(self.tr("Duplicadas"))
        self.tab_tags = SegmentButton(self.tr("Tags IA"))
        self.tabs = QButtonGroup(self)
        for i, b in enumerate((self.tab_organize, self.tab_duplicates, self.tab_tags)):
            self.tabs.addButton(b, i)
            seg_layout.addWidget(b)
        self.tab_organize.setChecked(True)
        self.tabs.idClicked.connect(self._show_page)
        layout.addWidget(segment)
        layout.addSpacing(6)

        self.scan_button = QPushButton(icons.icon("refresh", theme.TEXT), " " + self.tr("Escanear"))
        self.scan_button.setObjectName("Secondary")
        self.scan_button.clicked.connect(self.start_scan)
        self.organize_button = QPushButton(
            icons.icon("play", theme.ACCENT_TEXT), self.tr("Organizar")
        )
        self.organize_button.setObjectName("Primary")
        self.organize_button.clicked.connect(self.start_organize)
        for b in (self.scan_button, self.organize_button):
            b.setFixedHeight(38)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            layout.addWidget(b)
        return bar

    def _build_organize_page(self) -> QWidget:
        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        split.setHandleWidth(0)
        self.rules = RulesPanel()
        self.rules.lang = self.lang
        self.rules.changed.connect(self.schedule_plan)
        split.addWidget(self.rules)

        center = QWidget()
        center.setObjectName("Center")
        layout = QVBoxLayout(center)
        layout.setContentsMargins(20, 14, 12, 0)
        layout.setSpacing(10)
        head = QHBoxLayout()
        self.count_label = QLabel()
        self.count_label.setObjectName("BigCount")
        self.count_caption = QLabel()
        self.count_caption.setObjectName("Muted")
        head.addWidget(self.count_label)
        head.addSpacing(6)
        head.addWidget(self.count_caption)
        head.addStretch()
        self.filters = QButtonGroup(self)
        self.filter_buttons: dict[Filter, QPushButton] = {}
        for f, text in (
            (Filter.ALL, self.tr("Todos")),
            (Filter.PHOTOS, self.tr("Fotos")),
            (Filter.RAW, "RAW"),
            (Filter.VIDEO, self.tr("Vídeos")),
            (Filter.DUPLICATES, "● " + self.tr("Duplicadas")),
        ):
            chip = QPushButton(text)
            chip.setObjectName("FilterChip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.clicked.connect(lambda _=False, v=f: self._set_filter(v))
            self.filters.addButton(chip)
            self.filter_buttons[f] = chip
            head.addWidget(chip)
        self.filter_buttons[Filter.DUPLICATES].setStyleSheet("color: #FF8A8A;")
        self.filter_buttons[Filter.ALL].setChecked(True)
        layout.addLayout(head)

        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self._build_empty_state())
        self.library_model = LibraryModel(self.thumbnails, self)
        self.library_model.lang = self.lang
        self.library = LibraryView()
        self.library.number_locale = self.locale_
        self.library.setModel(self.library_model)
        self.center_stack.addWidget(self.library)
        layout.addWidget(self.center_stack, 1)
        split.addWidget(center)

        self.inspector = Inspector(self.thumbnails)
        self.inspector.lang = self.lang
        self.library.currentItemChanged.connect(self.inspector.show_item)
        self.library.includeRequested.connect(self._set_included)
        split.addWidget(self.inspector)
        split.setStretchFactor(1, 1)
        return split

    def _build_empty_state(self) -> QWidget:
        box = QWidget()
        layout = QVBoxLayout(box)
        layout.addStretch()
        ic = QLabel()
        ic.setPixmap(icons.pixmap("folder-open", theme.FAINT, 48))
        ic.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_title = QLabel()
        self.empty_title.setObjectName("EmptyTitle")
        self.empty_text = QLabel()
        self.empty_text.setObjectName("Muted")
        self.empty_text.setWordWrap(True)
        self.empty_text.setTextFormat(Qt.TextFormat.PlainText)  # caminhos \\servidor\...
        for w in (ic, self.empty_title, self.empty_text):
            w.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(w)

        # Depois de organizar: o resultado fica na tela até o próximo escaneamento.
        self.result_actions = QWidget()
        row = QHBoxLayout(self.result_actions)
        row.setContentsMargins(0, 16, 0, 0)
        row.addStretch()
        self.open_report_button = QPushButton(
            icons.icon("file-text", theme.ACCENT_TEXT), " " + self.tr("Abrir relatório")
        )
        self.open_report_button.setObjectName("Primary")
        self.open_report_button.clicked.connect(self.open_report)
        self.show_failures_button = QPushButton(
            icons.icon("alert", theme.TEXT), " " + self.tr("Ver falhas")
        )
        self.show_failures_button.setObjectName("Secondary")
        self.show_failures_button.clicked.connect(self.show_failures)
        self.open_dest_button = QPushButton(
            icons.icon("folder-open", theme.TEXT), " " + self.tr("Abrir destino")
        )
        self.open_dest_button.setObjectName("Secondary")
        self.open_dest_button.clicked.connect(self.open_dest)
        self.rescan_button = QPushButton(
            icons.icon("refresh", theme.TEXT), " " + self.tr("Escanear de novo")
        )
        self.rescan_button.setObjectName("Secondary")
        self.rescan_button.clicked.connect(self.start_scan)
        for b in (
            self.open_report_button,
            self.show_failures_button,
            self.open_dest_button,
            self.rescan_button,
        ):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(b)
        row.addStretch()
        self.result_actions.hide()
        layout.addWidget(self.result_actions)
        layout.addStretch(2)
        return box

    def _build_status_bar(self) -> None:
        bar = self.statusBar()
        bar.setSizeGripEnabled(False)
        self.status_icon = QLabel()
        self.status_label = QLabel()
        self.progress = QProgressBar()
        self.progress.setTextVisible(False)
        self.cancel_button = QPushButton(self.tr("Cancelar"))
        self.cancel_button.setObjectName("Link")
        self.cancel_button.clicked.connect(self.cancel_task)
        self.stats_label = QLabel()
        self.stats_label.setObjectName("Stats")
        for w in (self.status_icon, self.status_label, self.progress, self.cancel_button):
            bar.addWidget(w)
        bar.addPermanentWidget(self.stats_label)
        self._set_busy(None)

    # --- Origem / destino -------------------------------------------------------------

    def choose_source(self) -> None:
        start = str(self.source or Path.home())
        folder = QFileDialog.getExistingDirectory(self, self.tr("Pasta de origem"), start)
        if folder:
            self.set_source(Path(folder))

    def choose_dest(self) -> None:
        start = str(self.dest or self.source or Path.home())
        folder = QFileDialog.getExistingDirectory(self, self.tr("Pasta de destino"), start)
        if folder:
            self.set_dest(Path(folder))

    def set_source(self, path: Path | None) -> None:
        if path != self.source:
            self.source = path
            self.source_pill.set_path(path)
            self._clear_scan()

    def set_dest(self, path: Path | None) -> None:
        changed = path != self.dest
        self._listings = {}
        self.dest = path
        self.dest_pill.set_path(path)
        self.rules.set_dest(path)
        if self.scan_result is None:
            self._show_default_empty()
        elif changed:
            self._show_source_duplicates()
            self._start_dest_check()
        self.schedule_plan()
        self._update_state()

    # --- Escanear ---------------------------------------------------------------------

    def start_scan(self) -> None:
        if self._task is not None:
            return
        if self.source is None:
            return
        if problem := self._folder_problem(self.source):
            self._warn_folder(
                self.tr("Não foi possível acessar a pasta de origem:"), self.source, problem
            )
            return
        exclude = (
            self.dest
            if self.dest and self.dest.is_relative_to(self.source) and self.dest != self.source
            else None
        )
        task = Task(scan_job, self.source, exclude, self._cache_path())
        task.signals.finished.connect(self._on_scanned)
        self._run(task, "scan")

    def _on_scanned(self, result: ScanResult) -> None:
        self._task = None
        self._listings = {}  # escanear de novo é o "atualizar": o destino pode ter mudado
        self._set_busy(None)
        self.scan_result = result
        self.rules.set_counts(result.ext_counts)
        if result.files:
            media, date = result.files[0]
            self.rules.set_sample(media.path.name, media.kind, date.value or datetime.now())
        self._show_source_duplicates()
        if not result.files:
            self._clear_scan(
                self.tr("Nenhuma foto ou vídeo encontrado"),
                self.tr("A origem não tem JPEG, RAW ou vídeos suportados."),
                keep_result=True,
            )
        self._update_stats()
        self._start_plan()
        if result.unreadable:
            self._warn_unreadable(result.unreadable)
        self._start_dest_check()

    def _cache_path(self) -> Path:
        folder = QStandardPaths.writableLocation(
            QStandardPaths.StandardLocation.AppLocalDataLocation
        )
        return Path(folder) / "hashes.sqlite"

    def _show_source_duplicates(self) -> None:
        """Duplicadas só da origem, enquanto o destino não foi conferido."""
        self.dest_check = None
        result = self.scan_result
        groups = result.groups if result else []
        dates = {m.path: d for m, d in result.files} if result else {}
        self.duplicates.folder_name = self.rules.dup_folder.text()
        self.duplicates.set_groups(groups, dates)
        self.tab_duplicates.set_count(self.duplicates.count())

    # --- Procurar no destino ----------------------------------------------------------

    def _start_dest_check(self) -> None:
        result = self.scan_result
        if self._task is not None or result is None or not result.files or self.dest is None:
            return
        if self._folder_problem(self.dest):
            return  # o aviso aparece ao Organizar; sem destino legível não há o que comparar
        task = Task(dest_check_job, result, self.dest, self._cache_path())
        task.signals.finished.connect(self._on_dest_checked)
        self._run(task, "dest_scan")

    def _on_dest_checked(self, check: DestCheck) -> None:
        self._task = None
        self._set_busy(None)
        if self.scan_result is None or check.dest != self.dest:
            return
        self.dest_check = check
        dates = {m.path: d for m, d in self.scan_result.files}
        self.duplicates.folder_name = self.rules.dup_folder.text()
        self.duplicates.set_groups(check.groups, dates, check.matches)
        self.tab_duplicates.set_count(self.duplicates.count())
        self._update_stats()
        self.schedule_plan()

    def _on_duplicates_changed(self) -> None:
        self.schedule_plan()

    def _set_included(self, paths: list[Path], include: bool) -> None:
        if include:
            self.excluded.difference_update(paths)
        else:
            self.excluded.update(paths)
        self.schedule_plan()

    def _warn_unreadable(self, unreadable: list[tuple[str, str]]) -> None:
        fallback = self.tr("o arquivo não pôde ser aberto")
        lines = [f"• {path} — {reason or fallback}" for path, reason in unreadable[:8]]
        if len(unreadable) > 8:
            lines.append(self.tr("… e mais {n}").format(n=len(unreadable) - 8))
        intro = self.tr("{n} pastas ou arquivos não puderam ser lidos e ficaram de fora:").format(
            n=len(unreadable)
        )
        QMessageBox.warning(self, "Photo Organizer", intro + "\n\n" + "\n".join(lines))

    # --- Planejar ---------------------------------------------------------------------

    def schedule_plan(self) -> None:
        self._plan_timer.start()
        self._update_state()  # o plano atual ficou velho: Organizar espera o novo

    def _plan_pending(self) -> bool:
        return self._plan_timer.isActive() or self._done_gen != self._plan_gen

    def _start_plan(self) -> None:
        self._plan_timer.stop()
        result = self.scan_result
        if result is None or not result.files:
            self._update_state()
            return
        if self.dest is None:
            self.library_model.set_plan(None)
            self._show_empty(
                self.tr("Escolha o destino"),
                self.tr("{n} arquivos lidos. Escolha a pasta de destino para ver o plano.").format(
                    n=self.locale_.toString(len(result.files))
                ),
            )
            self.plan = None
            self._update_state()
            return
        options = self.rules.options(self.dest)
        if options is None:  # padrão inválido: o painel já mostra o erro
            self.plan = None
            self._update_state()
            return
        options = replace(
            options,
            not_duplicates=self.duplicates.not_duplicates(),
            in_dest=self.duplicates.in_dest(),
            excluded=frozenset(self.excluded),
            listings=self._listings,
        )
        self.duplicates.folder_name = options.duplicates_folder
        self._plan_gen += 1
        gen = self._plan_gen
        check = self.dest_check if self.dest_check and self.dest_check.dest == self.dest else None
        task = Task(plan_job, result, options, check)
        task.signals.finished.connect(lambda plan, g=gen, o=options: self._on_planned(plan, g, o))
        task.signals.failed.connect(self._on_failed)
        # O Task precisa de referência até terminar (setAutoDelete(False)); solta depois.
        for signal in (task.signals.finished, task.signals.failed):
            signal.connect(lambda *_, t=task: QTimer.singleShot(0, lambda: self._forget(t)))
        self._plan_tasks.append(task)
        self.pool.start(task)
        self._update_state()

    def _forget(self, task: Task) -> None:
        if task in self._plan_tasks:
            self._plan_tasks.remove(task)

    def _on_planned(self, plan: Plan, gen: int, options: PlanOptions) -> None:
        if gen != self._plan_gen or self.scan_result is None:
            return
        self._done_gen = gen
        self.plan = plan
        current = self.library.currentIndex().data(Qt.ItemDataRole.UserRole + 1)
        chosen = [i.media.path for i in self.library.selected_items()]
        self.library_model.set_plan(plan, options.rule_settings())
        self.center_stack.setCurrentWidget(self.library)
        self.inspector.show_item(None)
        if current is not None:
            self._reselect(current)
        selection = self.library.selectionModel()
        for path in chosen:
            row = self.library_model.row_of(path)
            if row is not None:
                selection.select(
                    self.library_model.index(row), QItemSelectionModel.SelectionFlag.Select
                )
        self._update_state()

    def _set_filter(self, value: Filter) -> None:
        self.library_model.set_filter(value)
        self._update_state()  # a contagem do cabeçalho acompanha o filtro

    def _reselect(self, previous) -> None:
        path = getattr(getattr(previous, "media", None), "path", None)
        row = self.library_model.row_of(path) if path is not None else None
        if row is not None:
            idx = self.library_model.index(row)
            self.library.setCurrentIndex(idx)
            self.library.scrollTo(idx)

    # --- Organizar --------------------------------------------------------------------

    def start_organize(self) -> None:
        if self._task is not None or self.plan is None or self.dest is None:
            return
        if self._plan_pending():  # destino/regras mudaram e o plano novo ainda não chegou
            return
        if problem := self._folder_problem(self.dest):
            self._warn_folder(
                self.tr("Não foi possível acessar a pasta de destino:"), self.dest, problem
            )
            return
        mode = self.rules.mode()
        todo = self.plan.to_process
        trash = self.plan.to_trash if mode is Mode.MOVE else []
        if not todo and not trash:
            QMessageBox.information(
                self, "Photo Organizer", self.tr("Nenhum arquivo para copiar ou mover.")
            )
            return
        n = self.locale_.toString(len(todo))
        if mode is Mode.MOVE:
            text = self.tr(
                "Mover {n} arquivos para\n{dest}?\n\nOs arquivos saem da origem. "
                "Não há desfazer; um relatório CSV registra cada arquivo."
            ).format(n=n, dest=self.dest)
        else:
            text = self.tr("Copiar {n} arquivos para\n{dest}?\n\nA origem não é alterada.").format(
                n=n, dest=self.dest
            )
        extra = []
        replacing = sum(1 for i in todo if i.replaces is not None)
        if replacing:
            extra.append(
                self.tr("{n} substituem fotos do destino; as antigas vão para a Lixeira.").format(
                    n=self.locale_.toString(replacing)
                )
            )
        if trash:
            extra.append(
                self.tr("{n} desmarcados saem da origem e vão para a Lixeira.").format(
                    n=self.locale_.toString(len(trash))
                )
            )
        if extra:
            text += "\n\n" + "\n".join(extra)
        box = QMessageBox(QMessageBox.Icon.Question, "Photo Organizer", text, parent=self)
        ok = box.addButton(
            self.tr("Mover") if mode is Mode.MOVE else self.tr("Copiar"),
            QMessageBox.ButtonRole.AcceptRole,
        )
        box.addButton(self.tr("Cancelar"), QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(ok)
        box.exec()
        if box.clickedButton() is not ok:
            return
        self.inspector.stop_video()  # solta o arquivo que estiver tocando
        report = default_report_path(self.dest, datetime.now())
        task = Task(execute_job, self.plan, mode, report, self.lang)
        task.signals.finished.connect(self._on_executed)
        self._run(task, "organize")

    def _on_executed(self, summary: ExecutionSummary) -> None:
        self._task = None
        self._listings = {}  # o Organizar criou pastas e arquivos no destino
        self._set_busy(None)
        c, k = summary.counts, summary.kinds
        lines = [
            self.tr("Organizados: {n}").format(n=k["done"]),
            self.tr("Já estavam no lugar: {n}").format(n=k["in-place"]),
        ]
        for key, text in (
            ("replaced", self.tr("Substituíram a do destino: {n}")),
            ("kept", self.tr("Já existiam no destino (ficou a de lá): {n}")),
            ("excluded", self.tr("Deixados de fora: {n}")),
            ("trashed", self.tr("Deixados de fora e enviados para a Lixeira: {n}")),
        ):
            if k[key]:
                lines.append(text.format(n=k[key]))
        if c[Status.PARTIAL]:
            lines.append(self.tr("Com aviso: {n}").format(n=c[Status.PARTIAL]))
        if c[Status.FAILED]:
            lines.append(self.tr("Com erro: {n}").format(n=c[Status.FAILED]))
        if c[Status.CANCELLED]:
            lines.append(self.tr("Cancelados (não tocados): {n}").format(n=c[Status.CANCELLED]))
        title = (
            self.tr("Organização cancelada")
            if summary.cancelled
            else self.tr("Organização concluída")
        )
        report_line = self.tr("Relatório: {path}").format(path=summary.report)
        # O resultado fica na janela (com os botões do relatório e das falhas) até o
        # próximo escaneamento; o aviso abaixo só informa a conclusão.
        self.last_summary = summary
        self._clear_scan()
        self._show_empty(title, "\n".join([*lines, "", report_line]), result=True)

        box = QMessageBox(QMessageBox.Icon.Information, title, "\n".join(lines), parent=self)
        if summary.errors:
            box.setIcon(QMessageBox.Icon.Warning)
        open_report = box.addButton(self.tr("Abrir relatório"), QMessageBox.ButtonRole.ActionRole)
        failures = None
        if summary.errors:
            failures = box.addButton(self.tr("Ver falhas"), QMessageBox.ButtonRole.ActionRole)
        ok = box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        box.setDefaultButton(ok)
        box.exec()
        if box.clickedButton() is open_report:
            self.open_report()
        elif failures is not None and box.clickedButton() is failures:
            self.show_failures()

    def open_report(self) -> None:
        if self.last_summary is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.last_summary.report)))

    def open_dest(self) -> None:
        if self.dest is not None:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.dest)))

    def show_failures(self) -> None:
        summary = self.last_summary
        if summary is None or not summary.errors:
            return
        n = self.locale_.toString(len(summary.errors))
        box = QMessageBox(
            QMessageBox.Icon.Warning,
            self.tr("Falhas"),
            self.tr("{n} arquivos tiveram erro ou aviso. A lista completa está no relatório.")
            .format(n=n),
            parent=self,
        )  # fmt: skip
        box.setDetailedText(
            "\n".join(
                f"{r.item.media.path}\n    {r.status.value}: {r.error}" for r in summary.errors
            )
        )
        open_report = box.addButton(self.tr("Abrir relatório"), QMessageBox.ButtonRole.ActionRole)
        box.addButton("OK", QMessageBox.ButtonRole.AcceptRole)
        box.exec()
        if box.clickedButton() is open_report:
            self.open_report()

    # --- Tags IA ----------------------------------------------------------------------

    def _show_page(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        if self.pages.currentWidget() is self.tagging and self.tagging.folder is None:
            self.tagging.set_folder(self.dest or self.source)

    def start_tagging(self, folder: Path, hemisphere: str) -> None:
        if self._task is not None:
            return
        if problem := self._folder_problem(folder):
            self._warn_folder(self.tr("Não foi possível acessar a pasta:"), folder, problem)
            return
        task = Task(tag_job, folder, self.lang, hemisphere)
        task.signals.finished.connect(self._on_tagged)
        self._run(task, "tags")

    def _on_tagged(self, items: list[TagItem]) -> None:
        self._task = None
        self._set_busy(None)
        self.tagging.set_results(items)
        if not items:
            QMessageBox.information(
                self, "Photo Organizer", self.tr("Nenhuma foto JPEG ou RAW encontrada nessa pasta.")
            )

    def start_write_tags(self, items: list) -> None:
        if self._task is not None:
            return
        text = self.tr(
            "Gravar as tags em {n} fotos?\n\nElas vão para os sidecars .xmp, somadas às que "
            "já existem; os arquivos originais não mudam."
        ).format(n=self.locale_.toString(len(items)))
        answer = QMessageBox.question(self, "Photo Organizer", text)
        if answer != QMessageBox.StandardButton.Yes:
            return
        task = Task(write_tags_job, items)
        task.signals.finished.connect(lambda summary: self._on_tags_written(items, summary))
        self._run(task, "write_tags")

    def _on_tags_written(self, items: list, summary: TagWriteSummary) -> None:
        self._task = None
        self._set_busy(None)
        failed = {path for path, _ in summary.errors}
        self.tagging.mark_written([(m, tags) for m, tags in items if m.path not in failed])
        lines = [self.tr("Fotos com tags gravadas: {n}").format(n=summary.written)]
        if summary.errors:
            lines.append(self.tr("Com erro: {n}").format(n=len(summary.errors)))
            lines += [f"• {path.name}: {error}" for path, error in summary.errors[:5]]
        box = QMessageBox.warning if summary.errors else QMessageBox.information
        box(self, self.tr("Tags gravadas"), "\n".join(lines))

    # --- Tarefas ----------------------------------------------------------------------

    def _run(self, task: Task, stage: str) -> None:
        self._task = task
        task.signals.progress.connect(self._on_progress)
        task.signals.failed.connect(self._on_failed)
        task.signals.cancelled.connect(self._on_cancelled)
        self._set_busy(stage)
        self.pool.start(task)

    def cancel_task(self) -> None:
        if self._task is not None:
            self._task.cancel.set()
            self.status_label.setText(self.tr("Cancelando…"))
            self.cancel_button.setEnabled(False)

    def _on_progress(self, done: int, total: int, stage: str) -> None:
        d, t = self.locale_.toString(done), self.locale_.toString(total)
        text = {
            "scan": self.tr("Procurando arquivos… {d}").format(d=d),
            "dates": self.tr("Lendo metadados… {d} / {t}").format(d=d, t=t),
            "hashes": self.tr("Comparando imagens… {d} / {t}").format(d=d, t=t),
            "dest_scan": self.tr("Procurando no destino… {d}").format(d=d),
            "dest_dates": self.tr("Lendo o destino… {d} / {t}").format(d=d, t=t),
            "organize": self.tr("Organizando… {d} / {t}").format(d=d, t=t),
            "tags": self.tr("Analisando fotos… {d} / {t}").format(d=d, t=t),
            "write_tags": self.tr("Gravando tags… {d} / {t}").format(d=d, t=t),
        }.get(stage, "")
        self.status_label.setText(text)
        if total:
            self.progress.setRange(0, total)
            self.progress.setValue(done)
        else:
            self.progress.setRange(0, 0)

    def _on_failed(self, message: str) -> None:
        if self._task is not None and self.sender() is self._task.signals:
            self._task = None
            self._set_busy(None)
        QMessageBox.critical(
            self, "Photo Organizer", self.tr("Ocorreu um erro:\n{m}").format(m=message)
        )
        self._update_state()

    def _on_cancelled(self) -> None:
        self._task = None
        self._set_busy(None)
        self.status_label.setText(self.tr("Tarefa cancelada."))
        self._update_state()

    def _set_busy(self, stage: str | None) -> None:
        busy = stage is not None
        self.progress.setVisible(busy)
        self.cancel_button.setVisible(busy)
        self.cancel_button.setEnabled(True)
        self.status_icon.setPixmap(
            icons.pixmap("refresh", theme.ACCENT if busy else theme.FAINT, 14)
        )
        if busy:
            self.progress.setRange(0, 0)
            self.status_label.setText(self.tr("Preparando…"))
        else:
            self.status_label.setText(self.tr("Pronto"))
        for w in (self.source_pill, self.dest_pill, self.rules, self.duplicates):
            w.setEnabled(not busy)
        self.tagging.set_busy(busy)
        self._update_state()

    # --- Estado e textos --------------------------------------------------------------

    def _clear_scan(
        self, title: str | None = None, text: str | None = None, keep_result: bool = False
    ) -> None:
        if not keep_result:
            self.scan_result = None
            self.dest_check = None
            self.excluded.clear()
            self.duplicates.set_groups([], {})
            self.tab_duplicates.set_count(0)
            self.rules.set_counts(Counter())
        self.plan = None
        self.library_model.set_plan(None)
        self.inspector.show_item(None)
        if title is None:
            self._show_default_empty()
        else:
            self._show_empty(title, text or "")
        self._update_stats()
        self._update_state()

    def _show_default_empty(self) -> None:
        if self.source is None or self.dest is None:
            self._show_empty(
                self.tr("Escolha a origem e o destino"),
                self.tr("Origem: onde estão as fotos (cartão, pasta do celular…). "
                        "Destino: onde ficará a biblioteca organizada."),
            )  # fmt: skip
        else:
            self._show_empty(
                self.tr("Pronto para escanear"),
                self.tr("Clique em Escanear para ler as datas dos arquivos da origem."),
            )

    def _show_empty(self, title: str, text: str, result: bool = False) -> None:
        self.empty_title.setText(title)
        self.empty_text.setText(text)
        self.result_actions.setVisible(result)
        if result:
            self.show_failures_button.setVisible(bool(self.last_summary.errors))
        self.center_stack.setCurrentIndex(0)

    def _update_state(self) -> None:
        busy = self._task is not None
        plan = self.plan
        todo = 0
        if plan:
            todo = len(plan.to_process)
            todo += len(plan.to_trash) if self.rules.mode() is Mode.MOVE else 0
        self.scan_button.setEnabled(not busy and self.source is not None)
        self.act_scan.setEnabled(self.scan_button.isEnabled())
        can_organize = not busy and plan is not None and todo > 0 and not self._plan_pending()
        self.organize_button.setEnabled(can_organize)
        self.act_organize.setEnabled(can_organize)
        verb = self.tr("Mover") if self.rules.mode() is Mode.MOVE else self.tr("Organizar")
        unit = self.tr("itens") if todo != 1 else self.tr("item")
        label = f"{verb} {self.locale_.toString(todo)} {unit}" if plan else self.tr("Organizar")
        self.organize_button.setText(" " + label)
        shown = self.library_model.file_count()
        total = len(plan.items) if plan else 0
        self.count_label.setText(
            self.tr("{n} itens").format(n=self.locale_.toString(shown)) if plan else ""
        )
        caption = ""
        if plan:
            caption = (
                self.tr("escaneados")
                if shown == total
                else self.tr("de {n}").format(n=self.locale_.toString(total))
            )
        self.count_caption.setText(caption)
        for chip in self.filter_buttons.values():
            chip.setVisible(plan is not None)

    def _update_stats(self) -> None:
        result = self.scan_result
        if result is None or not result.files:
            self.stats_label.setText("")
            return
        sources = Counter(d.source for _, d in result.files)
        n = self.locale_.toString
        xmp = sources[DateSource.XMP_SIDECAR] + sources[DateSource.XMP_EMBEDDED]
        named = 0
        if self.rules.name_dates.isChecked():
            named = sum(
                1 for m, d in result.files if d.value is None and date_from_name(m.path.name).value
            )
        parts = [
            f"EXIF {n(sources[DateSource.EXIF])}",
            f"XMP {n(xmp)}",
            self.tr("Vídeo {n}").format(n=n(sources[DateSource.VIDEO])),
            self.tr("Nome {n}").format(n=n(named)),
            self.tr("Sem data {n}").format(n=n(sources[None] - named)),
            self.tr("Duplicadas {n}").format(n=n(self.duplicates.count())),
        ]
        self.stats_label.setText("  ·  ".join(parts))

    # --- Acesso às pastas --------------------------------------------------------------

    def _folder_problem(self, path: Path) -> str | None:
        """Motivo de a pasta não poder ser lida, ou ``None`` se está tudo certo."""
        try:
            if not path.is_dir():
                return self.tr("A pasta não existe ou não está disponível.")
            with os.scandir(path) as entries:
                next(entries, None)  # lista de verdade: pega falta de permissão/senha
        except OSError as exc:
            return exc.strerror or str(exc)
        return None

    def _warn_folder(self, intro: str, path: Path, problem: str) -> None:
        hint = ""
        if str(path).startswith("\\\\"):
            hint = "\n\n" + self.tr(
                "Pasta de rede: abra-a uma vez no Explorador de Arquivos para entrar com "
                "usuário e senha e tente de novo."
            )
        QMessageBox.warning(self, "Photo Organizer", f"{intro}\n{path}\n\n{problem}{hint}")

    # --- Configurações e janela -------------------------------------------------------

    def _load_settings(self) -> None:
        s = self.settings
        self.rules.load(s)
        self.rules.copy_radio.toggled.connect(lambda _: self._update_state())
        self.rules.name_dates.toggled.connect(lambda _: self._update_stats())
        # Sem acessar o disco: uma pasta de rede fora do ar ou pedindo senha não pode
        # impedir a janela de abrir. O acesso é conferido ao Escanear/Organizar.
        if src := s.value("paths/source"):
            self.set_source(Path(src))
        if dst := s.value("paths/dest"):
            self.set_dest(Path(dst))
        if geometry := s.value("window/geometry"):
            self.restoreGeometry(geometry)
        self.tagging.set_hemisphere(str(s.value("tags/hemisphere", "south")))
        if folder := s.value("tags/folder"):
            self.tagging.set_folder(Path(folder))

    def _save_settings(self) -> None:
        s = self.settings
        self.rules.save(s)
        s.setValue("paths/source", str(self.source) if self.source else "")
        s.setValue("paths/dest", str(self.dest) if self.dest else "")
        s.setValue("window/geometry", self.saveGeometry())
        s.setValue("tags/hemisphere", self.tagging.hemisphere.currentData())
        s.setValue("tags/folder", str(self.tagging.folder) if self.tagging.folder else "")

    def _set_language(self, code: str) -> None:
        if code == self.lang:
            return
        self.settings.setValue("lang", code)
        QMessageBox.information(
            self,
            "Photo Organizer",
            self.tr("Reinicie o Photo Organizer para trocar o idioma.")
            if self.lang == "pt"
            else "Restart Photo Organizer to change the language.",
        )

    def _about(self) -> None:
        QMessageBox.about(
            self,
            self.tr("Sobre o Photo Organizer"),
            self.tr(
                "<b>Photo Organizer {v}</b><br>Organiza fotos e vídeos por data EXIF/XMP, "
                "separa duplicadas e sugere tags.<br><br>Usa ExifTool (Phil Harvey), Qt, OpenCV "
                "e ícones Lucide.<br>Tags: YOLOX (Megvii, Apache-2.0, via OpenCV Model Zoo) e "
                "SigLIP 2 (Google, Apache-2.0)."
            ).format(v=__version__),
        )

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        theme.use_dark_title_bar(int(self.winId()))

    def closeEvent(self, event) -> None:  # noqa: N802
        if self._task is not None:
            answer = QMessageBox.question(
                self,
                "Photo Organizer",
                self.tr("Há uma tarefa em andamento. Cancelar e sair?"),
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._task.cancel.set()
        # Sem prazo: o cancelamento vale entre arquivos, e um vídeo grande indo para o NAS
        # pode levar mais de 30 s; sair antes deixaria a cópia pela metade.
        self.pool.waitForDone()
        self._save_settings()
        self.thumbnails.stop()
        super().closeEvent(event)
