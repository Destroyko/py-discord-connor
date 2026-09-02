"""Отложенные муты (``pending_mutes``) — см. ``mute.md`` § "Отложенный мут".

Цель вышла с сервера до наложения Discord timeout → команда модератора
запоминается и применяется при возвращении пользователя. Одна запись на
пользователя (``user_id`` PK, ``INSERT OR REPLACE`` — последняя команда
побеждает). Персистентно: ждёт возвращения сутками; чистится по ``queued_at``
(TTL из ``config/mute.toml``).
"""

from __future__ import annotations

from dataclasses import dataclass

from connor.db import Database


@dataclass(frozen=True, slots=True)
class PendingMute:
    user_id: int
    duration: str
    reason: str
    moderator_id: int
    queued_at: int


class RepoPendingMute:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def upsert(
        self,
        user_id: int,
        *,
        duration: str,
        reason: str,
        moderator_id: int,
        queued_at: int,
    ) -> None:
        await self._db.conn.execute(
            "INSERT OR REPLACE INTO pending_mutes "
            "(user_id, duration, reason, moderator_id, queued_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, duration, reason, moderator_id, queued_at),
        )
        await self._db.conn.commit()

    async def get(self, user_id: int) -> PendingMute | None:
        async with self._db.conn.execute(
            "SELECT user_id, duration, reason, moderator_id, queued_at "
            "FROM pending_mutes WHERE user_id = ?",
            (user_id,),
        ) as cur:
            row = await cur.fetchone()
        return PendingMute(row[0], row[1], row[2], row[3], row[4]) if row is not None else None

    async def remove(self, user_id: int) -> bool:
        """``True`` — запись была и удалена."""
        cur = await self._db.conn.execute(
            "DELETE FROM pending_mutes WHERE user_id = ?", (user_id,)
        )
        await self._db.conn.commit()
        return cur.rowcount > 0

    async def all(self) -> list[PendingMute]:
        async with self._db.conn.execute(
            "SELECT user_id, duration, reason, moderator_id, queued_at FROM pending_mutes"
        ) as cur:
            rows = await cur.fetchall()
        return [PendingMute(r[0], r[1], r[2], r[3], r[4]) for r in rows]

    async def purge_older_than(self, cutoff_ts: int) -> int:
        """Удалить записи с ``queued_at < cutoff_ts``. Возвращает число удалённых."""
        cur = await self._db.conn.execute(
            "DELETE FROM pending_mutes WHERE queued_at < ?", (cutoff_ts,)
        )
        await self._db.conn.commit()
        return cur.rowcount
