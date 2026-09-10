"""RepoGiveStats — тэлли решений по заявкам (одобрено/отказ) по модераторам."""

from __future__ import annotations

from connor.db import Database
from connor.db.repo_give_stats import RepoGiveStats


def _flat(ladder: list) -> list[tuple[int, int, int, int]]:
    return [(t.moderator_id, t.total, t.approved, t.refused) for t in ladder]


async def test_ladder_tally_and_order(db: Database) -> None:
    repo = RepoGiveStats(db)
    for _ in range(3):
        await repo.record(target_id=1, moderator_id=10, decided_at=100, approved=True)
    await repo.record(target_id=2, moderator_id=10, decided_at=100, approved=False)
    await repo.record(target_id=3, moderator_id=20, decided_at=100, approved=True)

    assert _flat(await repo.ladder(0)) == [(10, 4, 3, 1), (20, 1, 1, 0)]


async def test_ladder_since_is_inclusive_lower_bound(db: Database) -> None:
    repo = RepoGiveStats(db)
    await repo.record(target_id=1, moderator_id=10, decided_at=100, approved=True)
    await repo.record(target_id=2, moderator_id=10, decided_at=200, approved=False)

    assert _flat(await repo.ladder(200)) == [(10, 1, 0, 1)]
    assert _flat(await repo.ladder(201)) == []
