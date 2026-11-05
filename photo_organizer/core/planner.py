"""Gera o plano completo (origem → destino) antes de qualquer arquivo ser tocado.

- Nada é sobrescrito: se o nome já existe no destino (no disco ou no próprio plano), o
  arquivo ganha sufixo ``_1``, ``_2``… Nomes são comparados sem diferenciar maiúsculas,
  como no Windows.
- O sidecar acompanha o arquivo e recebe o mesmo sufixo: ``DSC0001_1.ARW`` +
  ``DSC0001_1.xmp``; ``DSC0001_1.JPG`` + ``DSC0001_1.JPG.xmp``.
- Um arquivo que já está exatamente no destino é marcado para pular.
"""

from __future__ import annotations

import os
from collections.abc import Collection, Iterable
from dataclasses import dataclass, field
from pathlib import Path, PurePath

from photo_organizer.core.dates import FileDate
from photo_organizer.core.rules import RuleSettings, destination_dir
from photo_organizer.core.scanner import MediaFile


@dataclass(frozen=True, slots=True)
class PlanItem:
    media: MediaFile
    date: FileDate
    dest: Path
    sidecar_dest: Path | None = None
    duplicate: bool = False
    skip: bool = False  # já está no lugar certo


@dataclass(slots=True)
class Plan:
    root: Path
    items: list[PlanItem] = field(default_factory=list)

    @property
    def to_process(self) -> list[PlanItem]:
        return [i for i in self.items if not i.skip]


def build_plan(
    files: Iterable[tuple[MediaFile, FileDate]],
    root: str | Path,
    settings: RuleSettings,
    duplicates: Collection[Path] = (),
) -> Plan:
    """``duplicates`` são os arquivos que vão para a pasta de duplicadas (fase 3)."""
    root = Path(root)
    dup_keys = {_key(p) for p in duplicates}
    names = _NameIndex()
    plan = Plan(root)
    for media, date in files:
        duplicate = _key(media.path) in dup_keys
        folder = destination_dir(root, media.kind, date.value, settings, duplicate)
        if _key(folder / media.path.name) == _key(media.path):
            plan.items.append(
                PlanItem(media, date, media.path, media.sidecar, duplicate, skip=True)
            )
            continue
        dest, sidecar_dest = _free_names(folder, media, names)
        plan.items.append(PlanItem(media, date, dest, sidecar_dest, duplicate))
    return plan


def _free_names(folder: Path, media: MediaFile, names: _NameIndex) -> tuple[Path, Path | None]:
    name = media.path.name
    stem, ext = PurePath(name).stem, PurePath(name).suffix
    n = 0
    while True:
        candidate = name if n == 0 else f"{stem}_{n}{ext}"
        side = _sidecar_name(media, candidate)
        if not names.taken(folder, candidate) and not (side and names.taken(folder, side)):
            names.claim(folder, candidate)
            if side:
                names.claim(folder, side)
            return folder / candidate, folder / side if side else None
        n += 1


def _sidecar_name(media: MediaFile, new_name: str) -> str | None:
    if media.sidecar is None:
        return None
    side = media.sidecar.name
    side_ext = PurePath(side).suffix
    if side.lower() == f"{media.path.name}{side_ext}".lower():  # DSC0001.JPG.xmp
        return f"{new_name}{side_ext}"
    return f"{PurePath(new_name).stem}{side_ext}"  # DSC0001.xmp


class _NameIndex:
    """Nomes ocupados por pasta: o que já existe no disco mais o que o plano reservou."""

    def __init__(self) -> None:
        self._dirs: dict[str, set[str]] = {}

    def _names(self, folder: Path) -> set[str]:
        k = _key(folder)
        if k not in self._dirs:
            try:
                self._dirs[k] = {n.lower() for n in os.listdir(folder)}  # noqa: PTH208 (só nomes, mais rápido)
            except OSError:
                # Pasta ainda não existe ou sem acesso (rede fora do ar): o executor
                # nunca sobrescreve, então o pior caso é um erro por arquivo no relatório.
                self._dirs[k] = set()
        return self._dirs[k]

    def taken(self, folder: Path, name: str) -> bool:
        return name.lower() in self._names(folder)

    def claim(self, folder: Path, name: str) -> None:
        self._names(folder).add(name.lower())


def _key(path: str | Path) -> str:
    return os.path.normcase(os.path.abspath(path))  # noqa: PTH100 (resolve() acessa o disco)
