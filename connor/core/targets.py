"""Разбор аргумента ``target`` (см. ``mute.md``, ``banKick.md``, ``anti.md``).

Чистая часть — вытащить id из строки (``123`` или ``<@123>``/``<@!123>``). Резолв
в участника/пользователя и проверку присутствия на сервере делает вызывающая
команда (нужны ``discord.*`` объекты). Reply на сообщение как способ указать цель
**не поддерживается** — команда просто не смотрит на reply.
"""

from __future__ import annotations

import re

#: Общие тексты для трёх модулей (mute / banKick / anti). Уникальные — у команды локально.
ERR_NO_TARGET = "Укажите пользователя или id"
ERR_TARGET_ABSENT = (
    "Укажите пользователя или id. Также возможно пользователь уже отсутствует на сервере"
)

_MENTION_RE = re.compile(r"\A<@!?(\d+)>\Z")  # только user-mention; <@&…> (роль), <#…> (канал) — нет
_RAW_RE = re.compile(r"\A(\d+)\Z")
_MAX_SNOWFLAKE = 2**63 - 1


def parse_target_id(raw: str | None) -> int | None:
    """``"123"`` или ``"<@123>"`` / ``"<@!123>"`` → id.

    ``None`` для пустой строки, мусора, role/channel-mention и значений вне диапазона
    Discord snowflake (``0 < id ≤ 2^63-1``).
    """
    if not raw:
        return None
    match = _MENTION_RE.match(raw.strip()) or _RAW_RE.match(raw.strip())
    if match is None:
        return None
    value = int(match.group(1))
    if not (0 < value <= _MAX_SNOWFLAKE):
        return None
    return value
