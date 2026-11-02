"""banKick: тексты, embed, порядок проверок в /ban."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from connor.cogs.ban_kick import BanKick, build_mod_embed, hierarchy_reject
from connor.core.texts import ERR_NO_TARGET, REASON_NOT_GIVEN, SELF_MODERATION
from connor.db.repo_ban_watcher import RepoBanWatcher

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
        name=f"user{mid}",  # username → идёт в author-строку embed'а
        display_name=f"u{mid}",
        display_avatar=SimpleNamespace(url="http://a"),
    )


def _ctx(*, members: dict[int, SimpleNamespace] | None = None, already_banned: bool = False):
    members = members or {}

    async def fetch_member(i: int) -> SimpleNamespace:
        member = members.get(i)
        if member is None:
            raise _NOT_FOUND
        return member

    guild = SimpleNamespace(
        owner_id=999,
        get_member=lambda i: members.get(i),
        fetch_member=fetch_member,
        fetch_ban=AsyncMock(return_value=object())
        if already_banned
        else AsyncMock(side_effect=_NOT_FOUND),
        ban=AsyncMock(),
    )
    return SimpleNamespace(guild=guild, author=_member(1, pos=10), send=AsyncMock())


async def _ban(
    ctx: SimpleNamespace, target: str, reason: str | None = None, *, account_exists: bool = True
) -> None:
    fetch_user = AsyncMock() if account_exists else AsyncMock(side_effect=_NOT_FOUND)
    cog = BanKick(SimpleNamespace(fetch_user=fetch_user, db=None))  # type: ignore[arg-type]
    await BanKick.ban.callback(cog, ctx, target, reason=reason)


async def test_ban_no_target() -> None:
    ctx = _ctx()
    await _ban(ctx, "garbage")
    ctx.send.assert_awaited_once_with(ERR_NO_TARGET)


async def test_ban_absent_account_exists_still_bans() -> None:
    ctx = _ctx()  # get_member -> None
    await _ban(ctx, "123456789012345678", reason="каскад", account_exists=True)
    ctx.guild.ban.assert_awaited_once()
    assert isinstance(ctx.send.await_args.kwargs["embed"], discord.Embed)


async def test_ban_id_is_not_a_real_account() -> None:
    ctx = _ctx()
    await _ban(ctx, "123456789012345678", account_exists=False)
    ctx.send.assert_awaited_once_with(ERR_NO_TARGET)
    ctx.guild.ban.assert_not_awaited()


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
    assert ctx.send.await_args.kwargs["embed"].fields[0].value == "п11"


async def test_ban_success_default_reason() -> None:
    ctx = _ctx(members={2: _member(2, pos=1)})
    await _ban(ctx, "2")
    assert ctx.send.await_args.kwargs["embed"].fields[0].value == REASON_NOT_GIVEN


# --- вотчер ручных банов/разбанов (опрос audit log) -------------------------------

_BOT_ID = 999


async def _audit_iter(entries: list[object]):
    for entry in entries:
        yield entry


def _entry(
    *, entry_id: int, target_id: int, actor_id: int | None, reason: str | None = None
) -> SimpleNamespace:
    user = (
        None
        if actor_id is None
        else SimpleNamespace(
            id=actor_id, name=f"mod{actor_id}", display_avatar=SimpleNamespace(url="u")
        )
    )
    return SimpleNamespace(
        id=entry_id,
        user_id=actor_id,
        user=user,
        target=SimpleNamespace(id=target_id),
        reason=reason,
    )


def _watch_guild(
    *,
    bans: list[object] = (),
    unbans: list[object] = (),
    kicks: list[object] = (),
    latest: list[object] = (),
) -> SimpleNamespace:
    def audit_logs(**kw):
        action = kw.get("action")
        if action is None:
            return _audit_iter(list(latest))
        if action is discord.AuditLogAction.ban:
            return _audit_iter(list(bans))
        if action is discord.AuditLogAction.kick:
            return _audit_iter(list(kicks))
        return _audit_iter(list(unbans))

    return SimpleNamespace(audit_logs=audit_logs)


def _watch_cog(db, channel: object | None = None, bot_komandy: object | None = None) -> BanKick:
    bot = SimpleNamespace(
        db=db,
        user=SimpleNamespace(id=_BOT_ID),
        config=SimpleNamespace(guild_id=1, channels={"BANY": 444, "BOT_KOMANDY": 555}),
        get_channel=lambda cid: {444: channel, 555: bot_komandy}.get(cid),
    )
    return BanKick(bot)  # type: ignore[arg-type]


async def test_ban_poll_first_run_seeds_both_cursors(db) -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _watch_cog(db, channel)
    g = _watch_guild(latest=[_entry(entry_id=42, target_id=5, actor_id=7)])

    await cog._poll_manual_once(g)  # type: ignore[arg-type]

    channel.send.assert_not_awaited()
    repo = RepoBanWatcher(db)
    assert await repo.get_cursor("ban") == 42
    assert await repo.get_cursor("unban") == 42
    assert await repo.get_cursor("kick") == 42


async def test_ban_poll_first_run_no_history_leaves_cursor_unset(db) -> None:
    cog = _watch_cog(db)
    await cog._poll_manual_once(_watch_guild())  # type: ignore[arg-type]
    assert await RepoBanWatcher(db).get_cursor("ban") is None


async def test_manual_ban_via_ui_posts_embed(db) -> None:
    repo = RepoBanWatcher(db)
    await repo.set_cursor("ban", 1)
    await repo.set_cursor("unban", 1)
    await repo.set_cursor("kick", 1)
    channel = SimpleNamespace(send=AsyncMock())
    cog = _watch_cog(db, channel)
    g = _watch_guild(bans=[_entry(entry_id=2, target_id=5, actor_id=7, reason="п11")])

    await cog._poll_manual_once(g)  # type: ignore[arg-type]

    channel.send.assert_awaited_once()
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.description == "<@5> забанен. Помянем."
    assert embed.fields[0].value == "п11"
    assert embed.author.name == "mod7"
    assert embed.colour == discord.Color.green()
    assert await repo.get_cursor("ban") == 2
    assert await repo.get_cursor("unban") == 1  # курсоры независимы


async def test_manual_ban_via_ui_default_reason(db) -> None:
    repo = RepoBanWatcher(db)
    await repo.set_cursor("ban", 1)
    await repo.set_cursor("unban", 1)
    await repo.set_cursor("kick", 1)
    channel = SimpleNamespace(send=AsyncMock())
    cog = _watch_cog(db, channel)

    await cog._poll_manual_once(  # type: ignore[arg-type]
        _watch_guild(bans=[_entry(entry_id=2, target_id=5, actor_id=7)])
    )

    assert channel.send.await_args.kwargs["embed"].fields[0].value == REASON_NOT_GIVEN


async def test_manual_unban_via_ui_posts_embed(db) -> None:
    repo = RepoBanWatcher(db)
    await repo.set_cursor("ban", 1)
    await repo.set_cursor("unban", 1)
    await repo.set_cursor("kick", 1)
    channel = SimpleNamespace(send=AsyncMock())
    cog = _watch_cog(db, channel)

    await cog._poll_manual_once(  # type: ignore[arg-type]
        _watch_guild(unbans=[_entry(entry_id=3, target_id=5, actor_id=7, reason="смс")])
    )

    embed = channel.send.await_args.kwargs["embed"]
    assert embed.description == "<@5> разбанен. Возрадуемся!"
    assert embed.fields[0].value == "смс"
    assert await repo.get_cursor("unban") == 3


async def test_manual_ban_by_bot_is_ignored(db) -> None:
    repo = RepoBanWatcher(db)
    await repo.set_cursor("ban", 1)
    await repo.set_cursor("unban", 1)
    await repo.set_cursor("kick", 1)
    channel = SimpleNamespace(send=AsyncMock())
    cog = _watch_cog(db, channel)

    await cog._poll_manual_once(  # type: ignore[arg-type]
        _watch_guild(bans=[_entry(entry_id=2, target_id=5, actor_id=_BOT_ID)])
    )

    channel.send.assert_not_awaited()
    assert await repo.get_cursor("ban") == 2


async def test_manual_ban_actor_not_found_skips(db) -> None:
    repo = RepoBanWatcher(db)
    await repo.set_cursor("ban", 1)
    await repo.set_cursor("unban", 1)
    await repo.set_cursor("kick", 1)
    channel = SimpleNamespace(send=AsyncMock())
    cog = _watch_cog(db, channel)

    await cog._poll_manual_once(  # type: ignore[arg-type]
        _watch_guild(bans=[_entry(entry_id=2, target_id=5, actor_id=None)])
    )

    channel.send.assert_not_awaited()
    assert await repo.get_cursor("ban") == 2


async def test_manual_ban_send_failure_still_advances_cursor(db) -> None:
    repo = RepoBanWatcher(db)
    await repo.set_cursor("ban", 1)
    await repo.set_cursor("unban", 1)
    await repo.set_cursor("kick", 1)
    channel = SimpleNamespace(
        send=AsyncMock(side_effect=discord.HTTPException(MagicMock(status=500), "boom"))
    )
    cog = _watch_cog(db, channel)

    await cog._poll_manual_once(  # type: ignore[arg-type]
        _watch_guild(bans=[_entry(entry_id=2, target_id=5, actor_id=7)])
    )

    assert await repo.get_cursor("ban") == 2


async def test_manual_ban_without_channel_advances_cursor(db) -> None:
    repo = RepoBanWatcher(db)
    await repo.set_cursor("ban", 1)
    await repo.set_cursor("unban", 1)
    await repo.set_cursor("kick", 1)
    cog = _watch_cog(db, None)  # #баны не резолвится

    await cog._poll_manual_once(  # type: ignore[arg-type]
        _watch_guild(bans=[_entry(entry_id=2, target_id=5, actor_id=7)])
    )

    assert await repo.get_cursor("ban") == 2


async def test_manual_kick_via_ui_posts_embed_to_bot_komandy(db) -> None:
    repo = RepoBanWatcher(db)
    await repo.set_cursor("ban", 1)
    await repo.set_cursor("unban", 1)
    await repo.set_cursor("kick", 1)
    bany = SimpleNamespace(send=AsyncMock())
    bot_komandy = SimpleNamespace(send=AsyncMock())
    cog = _watch_cog(db, bany, bot_komandy)

    await cog._poll_manual_once(  # type: ignore[arg-type]
        _watch_guild(kicks=[_entry(entry_id=4, target_id=5, actor_id=7, reason="взлом аккаунта")])
    )

    bany.send.assert_not_awaited()
    embed = bot_komandy.send.await_args.kwargs["embed"]
    assert embed.description == "<@5> кикнут с сервера"
    assert embed.fields[0].value == "взлом аккаунта"
    assert embed.author.name == "mod7"
    assert embed.colour == discord.Color.green()
    assert await repo.get_cursor("kick") == 4


async def test_manual_kick_by_bot_is_ignored(db) -> None:
    repo = RepoBanWatcher(db)
    await repo.set_cursor("ban", 1)
    await repo.set_cursor("unban", 1)
    await repo.set_cursor("kick", 1)
    bot_komandy = SimpleNamespace(send=AsyncMock())
    cog = _watch_cog(db, None, bot_komandy)

    await cog._poll_manual_once(  # type: ignore[arg-type]
        _watch_guild(kicks=[_entry(entry_id=4, target_id=5, actor_id=_BOT_ID)])
    )

    bot_komandy.send.assert_not_awaited()
    assert await repo.get_cursor("kick") == 4
