"""Доступ к анти-списку (``anti_list``) — см. ``anti.md`` § "Хранимые данные".

Хранится: user_id, дата добавления, id добавившего модератора. Причина **не**
хранится (используется только в embed'е в момент отправки). Статус не привязан к
членству на сервере — переживает выход/повторный вход.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from connor.db import Database


@dataclass(frozen=True, slots=True)
class AntiEntry:
    user_id: int
    added_at: int
    added_by: int


class RepoAnti:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, user_id: int, *, added_at: int, added_by: int) -> bool:
        """``True`` — добавлен; ``False`` — уже был в списке (запись не тронута)."""
        try:
            await self._db.conn.execute(
                "INSERT INTO anti_list (user_id, added_at, added_by) VALUES (?, ?, ?)",
                (user_id, added_at, added_by),
            )
        except sqlite3.IntegrityError:
            return False
        await self._db.conn.commit()
        return True

    async def remove(self, user_id: int) -> bool:
        """``True`` — запись была и удалена; ``False`` — записи не было."""
        cur = await self._db.conn.execute("DELETE FROM anti_list WHERE user_id = ?", (user_id,))
        await self._db.conn.commit()
        return cur.rowcount > 0

    async def contains(self, user_id: int) -> bool:
        async with self._db.conn.execute(
            "SELECT 1 FROM anti_list WHERE user_id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone() is not None

    async def get(self, user_id: int) -> AntiEntry | None:
        async with self._db.conn.execute(
            "SELECT user_id, added_at, added_by FROM anti_list WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        return AntiEntry(row[0], row[1], row[2]) if row is not None else None
