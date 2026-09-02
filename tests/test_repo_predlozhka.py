"""P3.1 — RepoPredlozhka."""

from __future__ import annotations

from connor.db import Database
from connor.db.repo_predlozhka import RepoPredlozhka


async def test_add_contains_remove(db: Database) -> None:
    repo = RepoPredlozhka(db)

    assert await repo.contains(5) is False
    await repo.add(5, reason="анти-работяга", set_at=1000)
    assert await repo.contains(5) is True

    await repo.add(5, reason="повтор", set_at=2000)  # дубликат — молча игнор
    assert await repo.contains(5) is True

    assert await repo.remove(5) is True
    assert await repo.contains(5) is False
    assert await repo.remove(5) is False
