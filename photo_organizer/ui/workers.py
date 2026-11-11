"""Trabalho pesado fora da thread da interface.

- ``Task``: roda uma função no ``QThreadPool`` e devolve progresso/resultado por sinais.
- ``scan_job``, ``plan_job``, ``execute_job``: as etapas Escanear → planejar → Organizar.
- ``ThumbnailService``: miniaturas e metadados sob demanda, numa thread própria com um
  ExifTool só dela. Atende primeiro o pedido mais recente (o que está na tela).
"""

from __future__ import annotations

import logging
import threading
from collections import Counter, deque
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QObject, QRunnable, Signal
from PySide6.QtGui import QImage

from photo_organizer.core.cache import HashCache
from photo_organizer.core.dates import FileDate, date_from_name, read_dates
from photo_organizer.core.duplicates import (
    DestMatch,
    DuplicateGroup,
    duplicate_paths,
    find_duplicates,
    find_in_destination,
)
from photo_organizer.core.executor import ItemResult, Mode, Status, execute
from photo_organizer.core.images import PREVIEW, THUMB, load_image
from photo_organizer.core.metadata import MetadataReader
from photo_organizer.core.pattern import FolderPattern
from photo_organizer.core.planner import DestAction, Plan, build_plan
from photo_organizer.core.report import write_report
from photo_organizer.core.rules import RuleSettings
from photo_organizer.core.scanner import FileKind, MediaFile, scan
from photo_organizer.tagging.tagger import Tagger
from photo_organizer.tagging.xmp_writer import SUBJECT, existing_tags, write_tags

log = logging.getLogger(__name__)


class Cancelled(Exception):
    pass


class TaskSignals(QObject):
    progress = Signal(int, int, str)  # feito, total (0 = indefinido), etapa
    finished = Signal(object)
    failed = Signal(str)
    cancelled = Signal()


class Task(QRunnable):
    def __init__(self, fn: Callable[..., object], *args: object) -> None:
        super().__init__()
        self.setAutoDelete(False)  # quem cria guarda a referência
        self.fn, self.args = fn, args
        self.signals = TaskSignals()
        self.cancel = threading.Event()

    def report(self, done: int, total: int, stage: str) -> None:
        if self.cancel.is_set():
            raise Cancelled
        self.signals.progress.emit(done, total, stage)

    def run(self) -> None:
        try:
            result = self.fn(self, *self.args)
        except Cancelled:
            self.signals.cancelled.emit()
        except Exception as exc:
            log.exception("Falha na tarefa %s", getattr(self.fn, "__name__", self.fn))
            self.signals.failed.emit(str(exc) or type(exc).__name__)
        else:
            self.signals.finished.emit(result)


# --- Escanear -------------------------------------------------------------------------


@dataclass(slots=True)
class ScanResult:
    source: Path
    files: list[tuple[MediaFile, FileDate]]
    groups: list[DuplicateGroup]
    ext_counts: Counter[str] = field(default_factory=Counter)
    unreadable: list[tuple[str, str]] = field(default_factory=list)  # (pasta/arquivo, motivo)


def extension(media: MediaFile) -> str:
    return media.path.suffix.lower().lstrip(".").replace("jpeg", "jpg")


def scan_job(task: Task, source: Path, exclude: Path | None, cache_path: Path) -> ScanResult:
    files: list[MediaFile] = []
    unreadable: list[tuple[str, str]] = []

    def skipped(exc: OSError) -> None:
        unreadable.append((str(exc.filename), exc.strerror or str(exc)))

    for media in scan(source, exclude=exclude, on_error=skipped):
        files.append(media)
        if len(files) % 250 == 0:
            task.report(len(files), 0, "scan")
    task.report(len(files), 0, "scan")

    dated: list[tuple[MediaFile, FileDate]] = []
    failed: list[MediaFile] = []
    with MetadataReader() as reader, HashCache(cache_path) as cache:
        for pair in read_dates(reader, files, 200, cache, failed):
            dated.append(pair)
            if len(dated) % 200 == 0:
                task.report(len(dated), len(files), "dates")
        groups = find_duplicates(
            dated, reader, cache, progress=lambda d, t: task.report(d, t, "hashes")
        )
    unreadable += [(str(m.path), "") for m in failed]  # "": o ExifTool não abriu o arquivo
    counts = Counter(extension(m) for m, _ in dated)
    return ScanResult(Path(source), dated, groups, counts, unreadable)


