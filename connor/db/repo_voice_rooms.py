"""Реестр приватных войс-комнат (``voice_rooms``) — см. ``Voices.md`` §
"Хранимые данные".

Один активный канал на владельца (``owner_id`` PK). Используется созданием комнат
(``voices_rooms.py``), самомодерацией (``voices_selfmod.py``) и минутной сверкой
реестра (``voices_xp.py``). Тик начисления опыта реестр не читает.
"""

from __future__ import annotations

from dataclasses import dataclass

from connor.db import Database


@dataclass(frozen=True, slots=True)
class VoiceRoom:
    owner_id: int
    channel_id: int
    created_at: int


class RepoVoiceRooms:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(self, owner_id: int, channel_id: int, created_at: int) -> None:
        await self._db.conn.execute(
            "INSERT OR REPLACE INTO voice_rooms (owner_id, channel_id, created_at) "
            "VALUES (?, ?, ?)",
            (owner_id, channel_id, created_at),
        )
        await self._db.conn.commit()

    async def get_by_owner(self, owner_id: int) -> VoiceRoom | None:
        async with self._db.conn.execute(
            "SELECT owner_id, channel_id, created_at FROM voice_rooms WHERE owner_id = ?",
            (owner_id,),
        ) as cur:
            row = await cur.fetchone()
        return VoiceRoom(row[0], row[1], row[2]) if row is not None else None

    async def get_by_channel(self, channel_id: int) -> VoiceRoom | None:
        async with self._db.conn.execute(
            "SELECT owner_id, channel_id, created_at FROM voice_rooms WHERE channel_id = ?",
            (channel_id,),
        ) as cur:
            row = await cur.fetchone()
        return VoiceRoom(row[0], row[1], row[2]) if row is not None else None

    async def remove_by_owner(self, owner_id: int) -> bool:
        cur = await self._db.conn.execute("DELETE FROM voice_rooms WHERE owner_id = ?", (owner_id,))
        await self._db.conn.commit()
        return cur.rowcount > 0

    async def all(self) -> list[VoiceRoom]:
        async with self._db.conn.execute(
            "SELECT owner_id, channel_id, created_at FROM voice_rooms"
        ) as cur:
            rows = await cur.fetchall()
        return [VoiceRoom(r[0], r[1], r[2]) for r in rows]
