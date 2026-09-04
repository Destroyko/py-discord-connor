"""MuteState: резервация за автором + последняя длительность."""

from __future__ import annotations

from connor.core.mute_state import MuteState

TARGET = 100
OWNER = 1
OTHER = 2


def test_owner_can_update_within_window() -> None:
    st = MuteState(window_seconds=60)
    st.begin(TARGET, OWNER, now=1000.0, time_str="1h")
    assert st.can_update(TARGET, OWNER, now=1030.0) is True
    assert st.can_update(TARGET, OTHER, now=1030.0) is False


def test_window_lifts_after_60s_for_anyone() -> None:
    st = MuteState(window_seconds=60)
    st.begin(TARGET, OWNER, now=1000.0, time_str="1h")
    assert st.can_update(TARGET, OTHER, now=1060.0) is True


def test_window_not_extended_by_updates() -> None:
    st = MuteState(window_seconds=60)
    st.begin(TARGET, OWNER, now=1000.0, time_str="1h")
    st.record_update(TARGET, time_str="2h")  # премут владельцем
    # окно всё ещё отсчитывается от 1000, не от момента премута
    assert st.can_update(TARGET, OTHER, now=1055.0) is False
    assert st.can_update(TARGET, OTHER, now=1061.0) is True


def test_last_time_tracks_updates() -> None:
    st = MuteState()
    st.begin(TARGET, OWNER, now=0.0, time_str="1h")
    assert st.last_time(TARGET) == "1h"
    st.record_update(TARGET, time_str="30m")
    assert st.last_time(TARGET) == "30m"


def test_end_clears_cycle() -> None:
    st = MuteState()
    st.begin(TARGET, OWNER, now=0.0, time_str="1h")
    st.end(TARGET)
    assert st.can_update(TARGET, OTHER, now=1.0) is True
    assert st.last_time(TARGET) is None


def test_no_cycle_allows_update() -> None:
    st = MuteState()
    assert st.can_update(TARGET, OTHER, now=123.0) is True
    assert st.last_time(TARGET) is None


def test_orphan_update_has_no_owner_and_expired_window() -> None:
    st = MuteState(window_seconds=60)
    st.record_update(TARGET, time_str="1h")  # цикла не было (напр. рестарт посреди мьюта)
    assert st.last_time(TARGET) == "1h"
    assert st.can_update(TARGET, OTHER, now=100.0) is True
