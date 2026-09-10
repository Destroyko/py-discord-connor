"""Статистика обработанных заявок на роль «работяга» по модераторам
(``give_decisions``) — команда ``/givestats`` (см. ``roleGiver.md``).

Одна строка на решение по заявке (☑️/❌ в ``#реквесты-работяг``). Авто-выдача
чистым аккаунтам не пишется — там нет модератора. Решение терминально.
"""

from __future__ import annotations

from dataclasses import dataclass

from connor.db import Database


@dataclass(frozen=True, slots=True)
class GiveTally:
    moderator_id: int
    total: int
    approved: int
    refused: int


class RepoGiveStats:
    def __init__(self, db: Database) -> None:
        self._db = db

    async def record(
        self, *, target_id: int, moderator_id: int, decided_at: int, approved: bool
    ) -> None:
        await self._db.conn.execute(
            "INSERT INTO give_decisions (target_id, moderator_id, decided_at, approved) "
            "VALUES (?, ?, ?, ?)",
            (target_id, moderator_id, decided_at, int(approved)),
        )
        await self._db.conn.commit()

    async def ladder(self, since: int) -> list[GiveTally]:
        """Тэлли по модераторам, порядок ``total DESC`` (ничьи — по
        ``moderator_id``). ``since`` — нижняя граница ``decided_at`` (Unix-сек
        UTC); ``0`` = за всё время.

        Фильтр «модератор ещё имеет права» — на вызывающей стороне (нужен guild)."""
        async with self._db.conn.execute(
            "SELECT moderator_id, COUNT(*) AS n, "
            "COALESCE(SUM(approved), 0), COALESCE(SUM(1 - approved), 0) "
            "FROM give_decisions WHERE decided_at >= ? "
            "GROUP BY moderator_id ORDER BY n DESC, moderator_id ASC",
            (since,),
        ) as cur:
            rows = await cur.fetchall()
        return [GiveTally(r[0], r[1], r[2], r[3]) for r in rows]