@dataclass(slots=True)
class DestCheck:
    """Resultado da busca no destino: as duplicadas da origem entre si (sem as que já
    estão no destino) e as fotos da origem que o destino já tem."""

    dest: Path
    groups: list[DuplicateGroup]
    matches: list[DestMatch]


def dest_check_job(task: Task, result: ScanResult, dest: Path, cache_path: Path) -> DestCheck:
    if not result.files or dest == result.source or dest.is_relative_to(result.source):
        return DestCheck(dest, result.groups, [])  # o destino já foi lido como parte da origem
    exclude = result.source if result.source.is_relative_to(dest) else None
    files: list[MediaFile] = []
    for media in scan(dest, exclude=exclude, on_error=lambda _exc: None):
        files.append(media)
        if len(files) % 250 == 0:
            task.report(len(files), 0, "dest_scan")
    with MetadataReader() as reader, HashCache(cache_path) as cache:
        dated: list[tuple[MediaFile, FileDate]] = []
        for pair in read_dates(reader, files, 200, cache):  # ilegível no destino: só não compara
            dated.append(pair)
            if len(dated) % 200 == 0:
                task.report(len(dated), len(files), "dest_dates")
        groups, matches = find_in_destination(
            result.files,
            dated,
            reader,
            cache,
            progress=lambda d, t: task.report(d, t, "hashes"),
        )
    return DestCheck(dest, groups, matches)


# --- Planejar -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PlanOptions:
    dest: Path
    pattern: FolderPattern
    lang: str
    extensions: frozenset[str]
    separate_duplicates: bool
    duplicates_folder: str
    no_date_folder: str
    not_duplicates: frozenset[Path] = frozenset()
    name_dates: bool = True  # sem data nos metadados, usa a data do nome do arquivo
    excluded: frozenset[Path] = frozenset()  # desmarcados na lista
    trash_excluded: bool = False  # ao mover, desmarcados vão para a Lixeira
    in_dest: Mapping[Path, tuple[DestAction, MediaFile]] = field(default_factory=dict)
    listings: dict[str, frozenset[str]] = field(default_factory=dict)  # pastas do destino

    def rule_settings(self) -> RuleSettings:
        return RuleSettings(self.pattern, self.lang, self.no_date_folder, self.duplicates_folder)


def plan_job(
    task: Task | None, result: ScanResult, options: PlanOptions, check: DestCheck | None = None
) -> Plan:
    files = [
        (m, d if d.value or not options.name_dates else date_from_name(m.path.name))
        for m, d in result.files
        if extension(m) in options.extensions
    ]
    groups = check.groups if check is not None else result.groups
    duplicates: set[Path] = set()
    in_dest = dict(options.in_dest)
    if options.separate_duplicates:
        duplicates = duplicate_paths(groups) - options.not_duplicates
    else:  # sem pasta de duplicadas, "mover para duplicadas" vira organizar normalmente
        in_dest = {p: v for p, v in in_dest.items() if v[0] is not DestAction.DUPLICATE}
    return build_plan(
        files,
        options.dest,
        options.rule_settings(),
        duplicates,
        excluded=options.excluded,
        trash_excluded=options.trash_excluded,
        in_dest=in_dest,
        listings=options.listings,
    )


# --- Organizar ------------------------------------------------------------------------


@dataclass(slots=True)
class ExecutionSummary:
    counts: Counter[Status]
    kinds: Counter[str]  # done, trashed, replaced e os motivos de pular (Skip)
    report: Path
    cancelled: bool
    errors: list[ItemResult]


