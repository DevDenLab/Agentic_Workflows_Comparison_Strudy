"""SQLite access shared by the queue, idempotency store, human queue, DLQ and stand-in ITSM.

Every operation opens its own connection through `SqliteDatabase.transaction`, so the busy timeout
and WAL mode apply to every connection. Setting them once on a boot-time connection is a known trap.
"""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pydantic import Field

from triage.config import ConfigModel


class StorageConfig(ConfigModel):
    busy_timeout_seconds: float = Field(gt=0)


class SqliteDatabase:
    def __init__(self, path: Path, config: StorageConfig) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._timeout = config.busy_timeout_seconds

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """Commit on success, roll back on error, always close."""
        conn = sqlite3.connect(self.path, timeout=self._timeout)
        try:
            conn.execute("PRAGMA journal_mode = WAL")
            with conn:
                yield conn
        finally:
            conn.close()

    def apply_schema(self, schema_sql: str) -> None:
        with self.transaction() as conn:
            conn.executescript(schema_sql)
