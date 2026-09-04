"""P0.4 — слой БД: миграции, PRAGMA, ping, идемпотентность, тай-брейк voice_xp_week."""

from __future__ import annotations

from pathlib import Path

from connor.db import Database

_EXPECTED_TABLES = {
    "schema_version",
    "anti_list",
    "give_requests",
    "predlozhka_overwrites",
    "pending_mutes",
    "voice_rooms",
    "voice_banlist",
    "voice_xp_week",
    "voice_cycle",
    "anti_watcher_cursor",
}


async def _table_names(db: Database) -> set[str]:
    async with db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'") as cur:
        return {row[0] for row in await cur.fetchall()}


async def test_migrations_apply_on_fresh_file(db: Database) -> None:
    assert _EXPECTED_TABLES.issubset(await _table_names(db))
    async with db.conn.execute("SELECT version FROM schema_version") as cur:
        versions = {row[0] for row in await cur.fetchall()}
    assert versions == {1, 2, 3}


async def test_ping_ok(db: Database) -> None:
    await db.ping()  # не должно бросить


async def test_pragmas_set(db: Database) -> None:
    async with db.conn.execute("PRAGMA foreign_keys") as cur:
        assert (await cur.fetchone())[0] == 1
    async with db.conn.execute("PRAGMA journal_mode") as cur:
        assert (await cur.fetchone())[0].lower() == "wal"


async def test_reconnect_is_noop(tmp_path: Path) -> None:
    path = str(tmp_path / "test.sqlite3")

    first = Database(path)
    await first.connect()
    assert first.applied_migrations == [1, 2, 3]
    await first.close()

    second = Database(path)
    await second.connect()
    try:
        assert second.applied_migrations == []  # ничего нового
        assert _EXPECTED_TABLES.issubset(await _table_names(second))
    finally:
        await second.close()


async def test_voice_xp_week_tiebreak_is_insertion_order(db: Database) -> None:
    # три пользователя, все с одинаковыми очками, вставлены в известном порядке
    for user_id in (300, 100, 200):
        await db.conn.execute(
            "INSERT INTO voice_xp_week (user_id, points) VALUES (?, 10)", (user_id,)
        )
    await db.conn.commit()

    async with db.conn.execute(
        "SELECT user_id FROM voice_xp_week ORDER BY points DESC, seq ASC"
    ) as cur:
        order = [row[0] for row in await cur.fetchall()]

    assert order == [300, 100, 200]  # по порядку вставки, не по user_id
