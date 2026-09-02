"""P4.1/P4.2 — приватные комнаты: создание по триггеру, неудачный перенос,
повторный вход, удаление опустевшей, реактивный блок забаненного."""

from __future__ import annotations

from time import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from connor.cogs.voices_rooms import VoicesRooms
from connor.db import Database
from connor.db.repo_voice_banlist import RepoVoiceBanlist
from connor.db.repo_voice_rooms import RepoVoiceRooms

_TRIGGER_ID = 300
_CATEGORY_ID = 101
_NEW_ROOM_ID = 555


def _http_exc(status: int = 400) -> discord.HTTPException:
    return discord.HTTPException(MagicMock(status=status, reason="x"), "boom")


def _voices_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        room_bitrate=64000,
        room_user_limit=0,
        room_nsfw=False,
        room_slowmode=0,
        banlist_active_window_hours=24,
    )


def _bot(db: Database) -> SimpleNamespace:
    return SimpleNamespace(
        db=db,
        config=SimpleNamespace(
            guild_id=1,
            channels={"TRIGGER_VOICE": _TRIGGER_ID},
            categories={"PRIVATE_VOICE": _CATEGORY_ID},
            voices=_voices_cfg(),
        ),
    )


def _new_channel() -> SimpleNamespace:
    return SimpleNamespace(
        id=_NEW_ROOM_ID,
        delete=AsyncMock(),
        set_permissions=AsyncMock(),
        overwrites_for=lambda _m: discord.PermissionOverwrite(),
    )


def _category(new_channel: object) -> MagicMock:
    cat = MagicMock(spec=discord.CategoryChannel)
    cat.create_voice_channel = AsyncMock(return_value=new_channel)
    return cat


def _guild(extra: dict | None = None) -> SimpleNamespace:
    channels = dict(extra or {})

    def get_channel(cid: int) -> object:
        return channels.get(cid)

    g = SimpleNamespace(get_channel=get_channel, _channels=channels)
    return g


def _member(uid: int, guild: object, *, name: str = "alice") -> MagicMock:
    m = MagicMock(spec=discord.Member)
    m.id = uid
    m.name = name
    m.guild = guild
    m.move_to = AsyncMock()
    return m


def _vs(channel: object) -> SimpleNamespace:
    return SimpleNamespace(channel=channel)


async def _event(cog: VoicesRooms, member: object, before: object, after: object) -> None:
    await VoicesRooms.on_voice_state_update(cog, member, before, after)


# --- создание ----------------------------------------------------------------------


async def test_trigger_creates_and_registers_room(db: Database) -> None:
    new_channel = _new_channel()
    category = _category(new_channel)
    guild = _guild({_CATEGORY_ID: category})
    member = _member(10, guild)
    cog = VoicesRooms(_bot(db))

    await _event(cog, member, _vs(None), _vs(SimpleNamespace(id=_TRIGGER_ID)))

    category.create_voice_channel.assert_awaited_once()
    kwargs = category.create_voice_channel.await_args.kwargs
    assert kwargs["name"] == "alice"
    assert kwargs["bitrate"] == 64000
    assert member in kwargs["overwrites"]
    member.move_to.assert_awaited_once()
    room = await RepoVoiceRooms(db).get_by_owner(10)
    assert room is not None and room.channel_id == _NEW_ROOM_ID


async def test_trigger_move_fail_deletes_channel(db: Database) -> None:
    new_channel = _new_channel()
    category = _category(new_channel)
    guild = _guild({_CATEGORY_ID: category})
    member = _member(10, guild)
    member.move_to = AsyncMock(side_effect=_http_exc())
    cog = VoicesRooms(_bot(db))

    await _event(cog, member, _vs(None), _vs(SimpleNamespace(id=_TRIGGER_ID)))

    new_channel.delete.assert_awaited_once()
    assert await RepoVoiceRooms(db).get_by_owner(10) is None


async def test_trigger_with_live_room_moves_there(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=999, created_at=1)
    existing = SimpleNamespace(id=999)
    category = _category(_new_channel())
    guild = _guild({_CATEGORY_ID: category, 999: existing})
    member = _member(10, guild)
    cog = VoicesRooms(_bot(db))

    await _event(cog, member, _vs(None), _vs(SimpleNamespace(id=_TRIGGER_ID)))

    member.move_to.assert_awaited_once_with(existing, reason="повторный вход в триггер")
    category.create_voice_channel.assert_not_awaited()


