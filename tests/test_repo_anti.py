"""P3.1 — RepoAnti."""

from __future__ import annotations

from connor.db import Database
from connor.db.repo_anti import RepoAnti


async def test_add_contains_get_remove(db: Database) -> None:
    repo = RepoAnti(db)

    assert await repo.contains(42) is False
    assert await repo.add(42, added_at=1000, added_by=7) is True

    assert await repo.contains(42) is True
    entry = await repo.get(42)
    assert entry is not None
    assert (entry.user_id, entry.added_at, entry.added_by) == (42, 1000, 7)

    assert await repo.remove(42) is True
    assert await repo.contains(42) is False
    assert await repo.get(42) is None
    assert await repo.remove(42) is False  # уже нет


async def test_add_twice_returns_false(db: Database) -> None:
    repo = RepoAnti(db)
    assert await repo.add(1, added_at=1, added_by=1) is True
    assert await repo.add(1, added_at=2, added_by=2) is False
    entry = await repo.get(1)
    assert entry is not None and entry.added_at == 1  # первая запись не тронута
