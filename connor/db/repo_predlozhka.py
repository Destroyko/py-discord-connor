"""Учёт deny-overwrite'ов в «предложке», выставленных **самим ботом** (см.
``check.md`` § "Обязательное разграничение «чей это overwrite»").

Нужен, чтобы реконсиляция (``/del``, ``/check``) снимала только бот-овые
ограничения и не трогала те, что модератор поставил вручную.
"""

from __future__ import annotations

import sqlite3

from connor.db import Database


class RepoPredlozhka:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, user_id: int, *, reason: str, set_at: int) -> None:
        try:
            await self._db.conn.execute(
                "INSERT INTO predlozhka_overwrites (user_id, reason, set_at) VALUES (?, ?, ?)",
                (user_id, reason, set_at),
            )
        except sqlite3.IntegrityError:
            return  # уже отмечен — не дублируем
        await self._db.conn.commit()

    async def remove(self, user_id: int) -> bool:
        cur = await self._db.conn.execute(
            "DELETE FROM predlozhka_overwrites WHERE user_id = ?", (user_id,)
        )
        await self._db.conn.commit()
        return cur.rowcount > 0

    async def contains(self, user_id: int) -> bool:
        async with self._db.conn.execute(
            "SELECT 1 FROM predlozhka_overwrites WHERE user_id = ?", (user_id,)
        ) as cur:
            return await cur.fetchone() is not None
