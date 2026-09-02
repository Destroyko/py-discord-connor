"""Применение SQL-миграций по порядку (см. IMPLEMENTATION_PLAN.md P0.4).

Файлы ``migrations/NNNN_*.sql`` применяются в порядке номера. Применённые версии
записываются в таблицу ``schema_version``. Повторный запуск не делает ничего.

DDL в миграциях обязан быть идемпотентным (``IF NOT EXISTS``): если процесс упал
между ``executescript`` и записью версии, следующий старт прогонит миграцию ещё раз
и не должен на этом падать.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

import aiosqlite

_FILE_RE = re.compile(r"\A(\d{4})_.+\.sql\Z")


def _discover(migrations_dir: Path) -> list[tuple[int, Path]]:
    found: list[tuple[int, Path]] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        m = _FILE_RE.match(path.name)
        if m is None:
            continue
        found.append((int(m.group(1)), path))
    versions = [v for v, _ in found]
    if len(versions) != len(set(versions)):
        raise ValueError(f"дублирующиеся номера миграций в {migrations_dir}")
    return found


async def apply_migrations(conn: aiosqlite.Connection, migrations_dir: Path) -> list[int]:
    """Применить недостающие миграции. Возвращает список применённых версий (в порядке)."""
    await conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_version ("
        " version INTEGER PRIMARY KEY,"
        " applied_at INTEGER NOT NULL)"
    )
    await conn.commit()

    async with conn.execute("SELECT version FROM schema_version") as cur:
        applied = {row[0] for row in await cur.fetchall()}

    newly: list[int] = []
    for version, path in _discover(migrations_dir):
        if version in applied:
            continue
        await conn.executescript(path.read_text(encoding="utf-8"))
        await conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (version, int(time.time())),
        )
        await conn.commit()
        newly.append(version)

    return newly
