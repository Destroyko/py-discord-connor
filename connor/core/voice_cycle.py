"""Чистая логика недельного цикла «Души компании» (см. ``Voices.md`` §
"Перевыдача и недельный цикл").

Ког (``voices_xp.py``) хранит точку отсчёта в БД, резолвит участников через REST и
шлёт уведомления; здесь — только арифметика: истёк ли цикл, куда сдвинуть якорь,
кто победитель и какова разница со вторым местом.
"""

from __future__ import annotations


def is_cycle_expired(*, now: int, anchor_ts: int, week_seconds: int) -> bool:
    """``now - anchor >= неделя`` — пора делать перевыдачу."""
    return now - anchor_ts >= week_seconds


def next_anchor(*, now: int, anchor_ts: int, week_seconds: int) -> int:
    """Новая точка отсчёта после перевыдачи.

    Сдвигается на **целое** число прошедших циклов сразу за ``now`` — чтобы после
    одной перевыдачи цикл перестал считаться истёкшим, сколько бы бот ни лежал
    (догон ровно одной пропущенной перевыдачи, дальше — обычная недельная
    каденция по той же фазовой сетке). При штатной работе прошёл ровно 1 цикл и
    сдвиг равен одной неделе.
    """
    elapsed = now - anchor_ts
    if elapsed < week_seconds:
        return anchor_ts
    return anchor_ts + (elapsed // week_seconds) * week_seconds


def pick_winner(standings: list[tuple[int, int]], present: set[int]) -> tuple[int | None, int]:
    """``(id победителя | None, разница со вторым местом)``.

    ``standings`` — ``[(user_id, points), ...]``, уже упорядоченный выборкой из БД
    (``points DESC, seq ASC``). Победитель — первая строка, чей ``user_id`` есть в
    ``present`` (спуск по списку до присутствующего на сервере). Разница считается
    относительно позиции победителя: его очки минус очки следующей строки списка
    (0, если победитель — последняя строка или список пуст / никого нет на сервере).
    """
    for idx, (user_id, points) in enumerate(standings):
        if user_id in present:
            if idx + 1 < len(standings):
                return user_id, points - standings[idx + 1][1]
            return user_id, 0  # победитель — последняя строка: второго места нет
    return None, 0
