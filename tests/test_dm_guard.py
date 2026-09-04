"""Обработка команд в ЛС боту."""

from __future__ import annotations

from types import SimpleNamespace

from connor.bot import _dm_guard_check
from connor.core.dm_guard import is_allowed_in_dm


def test_is_allowed_in_dm() -> None:
    assert is_allowed_in_dm("vdel") is True
    assert is_allowed_in_dm("ban_list") is True
    assert is_allowed_in_dm("mute") is False
    assert is_allowed_in_dm("") is False
    assert is_allowed_in_dm("VDEL") is False  # имена команд в нижнем регистре


def _ctx(*, guild: object | None, command_name: str | None):
    command = SimpleNamespace(name=command_name) if command_name is not None else None
    return SimpleNamespace(guild=guild, command=command)


async def test_guild_context_always_passes() -> None:
    assert await _dm_guard_check(_ctx(guild=object(), command_name="mute")) is True


async def test_dm_allows_whitelisted() -> None:
    assert await _dm_guard_check(_ctx(guild=None, command_name="vdel")) is True
    assert await _dm_guard_check(_ctx(guild=None, command_name="ban_list")) is True


async def test_dm_blocks_others() -> None:
    assert await _dm_guard_check(_ctx(guild=None, command_name="mute")) is False
    assert await _dm_guard_check(_ctx(guild=None, command_name=None)) is False
