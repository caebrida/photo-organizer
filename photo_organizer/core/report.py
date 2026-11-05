"""Relatório CSV de cada execução: uma linha por arquivo, com origem → destino.

Gravado em UTF-8 com BOM e separador ``;`` para abrir direto no Excel em português.
"""

from __future__ import annotations

import csv
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from photo_organizer.core.executor import ItemResult, Mode

HEADERS = {
    "pt": (
        "Status", "Operação", "Origem", "Destino", "Sidecar origem", "Sidecar destino",
        "Data", "Fonte da data", "Tipo", "Duplicada", "Erro",
    ),
    "en": (
        "Status", "Operation", "Source", "Destination", "Source sidecar", "Destination sidecar",
        "Date", "Date source", "Type", "Duplicate", "Error",
    ),
}  # fmt: skip


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
                )
            )
            f.flush()  # cada linha vai para o disco antes do próximo arquivo
    return path
