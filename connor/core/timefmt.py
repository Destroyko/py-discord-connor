"""Форматирование дат (MSK) и разбор длительности мьюта.

**Даты.** Все текстовые (не Discord-нативные) даты бот выводит в MSK (UTC+3),
фиксированно, независимо от таймзоны VPS (``environment.md`` § "Технический стек").
Два формата из спеки:

- ``fmt_full``        → ``16-08-2026 18:49:30`` (тире, 4-зн. год) — ``anti.md`` "Дата добавления";
- ``fmt_full_minute`` → ``16-08-2026 18:49``    (без секунд) — футер embed'ов ``anti.md``;
- ``fmt_short``       → ``13.12.25 19:21:36``   (точки, 2-зн. год) — ``roleGiver.md``
  "Дата регистрации" / "Дата присоединения".

**Длительность мьюта.** Один число + один суффикс ``s/m/h/d``; диапазон 60s..28d
(жёсткий потолок Discord timeout). Составной (``1h30m``) и дробный (``1.5h``) —
ошибка (``mute.md`` § "Логика работы").
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

MSK = timezone(timedelta(hours=3))

MUTE_MIN_SECONDS = 60
MUTE_MAX_SECONDS = 28 * 24 * 60 * 60  # 2_419_200

_DURATION_RE = re.compile(r"\A(\d+)([smhd])\Z")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400}


# --------------------------------------------------------------------------- #
# Даты
# --------------------------------------------------------------------------- #


def _to_msk(value: datetime | int | float) -> datetime:
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    else:
        dt = datetime.fromtimestamp(value, tz=UTC)
    return dt.astimezone(MSK)


def fmt_full(value: datetime | int | float) -> str:
    """``16-08-2026 18:49:30`` (MSK)."""
    return _to_msk(value).strftime("%d-%m-%Y %H:%M:%S")


def fmt_full_minute(value: datetime | int | float) -> str:
    """``16-08-2026 18:49`` (MSK, без секунд)."""
    return _to_msk(value).strftime("%d-%m-%Y %H:%M")


def fmt_short(value: datetime | int | float) -> str:
    """``13.12.25 19:21:36`` (MSK)."""
    return _to_msk(value).strftime("%d.%m.%y %H:%M:%S")


def format_hms(total_seconds: int) -> str:
    """``4д 3ч 12м`` — грубая длительность (аптайм, остаток таймаута)."""
    total_seconds = max(0, total_seconds)
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return f"{days}д {hours}ч {minutes}м"


# --------------------------------------------------------------------------- #
# Длительность мьюта
# --------------------------------------------------------------------------- #


def parse_duration(text: str) -> int:
    """``"<число><s|m|h|d>"`` → секунды.

    ``ValueError``: составной (``1h30m``), дробный (``1.5h``), пустой, без суффикса,
    неизвестный суффикс, отрицательный.
    """
    match = _DURATION_RE.match(text.strip()) if text else None
    if match is None:
        raise ValueError(f"неверный формат длительности: {text!r}")
    return int(match.group(1)) * _UNIT_SECONDS[match.group(2)]


def parse_mute_duration(text: str) -> int:
    """``parse_duration`` + проверка диапазона 60s..28d.

    ``ValueError`` и на формат, и на выход за границы — команда отвечает одним и тем
    же ``Время указано некорректно`` в обоих случаях (``mute.md``).
    """
    seconds = parse_duration(text)
    if not (MUTE_MIN_SECONDS <= seconds <= MUTE_MAX_SECONDS):
        raise ValueError(f"длительность вне диапазона 60s..28d: {text!r} ({seconds}s)")
    return seconds
