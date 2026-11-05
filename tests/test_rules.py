from datetime import datetime
from pathlib import Path

from photo_organizer.core.pattern import FolderPattern
from photo_organizer.core.rules import RuleSettings, destination_dir
from photo_organizer.core.scanner import FileKind

ROOT = Path(r"E:\Fotos")
DT = datetime(2026, 10, 27)
SETTINGS = RuleSettings(FolderPattern.parse("aaaa > mm > dd"))


def test_jpeg_goes_directly_to_date_folder():
    assert destination_dir(ROOT, FileKind.JPEG, DT, SETTINGS) == ROOT / "2026" / "10" / "27"


def test_raw_and_video_get_subfolders():
    assert destination_dir(ROOT, FileKind.RAW, DT, SETTINGS) == ROOT / "2026/10/27/RAW"
    assert destination_dir(ROOT, FileKind.VIDEO, DT, SETTINGS) == ROOT / "2026/10/27/Video"


def test_no_date_folder_keeps_type_subfolders():
    assert destination_dir(ROOT, FileKind.JPEG, None, SETTINGS) == ROOT / "Sem data"
    assert destination_dir(ROOT, FileKind.RAW, None, SETTINGS) == ROOT / "Sem data" / "RAW"
    assert destination_dir(ROOT, FileKind.VIDEO, None, SETTINGS) == ROOT / "Sem data" / "Video"


def test_duplicates_mirror_the_normal_structure():
    got = destination_dir(ROOT, FileKind.RAW, DT, SETTINGS, duplicate=True)
    assert got == ROOT / "Duplicadas - Validar" / "2026/10/27/RAW"
    got = destination_dir(ROOT, FileKind.JPEG, None, SETTINGS, duplicate=True)
    assert got == ROOT / "Duplicadas - Validar" / "Sem data"


def test_custom_names_and_language():
    settings = RuleSettings(
        FolderPattern.parse("aaaa > month"),
        lang="en",
        no_date_folder="No date",
        duplicates_folder="Check",
    )
    assert destination_dir(ROOT, FileKind.JPEG, DT, settings) == ROOT / "2026" / "October"
    assert (
        destination_dir(ROOT, FileKind.VIDEO, None, settings, True) == ROOT / "Check/No date/Video"
    )
