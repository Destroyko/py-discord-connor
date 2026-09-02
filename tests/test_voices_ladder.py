"""P4.6 — /ladder: пустой список (текст), формирование строк, усечение до 10,
сырой id при нерезолве."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from connor.cogs.voices_ladder import _EMPTY, _TITLE, VoicesLadder
from connor.db import Database
from connor.db.repo_voice_xp import RepoVoiceXp


def _bot(db: Database, *, fetch_user: AsyncMock | None = None) -> SimpleNamespace:
    return SimpleNamespace(db=db, fetch_user=fetch_user or AsyncMock())


def _ctx(cached_ids: set[int]) -> SimpleNamespace:
    guild = SimpleNamespace(get_member=lambda uid: object() if uid in cached_ids else None)
    return SimpleNamespace(guild=guild, send=AsyncMock())


async def _ladder(cog: VoicesLadder, ctx: object) -> None:
    await VoicesLadder.ladder.callback(cog, ctx)


async def test_ladder_empty_is_plain_text(db: Database) -> None:
    ctx = _ctx(set())
    await _ladder(VoicesLadder(_bot(db)), ctx)

    ctx.send.assert_awaited_once_with(_EMPTY)
    assert "embed" not in ctx.send.await_args.kwargs


async def test_ladder_lists_cached_members(db: Database) -> None:
    await RepoVoiceXp(db).add_points({1: 50, 2: 30, 3: 10})
    ctx = _ctx({1, 2, 3})

    await _ladder(VoicesLadder(_bot(db)), ctx)

    embed = ctx.send.await_args.kwargs["embed"]
    assert embed.title == _TITLE
    assert embed.description.splitlines() == ["1: <@1>", "2: <@2>", "3: <@3>"]
    assert embed.footer.text  # строка-комментарий присутствует
    assert ctx.send.await_args.kwargs["allowed_mentions"].users is False


async def test_ladder_raw_id_when_account_unresolvable(db: Database) -> None:
    await RepoVoiceXp(db).add_points({999: 40})
    fetch_user = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "gone"))
    ctx = _ctx(set())  # не в кэше

    await _ladder(VoicesLadder(_bot(db, fetch_user=fetch_user)), ctx)

    assert ctx.send.await_args.kwargs["embed"].description == "1: 999"


async def test_ladder_caps_at_ten(db: Database) -> None:
    await RepoVoiceXp(db).add_points({i: 100 - i for i in range(1, 13)})
    ctx = _ctx(set(range(1, 13)))

    await _ladder(VoicesLadder(_bot(db)), ctx)

    lines = ctx.send.await_args.kwargs["embed"].description.splitlines()
    assert len(lines) == 10
    assert lines[0] == "1: <@1>" and lines[-1] == "10: <@10>"
