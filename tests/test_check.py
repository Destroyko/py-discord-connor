"""P3.3 — check: ответ /check, реконсиляция, ленивый deny в предложке."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from connor.cogs.check import Check
from connor.db import Database
from connor.db.repo_anti import RepoAnti
from connor.db.repo_predlozhka import RepoPredlozhka

_PREDLOZHKA_ID = 222


def _cog(db: Database) -> Check:
    config = SimpleNamespace(channels={"PREDLOZHKA": _PREDLOZHKA_ID})
    return Check(SimpleNamespace(db=db, config=config))  # type: ignore[arg-type]


def _member(member_id: int, *, bot: bool = False) -> MagicMock:
    member = MagicMock(spec=discord.Member)
    member.id = member_id
    member.bot = bot
    return member


def _predlozhka(*, can_write: bool) -> SimpleNamespace:
    return SimpleNamespace(
        id=_PREDLOZHKA_ID,
        permissions_for=lambda _m: SimpleNamespace(send_messages=can_write),
        overwrites_for=lambda _m: discord.PermissionOverwrite(),
        set_permissions=AsyncMock(),
    )


def _check_ctx(member_id: int, predlozhka: object):
    guild = SimpleNamespace(get_channel=lambda _i: predlozhka)
    return SimpleNamespace(guild=guild, author=_member(member_id), reply=AsyncMock())


async def _run_check(cog: Check, ctx: object) -> None:
    await Check.check.callback(cog, ctx)


async def test_check_open_when_access_and_not_anti(db: Database) -> None:
    ctx = _check_ctx(10, _predlozhka(can_write=True))
    await _run_check(_cog(db), ctx)
    ctx.reply.assert_awaited_once_with("Доступ открыт")


async def test_check_denied_without_access(db: Database) -> None:
    ctx = _check_ctx(10, _predlozhka(can_write=False))
    await _run_check(_cog(db), ctx)
    ctx.reply.assert_awaited_once_with("Недостаточно прав")


async def test_check_denied_when_anti_even_with_access(db: Database) -> None:
    await RepoAnti(db).add(10, added_at=1, added_by=1)
    ctx = _check_ctx(10, _predlozhka(can_write=True))
    await _run_check(_cog(db), ctx)
    ctx.reply.assert_awaited_once_with("Недостаточно прав")


async def test_check_reconciles_stale_overwrite(db: Database) -> None:
    await RepoPredlozhka(db).add(10, reason="старое", set_at=1)  # deny висит, анти-статуса нет
    predlozhka = _predlozhka(can_write=True)
    ctx = _check_ctx(10, predlozhka)

    await _run_check(_cog(db), ctx)

    predlozhka.set_permissions.assert_awaited_once()  # clear_deny сработал
    assert await RepoPredlozhka(db).contains(10) is False
    ctx.reply.assert_awaited_once_with("Доступ открыт")


async def test_check_no_predlozhka_channel_denies(db: Database) -> None:
    ctx = _check_ctx(10, None)
    await _run_check(_cog(db), ctx)
    ctx.reply.assert_awaited_once_with("Недостаточно прав")


# --- ленивый deny -------------------------------------------------------------


def _msg(*, author_id: int, channel_id: int, bot: bool = False) -> SimpleNamespace:
    channel = SimpleNamespace(
        id=channel_id,
        overwrites_for=lambda _m: discord.PermissionOverwrite(),
        set_permissions=AsyncMock(),
    )
    return SimpleNamespace(
        author=_member(author_id, bot=bot),
        channel=channel,
        webhook_id=None,
        guild=object(),
        delete=AsyncMock(),
    )


async def test_lazy_deny_for_anti_worker_in_predlozhka(db: Database) -> None:
    await RepoAnti(db).add(10, added_at=1, added_by=1)
    msg = _msg(author_id=10, channel_id=_PREDLOZHKA_ID)

    await Check.on_message(_cog(db), msg)

    msg.delete.assert_awaited_once()
    msg.channel.set_permissions.assert_awaited_once()
    assert await RepoPredlozhka(db).contains(10) is True


async def test_lazy_deny_ignores_non_anti(db: Database) -> None:
    msg = _msg(author_id=10, channel_id=_PREDLOZHKA_ID)
    await Check.on_message(_cog(db), msg)
    msg.delete.assert_not_awaited()


async def test_lazy_deny_ignores_other_channels(db: Database) -> None:
    await RepoAnti(db).add(10, added_at=1, added_by=1)
    msg = _msg(author_id=10, channel_id=999)
    await Check.on_message(_cog(db), msg)
    msg.delete.assert_not_awaited()
