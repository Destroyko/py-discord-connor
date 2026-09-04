"""Курсор опроса audit log для вотчера ручных изменений роли «работяга» (см.
``anti.md`` § "Наблюдение за ручными изменениями роли").

Одна строка (``id=1``): id последней уже обработанной записи журнала аудита.
Переживает рестарт — без этого при каждом старте пришлось бы либо заново
разбирать всю историю аудита, либо терять записи, случившиеся, пока бот лежал.
"""

from __future__ import annotations

from connor.db import Database


class RepoAntiWatcher:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_cursor(self) -> int | None:
        async with self._db.conn.execute(
            "SELECT last_entry_id FROM anti_watcher_cursor WHERE id = 1"
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row is not None else None

    async def set_cursor(self, last_entry_id: int) -> None:
        await self._db.conn.execute(
            "INSERT INTO anti_watcher_cursor (id, last_entry_id) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_entry_id = excluded.last_entry_id",
            (last_entry_id,),
        )
        await self._db.conn.commit()
