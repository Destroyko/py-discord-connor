"""RepoGive."""

from __future__ import annotations

from connor.db import Database
from connor.db.repo_give import RepoGive


async def test_add_get_remove(db: Database) -> None:
    repo = RepoGive(db)

    assert await repo.get(1000) is None
    await repo.add(1000, user_id=42, created_at=555)

    req = await repo.get(1000)
    assert req is not None
    assert (req.message_id, req.user_id, req.created_at) == (1000, 42, 555)

    assert await repo.remove(1000) is True
    assert await repo.remove(1000) is False  # атомарный «захват»: второй раз пусто
    assert await repo.get(1000) is None
