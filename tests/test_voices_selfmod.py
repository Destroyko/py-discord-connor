"""P4.3 — самомодерация: /vkick (права, лимит 100, disconnect-ветка), /vreturn,
!vdel, /ban_list."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from connor.cogs.voices_selfmod import (
    _BANLIST_DM_FAIL,
    _BANLIST_SENT,
    _ERR_LIMIT,
    _ERR_NO_RIGHTS,
    _ERR_NO_USER,
    _ERR_NOT_BANNED,
    _ERR_SELF,
    _VKICK_OK,
    _VRETURN_OK,
    VoicesSelfmod,
    build_banlist_embeds,
)
from connor.db import Database
from connor.db.repo_voice_banlist import RepoVoiceBanlist
from connor.db.repo_voice_rooms import RepoVoiceRooms

_ROOM_ID = 500
_GUILD_ID = 1


def _voices_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        banlist_limit=100,
        banlist_active_window_hours=24,
    )


def _bot(db: Database, *, guild: object = None) -> SimpleNamespace:
    return SimpleNamespace(
        db=db,
        config=SimpleNamespace(guild_id=_GUILD_ID, voices=_voices_cfg(), channels={}),
        http=SimpleNamespace(delete_channel_permissions=AsyncMock()),
        get_guild=lambda _i: guild,
    )


def _room_channel() -> SimpleNamespace:
    return SimpleNamespace(
        id=_ROOM_ID,
        overwrites_for=lambda _m: discord.PermissionOverwrite(),
        set_permissions=AsyncMock(),
    )


def _author(uid: int, *, in_channel_id: int | None) -> MagicMock:
    m = MagicMock(spec=discord.Member)
    m.id = uid
    m.mention = f"<@{uid}>"
    if in_channel_id is None:
        m.voice = None
    else:
        m.voice = SimpleNamespace(channel=SimpleNamespace(id=in_channel_id))
    return m


def _target(uid: int, *, in_channel_id: int | None) -> MagicMock:
    m = MagicMock(spec=discord.Member)
    m.id = uid
    m.mention = f"<@{uid}>"
    m.move_to = AsyncMock()
    if in_channel_id is None:
        m.voice = None
    else:
        m.voice = SimpleNamespace(channel=SimpleNamespace(id=in_channel_id))
    return m


def _guild(*, room_channel: object, target: object) -> SimpleNamespace:
    return SimpleNamespace(
        id=_GUILD_ID,
        get_channel=lambda cid: room_channel if cid == _ROOM_ID else None,
        fetch_member=AsyncMock(return_value=target),
    )


def _ctx(guild: object, author: object) -> SimpleNamespace:
    return SimpleNamespace(guild=guild, author=author, send=AsyncMock(), reply=AsyncMock())


async def _vkick(cog: VoicesSelfmod, ctx: object, target: str) -> None:
    await VoicesSelfmod.vkick.callback(cog, ctx, target)


async def _vreturn(cog: VoicesSelfmod, ctx: object, target: str) -> None:
    await VoicesSelfmod.vreturn.callback(cog, ctx, target)


# --- /vkick ---------------------------------------------------------------------


async def test_vkick_rejected_when_not_owner(db: Database) -> None:
    author = _author(10, in_channel_id=None)
    ctx = _ctx(_guild(room_channel=None, target=None), author)
    await _vkick(VoicesSelfmod(_bot(db)), ctx, "20")
    ctx.reply.assert_awaited_once()
    assert ctx.reply.await_args.args[0] == _ERR_NO_RIGHTS


async def test_vkick_rejected_when_owner_not_in_own_room(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_ROOM_ID, created_at=1)
    author = _author(10, in_channel_id=999)  # в другом войсе
    ctx = _ctx(_guild(room_channel=_room_channel(), target=None), author)
    await _vkick(VoicesSelfmod(_bot(db)), ctx, "20")
    assert ctx.reply.await_args.args[0] == _ERR_NO_RIGHTS


async def test_vkick_no_target(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_ROOM_ID, created_at=1)
    author = _author(10, in_channel_id=_ROOM_ID)
    ctx = _ctx(_guild(room_channel=_room_channel(), target=None), author)
    await _vkick(VoicesSelfmod(_bot(db)), ctx, "мусор")
    assert ctx.reply.await_args.args[0] == _ERR_NO_USER


async def test_vkick_self_rejected(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_ROOM_ID, created_at=1)
    author = _author(10, in_channel_id=_ROOM_ID)
    guild = _guild(room_channel=_room_channel(), target=None)
    ctx = _ctx(guild, author)
    await _vkick(VoicesSelfmod(_bot(db)), ctx, "10")
    assert ctx.reply.await_args.args[0] == _ERR_SELF
    guild.fetch_member.assert_not_awaited()  # себя не резолвим лишний раз


async def test_vkick_target_not_on_server(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_ROOM_ID, created_at=1)
    author = _author(10, in_channel_id=_ROOM_ID)
    guild = _guild(room_channel=_room_channel(), target=None)
    guild.fetch_member = AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "no"))
    ctx = _ctx(guild, author)
    await _vkick(VoicesSelfmod(_bot(db)), ctx, "20")
    assert ctx.reply.await_args.args[0] == _ERR_NO_USER


async def test_vkick_limit_reached_blocks_new_entry(db: Database) -> None:
    banlist = RepoVoiceBanlist(db)
    for i in range(100):
        await banlist.upsert(owner_id=10, banned_id=1000 + i, ts=1)
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_ROOM_ID, created_at=1)
    room = _room_channel()
    author = _author(10, in_channel_id=_ROOM_ID)
    ctx = _ctx(_guild(room_channel=room, target=_target(20, in_channel_id=None)), author)

    await _vkick(VoicesSelfmod(_bot(db)), ctx, "20")

    assert ctx.reply.await_args.args[0] == _ERR_LIMIT
    room.set_permissions.assert_not_awaited()
    assert await banlist.contains(10, 20) is False


async def test_vkick_already_banned_bypasses_limit(db: Database) -> None:
    banlist = RepoVoiceBanlist(db)
    for i in range(99):
        await banlist.upsert(owner_id=10, banned_id=1000 + i, ts=1)
    await banlist.upsert(owner_id=10, banned_id=20, ts=1)  # 100-я, и это наша цель
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_ROOM_ID, created_at=1)
    room = _room_channel()
    author = _author(10, in_channel_id=_ROOM_ID)
    ctx = _ctx(_guild(room_channel=room, target=_target(20, in_channel_id=None)), author)

    await _vkick(VoicesSelfmod(_bot(db)), ctx, "20")

    assert ctx.reply.await_args.args[0] == _VKICK_OK.format(mention="<@20>")
    room.set_permissions.assert_awaited_once()


async def test_vkick_success_disconnects_when_in_room(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_ROOM_ID, created_at=1)
    room = _room_channel()
    author = _author(10, in_channel_id=_ROOM_ID)
    target = _target(20, in_channel_id=_ROOM_ID)  # цель прямо сейчас в комнате
    ctx = _ctx(_guild(room_channel=room, target=target), author)

    await _vkick(VoicesSelfmod(_bot(db)), ctx, "<@20>")

    target.move_to.assert_awaited_once()
    assert target.move_to.await_args.args == (None,)
    room.set_permissions.assert_awaited_once()
    assert await RepoVoiceBanlist(db).contains(10, 20) is True
    assert ctx.reply.await_args.args[0] == _VKICK_OK.format(mention="<@20>")


async def test_vkick_success_no_disconnect_when_elsewhere(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_ROOM_ID, created_at=1)
    room = _room_channel()
    author = _author(10, in_channel_id=_ROOM_ID)
    target = _target(20, in_channel_id=777)  # цель в другом канале
    ctx = _ctx(_guild(room_channel=room, target=target), author)

    await _vkick(VoicesSelfmod(_bot(db)), ctx, "20")

    target.move_to.assert_not_awaited()  # не выгоняем из чужого канала
    room.set_permissions.assert_awaited_once()  # но overwrite ставим
    assert await RepoVoiceBanlist(db).contains(10, 20) is True
    assert ctx.reply.await_args.args[0] == _VKICK_OK.format(mention="<@20>")


# --- /vreturn + !vdel ------------------------------------------------------------


async def test_vreturn_not_in_banlist(db: Database) -> None:
    author = _author(10, in_channel_id=None)
    ctx = _ctx(_guild(room_channel=None, target=None), author)
    await _vreturn(VoicesSelfmod(_bot(db)), ctx, "20")
    assert ctx.reply.await_args.args[0] == _ERR_NOT_BANNED


async def test_vreturn_success_clears_room_deny(db: Database) -> None:
    await RepoVoiceBanlist(db).upsert(owner_id=10, banned_id=20, ts=1)
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_ROOM_ID, created_at=1)
    room = SimpleNamespace(
        id=_ROOM_ID,
        overwrites_for=lambda _m: discord.PermissionOverwrite(connect=False, send_messages=False),
    )
    bot = _bot(db)
    ctx = _ctx(_guild(room_channel=room, target=None), _author(10, in_channel_id=None))

    await _vreturn(VoicesSelfmod(bot), ctx, "20")

    bot.http.delete_channel_permissions.assert_awaited_once()
    assert bot.http.delete_channel_permissions.await_args.args[:2] == (_ROOM_ID, 20)
    assert await RepoVoiceBanlist(db).contains(10, 20) is False
    assert ctx.reply.await_args.args[0] == _VRETURN_OK.format(mention="<@20>")


async def test_vreturn_success_without_active_room(db: Database) -> None:
    await RepoVoiceBanlist(db).upsert(owner_id=10, banned_id=20, ts=1)
    bot = _bot(db)
    ctx = _ctx(_guild(room_channel=None, target=None), _author(10, in_channel_id=None))

    await _vreturn(VoicesSelfmod(bot), ctx, "20")

    bot.http.delete_channel_permissions.assert_not_awaited()
    assert ctx.reply.await_args.args[0] == _VRETURN_OK.format(mention="<@20>")


async def test_vdel_ignored_in_guild(db: Database) -> None:
    ctx = _ctx(_guild(room_channel=None, target=None), _author(10, in_channel_id=None))
    await VoicesSelfmod.vdel.callback(VoicesSelfmod(_bot(db)), ctx, "20")
    ctx.send.assert_not_awaited()


async def test_vdel_in_dm_unbans(db: Database) -> None:
    await RepoVoiceBanlist(db).upsert(owner_id=10, banned_id=20, ts=1)
    guild = _guild(room_channel=None, target=None)
    bot = _bot(db, guild=guild)
    ctx = SimpleNamespace(guild=None, author=_author(10, in_channel_id=None), send=AsyncMock())

    await VoicesSelfmod.vdel.callback(VoicesSelfmod(bot), ctx, "20")

    assert await RepoVoiceBanlist(db).contains(10, 20) is False
    assert ctx.send.await_args.args[0] == _VRETURN_OK.format(mention="<@20>")


# --- /ban_list ----------------------------------------------------------------------


def test_banlist_embed_structure() -> None:
    embeds = build_banlist_embeds([111, 222])
    assert len(embeds) == 1
    embed = embeds[0]
    assert embed.title == "Список забаненных"
    assert embed.colour == discord.Color.blue()
    assert "<@111>" in embed.description
    assert "`<@111>`" not in embed.description  # без code-разметки — кликабельно
    assert "id: 111" in embed.description
    assert "**1**" in embed.description and "**2**" in embed.description
    assert embed.footer.text == "Например !vdel 1234567891011"


def test_banlist_embed_splits_when_large() -> None:
    embeds = build_banlist_embeds(list(range(10**18, 10**18 + 100)))
    assert len(embeds) >= 2
    assert embeds[0].title == "Список забаненных"
    assert embeds[-1].title is None  # заголовок только у первого
    assert embeds[-1].footer.text == "Например !vdel 1234567891011"
    assert all(len(e.description) <= 4096 for e in embeds)
    # сквозная нумерация не сбрасывается между embed'ами
    assert "**100**" in embeds[-1].description


async def test_ban_list_sends_dm_and_confirms(db: Database) -> None:
    await RepoVoiceBanlist(db).upsert(owner_id=10, banned_id=20, ts=1)
    author = _author(10, in_channel_id=None)
    author.send = AsyncMock()
    ctx = _ctx(_guild(room_channel=None, target=None), author)

    await VoicesSelfmod.ban_list.callback(VoicesSelfmod(_bot(db)), ctx)

    author.send.assert_awaited_once()
    assert ctx.send.await_args.args[0] == _BANLIST_SENT


async def test_ban_list_dm_closed(db: Database) -> None:
    author = _author(10, in_channel_id=None)
    author.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(status=403), "closed"))
    ctx = _ctx(_guild(room_channel=None, target=None), author)

    await VoicesSelfmod.ban_list.callback(VoicesSelfmod(_bot(db)), ctx)

    assert ctx.send.await_args.args[0] == _BANLIST_DM_FAIL
