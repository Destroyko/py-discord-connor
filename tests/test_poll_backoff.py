"""PollBackoff: откат опросов audit log при сбоях (защита от спама невалидными запросами)."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import discord

from connor.cogs.ban_kick import BanKick
from connor.core.poll_backoff import BASE_DELAY_SECONDS, MAX_DELAY_SECONDS, PollBackoff

_log = logging.getLogger("test")


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_no_skip_before_any_failure() -> None:
    assert PollBackoff("x", _log, clock=_Clock()).should_skip() is False


def test_failure_pauses_then_resumes() -> None:
    clock = _Clock()
    b = PollBackoff("x", _log, clock=clock)
    b.failure(RuntimeError("boom"))
    assert b.should_skip() is True
    clock.now += BASE_DELAY_SECONDS - 1
    assert b.should_skip() is True
    clock.now += 1
    assert b.should_skip() is False


def test_delay_doubles_and_is_capped() -> None:
    clock = _Clock()
    b = PollBackoff("x", _log, clock=clock)
    for _ in range(3):
        b.failure(RuntimeError("boom"))
    clock.now += BASE_DELAY_SECONDS * 4 - 1  # третий сбой → 30 * 4
    assert b.should_skip() is True
    for _ in range(20):
        b.failure(RuntimeError("boom"))
    clock.now += MAX_DELAY_SECONDS
    assert b.should_skip() is False  # потолок: не дольше MAX_DELAY_SECONDS


def test_success_resets() -> None:
    clock = _Clock()
    b = PollBackoff("x", _log, clock=clock)
    b.failure(RuntimeError("boom"))
    b.failure(RuntimeError("boom"))
    b.success()
    assert b.failures == 0
    assert b.should_skip() is False


def test_logs_error_once_then_warnings(caplog) -> None:
    b = PollBackoff("x", _log, clock=_Clock())
    with caplog.at_level(logging.INFO, logger="test"):
        for _ in range(4):
            b.failure(RuntimeError("boom"))
    levels = [r.levelno for r in caplog.records]
    assert levels == [logging.ERROR, logging.WARNING, logging.WARNING, logging.WARNING]


async def test_ban_poll_loop_stops_hammering_api_on_forbidden(db) -> None:
    """Потеряно право View Audit Log: после первого 403 запросы к API прекращаются."""
    forbidden = discord.Forbidden(MagicMock(status=403), "Missing Permissions")
    calls = {"n": 0}

    def audit_logs(**kw):
        calls["n"] += 1
        raise forbidden

    guild = SimpleNamespace(audit_logs=audit_logs)
    bot = SimpleNamespace(
        db=db,
        user=SimpleNamespace(id=999),
        config=SimpleNamespace(guild_id=1, channels={"BANY": 444, "BOT_KOMANDY": 555}),
        get_guild=lambda gid: guild,
    )
    cog = BanKick(bot)  # type: ignore[arg-type]
    cog._poll_backoff = PollBackoff("вотчер банов/киков", _log, clock=_Clock())

    for _ in range(50):  # 50 тиков подряд (≈2.5 минуты при интервале 3 с)
        await BanKick._poll_manual_changes.coro(cog)

    assert calls["n"] == 1
    assert cog._poll_backoff.failures == 1
