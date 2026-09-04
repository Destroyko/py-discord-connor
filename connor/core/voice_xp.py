"""Чистая логика минутного тика начисления опыта (см. ``Voices.md`` § "Начисление
опыта", ``development.md`` § "Тик начисления опыта").

Ког (``voices_xp.py``) отвечает только за сбор войс-стейтов из локального кэша и
батч-запись; вся арифметика «кому сколько очков за тик» — здесь, на примитивах.

Два предиката:

- ``is_counted_channel`` — входит ли войс-канал в область подсчёта (исключаются
  категория «роддом», AFK-канал, канал-триггер, Stage-каналы);
- ``accrue_tick`` — сколько очков получает каждый участник канала на этом тике.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


class _PointsConfig(Protocol):
    points_mic_muted: int
    points_active: int
    points_stream_bonus: int


@dataclass(frozen=True, slots=True)
class VoiceMemberState:
    """Свёрнутый войс-стейт одного участника канала (то, что нужно для начисления).

    ``deaf`` — self-deaf ИЛИ server-deaf; ``mic_muted`` — self-mute ИЛИ server-mute
    (серверный мут трактуется как self-mute, ``development.md``); ``streaming`` —
    демонстрация экрана ИЛИ включённая вебка.
    """

    user_id: int
    is_bot: bool
    deaf: bool
    mic_muted: bool
    streaming: bool


def is_counted_channel(
    *,
    channel_id: int,
    category_id: int | None,
    is_stage: bool,
    roddom_category_id: int,
    afk_channel_id: int | None,
    trigger_channel_id: int,
) -> bool:
    """Входит ли войс-канал в область подсчёта опыта.

    Исключаются: Stage-каналы; канал-триггер «создать свою комнату»; AFK-канал
    гильдии; любой канал внутри модераторской категории «роддом» (по
    ``category_id``, без перечисления конкретных каналов).
    """
    if is_stage:
        return False
    if channel_id == trigger_channel_id:
        return False
    if afk_channel_id is not None and channel_id == afk_channel_id:
        return False
    if category_id is not None and category_id == roddom_category_id:
        return False
    return True


def accrue_tick(members: Sequence[VoiceMemberState], cfg: _PointsConfig) -> dict[int, int]:
    """``{user_id: очки}`` за один тик — только для участников с ненулевым приростом.

    Участник **полностью исключён** (сам 0 и не «сосед» для других), если он бот
    или заглушён (deaf). Не исключённый получает очки, только если в канале есть
    хотя бы один другой не исключённый участник:

    - мут микрофона (без deaf) → ``points_mic_muted`` (+8);
    - без мута → ``points_active`` (+10);
    - плюс разовый ``points_stream_bonus`` (+5), если стримит/включил вебку.

    Один в канале (или все соседи исключены) → пусто (даже если стримит).
    """
    active = [m for m in members if not m.is_bot and not m.deaf]
    if len(active) < 2:  # нет ни одного другого не исключённого участника
        return {}

    result: dict[int, int] = {}
    for m in active:
        gain = cfg.points_mic_muted if m.mic_muted else cfg.points_active
        if m.streaming:
            gain += cfg.points_stream_bonus
        if gain > 0:
            result[m.user_id] = gain
    return result
