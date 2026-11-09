import os
import time
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import make_jpeg, make_mp4, requires_exiftool, requires_models
from PySide6.QtCore import QObject, QSettings, Signal
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QMessageBox

from photo_organizer.app import create_window, install_translators
from photo_organizer.core.dates import NO_DATE, DateSource, FileDate
from photo_organizer.core.pattern import FolderPattern
from photo_organizer.core.planner import Plan, PlanItem
from photo_organizer.core.rules import RuleSettings
from photo_organizer.core.scanner import FileKind, MediaFile
from photo_organizer.ui.library_view import Filter, Header, ItemRole, LibraryModel, LibraryView
from photo_organizer.ui.rules_panel import RulesPanel


class FakeThumbnails(QObject):
    thumbnailReady = Signal(str, QImage, int)
    metadataReady = Signal(str, dict)

    def __init__(self) -> None:
        super().__init__()
        self.requested: list[Path] = []

    def request_thumbnail(self, path, kind, size=256) -> None:
        self.requested.append(path)


def big_plan(n: int) -> Plan:
    root = Path(r"E:\Fotos")
    start = datetime(2020, 1, 1)
    items = []
    for i in range(n):
        kind = (FileKind.JPEG, FileKind.RAW, FileKind.VIDEO)[i % 3]
        ext = {FileKind.JPEG: "JPG", FileKind.RAW: "ARW", FileKind.VIDEO: "MP4"}[kind]
        media = MediaFile(Path(rf"D:\DCIM\IMG_{i:05d}.{ext}"), kind)
        when = start + timedelta(hours=i // 3)
        date = NO_DATE if i % 50 == 0 else FileDate(when, DateSource.EXIF)
        items.append(PlanItem(media, date, root / media.path.name, duplicate=i % 97 == 0))
    return Plan(root, items)


def test_library_model_handles_50k_items(qtbot):
    service = FakeThumbnails()
    model = LibraryModel(service)
    view = LibraryView()
    qtbot.addWidget(view)
    view.setModel(model)
    view.resize(1000, 700)
    view.show()
    plan = big_plan(50_000)
    settings = RuleSettings(FolderPattern.parse("aaaa > mm > dd"))

    t = time.perf_counter()
    model.set_plan(plan, settings)
    view.doItemsLayout()
    view.viewport().repaint()
    elapsed = time.perf_counter() - t
    assert elapsed < 5, f"{elapsed:.1f}s"

    assert model.file_count() == 50_000
    rows = (model.index(r).data(ItemRole) for r in range(model.rowCount()))
    headers = [h for h in rows if isinstance(h, Header)]
    assert headers[-1].title == "Sem data"
    assert sum(h.count for h in headers) == 50_000
    # O layout em lotes desenha no próximo ciclo; só as células visíveis pedem miniatura.
    qtbot.waitUntil(lambda: len(service.requested) > 0, timeout=5_000)
    assert len(service.requested) < 200

    model.set_filter(Filter.DUPLICATES)
    assert model.file_count() == len([i for i in plan.items if i.duplicate])
    model.set_filter(Filter.VIDEO)
    assert model.file_count() == len([i for i in plan.items if i.media.kind is FileKind.VIDEO])


def test_rules_panel_validates_pattern(qtbot):
    panel = RulesPanel()
    qtbot.addWidget(panel)
    panel.set_dest(Path(r"E:\Fotos"))
    panel.pattern.setText("aaaa > month")
    options = panel.options(Path(r"E:\Fotos"))
    assert options is not None
    assert options.pattern.render(datetime(2026, 10, 27)) == ["2026", "Outubro"]
    assert "Outubro" in panel.preview.text()

    panel.pattern.setText("aaaa > fotos?")
    assert panel.options(Path(r"E:\Fotos")) is None
    assert "não podem ter" in panel.error
    assert panel.preview.text() == panel.error

    panel.dup_folder.setText("CON")
    panel.pattern.setText("aaaa")
    assert panel.options(Path(r"E:\Fotos")) is None
    assert "reservado" in panel.error


def test_rules_panel_type_filter(qtbot):
    panel = RulesPanel()
    qtbot.addWidget(panel)
    panel.set_counts(Counter({"jpeg": 2, "jpg": 3, "arw": 1}))
    assert panel.type_counts["jpg"].text() == "5"
    assert not panel.type_boxes["mp4"].isEnabled()
    panel.type_boxes["arw"].setChecked(False)
    options = panel.options(Path("E:/"))
    assert "arw" not in options.extensions
    assert {"jpg", "jpeg"} <= options.extensions


def auto_answer(monkeypatch) -> list[str]:
    """Responde as caixas de diálogo: aceita a confirmação e fecha o resumo."""
    shown: list[str] = []

    def exec_(box):
        shown.append(box.text())
        for role in (QMessageBox.ButtonRole.AcceptRole, QMessageBox.ButtonRole.RejectRole):
            for button in box.buttons():
                if box.buttonRole(button) == role:
                    button.click()
                    return 0
        return 0

    monkeypatch.setattr(QMessageBox, "exec", exec_)
    return shown


def ready(window) -> bool:
    """Escaneou, conferiu o destino e o plano atual chegou."""
    return window._task is None and window.plan is not None and not window._plan_pending()


@requires_exiftool
@pytest.mark.parametrize("mode", ["copy", "move"])
def test_full_flow_scan_review_organize(qtbot, qapp, tmp_path, monkeypatch, mode):
    src, dst = tmp_path / "origem", tmp_path / "destino"
    make_jpeg(src / "DSC0001.JPG", "2025:04:20 07:16:07")
    make_jpeg(src / "sub" / "DSC0002.jpg", "2025:07:13 03:37:14")
    make_jpeg(src / "sem_data.jpg")
    make_mp4(src / "C0001.MP4", datetime(2025, 7, 13, 12, 0, tzinfo=UTC))
    dst.mkdir()

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("lang", "pt")
    settings.setValue("rules/mode", mode)
    window = create_window(qapp, settings)
    qtbot.addWidget(window)
    window.show()
    window.set_source(src)
    window.set_dest(dst)

    window.scan_button.click()
    qtbot.waitUntil(lambda: ready(window), timeout=30_000)
    assert window.library_model.file_count() == 4
    assert window.organize_button.isEnabled()
    expected = "Organizar 4 itens" if mode == "copy" else "Mover 4 itens"
    assert window.organize_button.text().strip() == expected

    # Mudar a regra recalcula o plano sem novo escaneamento.
    window.rules.pattern.setText("aaaa > month")
    assert not window.organize_button.isEnabled()  # o plano velho não pode ser executado
    window.start_organize()  # nem pelo atalho: nada acontece até o plano novo chegar
    assert window._task is None
    qtbot.waitUntil(
        lambda: window.plan is not None and any("Abril" in str(i.dest) for i in window.plan.items),
        timeout=10_000,
    )

    shown = auto_answer(monkeypatch)
    window.organize_button.click()
    qtbot.waitUntil(lambda: window.plan is None and window._task is None, timeout=30_000)

    assert (dst / "2025" / "Abril" / "DSC0001.JPG").exists()
    assert (dst / "2025" / "Julho" / "DSC0002.jpg").exists()
    assert (dst / "2025" / "Julho" / "Video" / "C0001.MP4").exists()
    # As imagens de teste são idênticas: a sem data se liga a uma datada e vira duplicada
    # (as duas datadas não, porque foram tiradas em momentos diferentes).
    assert (dst / "Duplicadas - Validar" / "Sem data" / "sem_data.jpg").exists()
    assert len(list(dst.glob("Photo Organizer - *.csv"))) == 1
    assert (src / "DSC0001.JPG").exists() == (mode == "copy")
    assert any("Organizados: 4" in text for text in shown)
    # A janela continua aberta, com o resultado e o acesso ao relatório.
    assert window.isVisible()
    assert window.empty_title.text() == "Organização concluída"
    assert window.result_actions.isVisible()
    assert not window.show_failures_button.isVisible()  # nenhuma falha
    assert window.last_summary.report.exists()
    window.close()


def test_opens_with_unreachable_network_folder(qtbot, qapp, tmp_path, monkeypatch):
    """Pasta salva numa rede que pede senha (WinError 1326) não pode impedir a abertura."""
    share = Path(r"\\10.25.10.5\Photos\Camera Import")
    real_is_dir, real_scandir = Path.is_dir, os.scandir

    def denied(*_args):
        raise OSError(22, "Nome de usuário ou senha incorretos", str(share), 1326)

    def is_dir(self):
        return denied() if str(self).startswith(str(share)) else real_is_dir(self)

    def scandir(path="."):
        return denied() if str(path).startswith(str(share)) else real_scandir(path)

    monkeypatch.setattr(Path, "is_dir", is_dir)
    monkeypatch.setattr(os, "scandir", scandir)
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("lang", "pt")
    settings.setValue("paths/source", str(share))
    settings.setValue("paths/dest", str(share))

    window = create_window(qapp, settings)  # antes: OSError e o programa fechava
    qtbot.addWidget(window)
    assert window.source == share
    assert window.scan_button.isEnabled()

    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "warning", lambda _p, _t, text: shown.append(text))
    window.scan_button.click()
    assert window._task is None
    assert "Não foi possível acessar a pasta de origem" in shown[-1]
    assert "senha incorretos" in shown[-1]
    assert "Explorador de Arquivos" in shown[-1]
    window.close()


