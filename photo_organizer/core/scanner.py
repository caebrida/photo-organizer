"""Varre a pasta de origem, classifica os arquivos e associa cada um ao seu sidecar XMP.

Regras de associação do sidecar, dentro da mesma pasta (sem diferenciar maiúsculas):
- ``DSC0001.JPG.xmp`` pertence sempre ao ``DSC0001.JPG``;
- ``DSC0001.xmp`` pertence ao RAW ``DSC0001.*``; sem RAW, ao JPEG; sem JPEG, ao vídeo.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path, PurePath


class FileKind(StrEnum):
    JPEG = "jpeg"  # foto comum: JPEG ou HEIC (iPhone); vai para a pasta da data
    RAW = "raw"
    VIDEO = "video"


EXTENSIONS: dict[str, FileKind] = {
    ".jpg": FileKind.JPEG,
    ".jpeg": FileKind.JPEG,
    ".heic": FileKind.JPEG,
    ".arw": FileKind.RAW,
    ".cr2": FileKind.RAW,
    ".cr3": FileKind.RAW,
    ".crw": FileKind.RAW,
    ".dng": FileKind.RAW,
    ".mp4": FileKind.VIDEO,
    ".mov": FileKind.VIDEO,
    ".avi": FileKind.VIDEO,
}

SIDECAR_EXT = ".xmp"

# Ordem de preferência para o sidecar sem a extensão original no nome (DSC0001.xmp).
_STEM_SIDECAR_OWNER = (FileKind.RAW, FileKind.JPEG, FileKind.VIDEO)


@dataclass(frozen=True, slots=True)
class MediaFile:
    path: Path
    kind: FileKind
    sidecar: Path | None = None


def kind_of(path: str | Path) -> FileKind | None:
    return EXTENSIONS.get(PurePath(path).suffix.lower())


def path_key(path: str | Path) -> str:
    """Chave para comparar caminhos como o Windows (sem maiúsculas), sem acessar o disco."""
    return os.path.normcase(os.path.abspath(path))  # noqa: PTH100 (resolve() acessa o disco)


def scan(
    root: str | Path,
    kinds: Iterable[FileKind] | None = None,
    exclude: str | Path | None = None,
    on_error: Callable[[OSError], None] | None = None,
) -> Iterator[MediaFile]:
    """Percorre ``root`` recursivamente e gera os arquivos de mídia encontrados.

    ``kinds`` restringe os tipos (ex.: só fotos); ``None`` aceita todos. ``exclude`` é uma
    pasta que não é percorrida (o destino, quando ele fica dentro da origem). ``on_error``
    recebe as pastas que não puderam ser lidas (sem permissão, rede caiu); elas ficam de
    fora e o resto continua.
    """
    wanted = set(kinds) if kinds is not None else set(FileKind)
    skip = os.path.normcase(Path(exclude).absolute()) if exclude is not None else None
    # Caminhos absolutos: o relatório e o planejador não dependem da pasta atual.
    for dirpath, dirnames, filenames in os.walk(Path(root).absolute(), onerror=on_error):
        dirnames[:] = sorted(
            (d for d in dirnames if os.path.normcase(Path(dirpath, d)) != skip), key=str.lower
        )
        yield from _scan_dir(Path(dirpath), filenames, wanted)


def _scan_dir(folder: Path, filenames: list[str], wanted: set[FileKind]) -> Iterator[MediaFile]:
    sidecars = {n.lower(): n for n in filenames if n.lower().endswith(SIDECAR_EXT)}
    media = sorted(
        ((name, kind) for name in filenames if (kind := kind_of(name)) is not None),
        key=lambda item: item[0].lower(),
    )

    stem_owner: dict[str, str] = {}
    for kind in _STEM_SIDECAR_OWNER:
        for name, k in media:
            stem = PurePath(name).stem.lower()
            if k is kind and stem not in stem_owner:
                stem_owner[stem] = name

    for name, kind in media:
        if kind not in wanted:
            continue
        stem = PurePath(name).stem.lower()
        sidecar = sidecars.get(name.lower() + SIDECAR_EXT)
        if sidecar is None and stem_owner.get(stem) == name:
            sidecar = sidecars.get(stem + SIDECAR_EXT)
        yield MediaFile(folder / name, kind, folder / sidecar if sidecar else None)