async def test_owner_alone_reentering_trigger_keeps_room(db: Database) -> None:
    # владелец один в своей комнате заходит в триггер: его возвращают обратно,
    # комнату НЕ удаляют (кэш ещё показывает её пустой после «ухода»)
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_NEW_ROOM_ID, created_at=1)
    room_ch = SimpleNamespace(id=_NEW_ROOM_ID, members=[], delete=AsyncMock())
    category = _category(_new_channel())
    guild = _guild({_CATEGORY_ID: category, _NEW_ROOM_ID: room_ch})
    member = _member(10, guild)
    cog = VoicesRooms(_bot(db))

    await _event(cog, member, _vs(room_ch), _vs(SimpleNamespace(id=_TRIGGER_ID)))

    member.move_to.assert_awaited_once_with(room_ch, reason="повторный вход в триггер")
    room_ch.delete.assert_not_awaited()
    category.create_voice_channel.assert_not_awaited()
    assert await RepoVoiceRooms(db).get_by_owner(10) is not None


async def test_trigger_with_stale_registry_creates_new(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=999, created_at=1)
    new_channel = _new_channel()
    category = _category(new_channel)
    guild = _guild({_CATEGORY_ID: category})  # id 999 не резолвится — комната закрыта
    member = _member(10, guild)
    cog = VoicesRooms(_bot(db))

    await _event(cog, member, _vs(None), _vs(SimpleNamespace(id=_TRIGGER_ID)))

    category.create_voice_channel.assert_awaited_once()
    room = await RepoVoiceRooms(db).get_by_owner(10)
    assert room.channel_id == _NEW_ROOM_ID


async def test_active_bans_transferred_on_create(db: Database) -> None:
    now = int(time())
    await RepoVoiceBanlist(db).upsert(owner_id=10, banned_id=20, ts=now)  # активна
    await RepoVoiceBanlist(db).upsert(owner_id=10, banned_id=21, ts=1)  # старая
    new_channel = _new_channel()
    category = _category(new_channel)
    guild = _guild({_CATEGORY_ID: category})
    member = _member(10, guild)
    cog = VoicesRooms(_bot(db))

    await _event(cog, member, _vs(None), _vs(SimpleNamespace(id=_TRIGGER_ID)))

    overwrites = category.create_voice_channel.await_args.kwargs["overwrites"]
    target_ids = {t.id for t in overwrites}
    assert 20 in target_ids  # активная запись перенесена
    assert 21 not in target_ids  # старая — нет
    assert member.id in target_ids  # владелец


# --- жизненный цикл --------------------------------------------------------------


async def test_empty_room_deleted_on_last_leave(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_NEW_ROOM_ID, created_at=1)
    room_ch = SimpleNamespace(id=_NEW_ROOM_ID, members=[], delete=AsyncMock())
    guild = _guild()
    member = _member(10, guild)
    cog = VoicesRooms(_bot(db))

    await _event(cog, member, _vs(room_ch), _vs(None))

    room_ch.delete.assert_awaited_once()
    assert await RepoVoiceRooms(db).get_by_owner(10) is None


async def test_room_with_guests_survives(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=_NEW_ROOM_ID, created_at=1)
    guest = SimpleNamespace(id=77)
    room_ch = SimpleNamespace(id=_NEW_ROOM_ID, members=[guest], delete=AsyncMock())
    guild = _guild()
    member = _member(10, guild)
    cog = VoicesRooms(_bot(db))

    await _event(cog, member, _vs(room_ch), _vs(None))

    room_ch.delete.assert_not_awaited()
    assert await RepoVoiceRooms(db).get_by_owner(10) is not None


async def test_reactive_block_for_banned_joiner(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=99, channel_id=_NEW_ROOM_ID, created_at=1)
    await RepoVoiceBanlist(db).upsert(owner_id=99, banned_id=10, ts=1)  # старая запись
    room_ch = SimpleNamespace(
        id=_NEW_ROOM_ID,
        members=[],
        overwrites_for=lambda _m: discord.PermissionOverwrite(),
        set_permissions=AsyncMock(),
    )
    guild = _guild()
    member = _member(10, guild)
    cog = VoicesRooms(_bot(db))

    await _event(cog, member, _vs(None), _vs(room_ch))

    member.move_to.assert_awaited_once()
    assert member.move_to.await_args.args == (None,)
    room_ch.set_permissions.assert_awaited_once()
    # ts «самоисцелился» — запись обновлена на свежую
    assert [b.ts for b in await RepoVoiceBanlist(db).list_for(99)] != [1]


async def test_non_banned_joiner_ignored(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=99, channel_id=_NEW_ROOM_ID, created_at=1)
    room_ch = SimpleNamespace(id=_NEW_ROOM_ID, members=[], set_permissions=AsyncMock())
    guild = _guild()
    member = _member(10, guild)
    cog = VoicesRooms(_bot(db))

    await _event(cog, member, _vs(None), _vs(room_ch))

    member.move_to.assert_not_awaited()
    room_ch.set_permissions.assert_not_awaited()