def test_english_translation_loads(qtbot, qapp):
    translators = install_translators(qapp, "en")
    try:
        assert translators, "en.qm não carregou (rode scripts/build_translations.py)"
        panel = RulesPanel()
        qtbot.addWidget(panel)
        assert panel.pattern.text() == "yyyy > mm > dd"
        assert panel.dup_folder.text() == "Duplicates - Review"
    finally:
        for t in translators:
            qapp.removeTranslator(t)


@requires_exiftool
@requires_models
def test_tagging_tab_analyze_review_and_write(qtbot, qapp, tmp_path, monkeypatch):
    folder = tmp_path / "fotos"
    make_jpeg(folder / "a.jpg")
    make_jpeg(folder / "sub" / "b.jpg")
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("lang", "pt")
    window = create_window(qapp, settings)
    qtbot.addWidget(window)
    window.show()
    window.set_dest(folder)
    window.tab_tags.click()
    view = window.tagging
    assert window.pages.currentWidget() is view
    assert view.folder == folder  # começa pela pasta de destino

    view.analyze_button.click()
    qtbot.waitUntil(lambda: window._task is None and len(view.items) == 2, timeout=60_000)
    view.table.item(0, 1).setText("praia, Teste manual")
    view.table.item(1, 1).setText("")  # sem tags: não grava nada nessa foto
    assert [m.path.name for m, _ in view.pending()] == ["a.jpg"]

    monkeypatch.setattr(QMessageBox, "question", lambda *a: QMessageBox.StandardButton.Yes)
    shown: list[str] = []
    monkeypatch.setattr(QMessageBox, "information", lambda _p, _t, text: shown.append(text))
    view.write_button.click()
    qtbot.waitUntil(lambda: window._task is None and bool(shown), timeout=30_000)

    assert "Fotos com tags gravadas: 1" in shown[-1]
    sidecar = folder / "a.jpg.xmp"
    text = sidecar.read_text(encoding="utf-8")
    assert "<rdf:li>praia</rdf:li>" in text and "<rdf:li>Teste manual</rdf:li>" in text
    assert not (folder / "sub" / "b.jpg.xmp").exists()
    assert view.table.item(0, 2).text() == "praia, Teste manual"
    assert not view.write_button.isEnabled()  # nada novo para gravar
    window.close()


