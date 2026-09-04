"""P0.5 — bootstrap: intents/кэш/пинги и маппинг ошибок запуска на код выхода."""

from __future__ import annotations

from types import SimpleNamespace

import discord
import pytest

from connor.bot import ConnorBot, _command_perms_check, meets_default_permissions, run_bot
from connor.core.permissions import CommandPermissionsCache


class _FakeConfig:
    guild_id = 123456789012345678
    bot_token = "fake-token"
    db_path = ":memory:"


@pytest.fixture
def bot() -> ConnorBot:
    return ConnorBot(_FakeConfig())  # type: ignore[arg-type]


def test_intents(bot: ConnorBot) -> None:
    assert bot.intents.members is True
    assert bot.intents.message_content is True
    assert bot.intents.voice_states is True
    assert bot.intents.presences is False


def test_partial_member_cache(bot: ConnorBot) -> None:
    # полный кэш неприемлем по памяти на больших гильдиях (сотни тысяч участников);
    # вотчер anti.py поэтому не полагается на member cache — опрос audit log вместо
    # on_member_update, см. connor/cogs/anti.py
    flags = bot._connection.member_cache_flags
    assert flags.voice is True
    assert flags.joined is False
    assert bot._connection._chunk_guilds is False


def test_safe_defaults(bot: ConnorBot) -> None:
    assert bot.command_prefix == "!"
    assert bot.allowed_mentions.everyone is False
    assert bot.allowed_mentions.roles is False
    assert bot.allowed_mentions.users is False
    assert bot.help_command is None


def test_run_bot_maps_login_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise discord.LoginFailure("bad token")

    monkeypatch.setattr(ConnorBot, "run", boom)
    assert run_bot(_FakeConfig()) == 1  # type: ignore[arg-type]


def test_run_bot_maps_privileged_intents(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise discord.PrivilegedIntentsRequired(None)

    monkeypatch.setattr(ConnorBot, "run", boom)
    assert run_bot(_FakeConfig()) == 1  # type: ignore[arg-type]


def test_run_bot_maps_unexpected_error(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("gateway exploded")

    monkeypatch.setattr(ConnorBot, "run", boom)
    assert run_bot(_FakeConfig()) == 1  # type: ignore[arg-type]


def test_run_bot_clean_exit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ConnorBot, "run", lambda *_a, **_k: None)
    assert run_bot(_FakeConfig()) == 0  # type: ignore[arg-type]


# --- meets_default_permissions ------------------------------------------------

_MOD = discord.Permissions(moderate_members=True)


def test_meets_default_permissions() -> None:
    assert meets_default_permissions(None, discord.Permissions.none()) is True
    assert meets_default_permissions(_MOD, discord.Permissions(moderate_members=True)) is True
    assert meets_default_permissions(_MOD, discord.Permissions.none()) is False
    assert meets_default_permissions(_MOD, discord.Permissions(administrator=True)) is True


# --- _command_perms_check (glue) -------------------------------------------------


class _FakeHTTP:
    def __init__(self, raw: list[dict]) -> None:
        self._raw = raw

    async def get_guild_application_command_permissions(self, *_a: object) -> list[dict]:
        return self._raw


def _ctx(
    bot: object,
    *,
    interaction: object | None = None,
    guild: object | None = object(),
    command_name: str | None = "mute",
    app_default: discord.Permissions | None = None,
    member_perms: discord.Permissions | None = None,
    author_roles: tuple[int, ...] = (),
    channel_id: int = 42,
) -> SimpleNamespace:
    mperms = member_perms if member_perms is not None else discord.Permissions.none()
    command = (
        SimpleNamespace(
            name=command_name, app_command=SimpleNamespace(default_permissions=app_default)
        )
        if command_name is not None
        else None
    )
    return SimpleNamespace(
        interaction=interaction,
        guild=guild,
        command=command,
        bot=bot,
        channel=SimpleNamespace(id=channel_id, permissions_for=lambda _m: mperms),
        author=SimpleNamespace(id=1, roles=[SimpleNamespace(id=r) for r in author_roles]),
    )


async def test_command_perms_check_skips_slash_and_dm(bot: ConnorBot) -> None:
    assert await _command_perms_check(_ctx(bot, interaction=object())) is True
    assert await _command_perms_check(_ctx(bot, guild=None)) is True


async def test_command_perms_check_fail_closed_when_cache_missing(bot: ConnorBot) -> None:
    bot.command_perms = None
    assert await _command_perms_check(_ctx(bot, command_name="mute")) is False


async def test_command_perms_check_skips_prefix_only(bot: ConnorBot) -> None:
    cache = CommandPermissionsCache(application_id=5000, guild_id=1000)
    await cache.load(_FakeHTTP([]), command_ids={"mute": 777})
    bot.command_perms = cache
    assert await _command_perms_check(_ctx(bot, command_name="purge")) is True  # нет в дереве


async def test_command_perms_check_consults_cache_for_known(bot: ConnorBot) -> None:
    cache = CommandPermissionsCache(application_id=5000, guild_id=1000)
    await cache.load(
        _FakeHTTP([{"id": "777", "permissions": [{"id": "10", "type": 1, "permission": True}]}]),
        command_ids={"mute": 777},
    )
    bot.command_perms = cache

    # роль 10 явно разрешена оверрайдом
    assert await _command_perms_check(_ctx(bot, command_name="mute", author_roles=(10,))) is True

    # роль не совпала → падаем на default_member_permissions; у автора их нет → отказ
    denied = _ctx(
        bot,
        command_name="mute",
        author_roles=(99,),
        app_default=_MOD,
        member_perms=discord.Permissions.none(),
    )
    assert await _command_perms_check(denied) is False

    # та же ситуация, но у автора есть moderate_members → проходит по default
    allowed = _ctx(
        bot,
        command_name="mute",
        author_roles=(99,),
        app_default=_MOD,
        member_perms=discord.Permissions(moderate_members=True),
    )
    assert await _command_perms_check(allowed) is True
