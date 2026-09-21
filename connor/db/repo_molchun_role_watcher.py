"""Курсор опроса audit log для вотчера ручной выдачи/снятия роли «Молчун»
владельцем через Discord UI.

Одна строка (``id=1``): id последней уже обработанной записи журнала аудита.
Отдельная таблица от ``mute_watcher_cursor``: разные типы записей
(``member_role_update`` здесь, ``member_update`` у вотчера timeout).
"""

from __future__ import annotations

from connor.db import Database


class RepoMolchunRoleWatcher:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_cursor(self) -> int | None:
        async with self._db.conn.execute(
            "SELECT last_entry_id FROM molchun_role_watcher_cursor WHERE id = 1"
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row is not None else None

    async def set_cursor(self, last_entry_id: int) -> None:
        await self._db.conn.execute(
            "INSERT INTO molchun_role_watcher_cursor (id, last_entry_id) VALUES (1, ?) "
            "ON CONFLICT(id) DO UPDATE SET last_entry_id = excluded.last_entry_id",
            (last_entry_id,),
        )
        await self._db.conn.commit()
