"""P4.2b/P4.4/P4.5 — ког voices_xp: сверка реестра, тик начисления, недельная
перевыдача роли «Душа компании»."""

from __future__ import annotations

from time import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from connor.cogs.voices_xp import _CYCLE_DONE, _PREV_NOT_FOUND, VoicesXp
from connor.db import Database
from connor.db.repo_voice_rooms import RepoVoiceRooms
from connor.db.repo_voice_xp import RepoVoiceXp, VoiceCycle

_DUSHA_ROLE_ID = 3
_BOT_KOMANDY_ID = 11
_FLUDISLAVL_ID = 12
_TRIGGER_ID = 300
_RODDOM_ID = 100
_WEEK = 100


def _voices_cfg() -> SimpleNamespace:
    return SimpleNamespace(
        points_mic_muted=8,
        points_active=10,
        points_stream_bonus=5,
        tick_interval_seconds=60,
        week_seconds=_WEEK,
    )


def _bot(db: Database, *, bot_komandy=None, fludislavl=None) -> SimpleNamespace:
    channels = {_BOT_KOMANDY_ID: bot_komandy, _FLUDISLAVL_ID: fludislavl}
    return SimpleNamespace(
        db=db,
        config=SimpleNamespace(
            guild_id=1,
            roles={"DUSHA": _DUSHA_ROLE_ID},
            channels={
                "BOT_KOMANDY": _BOT_KOMANDY_ID,
                "FLUDISLAVL": _FLUDISLAVL_ID,
                "TRIGGER_VOICE": _TRIGGER_ID,
            },
            categories={"RODDOM": _RODDOM_ID},
            voices=_voices_cfg(),
        ),
        get_channel=lambda cid: channels.get(cid),
    )


def _member(uid: int, *, roles=()) -> MagicMock:
    m = MagicMock(spec=discord.Member)
    m.id = uid
    m.mention = f"<@{uid}>"
    m.bot = False
    m.roles = list(roles)
    m.add_roles = AsyncMock()
    m.remove_roles = AsyncMock()
    return m


def _voice_member(uid: int, **flags: bool) -> MagicMock:
    m = _member(uid)
    m.voice = SimpleNamespace(
        self_deaf=flags.get("self_deaf", False),
        deaf=flags.get("deaf", False),
        self_mute=flags.get("self_mute", False),
        mute=flags.get("mute", False),
        self_stream=flags.get("self_stream", False),
        self_video=flags.get("self_video", False),
    )
    return m


def _vc(cid: int, *, category_id: int | None, members: list) -> SimpleNamespace:
    return SimpleNamespace(id=cid, category_id=category_id, members=members)


def _guild(
    *, voice_channels=(), afk_channel=None, members: dict | None = None, role=None
) -> SimpleNamespace:
    members = members or {}
    return SimpleNamespace(
        voice_channels=list(voice_channels),
        afk_channel=afk_channel,
        get_channel=lambda _cid: None,
        get_member=lambda uid: members.get(uid),
        fetch_member=AsyncMock(side_effect=discord.NotFound(MagicMock(status=404), "no")),
        get_role=lambda _i: role,
    )


# --- P4.2b сверка реестра --------------------------------------------------------


async def test_reconcile_removes_row_for_missing_channel(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=999, created_at=1)
    cog = VoicesXp(_bot(db))

    await cog._reconcile_rooms(_guild())

    assert await RepoVoiceRooms(db).get_by_owner(10) is None


async def test_reconcile_deletes_room_empty_for_full_grace(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=999, created_at=1)
    room_ch = SimpleNamespace(id=999, members=[], delete=AsyncMock())
    guild = SimpleNamespace(get_channel=lambda cid: room_ch if cid == 999 else None)
    cog = VoicesXp(_bot(db))

    await cog._reconcile_rooms(guild)  # первый тик — только зафиксировали пустоту
    room_ch.delete.assert_not_awaited()
    assert await RepoVoiceRooms(db).get_by_owner(10) is not None

    # промотать «пусто с» назад за пределы grace и прогнать ещё тик
    cog._empty_since[999] -= cog.bot.config.voices.tick_interval_seconds
    await cog._reconcile_rooms(guild)

    room_ch.delete.assert_awaited_once()
    assert await RepoVoiceRooms(db).get_by_owner(10) is None


