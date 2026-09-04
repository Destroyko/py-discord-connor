"""Персональные бан-листы владельцев приватных войсов (``voice_banlist``) — см.
``Voices.md`` § "Хранимые данные".

Привязан к ``owner_id`` (не к экземпляру канала): переживает пересоздание комнаты
и выход/вход владельца на сервер. ``ts`` — момент добавления через ``/vkick``,
обновляется при реактивном блоке подключения к пересозданной комнате. Лимит
(≤100 на владельца) проверяется в коге, не здесь.
"""

from __future__ import annotations

from dataclasses import dataclass

from connor.db import Database


@dataclass(frozen=True, slots=True)
class VoiceBan:
    owner_id: int
    banned_id: int
    ts: int


class RepoVoiceBanlist:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, owner_id: int, banned_id: int, ts: int) -> None:
        """Добавить запись или обновить её ``ts`` (повторный ``/vkick``, реактивный блок)."""
        await self._db.conn.execute(
            "INSERT OR REPLACE INTO voice_banlist (owner_id, banned_id, ts) VALUES (?, ?, ?)",
            (owner_id, banned_id, ts),
        )
        await self._db.conn.commit()

    async def remove(self, owner_id: int, banned_id: int) -> bool:
        cur = await self._db.conn.execute(
            "DELETE FROM voice_banlist WHERE owner_id = ? AND banned_id = ?",
            (owner_id, banned_id),
        )
        await self._db.conn.commit()
        return cur.rowcount > 0

    async def contains(self, owner_id: int, banned_id: int) -> bool:
        async with self._db.conn.execute(
            "SELECT 1 FROM voice_banlist WHERE owner_id = ? AND banned_id = ?",
            (owner_id, banned_id),
        ) as cur:
            return await cur.fetchone() is not None

    async def count(self, owner_id: int) -> int:
        async with self._db.conn.execute(
            "SELECT COUNT(*) FROM voice_banlist WHERE owner_id = ?", (owner_id,)
        ) as cur:
            row = await cur.fetchone()
        return int(row[0]) if row is not None else 0

    async def list_for(self, owner_id: int) -> list[VoiceBan]:
        async with self._db.conn.execute(
            "SELECT owner_id, banned_id, ts FROM voice_banlist WHERE owner_id = ? "
            "ORDER BY ts ASC, banned_id ASC",
            (owner_id,),
        ) as cur:
            rows = await cur.fetchall()
        return [VoiceBan(r[0], r[1], r[2]) for r in rows]

    async def active_ids(self, owner_id: int, *, since_ts: int) -> list[int]:
        """id забаненных с ``ts >= since_ts`` — «активные» записи для проактивного
        переноса deny-overwrite на пересозданную комнату."""
        async with self._db.conn.execute(
            "SELECT banned_id FROM voice_banlist WHERE owner_id = ? AND ts >= ?",
            (owner_id, since_ts),
        ) as cur:
            rows = await cur.fetchall()
        return [r[0] for r in rows]
