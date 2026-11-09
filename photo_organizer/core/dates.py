"""Escolhe a data de cada arquivo, na ordem de prioridade do plano (§1, decisão 5):

1. EXIF do próprio arquivo (``DateTimeOriginal`` com milissegundos, depois ``CreateDate``;
   CRW usa MakerNotes);
2. XMP do sidecar;
3. XMP embutido no arquivo;
4. datas de vídeo (QuickTime / RIFF);
5. nenhuma: o arquivo vai para ``Sem data``.

A data devolvida é a hora local em que a foto foi feita (sem fuso), que é o que define a
pasta. A única conversão de fuso é a do ``QuickTime:CreateDate``, que por norma é UTC.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from photo_organizer.core.metadata import MetadataReader
from photo_organizer.core.scanner import MediaFile, path_key


class DateSource(StrEnum):
    EXIF = "exif"
    XMP_SIDECAR = "xmp-sidecar"
    XMP_EMBEDDED = "xmp-embedded"
    VIDEO = "video"
    FILENAME = "filename"  # opcional, decidido no plano (ver date_from_name)


@dataclass(frozen=True, slots=True)
class FileDate:
    value: datetime | None
    source: DateSource | None = None
    tag: str | None = None


NO_DATE = FileDate(None)

# O Composite junta DateTimeOriginal + SubSecTimeOriginal: os milissegundos separam fotos
# de rajada na detecção de duplicadas.
EXIF_TAGS = (
    "Composite:SubSecDateTimeOriginal",
    "EXIF:DateTimeOriginal",
    "EXIF:CreateDate",
    "MakerNotes:DateTimeOriginal",
)
XMP_TAGS = ("XMP:DateTimeOriginal", "XMP:CreateDate", "XMP:DateCreated")
# CreationDate (chaves da Apple) já vem com fuso; CreateDate do cabeçalho está em UTC.
VIDEO_TAGS = ("QuickTime:CreationDate", "QuickTime:CreateDate", "RIFF:DateTimeOriginal")
_UTC_TAGS = frozenset({"QuickTime:CreateDate"})

FILE_TAGS = [*EXIF_TAGS, *XMP_TAGS, *VIDEO_TAGS]
SIDECAR_TAGS = list(XMP_TAGS)

_DATE_RE = re.compile(
    r"^\s*(\d{4})[:-](\d{2})[:-](\d{2})"
    r"(?:[ T](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d+))?)?"
    r"\s*(Z|[+-]\d{2}:?\d{2})?"
)


def parse_date(value: object, assume_utc: bool = False) -> datetime | None:
    """Converte uma data do ExifTool ("2026:10:27 14:32:08-03:00") em ``datetime`` local.

    Valores vazios, zerados ("0000:00:00 00:00:00") ou inválidos devolvem ``None``.
    """
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value)
    if not m:
        return None
    year, month, day, hour, minute, second, frac, tz = m.groups()
    micro = int((frac or "0")[:6].ljust(6, "0"))
    try:
        dt = datetime(
            int(year),
            int(month),
            int(day),
            int(hour or 0),
            int(minute or 0),
            int(second or 0),
            micro,
        )
    except ValueError:
        return None
    if dt.year < 1826:  # antes da primeira fotografia: data de câmera não configurada
        return None
    if assume_utc and tz is None:
        # Vídeos sem fuso explícito: converte de UTC para o horário local deste computador.
        return dt.replace(tzinfo=UTC).astimezone().replace(tzinfo=None)
    return dt


# Data no nome: IMG_20261027_143208, IMG-20261027-WA0003 (WhatsApp), PXL_20261027_143208123,
# Screenshot_2026-10-27-14-32-08, "2026-10-27 14.32.08". Só ano-mês-dia, sem dígito colado
# antes ou depois, para não ler DSC01234 ou um número qualquer como data.
_NAME_RE = re.compile(
    r"(?<!\d)((?:19|20)\d{2})([-_.]?)(0[1-9]|1[0-2])\2(0[1-9]|[12]\d|3[01])"
    r"(?:[ _T.-]?([01]\d|2[0-3])[-_.:h]?([0-5]\d)[-_.:m]?([0-5]\d)\d{0,3})?(?!\d)"
)


def date_from_name(name: str) -> FileDate:
    """Data escrita no nome do arquivo, para quem não tem data nos metadados."""
    for m in _NAME_RE.finditer(name):
        year, _, month, day, hour, minute, second = m.groups()
        try:
            dt = datetime(
                int(year), int(month), int(day), int(hour or 0), int(minute or 0), int(second or 0)
            )
        except ValueError:  # 31 de fevereiro
            continue
        if 1990 <= dt.year <= datetime.now().year + 1:  # fora disso é quase sempre um número
            return FileDate(dt, DateSource.FILENAME, "FileName")
    return NO_DATE


def resolve_date(file_meta: dict, sidecar_meta: dict | None = None) -> FileDate:
    """Aplica a ordem de prioridade aos metadados já lidos de um arquivo e do seu sidecar."""
    tiers: list[tuple[DateSource, dict, Sequence[str]]] = [
        (DateSource.EXIF, file_meta, EXIF_TAGS),
        (DateSource.XMP_SIDECAR, sidecar_meta or {}, XMP_TAGS),
        (DateSource.XMP_EMBEDDED, file_meta, XMP_TAGS),
        (DateSource.VIDEO, file_meta, VIDEO_TAGS),
    ]
    for source, meta, tags in tiers:
        for tag in tags:
            dt = parse_date(meta.get(tag), assume_utc=tag in _UTC_TAGS)
            if dt is not None:
                return FileDate(dt, source, tag)
    return NO_DATE


def read_dates(
    reader: MetadataReader, files: Iterable[MediaFile], batch_size: int = 500
) -> Iterator[tuple[MediaFile, FileDate]]:
    """Lê as datas em lotes e gera ``(arquivo, data)`` na mesma ordem da entrada."""
    batch: list[MediaFile] = []
    for f in files:
        batch.append(f)
        if len(batch) >= batch_size:
            yield from _read_batch(reader, batch)
            batch = []
    if batch:
        yield from _read_batch(reader, batch)


def _read_batch(
    reader: MetadataReader, batch: list[MediaFile]
) -> Iterator[tuple[MediaFile, FileDate]]:
    file_meta = _by_path(reader.read([f.path for f in batch], FILE_TAGS))
    sidecars = [f.sidecar for f in batch if f.sidecar is not None]
    sidecar_meta = _by_path(reader.read(sidecars, SIDECAR_TAGS)) if sidecars else {}
    for f in batch:
        side = sidecar_meta.get(path_key(f.sidecar)) if f.sidecar else None
        yield f, resolve_date(file_meta.get(path_key(f.path), {}), side)


def _by_path(results: list[dict]) -> dict[str, dict]:
    return {path_key(r["SourceFile"]): r for r in results if "SourceFile" in r}
