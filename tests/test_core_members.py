"""connor.core.members.fetch_member — кэш → живой fetch, без ложных «не найден»."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from connor.core.members import fetch_member

_NOT_FOUND = discord.NotFound(SimpleNamespace(status=404, reason="x"), "no")


def _guild(*, cached: object | None, fetched: object | None) -> SimpleNamespace:
    fetch = (
        AsyncMock(side_effect=_NOT_FOUND) if fetched is None else AsyncMock(return_value=fetched)
    )
    return SimpleNamespace(get_member=lambda _i: cached, fetch_member=fetch)


async def test_returns_cached_member_without_fetching() -> None:
    sentinel = object()
    guild = _guild(cached=sentinel, fetched=None)
    assert await fetch_member(guild, 5) is sentinel
    guild.fetch_member.assert_not_awaited()


async def test_falls_back_to_live_fetch_when_not_cached() -> None:
    sentinel = object()
    guild = _guild(cached=None, fetched=sentinel)
    assert await fetch_member(guild, 5) is sentinel
    guild.fetch_member.assert_awaited_once_with(5)


async def test_returns_none_when_truly_absent() -> None:
    guild = _guild(cached=None, fetched=None)
    assert await fetch_member(guild, 5) is None
