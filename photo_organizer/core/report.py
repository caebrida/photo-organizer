"""Relatório CSV de cada execução: uma linha por arquivo, com origem → destino.

Gravado em UTF-8 com BOM e separador ``;`` para abrir direto no Excel em português.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from photo_organizer.core.executor import ItemResult, Mode
from photo_organizer.core.planner import PlanItem, Skip

HEADERS = {
    "pt": (
        "Status", "Operação", "Origem", "Destino", "Sidecar origem", "Sidecar destino",
        "Data", "Fonte da data", "Tipo", "Duplicada", "Erro", "Observação",
    ),
    "en": (
        "Status", "Operation", "Source", "Destination", "Source sidecar", "Destination sidecar",
        "Date", "Date source", "Type", "Duplicate", "Error", "Note",
    ),
}  # fmt: skip
NOTES = {
    "pt": {
        Skip.IN_PLACE: "Já estava no lugar",
        Skip.KEPT: "Já existe no destino; ficou a de lá",
        Skip.EXCLUDED: "Deixado de fora",
        "trash": "Deixado de fora; foi para a Lixeira",
        "replace": "Substituiu a do destino (a antiga foi para a Lixeira)",
    },
    "en": {
        Skip.IN_PLACE: "Already in place",
        Skip.KEPT: "Already in the destination; kept that one",
        Skip.EXCLUDED: "Left out",
        "trash": "Left out; moved to the Recycle Bin",
        "replace": "Replaced the destination file (the old one went to the Recycle Bin)",
    },
}


def _note(item: PlanItem, mode: Mode, lang: str) -> str:
    if item.trash and mode is Mode.MOVE:
        return NOTES[lang]["trash"]
    if item.replaces is not None:
        return NOTES[lang]["replace"]
    return NOTES[lang][item.skip] if item.skip else ""


def default_report_path(root: Path, when: datetime) -> Path:
    return root / f"Photo Organizer - {when:%Y-%m-%d %H%M%S}.csv"


def write_report(path: Path, results: Iterable[ItemResult], mode: Mode, lang: str = "pt") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(HEADERS[lang])
        for r in results:
            item, media = r.item, r.item.media
            writer.writerow(
                (
                    r.status.value,
                    mode.value,
                    media.path,
                    item.dest,
                    media.sidecar or "",
                    item.sidecar_dest or "",
                    item.date.value.isoformat(sep=" ") if item.date.value else "",
                    item.date.tag or "",
                    media.kind.value,
                    "1" if item.duplicate else "0",
                    r.error or "",
                    _note(item, mode, lang),
                )
            )
            f.flush()  # cada linha vai para o disco antes do próximo arquivo
    return path
