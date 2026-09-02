"""Недельный опыт (``voice_xp_week``) и недельный цикл (``voice_cycle``) — см.
``Voices.md`` § "Хранимые данные".

- ``voice_xp_week`` — накопленный за неделю счёт по участникам; ``seq``
  (AUTOINCREMENT) фиксирует порядок первого начисления в неделе, на нём держится
  разрешение ничьих (``ORDER BY points DESC, seq ASC``). Запись создаётся только
  при ненулевом приросте.
- ``voice_cycle`` — ровно одна строка: ``anchor_ts`` (точка отсчёта, ставится при
  первом чистом старте, сдвигается на перевыдаче) и ``current_dusha_id`` (кому
  сейчас выдана роль — нужно, чтобы снять её на следующей перевыдаче).
"""

from __future__ import annotations

from dataclasses import dataclass

from connor.db import Database


@dataclass(frozen=True, slots=True)
class VoiceCycle:
    anchor_ts: int
    current_dusha_id: int | None


class RepoVoiceXp:
    def __init__(self, db: Database) -> None:
        self._db = db

    # -- недельный счёт ------------------------------------------------------

    async def add_points(self, deltas: dict[int, int]) -> None:
        """Батч-начисление: ``points += delta`` по каждому ``user_id`` (UPSERT).

        Первое начисление пользователю в неделе создаёт строку и назначает ``seq``
        (порядок вставки). Нулевые дельты вызывающий не передаёт.
        """
        if not deltas:
            return
        await self._db.conn.executemany(
            "INSERT INTO voice_xp_week (user_id, points) VALUES (?, ?) "
            "ON CONFLICT(user_id) DO UPDATE SET points = points + excluded.points",
            list(deltas.items()),
        )
        await self._db.conn.commit()

    async def standings(self) -> list[tuple[int, int]]:
        """``[(user_id, points), ...]`` с ``points > 0``, порядок ``points DESC, seq ASC``."""
        async with self._db.conn.execute(
            "SELECT user_id, points FROM voice_xp_week WHERE points > 0 "
            "ORDER BY points DESC, seq ASC"
        ) as cur:
            rows = await cur.fetchall()
        return [(r[0], r[1]) for r in rows]

    async def reset_week(self) -> None:
        """Обнулить недельный счёт (после перевыдачи). ``seq`` начинается заново."""
        await self._db.conn.execute("DELETE FROM voice_xp_week")
        await self._db.conn.execute("DELETE FROM sqlite_sequence WHERE name = 'voice_xp_week'")
        await self._db.conn.commit()

    # -- недельный цикл ----------------------------------------------------------

    async def ensure_cycle(self, anchor_ts: int) -> VoiceCycle:
        """Создать строку цикла с ``anchor_ts``, если её ещё нет; вернуть текущую."""
        await self._db.conn.execute(
            "INSERT OR IGNORE INTO voice_cycle (id, anchor_ts, current_dusha_id) "
            "VALUES (1, ?, NULL)",
            (anchor_ts,),
        )
        await self._db.conn.commit()
        cycle = await self.get_cycle()
        assert cycle is not None
        return cycle

    async def get_cycle(self) -> VoiceCycle | None:
        async with self._db.conn.execute(
            "SELECT anchor_ts, current_dusha_id FROM voice_cycle WHERE id = 1"
        ) as cur:
            row = await cur.fetchone()
        return VoiceCycle(row[0], row[1]) if row is not None else None

    async def set_cycle(self, *, anchor_ts: int, current_dusha_id: int | None) -> None:
        await self._db.conn.execute(
            "UPDATE voice_cycle SET anchor_ts = ?, current_dusha_id = ? WHERE id = 1",
            (anchor_ts, current_dusha_id),
        )
        await self._db.conn.commit()
