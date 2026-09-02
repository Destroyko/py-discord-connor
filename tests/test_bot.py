"""P0.5 — bootstrap: intents/кэш/пинги и маппинг ошибок запуска на код выхода."""

from __future__ import annotations

import discord
import pytest

from connor.bot import ConnorBot, run_bot


class _FakeConfig:
    guild_id = 123456789012345678
    bot_token = "fake-token"


@pytest.fixture
def bot() -> ConnorBot:
    return ConnorBot(_FakeConfig())  # type: ignore[arg-type]


def test_intents(bot: ConnorBot) -> None:
    assert bot.intents.members is True
    assert bot.intents.message_content is True
    assert bot.intents.voice_states is True
    assert bot.intents.presences is False


def test_partial_member_cache(bot: ConnorBot) -> None:
    flags = bot._connection.member_cache_flags
    assert flags.voice is True
    assert flags.joined is False


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
