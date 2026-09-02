"""P3.1 — anti: embed'ы и порядок веток /add, /del."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from connor.cogs.anti import (
    _ERR_ALREADY,
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
    assert [f.name for f in e.fields] == ["Причина", "Дата добавления"]
    assert e.fields[0].value == "п11"
    assert e.footer.text.startswith("Claptrap желает вам приятного дня • ")


def test_build_del_embed_has_no_date_field() -> None:
    e = build_del_embed("<@5>", "отсидел")
    assert e.description == "Пользователь <@5> удалён из списка антиработяг"
    assert [f.name for f in e.fields] == ["Причина"]
    assert e.footer.text.startswith("Claptrap желает вам приятного дня • ")


def test_build_role_removed_embed() -> None:
    e = build_role_removed_embed("<@5>")
    assert "**изъяли роль**" in e.description
    assert "Работяга" in e.description
    assert "!add id/квот причина" in e.description
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


def _cog(db: Database, *, user_exists: bool = True) -> Anti:
    fetch_user = (
        AsyncMock()
        if user_exists
        else AsyncMock(side_effect=discord.NotFound(SimpleNamespace(status=404, reason="x"), "no"))
    )
    config = SimpleNamespace(
        roles={"RABOTYAGA": 111},
        channels={"PREDLOZHKA": 222},
    )
    return Anti(SimpleNamespace(db=db, config=config, fetch_user=fetch_user))  # type: ignore[arg-type]


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


async def test_del_deleted_account_cleans_silently(db: Database) -> None:
    await RepoAnti(db).add(50, added_at=1, added_by=1)
    ctx = _ctx(members={})
    await _del(_cog(db, user_exists=False), ctx, "50")

    assert await RepoAnti(db).contains(50) is False
    ctx.send.assert_awaited_once_with(ERR_NO_TARGET)  # без embed'ов
