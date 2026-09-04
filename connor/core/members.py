"""Резолв участника-цели по id: кэш → живой fetch.

``guild.get_member`` смотрит только в частичный member cache (``bot.py`` держит
``MemberCacheFlags(voice=True, joined=False)`` — кэшируются только войс-стейты,
см. ``environment.md`` "Реальная нагрузка от масштаба"). Участник, не бывавший в
войсе после последнего рестарта бота, туда не попадёт, хотя реально на сервере —
поэтому решение "цель на сервере или уже нет" нельзя принимать по одному
``get_member``, нужен фоллбек на живой запрос.
"""

from __future__ import annotations

import discord


async def fetch_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except discord.NotFound:
        return None
