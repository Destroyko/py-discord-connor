"""Курсор опроса audit log для вотчера ручных киков (через Discord UI, в обход
`/kick`), см. ``banKick.md`` § "Наблюдение за ручными киками".

По строке на тип записи (сейчас только ``kick``): id последней уже обработанной
записи журнала аудита. Переживает рестарт.
"""

from __future__ import annotations

from connor.db import Database


class RepoBanWatcher:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def get_cursor(self, kind: str) -> int | None:
        async with self._db.conn.execute(
            "SELECT last_entry_id FROM ban_watcher_cursor WHERE kind = ?", (kind,)
        ) as cur:
            row = await cur.fetchone()
        return row[0] if row is not None else None

    async def set_cursor(self, kind: str, last_entry_id: int) -> None:
        await self._db.conn.execute(
            "INSERT INTO ban_watcher_cursor (kind, last_entry_id) VALUES (?, ?) "
            "ON CONFLICT(kind) DO UPDATE SET last_entry_id = excluded.last_entry_id",
            (kind, last_entry_id),
        )
        await self._db.conn.commit()
