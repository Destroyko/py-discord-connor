"""/healthcheck: embed-отчёт и живая проверка каналов."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from connor.bot import ConnorBot
from connor.cogs.healthcheck import build_report_embed
from connor.core.preflight import (
    CheckResult,
    check_audit_log_readable,
    check_channel,
    check_channel_unreachable,
)

_NEEDED = (("view_channel", "View"), ("send_messages", "Send Messages"))


def test_report_all_ok_is_green() -> None:
    results = [
        CheckResult("БД", "подключение", ok=True),
        check_channel(channel_id=1, label="#баны", exists=True, missing_perms=[]),
    ]
    embed = build_report_embed(results, uptime="Аптайм: 1ч")
    assert embed.colour == discord.Colour.green()
    assert "Всё в порядке" in embed.description
    assert embed.footer.text == "Аптайм: 1ч"
    assert all("❌" not in f.value for f in embed.fields)


def test_report_problems_is_red_and_lists_missing_perms() -> None:
    results = [
        CheckResult("БД", "подключение", ok=True),
        check_channel(
            channel_id=1,
            label="#баны",
            exists=True,
            missing_perms=["Send Messages", "Embed Links"],
        ),
        check_channel(channel_id=2, label="#аудит", exists=True, missing_perms=[]),
    ]
    embed = build_report_embed(results, uptime="Аптайм: 1ч")
    assert embed.colour == discord.Colour.red()
    assert "Найдено проблем: 1" in embed.description
    channels = next(f for f in embed.fields if f.name == "Каналы и категории")
    assert "❌ **#баны** — не хватает прав: Send Messages, Embed Links" in channels.value
    assert "✅ #аудит" in channels.value


def test_report_audit_log_failure_is_listed() -> None:
    embed = build_report_embed(
        [check_audit_log_readable(readable=False, error="Discord API 403")], uptime="x"
    )
    assert embed.colour == discord.Colour.red()
    assert "журнал аудита" in embed.fields[0].value


# --- живая проверка канала --------------------------------------------------------


def _http_error(cls: type[discord.HTTPException], status: int) -> discord.HTTPException:
    return cls(MagicMock(status=status, reason="x"), "boom")


async def _live(guild: object) -> CheckResult:
    return await ConnorBot._check_channel(  # type: ignore[arg-type]
        SimpleNamespace(), guild, 1, "#чек-лист", _NEEDED, live=True
    )


def _guild(*, fetch: AsyncMock) -> SimpleNamespace:
    return SimpleNamespace(
        me=SimpleNamespace(), get_channel=lambda cid: object(), fetch_channel=fetch
    )


async def test_live_forbidden_means_bot_cannot_see_channel() -> None:
    result = await _live(_guild(fetch=AsyncMock(side_effect=_http_error(discord.Forbidden, 403))))
    assert result.ok is False
    assert "не видит канал" in result.detail


async def test_live_not_found() -> None:
    result = await _live(_guild(fetch=AsyncMock(side_effect=_http_error(discord.NotFound, 404))))
    assert result.ok is False
    assert "не найден" in result.detail


async def test_live_uses_fresh_channel_permissions() -> None:
    fresh = SimpleNamespace(
        permissions_for=lambda me: SimpleNamespace(view_channel=True, send_messages=False)
    )
    result = await _live(_guild(fetch=AsyncMock(return_value=fresh)))
    assert result.ok is False
    assert result.detail == "не хватает прав: Send Messages"


def test_channel_unreachable_result_shape() -> None:
    r = check_channel_unreachable(channel_id=5, label="#x", reason="нет доступа")
    assert r.ok is False and r.section == "каналы" and "5" in r.detail
