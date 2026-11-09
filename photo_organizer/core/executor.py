"""Executa o plano: move ou copia cada arquivo (e seu sidecar) com segurança.

- **Nunca sobrescreve.** O rename final usa ``os.rename``, que no Windows falha se o
  destino já existir (ex.: arquivo criado depois do plano).
- **Copiar** e **mover entre discos**: copia para um arquivo temporário na pasta de
  destino, confere o hash relendo a cópia e só então dá o nome final. Ao mover, a origem
  só é apagada depois disso.
- **Mover no mesmo disco**: ``os.rename``, atômico.
- Caminhos longos (> 260 caracteres) usam o prefixo ``\\\\?\\`` do Windows.
- **Lixeira** (desmarcados ao mover; foto do destino substituída): só em disco local.
  Em rede ou pendrive o Windows apagaria de vez, então o arquivo fica e vira erro.
- **Substituir**: a nova entra com nome temporário, a antiga vai para a Lixeira e só
  então a nova recebe o nome. Se a antiga não puder ir, a nova volta e nada muda.
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
_DRIVE_FIXED = 3  # GetDriveTypeW: disco local, o único com Lixeira garantida


class Mode(StrEnum):
    MOVE = "move"
    COPY = "copy"


class Status(StrEnum):
    DONE = "done"
    SKIPPED = "skipped"  # já estava no lugar, já existe no destino ou deixado de fora
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
        elif item.trash and mode is Mode.MOVE:
            result = _trash_item(item)
        elif item.skip:
            result = ItemResult(item, Status.SKIPPED)
        elif item.replaces is not None:
            result = _replace(item, mode)
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


def _trash_item(item: PlanItem) -> ItemResult:
    try:
        move_to_trash(item.media.path)
    except OSError as exc:
        return ItemResult(item, Status.FAILED, _describe(exc))
    if item.media.sidecar is not None:
        try:
            move_to_trash(item.media.sidecar)
        except OSError as exc:
            return ItemResult(item, Status.PARTIAL, f"Sidecar: {_describe(exc)}")
    return ItemResult(item, Status.DONE)


def _replace(item: PlanItem, mode: Mode) -> ItemResult:
    old = item.replaces
    assert old is not None
    src, dest = item.media.path, item.dest
    tmp = dest.with_name(f"~{dest.name}.{os.getpid()}.new")
    try:
        warning = _transfer(src, tmp, mode)
    except OSError as exc:
        return ItemResult(item, Status.FAILED, _describe(exc))
    try:
        move_to_trash(old.path)
    except OSError as exc:
        try:  # desfaz: a nova volta para a origem (ou some, se era cópia)
            if mode is Mode.MOVE and not warning:
                _transfer(tmp, src, Mode.MOVE)
            else:
                os.remove(_fs(tmp))
        except OSError as undo:
            return ItemResult(
                item, Status.FAILED,
                f"{_describe(exc)}. A nova ficou em {tmp}: {_describe(undo)}",
            )  # fmt: skip
        return ItemResult(item, Status.FAILED, f"{_describe(exc)}. Nada foi trocado.")
    try:
        os.rename(_fs(tmp), _fs(dest))
    except OSError as exc:
        return ItemResult(
            item, Status.PARTIAL,
            f"A antiga foi para a Lixeira, mas a nova ficou em {tmp}: {_describe(exc)}",
        )  # fmt: skip
    if item.media.sidecar is not None and item.sidecar_dest is not None:
        try:
            if os.path.exists(_fs(item.sidecar_dest)):  # sidecar da foto antiga
                move_to_trash(item.sidecar_dest)
            warning = _transfer(item.media.sidecar, item.sidecar_dest, mode) or warning
        except OSError as exc:
            return ItemResult(item, Status.PARTIAL, f"Sidecar: {_describe(exc)}")
    if warning:
        return ItemResult(item, Status.PARTIAL, warning)
    return ItemResult(item, Status.DONE)


def move_to_trash(path: Path) -> None:
    """Manda o arquivo para a Lixeira do Windows, ou levanta ``OSError``."""
    if sys.platform == "win32":
        import ctypes

        root = os.path.splitdrive(os.path.abspath(path))[0] + os.sep
        if ctypes.windll.kernel32.GetDriveTypeW(root) != _DRIVE_FIXED:
            raise OSError(
                errno.EPERM, "Esta unidade não tem Lixeira; o arquivo ficou onde estava", str(path)
            )
    from PySide6.QtCore import QFile  # a mesma Lixeira do Explorador, sem dependência nova

    if not QFile.moveToTrash(str(path)):
        raise OSError(errno.EIO, "Não foi possível mandar para a Lixeira", str(path))


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
