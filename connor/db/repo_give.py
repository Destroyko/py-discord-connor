"""Заявки ``!give`` на ручной проверке (``give_requests``) — см. ``roleGiver.md``
§ "Хранимые данные".

Ключ — id сообщения-заявки в ``#реквесты-работяг``. Персистентно: заявки висят
сутками, реакция может прийти уже после рестарта бота (обрабатывается через
"сырые" события).
"""

from __future__ import annotations

from dataclasses import dataclass

from connor.db import Database


@dataclass(frozen=True, slots=True)
class GiveRequest:
    message_id: int
    user_id: int
    created_at: int


class RepoGive:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def add(self, message_id: int, user_id: int, created_at: int) -> None:
        await self._db.conn.execute(
            "INSERT OR REPLACE INTO give_requests (message_id, user_id, created_at) "
            "VALUES (?, ?, ?)",
            (message_id, user_id, created_at),
        )
        await self._db.conn.commit()

    async def remove(self, message_id: int) -> bool:
        """``True`` — запись была и удалена (атомарный «захват» заявки)."""
        cur = await self._db.conn.execute(
            "DELETE FROM give_requests WHERE message_id = ?", (message_id,)
        )
        await self._db.conn.commit()
        return cur.rowcount > 0

    async def get(self, message_id: int) -> GiveRequest | None:
        async with self._db.conn.execute(
            "SELECT message_id, user_id, created_at FROM give_requests WHERE message_id = ?",
            (message_id,),
        ) as cur:
            row = await cur.fetchone()
        return GiveRequest(row[0], row[1], row[2]) if row is not None else None
