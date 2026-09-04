"""P3.4 — roleGiver: B/C/D, текст заявки, аудит-embed, сценарии /give, реакции."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from connor.cogs.role_giver import (
    _GRANTED,
    _PENDING,
    _REFUSAL,
    GiveReason,
    RoleGiver,
    build_audit_embed,
    build_review_message,
    evaluate_give,
)
from connor.db import Database
from connor.db.repo_anti import RepoAnti
from connor.db.repo_give import RepoGive

_CFG = SimpleNamespace(
    account_min_age_days=180, member_min_tenure_days=14, join_after_register_min_minutes=20
)
_NOW = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)


# --- evaluate_give (B/C/D) --------------------------------------------------------

# gap = joined - created; свободных параметра два (created, joined), D = account_age - tenure


def _ev(*, created_days_ago: float, joined_days_ago: float) -> list[GiveReason]:
    return evaluate_give(
        account_created_at=_NOW - timedelta(days=created_days_ago),
        joined_at=_NOW - timedelta(days=joined_days_ago),
        now=_NOW,
        cfg=_CFG,
    )


def test_clean_account() -> None:
    # старый аккаунт, давно на сервере, зашёл сильно позже регистрации
    assert _ev(created_days_ago=400, joined_days_ago=90) == []


def test_newreg_only() -> None:
    # аккаунт 30 дней (B), на сервере 25 дней (не C), gap 5 дней (не D)
    assert _ev(created_days_ago=30, joined_days_ago=25) == [GiveReason.NEWREG]


def test_short_tenure_only() -> None:
    # аккаунт 400 дней (не B), на сервере 3 дня (C), gap 397 дней (не D)
    assert _ev(created_days_ago=400, joined_days_ago=3) == [GiveReason.SHORT_TENURE]


def test_fast_join_only() -> None:
    # аккаунт ~200 дней (не B), на сервере ~200 дней (не C), зашёл через 10 минут (D)
    created = _NOW - timedelta(days=200)
    joined = created + timedelta(minutes=10)
    assert evaluate_give(account_created_at=created, joined_at=joined, now=_NOW, cfg=_CFG) == [
        GiveReason.FAST_JOIN
    ]


def test_multiple_reasons_in_order() -> None:
    # молодой аккаунт, только зашёл, почти сразу после регистрации
    created = _NOW - timedelta(days=1)
    joined = created + timedelta(minutes=5)
    assert evaluate_give(account_created_at=created, joined_at=joined, now=_NOW, cfg=_CFG) == [
        GiveReason.NEWREG,
        GiveReason.SHORT_TENURE,
        GiveReason.FAST_JOIN,
    ]


def test_joined_at_none_triggers_short_tenure() -> None:
    created = _NOW - timedelta(days=400)
    assert evaluate_give(account_created_at=created, joined_at=None, now=_NOW, cfg=_CFG) == [
        GiveReason.SHORT_TENURE
    ]


# --- build_review_message ------------------------------------------------------


def test_review_message_b_and_c() -> None:
    created = datetime(2025, 12, 13, 19, 21, 36, tzinfo=UTC)
    joined = datetime(2026, 8, 20, 14, 53, 38, tzinfo=UTC)
    text = build_review_message(
        "<@5>", [GiveReason.NEWREG, GiveReason.SHORT_TENURE], created, joined
    )
    lines = text.split("\n")
    assert lines[0] == "@here Пользователь <@5> запросил работягу. Причины, по которым я не выдал:"
    assert lines[1] == "Новорег. Дата регистрации: 13.12.25 22:21:36"  # MSK = UTC+3
    assert lines[2] == "Аккаунт находится на сервере менее 2х недель."
    assert lines[3] == "Дата присоединения: 20.08.26 17:53:38"


def test_review_message_d_line() -> None:
    created = datetime(2025, 10, 2, 22, 55, 40, tzinfo=UTC)
    joined = datetime(2025, 10, 2, 22, 56, 25, tzinfo=UTC)
    text = build_review_message("<@5>", [GiveReason.FAST_JOIN], created, joined)
    lines = text.split("\n")
    assert lines[1] == (
        "Между регистрацией аккаунта и присоединением на сервер прошло меньше 20 минут."
    )
    assert lines[2] == "Дата регистрации: 03.10.25 01:55:40; Дата присоединения: 03.10.25 01:56:25"


# --- build_audit_embed -------------------------------------------------------------


def test_audit_embed_approved() -> None:
    e = build_audit_embed(
        mod_id=9,
        mod_name="mod",
        mod_icon=None,
        target_mention="<@5>",
        target_avatar_url="https://example.com/a.png",
        role_mention="<@&7>",
        approved=True,
    )
    assert e.colour == discord.Color.green()
    assert e.description == "<@9> обновил <@5>"
    assert e.fields[0].name == "Выдана роль"
    assert e.fields[0].value == "<@&7>"
    assert e.thumbnail.url == "https://example.com/a.png"


def test_audit_embed_refused() -> None:
    e = build_audit_embed(
        mod_id=9,
        mod_name="mod",
        mod_icon=None,
        target_mention="<@5>",
        target_avatar_url=None,
        role_mention="<@&7>",
        approved=False,
    )
    assert e.colour == discord.Color.red()
    assert e.description == "<@9> отказал <@5>"
    assert e.fields[0].name == "Отказ в выдаче роли"
    assert e.thumbnail.url is None


# --- /give сценарии (реальная БД, фейки Discord) -----------------------------


def _member(mid: int, *, created: datetime, joined: datetime | None, guild: object) -> MagicMock:
    m = MagicMock(spec=discord.Member)
    m.id = mid
    m.mention = f"<@{mid}>"
    m.created_at = created
    m.joined_at = joined
    m.guild = guild
    m.add_roles = AsyncMock()
    return m


def _bot(db: Database, *, rekvesty=None) -> SimpleNamespace:
    config = SimpleNamespace(
        guild_id=1,
        roles={"RABOTYAGA": 111},
        channels={"REKVESTY": 10, "VYDACHA": 11, "AUDIT": 12},
        role_giver=_CFG,
    )
    return SimpleNamespace(
        db=db,
        config=config,
        user=SimpleNamespace(id=999),
        get_channel=lambda cid: rekvesty if cid == 10 else None,
    )


def _ctx(guild: object, member: object):
    return SimpleNamespace(guild=guild, author=member, send=AsyncMock())


async def _give(cog: RoleGiver, ctx: object) -> None:
    await RoleGiver.give.callback(cog, ctx)


def _guild_with_role() -> SimpleNamespace:
    return SimpleNamespace(get_role=lambda _i: MagicMock(spec=discord.Role))


async def test_give_anti_worker_instant_refusal(db: Database) -> None:
    await RepoAnti(db).add(5, added_at=1, added_by=1)
    guild = _guild_with_role()
    member = _member(
        5, created=_NOW - timedelta(days=400), joined=_NOW - timedelta(days=90), guild=guild
    )
    ctx = _ctx(guild, member)

    await _give(RoleGiver(_bot(db)), ctx)  # type: ignore[arg-type]

    ctx.send.assert_awaited_once()
    assert ctx.send.await_args.args[0] == _REFUSAL
    member.add_roles.assert_not_awaited()


async def test_give_clean_account_instant_grant(db: Database) -> None:
    guild = _guild_with_role()
    member = _member(
        5, created=_NOW - timedelta(days=400), joined=_NOW - timedelta(days=90), guild=guild
    )
    ctx = _ctx(guild, member)

    await _give(RoleGiver(_bot(db)), ctx)  # type: ignore[arg-type]

    member.add_roles.assert_awaited_once()
    assert ctx.send.await_args.args[0] == _GRANTED


async def test_give_clean_account_grant_fails_stays_silent(db: Database) -> None:
    guild = SimpleNamespace(get_role=lambda _i: None)  # роль «работяга» не резолвится
    member = _member(
        5, created=_NOW - timedelta(days=400), joined=_NOW - timedelta(days=90), guild=guild
    )
    ctx = _ctx(guild, member)

    await _give(RoleGiver(_bot(db)), ctx)  # type: ignore[arg-type]

    member.add_roles.assert_not_awaited()
    ctx.send.assert_not_awaited()  # ни успеха, ни ошибки пользователю — только серверный лог


async def test_give_suspicious_opens_manual_review(db: Database) -> None:
    review_msg = SimpleNamespace(id=777, add_reaction=AsyncMock())
    rekvesty = SimpleNamespace(send=AsyncMock(return_value=review_msg))
    guild = _guild_with_role()
    member = _member(
        5, created=_NOW - timedelta(days=10), joined=_NOW - timedelta(days=1), guild=guild
    )
    ctx = _ctx(guild, member)

    await _give(RoleGiver(_bot(db, rekvesty=rekvesty)), ctx)  # type: ignore[arg-type]

    assert ctx.send.await_args.args[0] == _PENDING
    rekvesty.send.assert_awaited_once()
    assert review_msg.add_reaction.await_count == 2
    member.add_roles.assert_not_awaited()
    assert await RepoGive(db).get(777) is not None


# --- on_raw_reaction_add ------------------------------------------------------


def _payload(*, message_id: int, emoji: str, user_id: int = 7) -> SimpleNamespace:
    mod = MagicMock(spec=discord.Member)
    mod.id = user_id
    mod.display_name = f"mod{user_id}"
    mod.display_avatar = SimpleNamespace(url="u")
    return SimpleNamespace(
        guild_id=1,
        user_id=user_id,
        message_id=message_id,
        channel_id=10,
        emoji=SimpleNamespace(name=emoji),
        member=mod,
    )


async def test_reaction_approve_grants_and_logs(db: Database) -> None:
    await RepoGive(db).add(777, user_id=5, created_at=1)
    target = MagicMock(spec=discord.Member)
    target.id = 5
    target.mention = "<@5>"
    target.add_roles = AsyncMock()
    role = MagicMock(spec=discord.Role)
    audit = SimpleNamespace(send=AsyncMock())
    vydacha = SimpleNamespace(send=AsyncMock())
    review_channel = SimpleNamespace(
        get_partial_message=lambda _m: SimpleNamespace(delete=AsyncMock())
    )
    guild = SimpleNamespace(get_role=lambda _i: role, fetch_member=AsyncMock(return_value=target))

    bot = _bot(db)
    bot.get_guild = lambda _i: guild
    bot.get_channel = lambda cid: {10: review_channel, 11: vydacha, 12: audit}.get(cid)

    await RoleGiver.on_raw_reaction_add(RoleGiver(bot), _payload(message_id=777, emoji="☑️"))  # type: ignore[arg-type]

    target.add_roles.assert_awaited_once()
    vydacha.send.assert_awaited_once()
    assert "роль выдана." in vydacha.send.await_args.args[0]
    audit.send.assert_awaited_once()
    assert await RepoGive(db).get(777) is None  # заявка снята


async def test_reaction_approve_grant_fails_no_announcements(db: Database) -> None:
    await RepoGive(db).add(777, user_id=5, created_at=1)
    target = MagicMock(spec=discord.Member)
    target.id = 5
    target.mention = "<@5>"
    target.add_roles = AsyncMock(
        side_effect=discord.HTTPException(MagicMock(status=500), "boom")
    )
    role = MagicMock(spec=discord.Role)
    audit = SimpleNamespace(send=AsyncMock())
    vydacha = SimpleNamespace(send=AsyncMock())
    review_channel = SimpleNamespace(
        get_partial_message=lambda _m: SimpleNamespace(delete=AsyncMock())
    )
    guild = SimpleNamespace(get_role=lambda _i: role, fetch_member=AsyncMock(return_value=target))

    bot = _bot(db)
    bot.get_guild = lambda _i: guild
    bot.get_channel = lambda cid: {10: review_channel, 11: vydacha, 12: audit}.get(cid)

    await RoleGiver.on_raw_reaction_add(RoleGiver(bot), _payload(message_id=777, emoji="☑️"))  # type: ignore[arg-type]

    target.add_roles.assert_awaited_once()
    vydacha.send.assert_not_awaited()  # ничего в #выдача
    audit.send.assert_not_awaited()  # и ничего в #аудит
    assert await RepoGive(db).get(777) is None  # но заявка снята — решение принято


async def test_reaction_race_second_is_noop(db: Database) -> None:
    await RepoGive(db).add(777, user_id=5, created_at=1)
    target = MagicMock(spec=discord.Member)
    target.id = 5
    target.mention = "<@5>"
    target.add_roles = AsyncMock()
    guild = SimpleNamespace(
        get_role=lambda _i: MagicMock(spec=discord.Role),
        fetch_member=AsyncMock(return_value=target),
    )
    bot = _bot(db)
    bot.get_guild = lambda _i: guild
    bot.get_channel = lambda _c: SimpleNamespace(
        send=AsyncMock(), get_partial_message=lambda _m: SimpleNamespace(delete=AsyncMock())
    )
    cog = RoleGiver(bot)  # type: ignore[arg-type]

    await RoleGiver.on_raw_reaction_add(cog, _payload(message_id=777, emoji="☑️"))
    calls_after_first = target.add_roles.await_count
    await RoleGiver.on_raw_reaction_add(cog, _payload(message_id=777, emoji="❌"))

    assert target.add_roles.await_count == calls_after_first  # вторая реакция — no-op


async def test_reaction_ignores_bot_own_and_unknown_emoji(db: Database) -> None:
    await RepoGive(db).add(777, user_id=5, created_at=1)
    cog = RoleGiver(_bot(db))  # type: ignore[arg-type]

    await RoleGiver.on_raw_reaction_add(cog, _payload(message_id=777, emoji="☑️", user_id=999))
    await RoleGiver.on_raw_reaction_add(cog, _payload(message_id=777, emoji="🤔"))

    assert await RepoGive(db).get(777) is not None  # заявка не тронута


async def test_raw_message_delete_removes_request(db: Database) -> None:
    await RepoGive(db).add(777, user_id=5, created_at=1)
    cog = RoleGiver(_bot(db))  # type: ignore[arg-type]

    await RoleGiver.on_raw_message_delete(cog, SimpleNamespace(channel_id=10, message_id=777))
    assert await RepoGive(db).get(777) is None
