"""mod_stats: фильтр «активный модератор», формат строк, пагинация и сброс
страницы во view, проверка «панель — только вызвавшему», расчёт периода."""

from __future__ import annotations

import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

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


def _guild(members: dict[int, SimpleNamespace]) -> SimpleNamespace:
    return SimpleNamespace(get_member=lambda uid: members.get(uid))


# -- _since_ts ---------------------------------------------------------------------


def test_since_ts_all_time_is_zero() -> None:
    assert _since_ts("0") == 0


def test_since_ts_is_rolling_window_from_now() -> None:
    now = int(time.time())
    assert abs(_since_ts("30") - (now - 30 * 86400)) <= 2


# -- _active_moderator -----------------------------------------------------------


def test_active_moderator_filters_absent_and_powerless() -> None:
    guild = _guild({1: _mod(1, can=True), 2: _mod(2, can=False)})
    assert _active_moderator(guild, 1).id == 1
    assert _active_moderator(guild, 2) is None  # лишён прав
    assert _active_moderator(guild, 3) is None  # не на сервере


# -- ModStats._mute_rows / _give_rows ------------------------------------------


async def test_mute_rows_only_current_moderators(db: Database) -> None:
    repo = RepoMuteStats(db)
    for target, mod in ((1, 10), (2, 10), (3, 11), (4, 12)):
        await repo.record(
            target_id=target, moderator_id=mod, created_at=100, message_id=None, channel_id=None
        )
    guild = _guild({10: _mod(10, can=True), 11: _mod(11, can=False)})  # 12 отсутствует

    cog = ModStats(SimpleNamespace(db=db))
    rows = await cog._mute_rows(guild, 0)

    assert [(m.id, metric) for m, metric in rows] == [(10, "2")]


async def test_give_rows_format_total_approved_refused(db: Database) -> None:
    repo = RepoGiveStats(db)
    await repo.record(target_id=1, moderator_id=10, decided_at=100, approved=True)
    await repo.record(target_id=2, moderator_id=10, decided_at=100, approved=False)
    await repo.record(target_id=3, moderator_id=10, decided_at=100, approved=True)
    guild = _guild({10: _mod(10, can=True)})

    cog = ModStats(SimpleNamespace(db=db))
    rows = await cog._give_rows(guild, 0)

    assert [(m.id, metric) for m, metric in rows] == [(10, "3 (2/1)")]


# -- _StatsView ----------------------------------------------------------------


def _view(rows: list[tuple[SimpleNamespace, str]]) -> _StatsView:
    async def fetch(_guild: object, _since: int) -> list[tuple[SimpleNamespace, str]]:
        return rows

    return _StatsView(invoker_id=1, guild=object(), title="T", empty="Пусто", fetch=fetch)


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
    assert first[0] == "1. <@1> — 99"
    assert "стр. 1/3" in view._embed().footer.text
    assert "модераторов: 45" in view._embed().footer.text
    assert view._prev.disabled is True
    assert view._next.disabled is False


async def test_view_next_prev_moves_page_and_toggles_buttons() -> None:
    rows = [(_mod(i), str(i)) for i in range(1, 46)]
    view = _view(rows)
    await view._reload()

    interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))
    await _StatsView._next(view, interaction, None)
    assert view._page == 1
    assert view._embed().description.splitlines()[0] == "21. <@21> — 21"

    await _StatsView._next(view, interaction, None)
    assert view._page == 2 and view._next.disabled is True  # последняя страница

    await _StatsView._prev(view, interaction, None)
    assert view._page == 1 and view._next.disabled is False


async def test_view_period_change_resets_to_first_page() -> None:
    rows = [(_mod(i), str(i)) for i in range(1, 46)]
    view = _view(rows)
    await view._reload()
    view._page = 2

    select = SimpleNamespace(values=["0"], options=[SimpleNamespace(value="30", default=True)])
    interaction = SimpleNamespace(response=SimpleNamespace(edit_message=AsyncMock()))
    await _StatsView._pick_period(view, interaction, select)

    assert view._period == "0"
    assert view._page == 0
    interaction.response.edit_message.assert_awaited_once()


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
