"""Grava e lê as tags no sidecar XMP (decisão 12: o arquivo original nunca muda).

As tags vão em ``dc:subject``, que Lightroom, Bridge, digiKam e o Windows leem como
palavras-chave. Tags que já estavam no sidecar são mantidas, e as que a foto já tem
(no sidecar ou dentro do arquivo) não são repetidas.

Qual sidecar: o que o arquivo já tem (ex.: ``DSC0001.xmp`` do Lightroom); senão
``DSC0001.xmp`` para RAW e ``DSC0001.JPG.xmp`` para JPEG, para não misturar com o XMP do
RAW de mesmo nome (PLANO.md, premissa 2).
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from photo_organizer.core.metadata import MetadataReader
from photo_organizer.core.scanner import FileKind, MediaFile

SUBJECT = "XMP-dc:Subject"
KEYWORDS = "IPTC:Keywords"  # formato antigo, ainda gravado por câmeras e pelo Windows
EMPTY_XMP = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    ' <rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#"/>\n'
    "</x:xmpmeta>\n"
    '<?xpacket end="w"?>\n'
)


def tag_sidecar(media: MediaFile) -> Path:
    if media.sidecar is not None:
        return media.sidecar
    if media.kind is FileKind.JPEG:
        return media.path.with_name(media.path.name + ".xmp")
    return media.path.with_suffix(".xmp")


def read_tags(reader: MetadataReader, sidecars: Iterable[Path]) -> dict[Path, list[str]]:
    """Tags de cada sidecar existente (os que não existem ficam de fora)."""
    paths = [p for p in sidecars if p.is_file()]
    by_key = {_key(p): p for p in paths}
    out: dict[Path, list[str]] = {}
    for meta in reader.read(paths, [SUBJECT]):
        path = by_key.get(_key(meta["SourceFile"]))
        value = meta.get("XMP:Subject")
        if path is not None and value is not None:
            out[path] = _values(value)
    return out


def _values(value: object) -> list[str]:
    if value is None:
        return []
    return [str(t) for t in value] if isinstance(value, list) else [str(value)]


def existing_tags(reader: MetadataReader, files: list[MediaFile]) -> dict[Path, list[str]]:
    """Palavras-chave de cada foto: as gravadas no próprio arquivo (XMP e IPTC, como o
    Lightroom e o Windows deixam) e as do sidecar de tags."""
    sidecars = {m.path: tag_sidecar(m) for m in files}
    paths = [m.path for m in files] + [p for p in sidecars.values() if p.is_file()]
    found: dict[str, list[str]] = {}
    for meta in reader.read(paths, [SUBJECT, KEYWORDS]) if paths else []:
        found[_key(meta["SourceFile"])] = _values(meta.get("XMP:Subject")) + _values(
            meta.get("IPTC:Keywords")
        )
    return {
        path: list(dict.fromkeys(found.get(_key(path), []) + found.get(_key(sidecar), [])))
        for path, sidecar in sidecars.items()
    }


def write_tags(reader: MetadataReader, media: MediaFile, tags: Iterable[str]) -> Path:
    """Acrescenta ao sidecar (criando-o se preciso) as ``tags`` que a foto ainda não tem e
    devolve o caminho dele."""
    sidecar = tag_sidecar(media)
    current = existing_tags(reader, [media])[media.path]
    new = [t for t in dict.fromkeys(tags) if t not in current]  # não repete nem reordena
    if not new:
        return sidecar
    params = ["-overwrite_original", *(f"-{SUBJECT}+={t}" for t in new)]
    created = not sidecar.exists()
    if created:
        sidecar.write_text(EMPTY_XMP, encoding="utf-8")
    try:
        reader.write(sidecar, params)
    except Exception:
        if created:
            sidecar.unlink(missing_ok=True)
        raise
    return sidecar


def _key(path: str | Path) -> str:
    return str(Path(path)).lower()
