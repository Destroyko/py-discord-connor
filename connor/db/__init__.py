"""Слой БД: SQLite через aiosqlite.

``Database`` — одно соединение на весь процесс (единственный писатель). Открытие
ставит PRAGMA (WAL / NORMAL / foreign_keys / busy_timeout) и прогоняет миграции.
Доступ к данным по доменам — модули ``repo_*.py``, они берут ``db.conn``.
"""

from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

from connor.db.migrations import apply_migrations

log = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_MIGRATIONS_DIR = _REPO_ROOT / "migrations"

# Порядок важен: journal_mode до записи; foreign_keys — только per-connection.
_PRAGMAS: tuple[str, ...] = (
    "PRAGMA journal_mode=WAL",
    "PRAGMA synchronous=NORMAL",
    "PRAGMA foreign_keys=ON",
    "PRAGMA busy_timeout=5000",
)


class Database:
    def __init__(self, path: str, *, migrations_dir: Path | None = None) -> None:
        self._path = path
        self._migrations_dir = migrations_dir or _MIGRATIONS_DIR
        self._conn: aiosqlite.Connection | None = None
        #: версии, реально применённые на последнем connect() (пусто, если БД уже актуальна)
        self.applied_migrations: list[int] = []

    @property
    def conn(self) -> aiosqlite.Connection:
        if self._conn is None:
            raise RuntimeError("Database не подключена: сначала await connect()")
        return self._conn

    async def connect(self) -> None:
        """Открыть соединение, применить PRAGMA и миграции."""
        conn = await aiosqlite.connect(self._path)
        conn.row_factory = aiosqlite.Row
        for pragma in _PRAGMAS:
            await conn.execute(pragma)
        await conn.commit()
        self._conn = conn

        self.applied_migrations = await apply_migrations(conn, self._migrations_dir)
        if self.applied_migrations:
            versions = ", ".join(f"{v:04d}" for v in self.applied_migrations)
            log.info("применены миграции БД: %s", versions)

    async def ping(self) -> None:
        """Живой запрос ``SELECT 1``. Бросает, если соединение отвалилось."""
        async with self.conn.execute("SELECT 1") as cur:
            await cur.fetchone()

    async def close(self) -> None:
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
