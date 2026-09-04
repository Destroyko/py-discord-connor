"""P2.D — mute: тексты/embed и порядок проверок в /mute."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from connor.cogs.mute import (
    _ERR_ALREADY_MUTED,
    _ERR_BAD_TIME,
    _ERR_HIERARCHY,
    Mute,
    _rules_link,
    build_mute_channel_embed,
    build_mute_dm_embed,
    build_pending_mute_embed,
)
from connor.core.texts import (
    ERR_NO_TARGET,
    ERR_TARGET_ABSENT,
    REASON_NOT_GIVEN,
    SELF_MODERATION,
)
from connor.db.repo_pending_mute import RepoPendingMute

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
        old_time="10ч",
    )
    assert upd.colour == discord.Color.yellow()
    assert upd.description == "<@5> перемьючен с 10ч на 48h"


# --- /mute branch ordering ----------------------------------------------------


def _config() -> SimpleNamespace:
    return SimpleNamespace(
        guild_id=1,
        roles={"MOLCHUN": 111},
        channels={"BOT_KOMANDY": 222},
        mute=SimpleNamespace(rules_url="", pending_mute_retention_days=30),
    )


def _member(
    mid: int, *, pos: int = 1, timed_out: bool = False, bot: bool = False
) -> SimpleNamespace:
    return SimpleNamespace(
        id=mid,
        bot=bot,
        mention=f"<@{mid}>",
        roles=[],
        top_role=SimpleNamespace(position=pos),
        name=f"user{mid}",  # username (в author-строку идёт он, не серверный ник)
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

    async def fetch_member(i: int) -> SimpleNamespace:
        member = members.get(i)
        if member is None:
            raise discord.NotFound(SimpleNamespace(status=404, reason="x"), "no")
        return member

    guild = SimpleNamespace(
        name="Коннор",
        owner_id=999,
        get_member=lambda i: members.get(i),
        get_role=lambda _i: role,
        fetch_member=fetch_member,
    )
    return SimpleNamespace(guild=guild, author=_member(1, pos=10), send=AsyncMock())


def _cog(db: object | None = None) -> Mute:
    return Mute(SimpleNamespace(config=_config(), db=db))  # type: ignore[arg-type]


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


# --- отложенный мут (цель вышла с сервера до наказания) ----------------------


def _pending_bot(db: object, *, bot_komandy: object | None = None, fetch_user_ok: bool = True):
    fetch_user = (
        AsyncMock(return_value=SimpleNamespace(id=0))
        if fetch_user_ok
        else AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "no"))
    )
    return SimpleNamespace(
        config=_config(),
        db=db,
        get_channel=lambda cid: bot_komandy if cid == 222 else None,
        fetch_user=fetch_user,
    )


def _pending_ctx(author_id: int = 1):
    async def fetch_member(_i: int) -> SimpleNamespace:
        raise discord.NotFound(SimpleNamespace(status=404, reason="x"), "no")

    guild = SimpleNamespace(
        name="Коннор",
        owner_id=999,
        get_member=lambda _i: None,
        get_role=lambda _i: None,
        fetch_member=fetch_member,
    )
    return SimpleNamespace(guild=guild, author=_member(author_id, pos=10), send=AsyncMock())


def test_pending_embed_is_blue_with_date() -> None:
    e = build_pending_mute_embed(until_ts=1_760_000_000)
    assert e.colour == discord.Color.blue()
    assert "вернётся до" in e.description


async def test_mute_absent_target_queues_pending(db) -> None:
    ctx = _pending_ctx(author_id=7)
    cog = Mute(_pending_bot(db))  # type: ignore[arg-type]

    await Mute.mute.callback(cog, ctx, "777", "24h", reason="п12")

    entry = await RepoPendingMute(db).get(777)
    assert entry is not None
    assert (entry.duration, entry.reason, entry.moderator_id) == ("24h", "п12", 7)
    embed = ctx.send.await_args.kwargs["embed"]
    assert embed.colour == discord.Color.blue()


async def test_mute_absent_target_bad_time_not_queued(db) -> None:
    ctx = _pending_ctx()
    cog = Mute(_pending_bot(db))  # type: ignore[arg-type]

    await Mute.mute.callback(cog, ctx, "777", "1h30m")

    assert await RepoPendingMute(db).get(777) is None
    ctx.send.assert_awaited_once_with(_ERR_BAD_TIME)


async def test_mute_absent_garbage_id_not_queued(db) -> None:
    ctx = _pending_ctx()
    cog = Mute(_pending_bot(db, fetch_user_ok=False))  # type: ignore[arg-type]

    await Mute.mute.callback(cog, ctx, "424242", "24h")

    assert await RepoPendingMute(db).get(424242) is None
    ctx.send.assert_awaited_once_with(ERR_TARGET_ABSENT)


async def test_pending_applied_on_join_indistinguishable_from_normal_mute(db) -> None:
    await RepoPendingMute(db).upsert(5, duration="24h", reason="п12", moderator_id=1, queued_at=100)
    bot_komandy = SimpleNamespace(send=AsyncMock())
    mod = _member(1)
    mod.display_name = "mod1"
    guild = SimpleNamespace(
        name="Коннор",
        get_member=lambda i: mod if i == 1 else None,
        get_role=lambda _i: SimpleNamespace(id=111),
    )
    member = _member(5, pos=1)
    member.guild = guild
    cog = Mute(_pending_bot(db, bot_komandy=bot_komandy))  # type: ignore[arg-type]

    await Mute.on_member_join(cog, member)

    member.timeout.assert_awaited_once()
    member.add_roles.assert_awaited_once()
    member.send.assert_awaited_once()  # DM как при обычном муте
    ch_embed = bot_komandy.send.await_args.kwargs["embed"]
    assert ch_embed.description == "<@5> замьючен на 24h"  # ни намёка на отложенность
    assert ch_embed.fields[0].value == "п12"
    assert await RepoPendingMute(db).get(5) is None  # запись снята
    assert cog.state.last_time(5) == "24h"


async def test_pending_apply_resolves_moderator_via_fetch_member(db) -> None:
    # модератор ещё на сервере, но не в кэше → берём через fetch_member; в author
    # идёт username, не серверный ник
    await RepoPendingMute(db).upsert(5, duration="1h", reason="п", moderator_id=1, queued_at=100)
    bot_komandy = SimpleNamespace(send=AsyncMock())
    mod = _member(1)
    mod.name = "mod_username"
    mod.display_name = "СерверныйНик"
    mod.display_avatar = SimpleNamespace(url="http://global-avatar")
    guild = SimpleNamespace(
        name="Коннор",
        get_member=lambda _i: None,
        get_role=lambda _i: SimpleNamespace(id=111),
        fetch_member=AsyncMock(return_value=mod),
    )
    member = _member(5)
    member.guild = guild
    cog = Mute(_pending_bot(db, bot_komandy=bot_komandy))  # type: ignore[arg-type]

    await Mute.on_member_join(cog, member)

    e = bot_komandy.send.await_args.kwargs["embed"]
    assert e.author.name == "mod_username"  # username, не "СерверныйНик"
    assert e.author.icon_url == "http://global-avatar"


async def test_pending_apply_moderator_gone_falls_back_to_raw_id(db) -> None:
    # модератор ушёл с сервера и не резолвится глобально → голый id, без иконки
    await RepoPendingMute(db).upsert(5, duration="1h", reason="п", moderator_id=42, queued_at=100)
    bot_komandy = SimpleNamespace(send=AsyncMock())
    guild = SimpleNamespace(
        name="Коннор",
        get_member=lambda _i: None,
        get_role=lambda _i: SimpleNamespace(id=111),
        fetch_member=AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "gone")),
    )
    member = _member(5)
    member.guild = guild
    cog = Mute(_pending_bot(db, bot_komandy=bot_komandy, fetch_user_ok=False))  # type: ignore[arg-type]

    await Mute.on_member_join(cog, member)

    e = bot_komandy.send.await_args.kwargs["embed"]
    assert e.author.name == "42"
    assert e.author.icon_url is None


async def test_pending_join_timeout_failure_keeps_record(db) -> None:
    await RepoPendingMute(db).upsert(5, duration="24h", reason="п", moderator_id=1, queued_at=100)
    guild = SimpleNamespace(name="X", get_member=lambda _i: None, get_role=lambda _i: None)
    member = _member(5)
    member.guild = guild
    member.timeout = AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "boom"))
    cog = Mute(_pending_bot(db))  # type: ignore[arg-type]

    await Mute.on_member_join(cog, member)

    assert await RepoPendingMute(db).get(5) is not None  # не удалили — попробуем позже


async def test_unmute_absent_cancels_pending(db) -> None:
    await RepoPendingMute(db).upsert(5, duration="1h", reason="п", moderator_id=1, queued_at=100)
    ctx = _pending_ctx()
    cog = Mute(_pending_bot(db))  # type: ignore[arg-type]

    await Mute.unmute.callback(cog, ctx, "5")

    assert await RepoPendingMute(db).get(5) is None
    msg = ctx.send.await_args.args[0]
    assert "отмен" in msg.lower() and "<@5>" in msg


async def test_unmute_absent_no_pending_is_absent_error(db) -> None:
    ctx = _pending_ctx()
    cog = Mute(_pending_bot(db))  # type: ignore[arg-type]

    await Mute.unmute.callback(cog, ctx, "5")

    ctx.send.assert_awaited_once_with(ERR_TARGET_ABSENT)


async def test_sweep_pending_purges_only_expired(db) -> None:
    repo = RepoPendingMute(db)
    now = int(discord.utils.utcnow().timestamp())
    await repo.upsert(1, duration="1h", reason="a", moderator_id=9, queued_at=now - 40 * 86400)
    await repo.upsert(2, duration="1h", reason="b", moderator_id=9, queued_at=now - 5 * 86400)
    cog = Mute(_pending_bot(db))  # type: ignore[arg-type]

    await Mute._sweep_pending.coro(cog)

    assert await repo.get(1) is None  # старше retention (30 дн)
    assert await repo.get(2) is not None  # свежая — осталась


async def test_pending_applied_on_startup_if_member_returned_during_downtime(db) -> None:
    await RepoPendingMute(db).upsert(5, duration="1h", reason="п", moderator_id=1, queued_at=100)
    bot_komandy = SimpleNamespace(send=AsyncMock())
    member = _member(5)
    guild = SimpleNamespace(
        name="Коннор",
        get_member=lambda i: member if i == 5 else None,
        get_role=lambda _i: SimpleNamespace(id=111),
        fetch_member=AsyncMock(return_value=member),
    )
    member.guild = guild
    bot = _pending_bot(db, bot_komandy=bot_komandy)
    bot.get_guild = lambda _i: guild
    cog = Mute(bot)  # type: ignore[arg-type]

    await Mute.on_ready(cog)

    member.timeout.assert_awaited_once()
    assert await RepoPendingMute(db).get(5) is None
    assert cog._pending_startup_done is True
