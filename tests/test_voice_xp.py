"""P4.4 — тик начисления опыта: отбор каналов и начисление за тик (чистая логика)."""

from __future__ import annotations

from types import SimpleNamespace

from connor.core.voice_xp import VoiceMemberState, accrue_tick, is_counted_channel

_CFG = SimpleNamespace(points_mic_muted=8, points_active=10, points_stream_bonus=5)

_RODDOM = 100
_AFK = 200
_TRIGGER = 300


def _counted(
    *, channel_id: int = 1, category_id: int | None = None, is_stage: bool = False
) -> bool:
    return is_counted_channel(
        channel_id=channel_id,
        category_id=category_id,
        is_stage=is_stage,
        roddom_category_id=_RODDOM,
        afk_channel_id=_AFK,
        trigger_channel_id=_TRIGGER,
    )


# --- is_counted_channel ---------------------------------------------------------


def test_normal_channel_counted() -> None:
    assert _counted(channel_id=5, category_id=42) is True


def test_roddom_category_excluded() -> None:
    assert _counted(channel_id=5, category_id=_RODDOM) is False


def test_afk_channel_excluded() -> None:
    assert _counted(channel_id=_AFK) is False


def test_trigger_channel_excluded() -> None:
    assert _counted(channel_id=_TRIGGER) is False


def test_stage_channel_excluded() -> None:
    assert _counted(channel_id=5, is_stage=True) is False


def test_no_afk_configured_is_fine() -> None:
    assert (
        is_counted_channel(
            channel_id=7,
            category_id=None,
            is_stage=False,
            roddom_category_id=_RODDOM,
            afk_channel_id=None,
            trigger_channel_id=_TRIGGER,
        )
        is True
    )


# --- accrue_tick --------------------------------------------------------------


def _m(uid: int, *, bot: bool = False, deaf: bool = False, mic: bool = False, stream: bool = False):
    return VoiceMemberState(user_id=uid, is_bot=bot, deaf=deaf, mic_muted=mic, streaming=stream)


def test_alone_gets_nothing() -> None:
    assert accrue_tick([_m(1)], _CFG) == {}


def test_alone_streaming_still_nothing() -> None:
    assert accrue_tick([_m(1, stream=True)], _CFG) == {}


def test_two_active_each_plus_ten() -> None:
    assert accrue_tick([_m(1), _m(2)], _CFG) == {1: 10, 2: 10}


def test_mic_muted_plus_eight() -> None:
    assert accrue_tick([_m(1, mic=True), _m(2)], _CFG) == {1: 8, 2: 10}


def test_server_and_self_mute_same_as_mic_muted() -> None:
    # серверный мут приходит в mic_muted так же, как self-mute
    assert accrue_tick([_m(1, mic=True), _m(2, mic=True)], _CFG) == {1: 8, 2: 8}


def test_stream_bonus_added_once() -> None:
    assert accrue_tick([_m(1, stream=True), _m(2)], _CFG) == {1: 15, 2: 10}


def test_mic_muted_plus_stream() -> None:
    assert accrue_tick([_m(1, mic=True, stream=True), _m(2)], _CFG) == {1: 13, 2: 10}


def test_deaf_member_excluded_and_not_a_neighbour() -> None:
    # активный + заглушённый → у активного нет учтённых соседей → +0
    assert accrue_tick([_m(1), _m(2, deaf=True)], _CFG) == {}


def test_bot_excluded_and_not_a_neighbour() -> None:
    assert accrue_tick([_m(1), _m(2, bot=True)], _CFG) == {}


def test_three_with_two_deaf() -> None:
    # 1 активный + 2 заглушённых → активный один среди не исключённых → +0
    assert accrue_tick([_m(1), _m(2, deaf=True), _m(3, deaf=True)], _CFG) == {}


def test_deaf_plus_two_active() -> None:
    assert accrue_tick([_m(1), _m(2), _m(3, deaf=True)], _CFG) == {1: 10, 2: 10}
