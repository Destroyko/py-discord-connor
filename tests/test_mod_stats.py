"""mod_stats: резолв/фильтр «активный модератор» (через fetch_member + кэш),
формат строк, пагинация и сброс страницы во view, «панель — только вызвавшему»,
расчёт периода, deferred-поток ответа."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord

from connor.cogs.mod_stats import (
    _VIEW_ERROR,
    ModStats,
    _active_moderator,
    _since_ts,
    _StatsView,
)
from connor.db import Database
from connor.db.repo_give_stats import RepoGiveStats
from connor.db.repo_mute_stats import RepoMuteStats


def _mod(uid: int, *, can: bool = True) -> SimpleNamespace:
    return SimpleNamespace(
        id=uid,
        mention=f"<@{uid}>",
        guild_permissions=SimpleNamespace(moderate_members=can),
    )


def _guild(mods: dict[int, SimpleNamespace], *, cached: set[int] | None = None) -> SimpleNamespace:
    """Гильдия с частичным кэшем: по умолчанию ``get_member`` ничего не отдаёт
    (как в проде), участники резолвятся через ``fetch_member``; ``cached`` — id,
    которые всё же лежат в кэше."""
    cached = cached or set()

    async def fetch_member(uid: int) -> SimpleNamespace:
        member = mods.get(uid)
        if member is None:
            raise discord.NotFound(MagicMock(status=404), "gone")
        return member

    return SimpleNamespace(
        get_member=lambda uid: mods.get(uid) if uid in cached else None,
        fetch_member=fetch_member,
    )


# -- _since_ts ---------------------------------------------------------------------


def test_since_ts_all_time_is_zero() -> None:
    assert _since_ts("0") == 0


def test_since_ts_is_rolling_window_from_now() -> None:
    now = int(time.time())
    assert abs(_since_ts("30") - (now - 30 * 86400)) <= 2


# -- _active_moderator -----------------------------------------------------------


async def test_active_moderator_resolves_via_fetch_and_filters() -> None:
    guild = _guild({1: _mod(1, can=True), 2: _mod(2, can=False)})
    cache: dict[int, discord.Member | None] = {}

    assert (await _active_moderator(guild, 1, cache)).id == 1  # не в кэше → fetch_member
    assert await _active_moderator(guild, 2, cache) is None  # лишён прав
    assert await _active_moderator(guild, 3, cache) is None  # NotFound → выбыл


async def test_active_moderator_prefers_cache_hit() -> None:
    guild = _guild({5: _mod(5, can=True)}, cached={5})
    guild.fetch_member = AsyncMock(side_effect=AssertionError("не должен вызываться"))
    assert (await _active_moderator(guild, 5, {})).id == 5


async def test_active_moderator_caches_resolution() -> None:
    calls: list[int] = []

    async def fetch_member(uid: int) -> SimpleNamespace:
        calls.append(uid)
        return _mod(uid, can=True)

    guild = SimpleNamespace(get_member=lambda _u: None, fetch_member=fetch_member)
    cache: dict[int, discord.Member | None] = {}

    await _active_moderator(guild, 7, cache)
    await _active_moderator(guild, 7, cache)
    assert calls == [7]  # второй раз — из кэша, без обращения к API


# -- ModStats._mute_rows / _give_rows ------------------------------------------


async def test_mute_rows_only_current_moderators(db: Database) -> None:
    repo = RepoMuteStats(db)
    for target, mod in ((1, 10), (2, 10), (3, 11), (4, 12)):
        await repo.record(
            target_id=target, moderator_id=mod, created_at=100, message_id=None, channel_id=None
        )
    guild = _guild({10: _mod(10, can=True), 11: _mod(11, can=False)})  # 12 — NotFound

    cog = ModStats(SimpleNamespace(db=db))
    rows = await cog._mute_rows(guild, 0, {})

    assert [(m.id, metric) for m, metric in rows] == [(10, "2")]


async def test_give_rows_format_total_approved_refused(db: Database) -> None:
    repo = RepoGiveStats(db)
    await repo.record(target_id=1, moderator_id=10, decided_at=100, approved=True)
    await repo.record(target_id=2, moderator_id=10, decided_at=100, approved=False)
    await repo.record(target_id=3, moderator_id=10, decided_at=100, approved=True)
    guild = _guild({10: _mod(10, can=True)})

    cog = ModStats(SimpleNamespace(db=db))
    rows = await cog._give_rows(guild, 0, {})

    assert [(m.id, metric) for m, metric in rows] == [(10, "3 (2/1)")]


# -- _StatsView ----------------------------------------------------------------


def _view(rows: list[tuple[SimpleNamespace, str]]) -> _StatsView:
    async def fetch(_guild: object, _since: int, _cache: dict) -> list[tuple[SimpleNamespace, str]]:
        return rows

    return _StatsView(invoker_id=1, guild=object(), title="T", empty="Пусто", fetch=fetch)


def _component_interaction() -> SimpleNamespace:
    resp = SimpleNamespace(_done=False, edit_message=AsyncMock())

    async def defer(**_kw: object) -> None:
        resp._done = True

    resp.defer = defer
    resp.is_done = lambda: resp._done
    return SimpleNamespace(response=resp, edit_original_response=AsyncMock())


async def test_view_empty_shows_empty_text_no_footer() -> None:
    view = _view([])
    await view._reload()
    embed = view._embed()
    assert embed.description == "Пусто"
    assert embed.footer.text is None
    assert view._pages == 1
    assert view._prev.disabled and view._next.disabled


async def test_view_paginates_20_per_page() -> None:
    rows = [(_mod(i), str(100 - i)) for i in range(1, 46)]  # 45 модераторов
    view = _view(rows)
    await view._reload()

    assert view._pages == 3
    first = view._embed().description.splitlines()
    assert len(first) == 20
    assert first[0] == "1. <@1> - 99"
    assert "стр. 1/3" in view._embed().footer.text
    assert "модераторов: 45" in view._embed().footer.text
    assert view._prev.disabled is True
    assert view._next.disabled is False


async def test_view_next_prev_moves_page_and_toggles_buttons() -> None:
    rows = [(_mod(i), str(i)) for i in range(1, 46)]
    view = _view(rows)
    await view._reload()

    it = _component_interaction()
    await _StatsView._next(view, it, None)
    assert view._page == 1
    assert view._embed().description.splitlines()[0] == "21. <@21> - 21"
    it.response.edit_message.assert_awaited()  # кнопка отвечает сразу, без defer

    await _StatsView._next(view, it, None)
    assert view._page == 2 and view._next.disabled is True  # последняя страница

    await _StatsView._prev(view, it, None)
    assert view._page == 1 and view._next.disabled is False


async def test_view_period_change_defers_resets_page_and_edits() -> None:
    rows = [(_mod(i), str(i)) for i in range(1, 46)]
    view = _view(rows)
    await view._reload()
    view._page = 2

    select = SimpleNamespace(values=["0"], options=[SimpleNamespace(value="30", default=True)])
    it = _component_interaction()
    await _StatsView._pick_period(view, it, select)

    assert view._period == "0"
    assert view._page == 0
    assert it.response._done is True  # сделали defer под резолв
    it.edit_original_response.assert_awaited_once()


async def test_view_start_uses_followup_after_defer() -> None:
    view = _view([(_mod(1), "3")])
    msg = SimpleNamespace(id=99, edit=AsyncMock())
    it = SimpleNamespace(followup=SimpleNamespace(send=AsyncMock(return_value=msg)))

    await view.start(it)

    it.followup.send.assert_awaited_once()
    assert it.followup.send.await_args.kwargs["ephemeral"] is True
    assert it.followup.send.await_args.kwargs["wait"] is True
    assert view.message is msg


async def test_view_interaction_check_invoker_only() -> None:
    view = _view([])
    stranger = SimpleNamespace(
        user=SimpleNamespace(id=2),
        response=SimpleNamespace(send_message=AsyncMock()),
    )
    assert await view.interaction_check(stranger) is False
    stranger.response.send_message.assert_awaited_once()

    owner = SimpleNamespace(user=SimpleNamespace(id=1))
    assert await view.interaction_check(owner) is True


async def test_view_on_error_replies_in_russian() -> None:
    view = _view([])
    interaction = SimpleNamespace(
        response=SimpleNamespace(is_done=lambda: False, send_message=AsyncMock()),
        followup=SimpleNamespace(send=AsyncMock()),
    )
    await view.on_error(interaction, RuntimeError("boom"), object())
    assert interaction.response.send_message.await_args.args[0] == _VIEW_ERROR
    assert interaction.response.send_message.await_args.kwargs["ephemeral"] is True