def execute_job(task: Task, plan: Plan, mode: Mode, report: Path, lang: str) -> ExecutionSummary:
    results: list[ItemResult] = []

    def progress(done: int, total: int, _result: ItemResult) -> None:
        if done % 10 == 0 or done == total:
            task.signals.progress.emit(done, total, "organize")

    def collect() -> Iterator[ItemResult]:
        # O próprio executor confere o cancelamento entre arquivos e marca o resto.
        for r in execute(plan, mode, progress=progress, cancel=task.cancel):
            results.append(r)
            yield r

    # O relatório é escrito arquivo a arquivo: se o programa cair no meio, o CSV mostra o
    # que já foi movido. Se ele não puder ser criado, nada é tocado.
    write_report(report, collect(), mode, lang)
    counts = Counter(r.status for r in results)
    kinds = Counter(_kind(r) for r in results)
    errors = [r for r in results if r.status in (Status.FAILED, Status.PARTIAL)]
    return ExecutionSummary(counts, kinds, report, counts[Status.CANCELLED] > 0, errors)


def _kind(r: ItemResult) -> str:
    if r.status is Status.DONE:
        return "trashed" if r.item.trash else "replaced" if r.item.replaces else "done"
    if r.status is Status.SKIPPED and r.item.skip:
        return r.item.skip.value
    return r.status.value


# --- Tags IA --------------------------------------------------------------------------


@dataclass(slots=True)
class TagItem:
    media: MediaFile
    date: FileDate
    suggested: list[str]
    current: list[str]  # que a foto já tem (no arquivo ou no sidecar)


def tag_job(task: Task, folder: Path, lang: str, hemisphere: str) -> list[TagItem]:
    """Analisa as fotos (JPEG e RAW; vídeos não, decisão 13) e sugere tags."""
    files: list[MediaFile] = []
    for media in scan(folder, kinds=[FileKind.JPEG, FileKind.RAW]):
        files.append(media)
        if len(files) % 250 == 0:
            task.report(len(files), 0, "scan")
    tagger = Tagger(lang, hemisphere)  # carrega os modelos (e falha cedo se faltarem)
    items: list[TagItem] = []
    with MetadataReader() as reader:
        # Em lotes: com 100 mil fotos a leitura dos metadados mostra progresso e cancela.
        for start in range(0, len(files), 200):
            chunk = files[start : start + 200]
            current = existing_tags(reader, chunk)
            for media, date in read_dates(reader, chunk, batch_size=200):
                suggested = _suggest(tagger, reader, media, date)
                items.append(TagItem(media, date, suggested, current[media.path]))
                task.report(len(items), len(files), "tags")
    return items


def _suggest(tagger: Tagger, reader: MetadataReader, media: MediaFile, date: FileDate) -> list[str]:
    try:
        img = load_image(media.path, media.kind, PREVIEW, reader)
        return tagger.tags(img, date.value) if img is not None else []
    except Exception:  # uma foto ruim (ex.: prévia corrompida) não derruba a análise toda
        log.warning("Não foi possível analisar %s", media.path, exc_info=True)
        return []


@dataclass(slots=True)
class TagWriteSummary:
    written: int
    errors: list[tuple[Path, str]]


def write_tags_job(task: Task, items: list[tuple[MediaFile, list[str]]]) -> TagWriteSummary:
    """``items``: só as tags novas de cada foto (TaggingView.pending já tirou as que ela tem)."""
    written, errors = 0, []
    with MetadataReader() as reader:
        for i, (media, tags) in enumerate(items, 1):
            if not media.path.exists():  # movida depois da análise: o sidecar ficaria sozinho
                errors.append((media.path, "O arquivo não está mais nesta pasta."))
                task.report(i, len(items), "write_tags")
                continue
            try:
                write_tags(reader, media, tags, current=[])
                written += 1
            except OSError as exc:
                errors.append((media.path, str(exc)))
            task.report(i, len(items), "write_tags")
    return TagWriteSummary(written, errors)


# --- Miniaturas e metadados -----------------------------------------------------------


META_TAGS = [
    "EXIF:Make",
    "EXIF:Model",
    "EXIF:LensModel",
    "Composite:LensID",
    "EXIF:ExposureTime",
    "EXIF:FNumber",
    "EXIF:ISO",
    "EXIF:FocalLength",
    "Composite:ImageSize",
    "QuickTime:Duration",
    "File:FileSize",
    SUBJECT,
]


