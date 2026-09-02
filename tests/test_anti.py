"""P3.1 — anti: embed'ы и порядок веток /add, /del."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from connor.cogs.anti import (
    _ERR_ALREADY,
    _ERR_NOT_IN_LIST,
    _ROLE_REMOVE_FAILED,
    _ROLE_RETURNED,
    Anti,
    build_add_embed,
    build_del_embed,
    build_role_removed_embed,
)
from connor.core.texts import ERR_NO_TARGET
from connor.db import Database
from connor.db.repo_anti import RepoAnti
from connor.db.repo_predlozhka import RepoPredlozhka

# --- pure embed builders --------------------------------------------------------


def test_build_add_embed() -> None:
    e = build_add_embed("<@5>", "п11", 1_755_366_570)
    assert e.description == "Пользователь <@5> добавлен в список антиработяг"
    assert e.colour == discord.Color.red()
    assert [f.name for f in e.fields] == ["Причина", "Дата добавления"]
    assert e.fields[0].value == "п11"
    assert e.footer.text.startswith("Claptrap желает вам приятного дня • ")


def test_build_del_embed_has_no_date_field() -> None:
    e = build_del_embed("<@5>", "отсидел")
    assert e.description == "Пользователь <@5> удалён из списка антиработяг"
    assert e.colour == discord.Color.green()
    assert [f.name for f in e.fields] == ["Причина"]
    assert e.footer.text.startswith("Claptrap желает вам приятного дня • ")


def test_build_role_removed_embed() -> None:
    e = build_role_removed_embed("<@5>")
    assert "**изъяли роль**" in e.description
    assert "Работяга" in e.description
    assert "!add id/квот причина" in e.description
    assert e.colour == discord.Color.red()
    assert e.author.name is None  # без модератора

    m = SimpleNamespace(display_name="enteii", display_avatar=SimpleNamespace(url="http://a"))
    e2 = build_role_removed_embed("<@5>", moderator=m)
    assert e2.author.name == "enteii"


# --- /add, /del flow (real DB, fake Discord) -----------------------------------


def _member(mid: int, *, roles: list[object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=mid,
        roles=roles if roles is not None else [],
        remove_roles=AsyncMock(),
        add_roles=AsyncMock(),
    )


_BOT_ID = 999


def _cog(db: Database, *, user_exists: bool = True) -> Anti:
    fetch_user = (
        AsyncMock()
        if user_exists
        else AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404, reason="x"), "no"))
    )
    config = SimpleNamespace(
        roles={"RABOTYAGA": 111},
        channels={"PREDLOZHKA": 222, "ANTIRABOTYAGI": 333},
    )
    bot = SimpleNamespace(
        db=db, config=config, fetch_user=fetch_user, user=SimpleNamespace(id=_BOT_ID)
    )
    return Anti(bot)  # type: ignore[arg-type]


def _ctx(*, members: dict[int, SimpleNamespace], role: object = None, predlozhka: object = None):
    guild = SimpleNamespace(
        get_member=lambda i: members.get(i),
        get_role=lambda _i: role,
        get_channel=lambda _i: predlozhka,
    )
    return SimpleNamespace(guild=guild, author=SimpleNamespace(id=1), send=AsyncMock())


async def _add(cog: Anti, ctx: object, target: str, reason: str | None = None) -> None:
    await Anti.add.callback(cog, ctx, target, reason=reason)


async def _del(cog: Anti, ctx: object, target: str, reason: str | None = None) -> None:
    await Anti.del_.callback(cog, ctx, target, reason=reason)


async def test_add_no_target(db: Database) -> None:
    ctx = _ctx(members={})
    await _add(_cog(db), ctx, "junk")
    ctx.send.assert_awaited_once_with(ERR_NO_TARGET)


async def test_add_unresolvable_account(db: Database) -> None:
    ctx = _ctx(members={})
    await _add(_cog(db, user_exists=False), ctx, "123456789012345678")
    ctx.send.assert_awaited_once_with(ERR_NO_TARGET)


async def test_add_already_in_list(db: Database) -> None:
    await RepoAnti(db).add(50, added_at=1, added_by=1)
    ctx = _ctx(members={})
    await _add(_cog(db), ctx, "50")
    ctx.send.assert_awaited_once_with(_ERR_ALREADY.format(mention="<@50>"))


async def test_add_success_removes_role(db: Database) -> None:
    role = object()
    member = _member(50, roles=[role])
    ctx = _ctx(members={50: member}, role=role)

    await _add(_cog(db), ctx, "50", "п11")

    assert await RepoAnti(db).contains(50) is True
    member.remove_roles.assert_awaited_once()
    kinds = [c.kwargs.get("embed") for c in ctx.send.await_args_list]
    assert isinstance(kinds[0], discord.Embed)  # "Добавление"
    assert isinstance(kinds[1], discord.Embed)  # "изъяли роль"


async def test_add_success_member_absent_reports_role_failure(db: Database) -> None:
    ctx = _ctx(members={}, role=object())
    await _add(_cog(db), ctx, "50")
    assert await RepoAnti(db).contains(50) is True
    assert ctx.send.await_args_list[-1].args == (_ROLE_REMOVE_FAILED,)


async def test_add_sets_predlozhka_deny_when_access_exists(db: Database) -> None:
    role = object()
    member = _member(50, roles=[role])
    predlozhka = SimpleNamespace(
        permissions_for=lambda _m: SimpleNamespace(send_messages=True),
        overwrites_for=lambda _m: discord.PermissionOverwrite(),
        set_permissions=AsyncMock(),
    )
    ctx = _ctx(members={50: member}, role=role, predlozhka=predlozhka)

    await _add(_cog(db), ctx, "50")

    predlozhka.set_permissions.assert_awaited_once()
    assert await RepoPredlozhka(db).contains(50) is True


async def test_del_removes_and_returns_role(db: Database) -> None:
    await RepoAnti(db).add(50, added_at=1, added_by=1)
    role = object()
    member = _member(50, roles=[])  # роли нет -> должна добавиться
    ctx = _ctx(members={50: member}, role=role)

    await _del(_cog(db), ctx, "50", "отсидел")

    assert await RepoAnti(db).contains(50) is False
    member.add_roles.assert_awaited_once()
    assert ctx.send.await_args_list[-1].args == (_ROLE_RETURNED,)


async def test_del_not_in_list_plain_error(db: Database) -> None:
    ctx = _ctx(members={})
    await _del(_cog(db), ctx, "50")
    ctx.send.assert_awaited_once_with(_ERR_NOT_IN_LIST)  # текст, не embed


async def test_del_not_in_list_still_clears_stale_predlozhka_deny(db: Database) -> None:
    # анти-статуса нет, но бот-овый deny в «предложке» когда-то остался — снять
    await RepoPredlozhka(db).add(50, reason="анти-работяга", set_at=1)
    member = _member(50, roles=[])
    predlozhka = SimpleNamespace(
        overwrites_for=lambda _m: discord.PermissionOverwrite(send_messages=False),
        set_permissions=AsyncMock(),
    )
    ctx = _ctx(members={50: member}, predlozhka=predlozhka)

    await _del(_cog(db), ctx, "50")

    predlozhka.set_permissions.assert_awaited_once()
    assert await RepoPredlozhka(db).contains(50) is False
    ctx.send.assert_awaited_once_with(_ERR_NOT_IN_LIST)


async def test_del_deleted_account_cleans_silently(db: Database) -> None:
    await RepoAnti(db).add(50, added_at=1, added_by=1)
    ctx = _ctx(members={})
    await _del(_cog(db, user_exists=False), ctx, "50")

    assert await RepoAnti(db).contains(50) is False
    ctx.send.assert_awaited_once_with(ERR_NO_TARGET)  # без embed'ов


# --- watcher: ручные изменения роли «работяга» --------------------------------

_RABOTYAGA = SimpleNamespace(id=111)


async def _audit_iter(entries: list[object]):
    for entry in entries:
        yield entry


def _entry(*, target_id: int, actor_id: int, granted: bool) -> SimpleNamespace:
    role_side = [_RABOTYAGA]
    return SimpleNamespace(
        target=SimpleNamespace(id=target_id),
        user=SimpleNamespace(
            id=actor_id, display_name=f"mod{actor_id}", display_avatar=SimpleNamespace(url="u")
        ),
        after=SimpleNamespace(roles=role_side if granted else []),
        before=SimpleNamespace(roles=[] if granted else role_side),
    )


def _mu_member(uid: int, *, has_role: bool, guild: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=uid,
        mention=f"<@{uid}>",
        roles=[_RABOTYAGA] if has_role else [],
        guild=guild,
    )


def _guild(*, entries: list[object], antichannel: object = None):
    return SimpleNamespace(
        audit_logs=lambda **_kw: _audit_iter(entries),
        get_channel=lambda cid: antichannel if cid == 333 else None,
    )


async def _member_update(cog: Anti, before: object, after: object, monkeypatch) -> None:
    monkeypatch.setattr("connor.cogs.anti.asyncio.sleep", AsyncMock())
    await Anti.on_member_update(cog, before, after)


async def test_watcher_ignores_unrelated_update(db: Database, monkeypatch) -> None:
    g = _guild(entries=[])
    m = _mu_member(50, has_role=True, guild=g)
    await _member_update(_cog(db), m, m, monkeypatch)  # роль не менялась


async def test_watcher_manual_removal_by_mod(db: Database, monkeypatch) -> None:
    channel = SimpleNamespace(send=AsyncMock())
    g = _guild(entries=[_entry(target_id=50, actor_id=7, granted=False)], antichannel=channel)
    before = _mu_member(50, has_role=True, guild=g)
    after = _mu_member(50, has_role=False, guild=g)

    await _member_update(_cog(db), before, after, monkeypatch)

    channel.send.assert_awaited_once()
    embed = channel.send.await_args.kwargs["embed"]
    assert "**изъяли роль**" in embed.description
    assert embed.author.name == "mod7"


async def test_watcher_ignores_removal_by_bot(db: Database, monkeypatch) -> None:
    channel = SimpleNamespace(send=AsyncMock())
    g = _guild(entries=[_entry(target_id=50, actor_id=_BOT_ID, granted=False)], antichannel=channel)
    before = _mu_member(50, has_role=True, guild=g)
    after = _mu_member(50, has_role=False, guild=g)

    await _member_update(_cog(db), before, after, monkeypatch)
    channel.send.assert_not_awaited()


async def test_watcher_manual_grant_to_anti_user(db: Database, monkeypatch) -> None:
    await RepoAnti(db).add(50, added_at=1, added_by=1)
    channel = SimpleNamespace(send=AsyncMock())
    g = _guild(entries=[_entry(target_id=50, actor_id=7, granted=True)], antichannel=channel)
    g.get_channel = lambda cid: channel if cid == 333 else None  # предложка -> None (не трогаем)
    before = _mu_member(50, has_role=False, guild=g)
    after = _mu_member(50, has_role=True, guild=g)

    await _member_update(_cog(db), before, after, monkeypatch)

    assert await RepoAnti(db).contains(50) is False
    assert channel.send.await_count == 2  # "Удаление" embed + "Роль возвращена"


async def test_watcher_ignores_grant_to_non_anti_user(db: Database, monkeypatch) -> None:
    channel = SimpleNamespace(send=AsyncMock())
    g = _guild(entries=[_entry(target_id=50, actor_id=7, granted=True)], antichannel=channel)
    before = _mu_member(50, has_role=False, guild=g)
    after = _mu_member(50, has_role=True, guild=g)

    await _member_update(_cog(db), before, after, monkeypatch)
    channel.send.assert_not_awaited()


async def test_watcher_actor_not_found(db: Database, monkeypatch) -> None:
    channel = SimpleNamespace(send=AsyncMock())
    g = _guild(entries=[], antichannel=channel)  # аудит-лог пуст
    before = _mu_member(50, has_role=True, guild=g)
    after = _mu_member(50, has_role=False, guild=g)

    await _member_update(_cog(db), before, after, monkeypatch)
    channel.send.assert_not_awaited()
