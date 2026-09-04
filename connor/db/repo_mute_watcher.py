"""Курсор опроса audit log для вотчера ручных изменений Discord timeout (мут/анмут
через UI, в обход `/mute` и `/unmute`), см. ``mute.md`` § "Наблюдение за ручными
изменениями таймаута".

Одна строка (``id=1``): id последней уже обработанной записи журнала аудита.
Переживает рестарт — тот же принцип, что и у ``RepoAntiWatcher``, но отдельная
таблица: вотчеры следят за разными типами записей audit log
(``member_update`` здесь, ``member_role_update`` у анти-работяги).
"""

from __future__ import annotations

from connor.db import Database


class RepoMuteWatcher:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_cursor(self) -> int | None:
        async with self._db.conn.execute(
            "SELECT last_entry_id FROM mute_watcher_cursor WHERE id = 1"
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row is not None else None

    async def set_cursor(self, last_entry_id: int) -> None:
        await self._db.conn.execute(
            "INSERT INTO mute_watcher_cursor (id, last_entry_id) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_entry_id = excluded.last_entry_id",
            (last_entry_id,),
        )
        await self._db.conn.commit()
