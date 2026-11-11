"""Gera o plano completo (origem → destino) antes de qualquer arquivo ser tocado.

- Nada é sobrescrito: se o nome já existe no destino (no disco ou no próprio plano), o
  arquivo ganha sufixo ``_1``, ``_2``… Nomes são comparados sem diferenciar maiúsculas,
  como no Windows.
- O sidecar acompanha o arquivo e recebe o mesmo sufixo: ``DSC0001_1.ARW`` +
  ``DSC0001_1.xmp``; ``DSC0001_1.JPG`` + ``DSC0001_1.JPG.xmp``.
- Um arquivo que já está exatamente no destino é marcado para pular.
- Desmarcados pelo usuário ficam onde estão; ao mover, podem ir para a Lixeira.
- Foto que já existe no destino: fica a de lá, vai para duplicadas ou toma o lugar dela
  (a antiga vai para a Lixeira, no executor).
"""

from __future__ import annotations

import os
from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path, PurePath

from photo_organizer.core.dates import FileDate
from photo_organizer.core.rules import RuleSettings, destination_dir
from photo_organizer.core.scanner import MediaFile, path_key


class DestAction(StrEnum):
    """O que fazer com uma foto da origem que já existe no destino."""

    KEEP = "keep"  # fica a do destino; a da origem não é copiada nem movida
    DUPLICATE = "duplicate"  # a da origem vai para a pasta de duplicadas
    REPLACE = "replace"  # a da origem toma o lugar da do destino (a antiga vai para a Lixeira)


class Skip(StrEnum):
    IN_PLACE = "in-place"  # já está no lugar certo
    KEPT = "kept"  # a foto já existe no destino e fica a de lá
    EXCLUDED = "excluded"  # desmarcada pelo usuário


@dataclass(frozen=True, slots=True)
class PlanItem:
    media: MediaFile
    date: FileDate
    dest: Path  # pulados: onde o arquivo fica (para KEPT, a foto do destino)
    sidecar_dest: Path | None = None
    duplicate: bool = False
    skip: Skip | None = None
    replaces: MediaFile | None = None  # foto do destino que vai para a Lixeira
    trash: bool = False  # desmarcado: ao mover, vai para a Lixeira em vez de ficar


@dataclass(slots=True)
class Plan:
    root: Path
    items: list[PlanItem] = field(default_factory=list)

    @property
    def to_process(self) -> list[PlanItem]:
        return [i for i in self.items if not i.skip]

    @property
    def to_trash(self) -> list[PlanItem]:
        """Desmarcados que vão para a Lixeira (só ao mover; o executor confere o modo)."""
        return [i for i in self.items if i.trash]


def build_plan(
    files: Iterable[tuple[MediaFile, FileDate]],
    root: str | Path,
    settings: RuleSettings,
    duplicates: Collection[Path] = (),
    excluded: Collection[Path] = (),
    trash_excluded: bool = False,
    in_dest: Mapping[Path, tuple[DestAction, MediaFile]] | None = None,
    listings: dict[str, frozenset[str]] | None = None,
) -> Plan:
    """``duplicates`` vão para a pasta de duplicadas; ``excluded`` ficam onde estão (ou vão
    para a Lixeira, com ``trash_excluded``); ``in_dest`` diz, para cada foto que já existe
    no destino, a ação e a foto de lá. ``listings`` guarda o conteúdo das pastas do destino
    entre um plano e outro (cada ajuste nas regras refaz o plano; numa rede, relistar mil
    pastas a cada clique demora). Quem passa limpa quando o destino muda."""
    root = Path(root)
    dup_keys = {path_key(p) for p in duplicates}
    out_keys = {path_key(p) for p in excluded}
    found = {path_key(p): v for p, v in (in_dest or {}).items()}
    replaced: set[str] = set()
    names = _NameIndex(listings)
    plan = Plan(root)
    for media, date in files:
        key = path_key(media.path)
        if key in out_keys:
            plan.items.append(
                PlanItem(media, date, media.path, media.sidecar, skip=Skip.EXCLUDED,
                         trash=trash_excluded)
            )  # fmt: skip
            continue
        action, existing = found.get(key, (None, None))
        if action is DestAction.REPLACE and path_key(existing.path) in replaced:
            action = DestAction.DUPLICATE  # só uma foto da origem toma o lugar de cada uma
        if action is DestAction.KEEP:
            plan.items.append(
                PlanItem(media, date, existing.path, existing.sidecar, skip=Skip.KEPT)
            )
            continue
        if action is DestAction.REPLACE:
            replaced.add(path_key(existing.path))
            side = _sidecar_name(media, existing.path.name)
            side_dest = existing.path.with_name(side) if side else None
            plan.items.append(PlanItem(media, date, existing.path, side_dest, replaces=existing))
            continue
        duplicate = key in dup_keys or action is DestAction.DUPLICATE
        folder = destination_dir(root, media.kind, date.value, settings, duplicate)
        if path_key(folder / media.path.name) == key:
            plan.items.append(
                PlanItem(media, date, media.path, media.sidecar, duplicate, skip=Skip.IN_PLACE)
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

    def __init__(self, disk: dict[str, frozenset[str]] | None = None) -> None:
        self._disk = disk if disk is not None else {}  # pode vir de planos anteriores
        self._claimed: dict[str, set[str]] = {}

    def _on_disk(self, k: str, folder: Path) -> frozenset[str]:
        if k not in self._disk:
            try:
                names = frozenset(n.lower() for n in os.listdir(folder))  # noqa: PTH208 (só nomes, mais rápido)
            except FileNotFoundError:
                names = frozenset()  # pasta ainda não existe: o Organizar a cria
            except OSError:
                # Sem acesso (rede fora do ar): não guarda, o próximo plano tenta de novo. O
                # executor nunca sobrescreve: o pior caso é um erro por arquivo no relatório.
                return frozenset()
            self._disk[k] = names
        return self._disk[k]

    def taken(self, folder: Path, name: str) -> bool:
        k, n = path_key(folder), name.lower()
        return n in self._claimed.get(k, ()) or n in self._on_disk(k, folder)

    def claim(self, folder: Path, name: str) -> None:
        self._claimed.setdefault(path_key(folder), set()).add(name.lower())
