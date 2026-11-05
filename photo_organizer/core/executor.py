"""Executa o plano: move ou copia cada arquivo (e seu sidecar) com segurança.

- **Nunca sobrescreve.** O rename final usa ``os.rename``, que no Windows falha se o
  destino já existir (ex.: arquivo criado depois do plano).
- **Copiar** e **mover entre discos**: copia para um arquivo temporário na pasta de
  destino, confere o hash relendo a cópia e só então dá o nome final. Ao mover, a origem
  só é apagada depois disso.
- **Mover no mesmo disco**: ``os.rename``, atômico.
- Caminhos longos (> 260 caracteres) usam o prefixo ``\\\\?\\`` do Windows.
"""

from __future__ import annotations

import contextlib
import errno
import hashlib
import os
import shutil
import sys
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from photo_organizer.core.planner import Plan, PlanItem

CHUNK = 1024 * 1024
_ERROR_NOT_SAME_DEVICE = 17  # winerror do Windows para rename entre volumes


class Mode(StrEnum):
    MOVE = "move"
    COPY = "copy"


class Status(StrEnum):
    DONE = "done"
    SKIPPED = "skipped"  # já estava no lugar certo
    PARTIAL = "partial"  # arquivo no destino, mas algo falhou (sidecar ou apagar origem)
    FAILED = "failed"  # nada mudou para este arquivo
    CANCELLED = "cancelled"


class VerifyError(OSError):
    """A cópia gravada no destino não confere com a origem."""


@dataclass(frozen=True, slots=True)
class ItemResult:
    item: PlanItem
    status: Status
    error: str | None = None


Progress = Callable[[int, int, ItemResult], None]


def execute(
    plan: Plan,
    mode: Mode,
    progress: Progress | None = None,
    cancel: threading.Event | None = None,
) -> Iterator[ItemResult]:
    """Processa os itens em ordem, gerando um resultado por item (inclusive os pulados)."""
    total = len(plan.items)
    for done, item in enumerate(plan.items, 1):
        if cancel is not None and cancel.is_set():
            result = ItemResult(item, Status.CANCELLED)
        elif item.skip:
            result = ItemResult(item, Status.SKIPPED)
        else:
            result = _process(item, mode)
        if progress is not None:
            progress(done, total, result)
        yield result


def _process(item: PlanItem, mode: Mode) -> ItemResult:
    try:
        os.makedirs(_fs(item.dest.parent), exist_ok=True)
        warning = _transfer(item.media.path, item.dest, mode)
    except OSError as exc:
        return ItemResult(item, Status.FAILED, _describe(exc))
    if item.media.sidecar is not None and item.sidecar_dest is not None:
        try:
            side_warning = _transfer(item.media.sidecar, item.sidecar_dest, mode)
        except OSError as exc:
            return ItemResult(item, Status.PARTIAL, f"Sidecar: {_describe(exc)}")
        warning = warning or side_warning
    if warning:
        return ItemResult(item, Status.PARTIAL, warning)
    return ItemResult(item, Status.DONE)


def _transfer(src: Path, dst: Path, mode: Mode) -> str | None:
    """Move ou copia um arquivo. Devolve um aviso quando o destino ficou pronto, mas a
    origem não pôde ser apagada; erros que deixam tudo como estava viram exceção."""
    if mode is Mode.MOVE:
        try:
            os.rename(_fs(src), _fs(dst))
            return None
        except OSError as exc:
            if not _cross_device(exc):
                raise
    copy_verified(src, dst)
    if mode is Mode.MOVE:
        try:
            os.remove(_fs(src))
        except OSError as exc:
            return f"Copiado e conferido, mas a origem não pôde ser apagada: {_describe(exc)}"
    return None


def copy_verified(src: Path, dst: Path) -> None:
    tmp = dst.with_name(f"~{dst.name}.{os.getpid()}.tmp")
    try:
        digest = hashlib.blake2b()
        with open(_fs(src), "rb") as fin, open(_fs(tmp), "wb") as fout:
            while chunk := fin.read(CHUNK):
                digest.update(chunk)
                fout.write(chunk)
            fout.flush()
            os.fsync(fout.fileno())
        shutil.copystat(_fs(src), _fs(tmp))
        if hash_file(tmp) != digest.digest():
            raise VerifyError(f"A cópia em {dst} não confere com a origem.")
        os.rename(_fs(tmp), _fs(dst))
    except BaseException:
        with contextlib.suppress(OSError):
            os.remove(_fs(tmp))
        raise


def hash_file(path: Path) -> bytes:
    digest = hashlib.blake2b()
    with open(_fs(path), "rb") as f:
        while chunk := f.read(CHUNK):
            digest.update(chunk)
    return digest.digest()


def _cross_device(exc: OSError) -> bool:
    return exc.errno == errno.EXDEV or getattr(exc, "winerror", None) == _ERROR_NOT_SAME_DEVICE


def _describe(exc: OSError) -> str:
    if isinstance(exc, FileExistsError):
        return f"Já existe um arquivo em {exc.filename2 or exc.filename}; nada foi sobrescrito."
    if isinstance(exc, VerifyError) or not exc.strerror:
        return str(exc)
    return f"{exc.strerror}: {exc.filename}" if exc.filename else exc.strerror


def _fs(path: Path) -> str:
    """Caminho para chamadas ao sistema; acima do limite do Windows usa ``\\\\?\\``."""
    s = os.path.abspath(path)
    if sys.platform != "win32" or len(s) < 240 or s.startswith("\\\\?\\"):
        return s
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s