@requires_exiftool
def test_metadata_service_reports_sidecar_tags(qtbot, tmp_path):
    from photo_organizer.core.metadata import MetadataReader
    from photo_organizer.core.scanner import scan
    from photo_organizer.tagging.xmp_writer import write_tags
    from photo_organizer.ui.workers import ThumbnailService

    make_jpeg(tmp_path / "a.jpg")
    [media] = scan(tmp_path)
    with MetadataReader() as reader:
        write_tags(reader, media, ["praia", "verão"])
    [media] = scan(tmp_path)  # agora com o sidecar a.jpg.xmp
    service = ThumbnailService()
    try:
        with qtbot.waitSignal(service.metadataReady, timeout=15_000) as blocker:
            service.request_metadata(media.path, media.kind, media.sidecar)
        assert blocker.args[1]["Tags"] == ["praia", "verão"]
    finally:
        service.stop()


@requires_exiftool
def test_write_tags_skips_photos_moved_after_analysis(tmp_path):
    from photo_organizer.ui.workers import Task, write_tags_job

    gone = MediaFile(tmp_path / "movida.jpg", FileKind.JPEG)  # saiu da pasta com "Mover"
    summary = write_tags_job(Task(write_tags_job), [(gone, ["praia"])])
    assert summary.written == 0
    assert [path for path, _ in summary.errors] == [gone.path]
    assert not (tmp_path / "movida.jpg.xmp").exists()  # nenhum sidecar sozinho


def _plan_options(dest: Path, **kw):
    from photo_organizer.ui.workers import PlanOptions

    base = dict(
        dest=dest,
        pattern=FolderPattern.parse("aaaa > mm > dd"),
        lang="pt",
        extensions=frozenset({"jpg", "jpeg", "mp4"}),
        separate_duplicates=True,
        duplicates_folder="Duplicadas - Validar",
        no_date_folder="Sem data",
    )
    return PlanOptions(**(base | kw))


