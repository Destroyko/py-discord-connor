"""P4 — репозитории Voices: реестр комнат, персональные бан-листы, недельный опыт."""

from __future__ import annotations

from connor.db import Database
from connor.db.repo_voice_banlist import RepoVoiceBanlist
from connor.db.repo_voice_rooms import RepoVoiceRooms
from connor.db.repo_voice_xp import RepoVoiceXp

# --- voice_rooms ------------------------------------------------------------------


async def test_rooms_upsert_and_lookup(db: Database) -> None:
    repo = RepoVoiceRooms(db)
    await repo.upsert(owner_id=1, channel_id=10, created_at=100)

    assert (await repo.get_by_owner(1)).channel_id == 10
    assert (await repo.get_by_channel(10)).owner_id == 1
    assert await repo.get_by_owner(999) is None
    assert await repo.get_by_channel(999) is None


async def test_rooms_upsert_replaces_channel(db: Database) -> None:
    repo = RepoVoiceRooms(db)
    await repo.upsert(owner_id=1, channel_id=10, created_at=100)
    await repo.upsert(owner_id=1, channel_id=20, created_at=200)

    assert (await repo.get_by_owner(1)).channel_id == 20
    assert await repo.get_by_channel(10) is None
    assert len(await repo.all()) == 1


async def test_rooms_remove(db: Database) -> None:
    repo = RepoVoiceRooms(db)
    await repo.upsert(owner_id=1, channel_id=10, created_at=100)
    assert await repo.remove_by_owner(1) is True
    assert await repo.remove_by_owner(1) is False
    assert await repo.all() == []


# --- voice_banlist ------------------------------------------------------------------


async def test_banlist_add_contains_count(db: Database) -> None:
    repo = RepoVoiceBanlist(db)
    await repo.upsert(owner_id=1, banned_id=5, ts=100)
    await repo.upsert(owner_id=1, banned_id=6, ts=110)
    await repo.upsert(owner_id=2, banned_id=5, ts=120)

    assert await repo.contains(1, 5) is True
    assert await repo.contains(1, 99) is False
    assert await repo.count(1) == 2
    assert await repo.count(2) == 1


async def test_banlist_upsert_refreshes_ts(db: Database) -> None:
    repo = RepoVoiceBanlist(db)
    await repo.upsert(owner_id=1, banned_id=5, ts=100)
    await repo.upsert(owner_id=1, banned_id=5, ts=500)

    assert await repo.count(1) == 1
    assert [b.ts for b in await repo.list_for(1)] == [500]


async def test_banlist_remove(db: Database) -> None:
    repo = RepoVoiceBanlist(db)
    await repo.upsert(owner_id=1, banned_id=5, ts=100)
    assert await repo.remove(1, 5) is True
    assert await repo.remove(1, 5) is False


async def test_banlist_list_ordered_by_ts(db: Database) -> None:
    repo = RepoVoiceBanlist(db)
    await repo.upsert(owner_id=1, banned_id=7, ts=300)
    await repo.upsert(owner_id=1, banned_id=8, ts=100)
    await repo.upsert(owner_id=1, banned_id=9, ts=200)

    assert [b.banned_id for b in await repo.list_for(1)] == [8, 9, 7]


async def test_banlist_active_ids_window(db: Database) -> None:
    repo = RepoVoiceBanlist(db)
    await repo.upsert(owner_id=1, banned_id=5, ts=1000)  # свежая
    await repo.upsert(owner_id=1, banned_id=6, ts=200)  # старая

    assert sorted(await repo.active_ids(1, since_ts=500)) == [5]
    assert sorted(await repo.active_ids(1, since_ts=100)) == [5, 6]


# --- voice_xp_week / voice_cycle -------------------------------------------------


async def test_xp_add_and_accumulate(db: Database) -> None:
    repo = RepoVoiceXp(db)
    await repo.add_points({1: 10, 2: 8})
    await repo.add_points({1: 5})

    assert await repo.standings() == [(1, 15), (2, 8)]


async def test_xp_standings_tie_break_is_insertion_order(db: Database) -> None:
    repo = RepoVoiceXp(db)
    await repo.add_points({7: 10})  # seq 1
    await repo.add_points({3: 10})  # seq 2
    await repo.add_points({9: 10})  # seq 3

    assert await repo.standings() == [(7, 10), (3, 10), (9, 10)]


async def test_xp_standings_excludes_zero(db: Database) -> None:
    repo = RepoVoiceXp(db)
    await repo.add_points({1: 0})
    assert await repo.standings() == []


async def test_xp_reset_clears_and_restarts_seq(db: Database) -> None:
    repo = RepoVoiceXp(db)
    await repo.add_points({1: 10, 2: 20})
    await repo.reset_week()
    assert await repo.standings() == []

    # после сброса seq начинается заново: порядок вставки снова с 1
    await repo.add_points({5: 10})
    await repo.add_points({6: 10})
    assert await repo.standings() == [(5, 10), (6, 10)]


async def test_cycle_ensure_is_idempotent(db: Database) -> None:
    repo = RepoVoiceXp(db)
    first = await repo.ensure_cycle(1000)
    again = await repo.ensure_cycle(9999)  # не перезаписывает существующий anchor

    assert first.anchor_ts == 1000
    assert again.anchor_ts == 1000
    assert again.current_dusha_id is None


async def test_cycle_set(db: Database) -> None:
    repo = RepoVoiceXp(db)
    await repo.ensure_cycle(1000)
    await repo.set_cycle(anchor_ts=2000, current_dusha_id=42)

    cycle = await repo.get_cycle()
    assert cycle.anchor_ts == 2000
    assert cycle.current_dusha_id == 42

    await repo.set_cycle(anchor_ts=3000, current_dusha_id=None)
    assert (await repo.get_cycle()).current_dusha_id is None
