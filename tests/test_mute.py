"""P2.D — mute: тексты/embed и порядок проверок в /mute."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from connor.cogs.mute import (
    _ERR_ALREADY_MUTED,
    _ERR_BAD_TIME,
    _ERR_HIERARCHY,
    Mute,
    _rules_link,
    build_mute_channel_embed,
    build_mute_dm_embed,
)
from connor.core.texts import ERR_NO_TARGET, REASON_NOT_GIVEN, SELF_MODERATION

# --- pure builders -------------------------------------------------------------


def test_rules_link() -> None:
    assert _rules_link("http://x/rules") == "[Правила сервера](http://x/rules)"
    assert _rules_link("") == "Правила сервера"


def test_dm_embed_first_mute() -> None:
    e = build_mute_dm_embed(
        server_name="Коннор", time_str="24h", reason="п11", rules_url="http://r", updated=False
    )
    assert e.colour == discord.Color.green()
    assert 'Вы получили мут на сервере "Коннор" продолжительностью 24h' in e.description
    assert "**Причина**\nп11" in e.description
    assert "[Правила сервера](http://r)" in e.description
    assert "Для обжалования" in e.description


def test_dm_embed_update_is_yellow() -> None:
    e = build_mute_dm_embed(
        server_name="Коннор", time_str="1h", reason="x", rules_url="", updated=True
    )
    assert e.colour == discord.Color.yellow()
    assert "Вам обновили время мута" in e.description


def test_channel_embed_first_and_update() -> None:
    first = build_mute_channel_embed(
        mod_name="mod", mod_icon=None, mention="<@5>", time_str="24h", reason="п11", updated=False
    )
    assert first.colour == discord.Color.green()
    assert first.description == "<@5> замьючен на 24h"
    assert first.fields[0].name == "Причина" and first.fields[0].value == "п11"

    upd = build_mute_channel_embed(
        mod_name="mod",
        mod_icon=None,
        mention="<@5>",
        time_str="48h",
        reason="ещё",
        updated=True,
        old_time="0д 1ч 0м",
    )
    assert upd.colour == discord.Color.yellow()
    assert upd.description == "<@5> перемьючен с 0д 1ч 0м на 48h"


# --- /mute branch ordering ----------------------------------------------------


def _config() -> SimpleNamespace:
    return SimpleNamespace(roles={"MOLCHUN": 111}, mute=SimpleNamespace(rules_url=""))


def _member(
    mid: int, *, pos: int = 1, timed_out: bool = False, bot: bool = False
) -> SimpleNamespace:
    return SimpleNamespace(
        id=mid,
        bot=bot,
        mention=f"<@{mid}>",
        roles=[],
        top_role=SimpleNamespace(position=pos),
        display_name=f"u{mid}",
        display_avatar=SimpleNamespace(url="http://a"),
        timed_out_until=None,
        is_timed_out=lambda: timed_out,
        timeout=AsyncMock(),
        add_roles=AsyncMock(),
        remove_roles=AsyncMock(),
        send=AsyncMock(),
    )


def _ctx(*, members: dict[int, SimpleNamespace]):
    role = SimpleNamespace(id=111)
    guild = SimpleNamespace(
        name="Коннор",
        owner_id=999,
        get_member=lambda i: members.get(i),
        get_role=lambda _i: role,
    )
    return SimpleNamespace(guild=guild, author=_member(1, pos=10), send=AsyncMock())


def _cog() -> Mute:
    return Mute(SimpleNamespace(config=_config()))  # type: ignore[arg-type]


async def _mute(
    ctx: SimpleNamespace,
    target: str,
    time: str,
    reason: str | None = None,
    *,
    cog: Mute | None = None,
) -> Mute:
    cog = cog or _cog()
    await Mute.mute.callback(cog, ctx, target, time, reason=reason)
    return cog


async def test_mute_no_target() -> None:
    ctx = _ctx(members={})
    await _mute(ctx, "junk", "1h")
    ctx.send.assert_awaited_once_with(ERR_NO_TARGET)


async def test_mute_bad_time() -> None:
    ctx = _ctx(members={2: _member(2)})
    await _mute(ctx, "2", "1h30m")
    ctx.send.assert_awaited_once_with(_ERR_BAD_TIME)


async def test_mute_self() -> None:
    ctx = _ctx(members={1: _member(1, pos=10)})
    await _mute(ctx, "1", "1h")
    ctx.send.assert_awaited_once_with(SELF_MODERATION)


async def test_mute_hierarchy() -> None:
    ctx = _ctx(members={2: _member(2, pos=10)})
    await _mute(ctx, "2", "1h")
    ctx.send.assert_awaited_once_with(_ERR_HIERARCHY)


async def test_mute_first_time_applies_timeout_role_dm_embed() -> None:
    member = _member(2, pos=1)
    ctx = _ctx(members={2: member})
    cog = await _mute(ctx, "2", "24h", "п11")

    member.timeout.assert_awaited_once()
    member.add_roles.assert_awaited_once()
    member.send.assert_awaited_once()
    embed = ctx.send.await_args.kwargs["embed"]
    assert embed.description == "<@2> замьючен на 24h"
    assert embed.fields[0].value == "п11"
    assert cog.state.last_time(2) == "24h"


async def test_mute_default_reason() -> None:
    member = _member(2, pos=1)
    ctx = _ctx(members={2: member})
    await _mute(ctx, "2", "24h")
    assert ctx.send.await_args.kwargs["embed"].fields[0].value == REASON_NOT_GIVEN


async def test_mute_update_blocked_by_reservation() -> None:
    member = _member(2, pos=1, timed_out=True)
    ctx = _ctx(members={2: member})
    cog = _cog()
    # чужая резервация с точкой отсчёта в далёком «будущем» (1e9 c >> monotonic()):
    # окно ещё не истекло и вызывающий — не владелец → обновление запрещено
    cog.state.begin(2, owner_id=555, now=1e9, time_str="1h")

    await _mute(ctx, "2", "48h", cog=cog)
    ctx.send.assert_awaited_once_with(_ERR_ALREADY_MUTED)
    member.timeout.assert_not_awaited()
