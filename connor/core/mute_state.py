"""Состояние активных мьютов в памяти — резервация за автором + последняя выданная
длительность (см. ``mute.md`` § "Резервация после наложения мута").

Только в памяти: рестарт переживать не обязано (по истечении окна резервация в
любом случае теряет смысл). Персистентного хранилища у мьюта нет — источник истины
Discord timeout + роль «Молчун».

Запись живёт весь цикл мьюта (не только 60 c): ``last_time`` нужен для embed
«перемьючен с <old> на <new>» и после того, как окно резервации закрылось.
"""

from __future__ import annotations

from dataclasses import dataclass

RESERVATION_WINDOW_SECONDS = 60


@dataclass(slots=True)
class _Cycle:
    owner_id: int
    first_applied_at: float  # монотонное время первого наложения текущего цикла
    last_time: str  # последняя выданная длительность как её ввели («24h»)


class MuteState:
    def __init__(self, *, window_seconds: int = RESERVATION_WINDOW_SECONDS) -> None:
        self._window = window_seconds
        self._cycles: dict[int, _Cycle] = {}

    def begin(self, target_id: int, owner_id: int, now: float, time_str: str) -> None:
        """Новый цикл мьюта (первое наложение на не-замьюченного)."""
        self._cycles[target_id] = _Cycle(
            owner_id=owner_id, first_applied_at=now, last_time=time_str
        )

    def record_update(self, target_id: int, time_str: str) -> None:
        """Обновление («премут»): владелец и точка отсчёта окна не меняются,
        запоминаем новую длительность. Если цикла нет — заводим осиротевший
        (напр. рестарт посреди мьюта): владелец неизвестен, окно уже истекло."""
        cycle = self._cycles.get(target_id)
        if cycle is None:
            self._cycles[target_id] = _Cycle(owner_id=0, first_applied_at=0.0, last_time=time_str)
        else:
            cycle.last_time = time_str

    def can_update(self, target_id: int, mod_id: int, now: float) -> bool:
        """Может ли этот модератор сейчас обновить мьют цели.

        Да, если: цикла нет / окно резервации истекло / модератор — владелец окна.
        """
        cycle = self._cycles.get(target_id)
        if cycle is None:
            return True
        if now - cycle.first_applied_at >= self._window:
            return True
        return mod_id == cycle.owner_id

    def last_time(self, target_id: int) -> str | None:
        cycle = self._cycles.get(target_id)
        return cycle.last_time if cycle is not None else None

    def end(self, target_id: int) -> None:
        """Цикл мьюта закончился (``/unmute`` или замечено истечение таймаута)."""
        self._cycles.pop(target_id, None)