async def test_reconcile_keeps_empty_room_seen_only_once(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=999, created_at=1)
    room_ch = SimpleNamespace(id=999, members=[], delete=AsyncMock())
    guild = SimpleNamespace(get_channel=lambda cid: room_ch if cid == 999 else None)
    cog = VoicesXp(_bot(db))

    await cog._reconcile_rooms(guild)

    room_ch.delete.assert_not_awaited()
    assert await RepoVoiceRooms(db).get_by_owner(10) is not None
    assert 999 in cog._empty_since


async def test_reconcile_forgets_room_that_refilled(db: Database) -> None:
    await RepoVoiceRooms(db).upsert(owner_id=10, channel_id=999, created_at=1)
    room_ch = SimpleNamespace(id=999, members=[], delete=AsyncMock())
    guild = SimpleNamespace(get_channel=lambda cid: room_ch if cid == 999 else None)
    cog = VoicesXp(_bot(db))

    await cog._reconcile_rooms(guild)  # увидели пустой
    room_ch.members = [object()]  # кто-то зашёл
    await cog._reconcile_rooms(guild)

    assert 999 not in cog._empty_since
    room_ch.delete.assert_not_awaited()


# --- P4.4 тик начисления --------------------------------------------------------


async def test_accrue_writes_batch(db: Database) -> None:
    vc = _vc(5, category_id=42, members=[_voice_member(1), _voice_member(2, self_mute=True)])
    guild = _guild(voice_channels=[vc])
    cog = VoicesXp(_bot(db))

    await cog._accrue(guild)

    assert await RepoVoiceXp(db).standings() == [(1, 10), (2, 8)]


async def test_accrue_skips_excluded_channels(db: Database) -> None:
    afk = SimpleNamespace(id=200)
    counted = _vc(5, category_id=42, members=[_voice_member(1), _voice_member(2)])
    guild = _guild(
        voice_channels=[
            counted,
            _vc(
                _RODDOM_ID + 1, category_id=_RODDOM_ID, members=[_voice_member(3), _voice_member(4)]
            ),
            _vc(200, category_id=None, members=[_voice_member(5), _voice_member(6)]),
            _vc(_TRIGGER_ID, category_id=None, members=[_voice_member(7), _voice_member(8)]),
        ],
        afk_channel=afk,
    )
    cog = VoicesXp(_bot(db))

    await cog._accrue(guild)

    assert {uid for uid, _ in await RepoVoiceXp(db).standings()} == {1, 2}


# --- P4.5 недельная перевыдача -------------------------------------------------


async def test_weekly_reassigns_and_resets(db: Database) -> None:
    xp = RepoVoiceXp(db)
    await xp.add_points({1: 50, 2: 30})
    await xp.ensure_cycle(1000)

    role = MagicMock(spec=discord.Role)
    prev = _member(9, roles=[role])
    winner = _member(1)
    bot_komandy, fludislavl = SimpleNamespace(send=AsyncMock()), SimpleNamespace(send=AsyncMock())
    guild = _guild(members={1: winner, 2: _member(2), 9: prev}, role=role)
    cog = VoicesXp(_bot(db, bot_komandy=bot_komandy, fludislavl=fludislavl))

    await cog._run_weekly(guild, VoiceCycle(anchor_ts=1000, current_dusha_id=9), now=1100)

    prev.remove_roles.assert_awaited_once()
    winner.add_roles.assert_awaited_once()
    assert "разница со вторым местом составила 20 экспы" in fludislavl.send.await_args.args[0]
    assert bot_komandy.send.await_args.args[0] == _CYCLE_DONE
    assert await xp.standings() == []
    cycle = await xp.get_cycle()
    assert cycle.current_dusha_id == 1 and cycle.anchor_ts == 1100


async def test_weekly_recurring_winner_reconfirms_role_without_flicker(db: Database) -> None:
    # тот же человек снова лидер: снятие роли НЕ вызывается (не опираемся на
    # устаревший кэш ролей после remove), но add_roles подтверждает роль
    xp = RepoVoiceXp(db)
    await xp.add_points({1: 50, 2: 30})
    await xp.ensure_cycle(1000)

    role = MagicMock(spec=discord.Role)
    winner = _member(1, roles=[role])  # роль уже на нём
    bot_komandy, fludislavl = SimpleNamespace(send=AsyncMock()), SimpleNamespace(send=AsyncMock())
    guild = _guild(members={1: winner, 2: _member(2)}, role=role)
    cog = VoicesXp(_bot(db, bot_komandy=bot_komandy, fludislavl=fludislavl))

    await cog._run_weekly(guild, VoiceCycle(anchor_ts=1000, current_dusha_id=1), now=1100)

    winner.remove_roles.assert_not_awaited()  # без снятия-и-повторной-выдачи
    winner.add_roles.assert_awaited_once()  # но роль подтверждается (идемпотентно)
    fludislavl.send.assert_awaited_once()
    assert bot_komandy.send.await_args.args[0] == _CYCLE_DONE
    assert (await xp.get_cycle()).current_dusha_id == 1


