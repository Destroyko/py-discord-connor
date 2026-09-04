"""Недельный цикл: истечение, сдвиг якоря, выбор победителя (чистая логика)."""

from __future__ import annotations

from connor.core.voice_cycle import is_cycle_expired, next_anchor, pick_winner

_WEEK = 100


# --- is_cycle_expired --------------------------------------------------------------


def test_not_expired_before_week() -> None:
    assert is_cycle_expired(now=99, anchor_ts=0, week_seconds=_WEEK) is False


def test_expired_exactly_at_week() -> None:
    assert is_cycle_expired(now=100, anchor_ts=0, week_seconds=_WEEK) is True


def test_expired_long_after() -> None:
    assert is_cycle_expired(now=1000, anchor_ts=0, week_seconds=_WEEK) is True


# --- next_anchor ---------------------------------------------------------------


def test_normal_shift_one_week() -> None:
    # штатная перевыдача: прошёл ровно один цикл
    assert next_anchor(now=100, anchor_ts=0, week_seconds=_WEEK) == 100


def test_shift_lands_within_current_window() -> None:
    assert next_anchor(now=150, anchor_ts=0, week_seconds=_WEEK) == 100


def test_long_offline_catches_up_once() -> None:
    # бот лежал ~10 недель — после ОДНОЙ перевыдачи цикл больше не истёкший
    new_anchor = next_anchor(now=1050, anchor_ts=0, week_seconds=_WEEK)
    assert new_anchor == 1000
    assert is_cycle_expired(now=1050, anchor_ts=new_anchor, week_seconds=_WEEK) is False


def test_not_expired_returns_anchor_unchanged() -> None:
    assert next_anchor(now=50, anchor_ts=0, week_seconds=_WEEK) == 0


# --- pick_winner -------------------------------------------------------------------


def test_empty_standings() -> None:
    assert pick_winner([], set()) == (None, 0)


def test_winner_is_top_row_margin_to_second() -> None:
    assert pick_winner([(1, 50), (2, 30), (3, 10)], {1}) == (1, 20)


def test_single_scorer_margin_zero() -> None:
    assert pick_winner([(1, 50)], {1}) == (1, 0)


def test_top_left_descends_to_next_present() -> None:
    # строка 1 (100) ушла → победитель строка 2 (60), «второе место» — строка 3 (25)
    assert pick_winner([(1, 100), (2, 60), (3, 25)], {2, 3}) == (2, 35)


def test_nobody_present_returns_none() -> None:
    assert pick_winner([(1, 100), (2, 60)], set()) == (None, 0)


def test_tie_break_keeps_list_order() -> None:
    # выборка уже упорядочена (points DESC, seq ASC); равные очки — по порядку списка
    assert pick_winner([(7, 40), (3, 40), (9, 40)], {7, 3, 9}) == (7, 0)