def test_plan_uses_file_name_date_only_without_metadata_date(tmp_path):
    from photo_organizer.ui.workers import ScanResult, plan_job

    exif = FileDate(datetime(2025, 1, 2), DateSource.EXIF, "EXIF:DateTimeOriginal")
    files = [
        (MediaFile(tmp_path / "IMG-20261027-WA0003.jpg", FileKind.JPEG), NO_DATE),
        (MediaFile(tmp_path / "IMG_20240101_101010.jpg", FileKind.JPEG), exif),  # EXIF vence
        (MediaFile(tmp_path / "foto.jpg", FileKind.JPEG), NO_DATE),
    ]
    result = ScanResult(tmp_path, files, [])
    dest = tmp_path / "destino"
    folders = [i.dest.parent for i in plan_job(None, result, _plan_options(dest)).items]
    assert folders == [dest / "2026" / "10" / "27", dest / "2025" / "01" / "02", dest / "Sem data"]

    off = plan_job(None, result, _plan_options(dest, name_dates=False))
    assert off.items[0].dest.parent == dest / "Sem data"


@requires_exiftool
def test_destination_copies_bulk_marks_and_left_out_files(qtbot, qapp, tmp_path, monkeypatch):
    from photo_organizer.core import executor
    from photo_organizer.core.planner import DestAction, Skip

    src, dst, bin_ = tmp_path / "origem", tmp_path / "destino", tmp_path / "lixeira"
    a = make_jpeg(src / "DSC0001.JPG", "2025:04:20 07:16:07")
    b = make_jpeg(src / "DSC0002.JPG", "2025:07:13 03:37:14")
    existing = dst / "2025" / "04" / "20" / "DSC0001.JPG"
    existing.parent.mkdir(parents=True)
    existing.write_bytes(a.read_bytes())  # a mesma foto já está no destino
    bin_.mkdir()
    monkeypatch.setattr(executor, "move_to_trash", lambda p: Path(p).replace(bin_ / Path(p).name))

    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.Format.IniFormat)
    settings.setValue("lang", "pt")
    settings.setValue("rules/mode", "move")
    settings.setValue("rules/trash_excluded", True)
    window = create_window(qapp, settings)
    qtbot.addWidget(window)
    window.set_source(src)
    window.set_dest(dst)
    window.scan_button.click()
    qtbot.waitUntil(lambda: ready(window), timeout=30_000)

    def item(path):
        return next(i for i in window.plan.items if i.media.path == path)

    # Iguais em resolução e tamanho: a sugestão é ficar com a do destino.
    assert window.duplicates.count() == 1
    assert window.duplicates.in_dest()[a] == (DestAction.KEEP, MediaFile(existing, FileKind.JPEG))
    assert item(a).skip is Skip.KEPT

    window.duplicates.mark_all()  # em massa: tudo para a pasta de duplicadas
    qtbot.waitUntil(lambda: ready(window) and item(a).duplicate, timeout=10_000)
    window.duplicates.mark_suggested()
    qtbot.waitUntil(lambda: ready(window) and item(a).skip is Skip.KEPT, timeout=10_000)

    window._set_included([b], False)  # desmarcada na lista
    qtbot.waitUntil(lambda: ready(window) and item(b).trash, timeout=10_000)
    assert window.organize_button.text().strip() == "Mover 1 item"

    shown = auto_answer(monkeypatch)
    window.organize_button.click()
    qtbot.waitUntil(lambda: window.plan is None and window._task is None, timeout=30_000)
    assert a.exists()  # ficou a do destino; a da origem não foi tocada
    assert (bin_ / "DSC0002.JPG").exists()
    assert not (dst / "2025" / "07").exists()
    assert any("enviados para a Lixeira: 1" in t for t in shown)
    window.close()


def test_inspector_plays_videos_and_releases_the_file(qtbot, tmp_path):
    from photo_organizer.ui.inspector import Inspector

    service = FakeThumbnails()
    service.request_metadata = lambda *a: None
    inspector = Inspector(service)
    qtbot.addWidget(inspector)
    inspector.show()
    video = make_mp4(tmp_path / "clip.mp4", datetime(2026, 1, 1, tzinfo=UTC))
    item = PlanItem(MediaFile(video, FileKind.VIDEO), NO_DATE, tmp_path / "out" / "clip.mp4")
    inspector.show_item(item)
    assert inspector.video_bar.isVisible()

    inspector.toggle_play()
    assert not inspector._player.source().isEmpty()

    photo = PlanItem(MediaFile(tmp_path / "a.jpg", FileKind.JPEG), NO_DATE, tmp_path / "a.jpg")
    inspector.show_item(photo)  # trocar de seleção solta o vídeo (senão o Mover falha)
    assert inspector._player.source().isEmpty()
    assert not inspector.video_bar.isVisible()
