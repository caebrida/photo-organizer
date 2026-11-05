"""Cache em SQLite dos hashes já calculados, para um novo escaneamento ser rápido.

A chave é caminho + tamanho + data de modificação: se o arquivo mudar, o hash é refeito.
"""

from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterable
from pathlib import Path


class HashCache:
    def __init__(self, path: str | Path) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.execute(
            "CREATE TABLE IF NOT EXISTS hashes ("
            " path TEXT NOT NULL, method TEXT NOT NULL, size INTEGER NOT NULL,"
            " mtime_ns INTEGER NOT NULL, value BLOB NOT NULL, PRIMARY KEY (path, method))"
        )

    def __enter__(self) -> HashCache:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._db.commit()
        self._db.close()

    def get(self, path: Path, method: str) -> bytes | None:
        try:
            st = Path(path).stat()
        except OSError:
            return None
        row = self._db.execute(
            "SELECT value FROM hashes WHERE path = ? AND method = ? AND size = ? AND mtime_ns = ?",
            (_key(path), method, st.st_size, st.st_mtime_ns),
        ).fetchone()
        return row[0] if row else None

    def put_many(self, method: str, items: Iterable[tuple[Path, bytes]]) -> None:
        rows = []
        for path, value in items:
            try:
                st = Path(path).stat()
            except OSError:
                continue
            rows.append((_key(path), method, st.st_size, st.st_mtime_ns, value))
        self._db.executemany("INSERT OR REPLACE INTO hashes VALUES (?, ?, ?, ?, ?)", rows)
        self._db.commit()


def _key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(path))  # noqa: PTH100 (resolve() acessa o disco)
