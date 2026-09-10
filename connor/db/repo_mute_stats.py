"""Статистика выданных мьютов по модераторам (``mute_events``) — команда
``/mutestats`` (см. ``mute.md`` §"Статистика").

Одна строка на выданное наказание. Обновление длительности мьюта строк не
добавляет и ``moderator_id`` не меняет (наказание остаётся за первым выдавшим).
Строка перестаёт учитываться (``strike_by_message``), когда лог-сообщение бота о
муте удаляют из чата.
"""

from __future__ import annotations

from connor.db import Database


class RepoMuteStats:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self,
        *,
        target_id: int,
        moderator_id: int,
        created_at: int,
        message_id: int | None,
        channel_id: int | None,
    ) -> None:
        """Зафиксировать свежий мут. Для обновления длительности не вызывается."""
        await self._db.conn.execute(
            "INSERT INTO mute_events "
            "(target_id, moderator_id, created_at, message_id, channel_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (target_id, moderator_id, created_at, message_id, channel_id),
        )
        await self._db.conn.commit()

    async def strike_by_message(self, message_id: int, struck_at: int) -> int:
        """Лог-сообщение о муте удалено → наказание больше не считается. Возвращает
        число затронутых строк (``0``, если сообщение не наше или уже вычеркнуто)."""
        cur = await self._db.conn.execute(
            "UPDATE mute_events SET struck_at = ? WHERE message_id = ? AND struck_at IS NULL",
            (struck_at, message_id),
        )
        await self._db.conn.commit()
        return cur.rowcount

    async def ladder(self, since: int) -> list[tuple[int, int]]:
        """``[(moderator_id, count), ...]`` по убыванию count (ничьи — по
        ``moderator_id``). ``since`` — нижняя граница ``created_at`` (Unix-сек
        UTC); ``0`` = за всё время. Вычеркнутые строки не считаются.

        Фильтр «модератор ещё имеет права» — на вызывающей стороне (нужен guild)."""
        async with self._db.conn.execute(
            "SELECT moderator_id, COUNT(*) AS n FROM mute_events "
            "WHERE struck_at IS NULL AND created_at >= ? "
            "GROUP BY moderator_id ORDER BY n DESC, moderator_id ASC",
            (since,),
        ) as cur:
            rows = await cur.fetchall()
        return [(r[0], r[1]) for r in rows]
