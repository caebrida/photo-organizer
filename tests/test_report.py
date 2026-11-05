import csv
from datetime import datetime

from photo_organizer.core.dates import NO_DATE, DateSource, FileDate
from photo_organizer.core.executor import ItemResult, Mode, Status
from photo_organizer.core.planner import PlanItem
from photo_organizer.core.report import HEADERS, default_report_path, write_report
from photo_organizer.core.scanner import FileKind, MediaFile


def test_report_rows(tmp_path):
    date = FileDate(datetime(2026, 10, 27, 14, 32, 8), DateSource.EXIF, "EXIF:DateTimeOriginal")
    raw = MediaFile(tmp_path / "Férias" / "a.ARW", FileKind.RAW, tmp_path / "Férias" / "a.xmp")
    jpg = MediaFile(tmp_path / "b.jpg", FileKind.JPEG)
    results = [
        ItemResult(PlanItem(raw, date, tmp_path / "d/a.ARW", tmp_path / "d/a.xmp"), Status.DONE),
        ItemResult(PlanItem(jpg, NO_DATE, tmp_path / "d/b.jpg", None, True), Status.FAILED, "x;y"),
    ]
    path = write_report(
        default_report_path(tmp_path, datetime(2026, 10, 28, 9, 5)), results, Mode.MOVE
    )
    assert path.name == "Photo Organizer - 2026-10-28 090500.csv"
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM para o Excel

    with path.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.reader(f, delimiter=";"))
    assert tuple(rows[0]) == HEADERS["pt"]
    assert rows[1][:5] == [
        "done",
        "move",
        str(raw.path),
        str(tmp_path / "d/a.ARW"),
        str(raw.sidecar),
    ]
    assert rows[1][6:10] == ["2026-10-27 14:32:08", "EXIF:DateTimeOriginal", "raw", "0"]
    assert rows[2][0] == "failed"
    assert rows[2][4:10] == ["", "", "", "", "jpeg", "1"]
    assert rows[2][10] == "x;y"  # separador dentro do campo é escapado
