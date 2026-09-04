"""MSK-форматирование дат и разбор длительности мьюта."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from connor.core.timefmt import (
    MUTE_MAX_SECONDS,
    MUTE_MIN_SECONDS,
    fmt_full,
    fmt_full_minute,
    fmt_short,
    format_hms,
    format_remaining_coarse,
    parse_duration,
    parse_mute_duration,
)

# 2026-08-16 15:49:30 UTC == 2026-08-16 18:49:30 MSK
_INSTANT_UTC = datetime(2026, 8, 16, 15, 49, 30, tzinfo=UTC)
_EPOCH = _INSTANT_UTC.timestamp()


def test_fmt_full_msk() -> None:
    assert fmt_full(_INSTANT_UTC) == "16-08-2026 18:49:30"


def test_fmt_short_msk() -> None:
    assert fmt_short(_INSTANT_UTC) == "16.08.26 18:49:30"


def test_fmt_full_minute_msk() -> None:
    assert fmt_full_minute(_INSTANT_UTC) == "16-08-2026 18:49"


def test_fmt_accepts_epoch_int_and_float() -> None:
    assert fmt_full(int(_EPOCH)) == "16-08-2026 18:49:30"
    assert fmt_full(_EPOCH) == "16-08-2026 18:49:30"


def test_fmt_naive_datetime_treated_as_utc() -> None:
    naive = datetime(2026, 8, 16, 15, 49, 30)  # намеренно naive
    assert fmt_full(naive) == "16-08-2026 18:49:30"


def test_fmt_independent_of_input_tz() -> None:
    # тот же момент, выраженный в другой зоне — результат тот же
    other = _INSTANT_UTC.astimezone(timezone(timedelta(hours=-5)))
    assert fmt_full(other) == "16-08-2026 18:49:30"


@pytest.mark.parametrize(
    ("text", "seconds"),
    [
        ("60s", 60),
        ("1m", 60),
        ("90m", 5400),
        ("24h", 86400),
        ("28d", MUTE_MAX_SECONDS),
        ("  24h  ", 86400),
        ("0s", 0),
    ],
)
def test_parse_duration_ok(text: str, seconds: int) -> None:
    assert parse_duration(text) == seconds


@pytest.mark.parametrize(
    "text",
    ["", "   ", "10", "10x", "1h30m", "1.5h", "abc", "-5s", "h", "s10", "10 s"],
)
def test_parse_duration_bad(text: str) -> None:
    with pytest.raises(ValueError):
        parse_duration(text)


@pytest.mark.parametrize("text", ["60s", "1m", "28d", "27d"])
def test_parse_mute_duration_in_range(text: str) -> None:
    value = parse_mute_duration(text)
    assert MUTE_MIN_SECONDS <= value <= MUTE_MAX_SECONDS


@pytest.mark.parametrize("text", ["59s", "0s", "1s", "29d", "40d", "1000d"])
def test_parse_mute_duration_out_of_range(text: str) -> None:
    with pytest.raises(ValueError):
        parse_mute_duration(text)


@pytest.mark.parametrize("text", ["1h30m", "1.5h", "abc", ""])
def test_parse_mute_duration_bad_format(text: str) -> None:
    with pytest.raises(ValueError):
        parse_mute_duration(text)


def test_format_hms() -> None:
    assert format_hms(0) == "0д 0ч 0м"
    assert format_hms(59) == "0д 0ч 0м"
    assert format_hms(60) == "0д 0ч 1м"
    assert format_hms(4 * 86400 + 3 * 3600 + 12 * 60 + 5) == "4д 3ч 12м"
    assert format_hms(-10) == "0д 0ч 0м"


def test_format_remaining_coarse() -> None:
    assert format_remaining_coarse(10 * 3600 + 40 * 60) == "10ч"  # 0д 10ч 40м -> 10ч
    assert format_remaining_coarse(3 * 86400 + 5 * 3600) == "77ч"  # часы, не дни
    assert format_remaining_coarse(90 * 60) == "1ч"  # 1.5 ч -> 1ч
    assert format_remaining_coarse(45 * 60) == "45м"
    assert format_remaining_coarse(59) == "59с"
    assert format_remaining_coarse(-5) == "0с"
