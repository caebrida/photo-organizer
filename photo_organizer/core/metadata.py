"""Acesso ao ExifTool empacotado com o aplicativo.

O ExifTool roda em modo persistente (-stay_open): um único processo atende todas as
leituras, em lotes, o que é essencial para dezenas de milhares de arquivos.
"""

from __future__ import annotations

import errno
import logging
import os
import sys
import threading
from collections.abc import Iterable
from pathlib import Path

import exiftool
import exiftool.exiftool as _pyexiftool
from exiftool.exceptions import ExifToolOutputEmptyError

log = logging.getLogger(__name__)


class ExifToolNotFoundError(RuntimeError):
    """O exiftool.exe não está em photo_organizer/resources/exiftool."""


def resources_dir() -> Path:
    """Pasta de recursos, tanto rodando do código-fonte quanto do .exe do PyInstaller."""
    bundle = getattr(sys, "_MEIPASS", None)
    if bundle:
        return Path(bundle) / "photo_organizer" / "resources"
    return Path(__file__).resolve().parent.parent / "resources"


def exiftool_path() -> Path:
    exe = resources_dir() / "exiftool" / "exiftool.exe"
    if not exe.is_file():
        raise ExifToolNotFoundError(
            f"ExifTool não encontrado em {exe}. Rode `uv run python scripts/fetch_exiftool.py`."
        )
    return exe


class _StderrDrain:
    """Esvazia o stderr do ExifTool continuamente, numa thread.

    O pyexiftool lê o stdout inteiro e só depois o stderr. Se o ExifTool escreve no stderr
    mais do que cabe no pipe (~4 KB no Windows), ele para e espera, enquanto o pyexiftool
    espera o stdout: o programa trava. Acontece com ``-b``, que manda os avisos para o
    stderr (cada DNG do Lightroom gera quatro), e com lotes de arquivos corrompidos.
    """

    def __init__(self, fd: int) -> None:
        self._fd = fd
        self._buffer = bytearray()
        self._eof = False
        self._ready = threading.Condition()
        threading.Thread(target=self._pump, name="exiftool-stderr", daemon=True).start()

    def _pump(self) -> None:
        while True:
            try:
                chunk = os.read(self._fd, 65536)
            except OSError:
                chunk = b""
            with self._ready:
                if chunk:
                    self._buffer += chunk
                else:
                    self._eof = True
                self._ready.notify_all()
            if not chunk:
                return

    def read_until(self, end: bytes) -> bytes:
        """Tudo o que chegou até ``end`` (o marcador que o pyexiftool põe no fim de cada
        comando); depois dele o ExifTool não escreve mais nada até o próximo comando."""
        with self._ready:
            self._ready.wait_for(lambda: self._eof or self._buffer.rstrip().endswith(end))
            data = bytes(self._buffer)
            self._buffer.clear()
            return data


_drains: dict[int, _StderrDrain] = {}
_read_fd_endswith = _pyexiftool._read_fd_endswith


def _read_drained(fd: int, end: bytes, block_size: int) -> bytes:
    drain = _drains.get(fd)
    return drain.read_until(end) if drain else _read_fd_endswith(fd, end, block_size)


_pyexiftool._read_fd_endswith = _read_drained


class _ExifTool(exiftool.ExifToolHelper):
    def run(self) -> None:
        super().run()
        fd = self._process.stderr.fileno()
        _drains[fd] = _StderrDrain(fd)

    def terminate(self, *args: object, **kwargs: object) -> None:
        if self.running:
            _drains.pop(self._process.stderr.fileno(), None)
        super().terminate(*args, **kwargs)


class MetadataReader:
    """Sessão do ExifTool. Use como gerenciador de contexto:

    >>> with MetadataReader() as reader:
    ...     reader.read(["foto.jpg"], ["EXIF:DateTimeOriginal"])
    """

    def __init__(self) -> None:
        self._et = _ExifTool(
            executable=str(exiftool_path()),
            # UTF-8 nos dois lados: sem isso o Windows usa cp1252 e nomes como "Łódź" falham.
            encoding="utf-8",
            common_args=["-G", "-n", "-charset", "filename=utf8"],
            # Num lote, um arquivo ilegível faz o ExifTool sair com status 1, mas os demais
            # resultados continuam válidos; quem chama trata os ausentes.
            check_execute=False,
        )

    def __enter__(self) -> MetadataReader:
        self._et.run()
        return self

    def __exit__(self, *exc: object) -> None:
        self._et.terminate()

    @property
    def version(self) -> str:
        return self._et.version

    def read(
        self,
        files: Iterable[str | Path],
        tags: list[str] | None = None,
        params: list[str] | None = None,
    ) -> list[dict]:
        """Lê metadados de vários arquivos de uma vez.

        Retorna um dicionário por arquivo, com chaves no formato "Grupo:Tag"
        (ex.: "EXIF:DateTimeOriginal") e "SourceFile". Arquivos que o ExifTool não
        conseguiu abrir ficam de fora da lista. Com ``params=["-b"]``, tags binárias (ex.:
        miniaturas) vêm como texto ``"base64:..."``.
        """
        paths = [str(f) for f in files]
        if not paths:
            return []
        try:
            return self._et.get_tags(paths, tags=tags, params=params)
        except ExifToolOutputEmptyError:
            # Saída vazia: nenhum arquivo do lote pôde ser lido (rede caiu, arquivo sumiu ou
            # bloqueado). Divide o lote para salvar os legíveis em vez de perder a tarefa.
            folder = Path(paths[0]).parent
            if not folder.exists():  # compartilhamento fora do ar: dividir só somaria esperas
                message = "Pasta inacessível (a rede caiu?)"
                raise OSError(errno.ENOENT, message, str(folder)) from None
            if len(paths) == 1:
                stderr = (self._et.last_stderr or "").strip().splitlines()
                log.warning("ExifTool não leu %s: %s", paths[0], stderr[0] if stderr else "")
                return []
            mid = len(paths) // 2
            return self.read(paths[:mid], tags, params) + self.read(paths[mid:], tags, params)

    def write(self, path: str | Path, params: list[str]) -> None:
        """Executa um comando de escrita (ex.: ``["-XMP-dc:Subject+=praia"]``) num arquivo.
        Levanta ``OSError`` com a mensagem do ExifTool se ele falhar."""
        self._et.execute(*params, str(path))
        if self._et.last_status:
            message = (self._et.last_stderr or "").strip()
            raise OSError(message or f"ExifTool terminou com status {self._et.last_status}")
