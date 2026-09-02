"""P2.C — banKick: тексты, embed, порядок проверок в /ban."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from connor.cogs.ban_kick import BanKick, build_mod_embed, hierarchy_reject
from connor.core.texts import ERR_NO_TARGET, ERR_TARGET_ABSENT, REASON_NOT_GIVEN, SELF_MODERATION

_NOT_FOUND = discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "not found")


def test_hierarchy_reject_texts() -> None:
    assert (
        hierarchy_reject("банить")
        == "Вы не можете банить старших или эквивалентных по роли или ботов"
    )
    assert (
        hierarchy_reject("кикать")
        == "Вы не можете кикать старших или эквивалентных по роли или ботов"
    )


def test_build_mod_embed() -> None:
    embed = build_mod_embed(
        author_name="enteii",
        author_icon="http://a",
        description="@x забанен. Помянем.",
        reason="п11",
    )
    assert embed.colour == discord.Color.green()
    assert embed.author.name == "enteii"
    assert embed.description == "@x забанен. Помянем."
    assert embed.fields[0].name == "Причина"
    assert embed.fields[0].value == "п11"


# --- /ban branch ordering --------------------------------------------------------


def _member(mid: int, *, pos: int = 1, bot: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        id=mid,
        bot=bot,
        mention=f"<@{mid}>",
        top_role=SimpleNamespace(position=pos),
        display_name=f"u{mid}",
        display_avatar=SimpleNamespace(url="http://a"),
    )


def _ctx(*, members: dict[int, SimpleNamespace] | None = None, already_banned: bool = False):
    members = members or {}
    guild = SimpleNamespace(
        owner_id=999,
        get_member=lambda i: members.get(i),
        fetch_ban=AsyncMock(return_value=object())
        if already_banned
        else AsyncMock(side_effect=_NOT_FOUND),
        ban=AsyncMock(),
    )
    return SimpleNamespace(guild=guild, author=_member(1, pos=10), send=AsyncMock())


async def _ban(ctx: SimpleNamespace, target: str, reason: str | None = None) -> None:
    await BanKick.ban.callback(BanKick(SimpleNamespace()), ctx, target, reason=reason)  # type: ignore[arg-type]


async def test_ban_no_target() -> None:
    ctx = _ctx()
    await _ban(ctx, "garbage")
    ctx.send.assert_awaited_once_with(ERR_NO_TARGET)


async def test_ban_target_not_on_server() -> None:
    ctx = _ctx()
    await _ban(ctx, "123456789012345678")
    ctx.send.assert_awaited_once_with(ERR_TARGET_ABSENT)


async def test_ban_self() -> None:
    ctx = _ctx(members={1: _member(1, pos=10)})
    await _ban(ctx, "1")
    ctx.send.assert_awaited_once_with(SELF_MODERATION)


async def test_ban_hierarchy_block() -> None:
    ctx = _ctx(members={2: _member(2, pos=10)})  # равная позиция
    await _ban(ctx, "2")
    ctx.send.assert_awaited_once_with(hierarchy_reject("банить"))


async def test_ban_already_banned() -> None:
    ctx = _ctx(members={2: _member(2, pos=1)}, already_banned=True)
    await _ban(ctx, "2")
    ctx.send.assert_awaited_once_with("Пользователь уже в бане")


async def test_ban_success_sends_embed_and_calls_ban() -> None:
    ctx = _ctx(members={2: _member(2, pos=1)})
    await _ban(ctx, "2", reason="п11")
    ctx.guild.ban.assert_awaited_once()
    (kwargs,) = [c.kwargs for c in ctx.send.await_args_list]
    assert isinstance(kwargs["embed"], discord.Embed)
    assert kwargs["embed"].fields[0].value == "п11"


async def test_ban_success_default_reason() -> None:
    ctx = _ctx(members={2: _member(2, pos=1)})
    await _ban(ctx, "2")
    embed = ctx.send.await_args.kwargs["embed"]
    assert embed.fields[0].value == REASON_NOT_GIVEN
