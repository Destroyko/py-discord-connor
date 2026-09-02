"""Точечный запрет писать в «предложку» для анти-работяг (см. ``check.md``).

Общий код для ``anti`` (``/add`` ставит, ``/del`` снимает) и ``check`` (ленивая
простановка на ``on_message``, реконсиляция в ``/check``).

Overwrite ставится **персонально на пользователя** (не через роль) и блокирует
только ``Send Messages``; ``View Channel`` и чтение истории не трогаются. Факт
простановки ботом отмечается в БД (``RepoPredlozhka``), чтобы реконсиляция снимала
только своё.
"""

from __future__ import annotations

import logging
from time import time
from typing import Protocol

import discord

from connor.db.repo_predlozhka import RepoPredlozhka

log = logging.getLogger(__name__)


class _Overwritable(Protocol):
    async def set_permissions(
        self, target: discord.Member, *, overwrite: discord.PermissionOverwrite | None, reason: str
    ) -> None: ...

    def overwrites_for(self, target: discord.Member) -> discord.PermissionOverwrite: ...


async def apply_deny(
    channel: _Overwritable, member: discord.Member, repo: RepoPredlozhka, *, reason: str
) -> None:
    """Запретить ``member`` писать в «предложку» и отметить это в БД."""
    overwrite = channel.overwrites_for(member)
    overwrite.send_messages = False
    try:
        await channel.set_permissions(member, overwrite=overwrite, reason=reason)
    except discord.HTTPException:
        log.error("не удалось поставить deny-overwrite в предложке для %s (%d)", member, member.id)
        return
    await repo.add(member.id, reason=reason, set_at=int(time()))


async def clear_deny(channel: _Overwritable, member: discord.Member, repo: RepoPredlozhka) -> bool:
    """Снять бот-овый запрет, если он есть. ``True`` — что-то сняли.

    Снимает только точечный ``send_messages``-deny; если после этого у пользователя
    на канале не осталось никаких персональных прав — overwrite убирается целиком.
    Запись модератора (если он ставил свой overwrite) не трогается — ориентир на БД.
    """
    if not await repo.contains(member.id):
        return False

    overwrite = channel.overwrites_for(member)
    overwrite.send_messages = None
    new_overwrite = None if overwrite.is_empty() else overwrite
    try:
        await channel.set_permissions(member, overwrite=new_overwrite, reason="снят анти-запрет")
    except discord.HTTPException:
        log.error("не удалось снять deny-overwrite в предложке для %s (%d)", member, member.id)
        return False
    await repo.remove(member.id)
    return True
