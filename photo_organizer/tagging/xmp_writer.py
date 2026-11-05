"""Grava e lê as tags no sidecar XMP (decisão 12: o arquivo original nunca muda).

As tags vão em ``dc:subject``, que Lightroom, Bridge, digiKam e o Windows leem como
palavras-chave. Tags que já estavam no sidecar são mantidas, e as que a foto já tem
(no sidecar ou dentro do arquivo) não são repetidas, sem diferenciar maiúsculas.

Qual sidecar: o que o arquivo já tem (ex.: ``DSC0001.xmp`` do Lightroom); senão
``DSC0001.xmp`` para RAW e ``DSC0001.JPG.xmp`` para JPEG, para não misturar com o XMP do
RAW de mesmo nome (PLANO.md, premissa 2).
"""

from __future__ import annotations

import glob
from collections.abc import Iterable
from pathlib import Path

from photo_organizer.core.metadata import MetadataReader
from photo_organizer.core.scanner import FileKind, MediaFile, kind_of, path_key

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
    stem = media.path.with_suffix(".xmp")
    if not stem.exists():
        return stem
    # DSC1.xmp existe mas não veio com o arquivo: é dele (criado depois do escaneamento)
    # ou de outro RAW de mesmo nome, que o escaneamento associa ao primeiro em ordem
    # alfabética (DSC1.CR2 fica com DSC1.xmp; DSC1.DNG usa DSC1.DNG.xmp).
    raws = [
        p
        for p in media.path.parent.glob(glob.escape(media.path.stem) + ".*")
        if kind_of(p) is FileKind.RAW
    ]
    owner = min(raws, key=lambda p: p.name.lower(), default=media.path)
    return (
        stem
        if owner.name.lower() == media.path.name.lower()
        else media.path.with_name(media.path.name + ".xmp")
    )


def merge_tags(current: list[str], tags: Iterable[str]) -> list[str]:
    """``current`` mais as ``tags`` que ainda não estão nela, sem diferenciar maiúsculas.

    Espaços e quebras de linha viram um espaço só: o ExifTool lê um argumento por linha,
    e uma tag colada como "praia⏎-all=" apagaria o sidecar inteiro.
    """
    out, seen = list(current), {t.casefold() for t in current}
    for tag in tags:
        tag = " ".join(tag.split())
        if tag and tag.casefold() not in seen:
            seen.add(tag.casefold())
            out.append(tag)
    return out


def existing_tags(reader: MetadataReader, files: list[MediaFile]) -> dict[Path, list[str]]:
    """Palavras-chave de cada foto: as gravadas no próprio arquivo (XMP e IPTC, como o
    Lightroom e o Windows deixam) e as do sidecar de tags."""
    sidecars = {m.path: tag_sidecar(m) for m in files}
    paths = [m.path for m in files] + [p for p in sidecars.values() if p.is_file()]
    found: dict[str, list[str]] = {}
    for meta in reader.read(paths, [SUBJECT, KEYWORDS]) if paths else []:
        found[path_key(meta["SourceFile"])] = _values(meta.get("XMP:Subject")) + _values(
            meta.get("IPTC:Keywords")
        )
    return {
        path: list(dict.fromkeys(found.get(path_key(path), []) + found.get(path_key(side), [])))
        for path, side in sidecars.items()
    }


def write_tags(
    reader: MetadataReader,
    media: MediaFile,
    tags: Iterable[str],
    current: list[str] | None = None,
) -> Path:
    """Acrescenta ao sidecar (criando-o se preciso) as ``tags`` que a foto ainda não tem e
    devolve o caminho dele. ``current``: as tags que a foto já tem, se já foram lidas."""
    sidecar = tag_sidecar(media)
    if current is None:
        current = existing_tags(reader, [media])[media.path]
    new = merge_tags(current, tags)[len(current) :]
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


def _values(value: object) -> list[str]:
    if value is None:
        return []
    return [str(t) for t in value] if isinstance(value, list) else [str(value)]
