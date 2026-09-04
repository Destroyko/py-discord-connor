"""Курсор опроса audit log вотчера anti (см. anti.py § "Наблюдение...")."""

from __future__ import annotations

from connor.db import Database
from connor.db.repo_anti_watcher import RepoAntiWatcher


async def test_cursor_starts_unset(db: Database) -> None:
    assert await RepoAntiWatcher(db).get_cursor() is None


async def test_set_then_get_cursor(db: Database) -> None:
    repo = RepoAntiWatcher(db)
    await repo.set_cursor(100)
    assert await repo.get_cursor() == 100


async def test_set_cursor_overwrites_previous(db: Database) -> None:
    repo = RepoAntiWatcher(db)
    await repo.set_cursor(100)
    await repo.set_cursor(200)
    assert await repo.get_cursor() == 200
