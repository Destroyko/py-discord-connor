"""RepoMuteStats — запись свежего мута, ладдер с нижней границей, вычёркивание
по удалённому лог-сообщению."""

from __future__ import annotations

from connor.db import Database
from connor.db.repo_mute_stats import RepoMuteStats


async def _rec(
    repo: RepoMuteStats,
    *,
    target: int,
    mod: int,
    at: int,
    msg: int | None = None,
    chan: int | None = None,
) -> None:
    await repo.record(
        target_id=target, moderator_id=mod, created_at=at, message_id=msg, channel_id=chan
    )


async def test_ladder_counts_and_orders_desc(db: Database) -> None:
    repo = RepoMuteStats(db)
    await _rec(repo, target=1, mod=10, at=100)
    await _rec(repo, target=2, mod=10, at=110)
    await _rec(repo, target=3, mod=20, at=120)

    assert await repo.ladder(0) == [(10, 2), (20, 1)]


async def test_ladder_since_is_inclusive_lower_bound(db: Database) -> None:
    repo = RepoMuteStats(db)
    await _rec(repo, target=1, mod=10, at=100)
    await _rec(repo, target=2, mod=10, at=200)

    assert await repo.ladder(150) == [(10, 1)]
    assert await repo.ladder(200) == [(10, 1)]  # граница включительна
    assert await repo.ladder(201) == []


async def test_strike_by_message_excludes_row(db: Database) -> None:
    repo = RepoMuteStats(db)
    await _rec(repo, target=1, mod=10, at=100, msg=555, chan=1)
    await _rec(repo, target=2, mod=10, at=110, msg=556, chan=1)

    assert await repo.strike_by_message(555, struck_at=900) == 1
    assert await repo.ladder(0) == [(10, 1)]


async def test_strike_is_idempotent_and_scoped_to_message(db: Database) -> None:
    repo = RepoMuteStats(db)
    await _rec(repo, target=1, mod=10, at=100, msg=555, chan=1)

    assert await repo.strike_by_message(555, struck_at=900) == 1
    assert await repo.strike_by_message(555, struck_at=999) == 0  # уже вычеркнут
    assert await repo.strike_by_message(123, struck_at=900) == 0  # не наше сообщение
    assert await repo.ladder(0) == []


async def test_record_without_message_ref_still_counts(db: Database) -> None:
    repo = RepoMuteStats(db)
    await _rec(repo, target=1, mod=10, at=100)  # message_id / channel_id = None
    assert await repo.ladder(0) == [(10, 1)]
