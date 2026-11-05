"""Monta a pasta de destino de cada arquivo (PLANO.md §2, "Caminho final de cada arquivo").

    <destino>\\<padrão de data>\\DSC0001.JPG
    <destino>\\<padrão de data>\\RAW\\DSC0001.ARW      (e o DSC0001.xmp junto)
    <destino>\\<padrão de data>\\Video\\C0031.MP4
    <destino>\\Sem data\\[RAW|Video\\]arquivo
    <destino>\\Duplicadas - Validar\\<padrão de data>\\[RAW|Video\\]arquivo

O nome final (com sufixo ``_1``, ``_2``… em caso de conflito) é decidido pelo planejador.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from photo_organizer.core.pattern import FolderPattern
from photo_organizer.core.scanner import FileKind

RAW_FOLDER = "RAW"
VIDEO_FOLDER = "Video"


@dataclass(frozen=True, slots=True)
class RuleSettings:
    pattern: FolderPattern
    lang: str = "pt"
    no_date_folder: str = "Sem data"
    duplicates_folder: str = "Duplicadas - Validar"


def destination_dir(
    root: Path,
    kind: FileKind,
    date: datetime | None,
    settings: RuleSettings,
    duplicate: bool = False,
) -> Path:
    folder = root
    if duplicate:
        folder /= settings.duplicates_folder
    if date is None:
        folder /= settings.no_date_folder
    else:
        folder = folder.joinpath(*settings.pattern.render(date, settings.lang))
    if kind is FileKind.RAW:
        folder /= RAW_FOLDER
    elif kind is FileKind.VIDEO:
        folder /= VIDEO_FOLDER
    return folder