async def test_weekly_winner_left_descends_to_next(db: Database) -> None:
    xp = RepoVoiceXp(db)
    await xp.add_points({1: 50, 2: 30})
    await xp.ensure_cycle(1000)

    role = MagicMock(spec=discord.Role)
    second = _member(2)
    bot_komandy, fludislavl = SimpleNamespace(send=AsyncMock()), SimpleNamespace(send=AsyncMock())
    guild = _guild(members={2: second}, role=role)  # id 1 не резолвится
    cog = VoicesXp(_bot(db, bot_komandy=bot_komandy, fludislavl=fludislavl))

    await cog._run_weekly(guild, VoiceCycle(anchor_ts=1000, current_dusha_id=None), now=1100)

    second.add_roles.assert_awaited_once()
    assert "составила 0 экспы" in fludislavl.send.await_args.args[0]
    assert (await xp.get_cycle()).current_dusha_id == 2


async def test_weekly_nobody_scored_leaves_role(db: Database) -> None:
    xp = RepoVoiceXp(db)
    await xp.ensure_cycle(1000)
    bot_komandy, fludislavl = SimpleNamespace(send=AsyncMock()), SimpleNamespace(send=AsyncMock())
    guild = _guild(members={}, role=MagicMock(spec=discord.Role))
    cog = VoicesXp(_bot(db, bot_komandy=bot_komandy, fludislavl=fludislavl))

    await cog._run_weekly(guild, VoiceCycle(anchor_ts=1000, current_dusha_id=7), now=1100)

    fludislavl.send.assert_not_awaited()  # #флудиславль молчит
    bot_komandy.send.assert_awaited_once_with(_CYCLE_DONE)
    cycle = await xp.get_cycle()
    assert cycle.current_dusha_id == 7 and cycle.anchor_ts == 1100  # роль не тронута, цикл закрыт


async def test_weekly_prev_holder_gone_warns_but_grants(db: Database) -> None:
    xp = RepoVoiceXp(db)
    await xp.add_points({1: 50})
    await xp.ensure_cycle(1000)

    role = MagicMock(spec=discord.Role)
    winner = _member(1)
    bot_komandy, fludislavl = SimpleNamespace(send=AsyncMock()), SimpleNamespace(send=AsyncMock())
    guild = _guild(members={1: winner}, role=role)  # прежний обладатель 9 не резолвится
    cog = VoicesXp(_bot(db, bot_komandy=bot_komandy, fludislavl=fludislavl))

    await cog._run_weekly(guild, VoiceCycle(anchor_ts=1000, current_dusha_id=9), now=1100)

    sent = [c.args[0] for c in bot_komandy.send.await_args_list]
    assert _PREV_NOT_FOUND in sent and _CYCLE_DONE in sent
    winner.add_roles.assert_awaited_once()


async def test_maybe_weekly_noop_when_not_expired(db: Database) -> None:
    xp = RepoVoiceXp(db)
    await xp.ensure_cycle(int(time()))  # только что — цикл не истёк
    bot_komandy = SimpleNamespace(send=AsyncMock())
    cog = VoicesXp(_bot(db, bot_komandy=bot_komandy))

    await cog._maybe_weekly(_guild(role=MagicMock(spec=discord.Role)))

    bot_komandy.send.assert_not_awaited()


# --- P1.0a: исключение в итерации не убивает tasks.loop -------------------------


async def test_tick_iteration_swallows_exception(db: Database) -> None:
    cog = VoicesXp(_bot(db))
    cog._accrue = AsyncMock(side_effect=RuntimeError("тик рухнул"))
    guild = _guild(role=MagicMock(spec=discord.Role))
    cog.bot.get_guild = lambda _i: guild
    await cog.xp.ensure_cycle(int(time()))

    # тело итерации завёрнуто в try/except — не должно пробросить наружу
    await VoicesXp.tick.coro(cog)