class ThumbnailService(QObject):
    """Fila LIFO de pedidos atendida por uma thread própria."""

    thumbnailReady = Signal(str, QImage, int)  # caminho, imagem, tamanho pedido
    metadataReady = Signal(str, dict)

    MAX_QUEUE = 300

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._queue: deque[tuple[str, str, FileKind, int, Path | None]] = deque()
        self._pending: set[tuple[str, str, int]] = set()
        self._failed: set[tuple[str, str, int]] = set()  # ilegíveis: não tenta a cada repintura
        self._cond = threading.Condition()
        self._stop = False
        self._thread = threading.Thread(target=self._run, name="miniaturas", daemon=True)
        self._thread.start()

    def request_thumbnail(self, path: Path, kind: FileKind, size: int = THUMB) -> None:
        self._push(("thumb", str(path), kind, size, None))

    def request_metadata(self, path: Path, kind: FileKind, sidecar: Path | None = None) -> None:
        """Emite ``metadataReady`` com as tags de META_TAGS e, em "Tags", as palavras-chave
        do arquivo e do sidecar de tags."""
        self._push(("meta", str(path), kind, 0, sidecar))

    def stop(self) -> None:
        with self._cond:
            self._stop = True
            self._cond.notify()
        self._thread.join(timeout=5)

    def _push(self, request: tuple[str, str, FileKind, int, Path | None]) -> None:
        key = (request[0], request[1], request[3])
        with self._cond:
            if key in self._pending or key in self._failed:
                return
            self._pending.add(key)
            self._queue.append(request)
            while len(self._queue) > self.MAX_QUEUE:  # o mais antigo já saiu da tela
                old = self._queue.popleft()
                self._pending.discard((old[0], old[1], old[3]))
            self._cond.notify()

    def _run(self) -> None:
        reader: MetadataReader | None = None
        try:
            while True:
                with self._cond:
                    while not self._queue and not self._stop:
                        self._cond.wait()
                    if self._stop:
                        return
                    request = self._queue.pop()
                    self._pending.discard((request[0], request[1], request[3]))
                what, path, kind, size, sidecar = request
                try:
                    if reader is None and (what == "meta" or kind is FileKind.RAW):
                        reader = MetadataReader()
                        reader.__enter__()
                    if what == "meta":
                        assert reader is not None
                        [meta] = reader.read([path], META_TAGS) or [{}]
                        meta["Tags"] = _keywords(reader, path, kind, sidecar, meta)
                        self.metadataReady.emit(path, meta)
                    else:
                        image = self._thumbnail(Path(path), kind, size, reader)
                        if image is None:
                            self._fail(what, path, size)
                        else:
                            self.thumbnailReady.emit(path, image, size)
                except Exception:
                    log.exception("Falha ao gerar miniatura de %s", path)
                    self._fail(what, path, size)
        finally:
            if reader is not None:
                reader.__exit__(None, None, None)

    def _fail(self, what: str, path: str, size: int) -> None:
        with self._cond:
            self._failed.add((what, path, size))

    def _thumbnail(
        self, path: Path, kind: FileKind, size: int, reader: MetadataReader | None
    ) -> QImage | None:
        img = load_image(path, kind, size, reader)
        return _to_qimage(img, size) if img is not None else None


def _keywords(
    reader: MetadataReader, path: str, kind: FileKind, sidecar: Path | None, meta: dict
) -> list[str]:
    meta.pop("XMP:Subject", None)  # vem de novo, junto com IPTC e sidecar, em existing_tags
    return existing_tags(reader, [MediaFile(Path(path), kind, sidecar)])[Path(path)]


def _to_qimage(img: np.ndarray, size: int) -> QImage:
    h, w = img.shape[:2]
    scale = size / max(h, w)
    if scale < 1:
        img = cv2.resize(img, (round(w * scale), round(h * scale)), interpolation=cv2.INTER_AREA)
    rgb = np.ascontiguousarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    h, w = rgb.shape[:2]
    return QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy()
