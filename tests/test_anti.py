"""P3.1 — anti: embed'ы и порядок веток /add, /del."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from connor.cogs.anti import (
    _ERR_ALREADY,
    _ERR_NOT_IN_LIST,
    _ROLE_REMOVE_FAILED,
    _ROLE_RETURN_FAILED,
    Anti,
    build_add_embed,
    build_del_embed,
    build_role_removed_embed,
    build_role_returned_embed,
)
from connor.core.texts import ERR_NO_TARGET
from connor.db import Database
from connor.db.repo_anti import RepoAnti
from connor.db.repo_anti_watcher import RepoAntiWatcher
from connor.db.repo_predlozhka import RepoPredlozhka

# --- pure embed builders --------------------------------------------------------


def test_build_add_embed() -> None:
    e = build_add_embed("<@5>", "п11", 1_755_366_570)
    assert e.title == "Добавление"
    assert e.description == "Пользователь <@5> добавлен в список антиработяг"
    assert e.colour == discord.Color.red()
    assert [f.name for f in e.fields] == ["Причина", "Дата добавления"]
    assert e.fields[0].value == "п11"
    assert e.footer.text.startswith("Claptrap желает вам приятного дня • ")


def test_build_del_embed_has_no_date_field() -> None:
    e = build_del_embed("<@5>", "отсидел")
    assert e.title == "Удаление"
    assert e.description == "Пользователь <@5> удалён из списка антиработяг"
    assert e.colour == discord.Color.green()
    assert [f.name for f in e.fields] == ["Причина"]
    assert e.footer.text.startswith("Claptrap желает вам приятного дня • ")


_MOD = SimpleNamespace(
    name="enteii", display_name="СерверныйНик", display_avatar=SimpleNamespace(url="http://a")
)


def test_build_role_removed_embed() -> None:
    e = build_role_removed_embed("<@5>")
    assert "**изъяли роль**" in e.description
    assert "Работяга" in e.description
    assert e.footer.text is None
    assert e.colour == discord.Color.red()
    assert e.author.name is None  # без модератора
    assert e.thumbnail.url is None

    e2 = build_role_removed_embed("<@5>", moderator=_MOD, target_avatar_url="http://target")
    assert e2.author.name == "enteii"  # username, не серверный ник
    assert e2.thumbnail.url == "http://target"


def test_build_role_returned_embed() -> None:
    e = build_role_returned_embed("<@5>", moderator=_MOD, target_avatar_url="http://target")
    assert "**вернули роль**" in e.description
    assert "Работяга" in e.description
    assert e.colour == discord.Color.green()
    assert e.author.name == "enteii"
    assert e.thumbnail.url == "http://target"


# --- /add, /del flow (real DB, fake Discord) -----------------------------------


def _member(mid: int, *, roles: list[object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=mid,
        roles=roles if roles is not None else [],
        remove_roles=AsyncMock(),
        add_roles=AsyncMock(),
        display_avatar=SimpleNamespace(url=f"http://avatar/{mid}"),
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
    async def fetch_member(i: int) -> SimpleNamespace:
        member = members.get(i)
        if member is None:
            raise discord.NotFound(SimpleNamespace(status=404, reason="x"), "no")
        return member

    guild = SimpleNamespace(
        get_member=lambda i: members.get(i),
        get_role=lambda _i: role,
        get_channel=lambda _i: predlozhka,
        fetch_member=fetch_member,
    )
    author = SimpleNamespace(id=1, name="mod1", display_avatar=SimpleNamespace(url="http://mod"))
    return SimpleNamespace(guild=guild, author=author, send=AsyncMock())


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
    last_embed = ctx.send.await_args_list[-1].kwargs["embed"]
    assert "**вернули роль**" in last_embed.description
    assert last_embed.author.name == "mod1"
    assert last_embed.thumbnail.url == member.display_avatar.url


async def test_del_return_failed_when_member_absent(db: Database) -> None:
    await RepoAnti(db).add(50, added_at=1, added_by=1)
    ctx = _ctx(members={}, role=object())

    await _del(_cog(db), ctx, "50", "отсидел")

    assert await RepoAnti(db).contains(50) is False
    assert ctx.send.await_args_list[-1].args == (_ROLE_RETURN_FAILED,)


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


# --- watcher: опрос audit log --------------------------------------------------

_RABOTYAGA_ID = 111


async def _audit_iter(entries: list[object]):
    for entry in entries:
        yield entry


def _entry(
    *, entry_id: int, target_id: int, actor_id: int | None, granted: bool, unrelated: bool = False
) -> SimpleNamespace:
    """``unrelated=True`` — запись про смену другой роли (не «работяга»)."""
    role_side = [] if unrelated else [SimpleNamespace(id=_RABOTYAGA_ID)]
    user = (
        None
        if actor_id is None
        else SimpleNamespace(
            id=actor_id,
            name=f"mod{actor_id}",
            display_avatar=SimpleNamespace(url="u"),
        )
    )
    return SimpleNamespace(
        id=entry_id,
        user_id=actor_id,
        user=user,
        target=SimpleNamespace(id=target_id, mention=f"<@{target_id}>"),
        after=SimpleNamespace(roles=role_side if granted else []),
        before=SimpleNamespace(roles=[] if granted else role_side),
    )


def _guild(*, entries: list[object], antichannel: object = None, latest: list[object] = ()):
    def audit_logs(**kw):
        if kw.get("limit") == 1 and "action" not in kw:
            return _audit_iter(list(latest))
        return _audit_iter(entries)

    return SimpleNamespace(
        audit_logs=audit_logs,
        get_channel=lambda cid: antichannel if cid == 333 else None,
    )


async def _poll(cog: Anti, guild: object) -> None:
    await Anti._poll_once(cog, guild)


async def test_poll_first_run_seeds_cursor_without_processing(db: Database) -> None:
    channel = SimpleNamespace(send=AsyncMock())
    latest = [_entry(entry_id=42, target_id=50, actor_id=7, granted=False)]
    g = _guild(entries=[], antichannel=channel, latest=latest)

    await _poll(_cog(db), g)

    channel.send.assert_not_awaited()  # первый запуск — без ретроактивной обработки истории
    assert await RepoAntiWatcher(db).get_cursor() == 42


async def test_poll_first_run_no_history_leaves_cursor_unset(db: Database) -> None:
    g = _guild(entries=[], antichannel=None, latest=[])
    await _poll(_cog(db), g)
    assert await RepoAntiWatcher(db).get_cursor() is None


async def test_poll_ignores_unrelated_role_change(db: Database) -> None:
    await RepoAntiWatcher(db).set_cursor(1)
    channel = SimpleNamespace(send=AsyncMock())
    entry = _entry(entry_id=2, target_id=50, actor_id=7, granted=True, unrelated=True)
    g = _guild(entries=[entry], antichannel=channel)

    await _poll(_cog(db), g)

    channel.send.assert_not_awaited()
    assert await RepoAntiWatcher(db).get_cursor() == 2  # курсор всё равно двигается


async def test_poll_manual_removal_by_mod(db: Database) -> None:
    await RepoAntiWatcher(db).set_cursor(1)
    channel = SimpleNamespace(send=AsyncMock())
    entry = _entry(entry_id=2, target_id=50, actor_id=7, granted=False)
    g = _guild(entries=[entry], antichannel=channel)

    await _poll(_cog(db), g)

    channel.send.assert_awaited_once()
    embed = channel.send.await_args.kwargs["embed"]
    assert "**изъяли роль**" in embed.description
    assert embed.author.name == "mod7"
    assert await RepoAntiWatcher(db).get_cursor() == 2


async def test_poll_ignores_removal_by_bot(db: Database) -> None:
    await RepoAntiWatcher(db).set_cursor(1)
    channel = SimpleNamespace(send=AsyncMock())
    entry = _entry(entry_id=2, target_id=50, actor_id=_BOT_ID, granted=False)
    g = _guild(entries=[entry], antichannel=channel)

    await _poll(_cog(db), g)

    channel.send.assert_not_awaited()
    assert await RepoAntiWatcher(db).get_cursor() == 2  # запись просмотрена, курсор двигается


async def test_poll_manual_grant_to_anti_user(db: Database) -> None:
    await RepoAnti(db).add(50, added_at=1, added_by=1)
    await RepoAntiWatcher(db).set_cursor(1)
    channel = SimpleNamespace(send=AsyncMock())
    entry = _entry(entry_id=2, target_id=50, actor_id=7, granted=True)
    g = _guild(entries=[entry], antichannel=channel)

    await _poll(_cog(db), g)

    assert await RepoAnti(db).contains(50) is False
    assert channel.send.await_count == 2  # "Удаление" embed + "вернули роль" embed


async def test_poll_ignores_grant_to_non_anti_user(db: Database) -> None:
    await RepoAntiWatcher(db).set_cursor(1)
    channel = SimpleNamespace(send=AsyncMock())
    entry = _entry(entry_id=2, target_id=50, actor_id=7, granted=True)
    g = _guild(entries=[entry], antichannel=channel)

    await _poll(_cog(db), g)
    channel.send.assert_not_awaited()


async def test_poll_actor_not_found_logs_and_skips(db: Database) -> None:
    await RepoAntiWatcher(db).set_cursor(1)
    channel = SimpleNamespace(send=AsyncMock())
    entry = _entry(entry_id=2, target_id=50, actor_id=None, granted=False)
    g = _guild(entries=[entry], antichannel=channel)

    await _poll(_cog(db), g)

    channel.send.assert_not_awaited()
    assert await RepoAntiWatcher(db).get_cursor() == 2
