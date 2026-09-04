"""Проверка иерархии ролей и самомодерации (см. ``rules.md`` § "Роли и права",
§ "Самомодерация").

Обе функции — **чистые**: на входе примитивы / маленький dataclass, никаких
``discord.Member``/``discord.Guild`` (``development.md`` § "Тестирование").
Текст отказа выбирает вызывающая команда — здесь только решение + причина (для лога).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class HierarchyBlock(Enum):
    """Результат проверки иерархии. ``OK`` — можно наказывать; остальное — причина
    отказа (пользователю все три ветки отвечают ОДНИМ текстом команды, см. ниже)."""

    OK = "ok"
    TARGET_IS_OWNER = "target_is_owner"  # цель — владелец гильдии
    TARGET_IS_BOT = "target_is_bot"  # цель — бот
    ROLE_NOT_LOWER = "role_not_lower"  # топовая роль цели >= топовой роли инициатора


@dataclass(frozen=True, slots=True)
class HierarchyInput:
    initiator_top_role_pos: int
    target_top_role_pos: int
    target_is_bot: bool
    target_id: int
    guild_owner_id: int


def check_hierarchy(data: HierarchyInput) -> HierarchyBlock:
    """Может ли инициатор применить наказание (мут/бан/кик/снятие роли) к цели?

    Порядок веток задаёт лишь то, какую причину увидим в логе; пользователю при
    любой из них команда отвечает своим единым текстом ("…старших или эквивалентных
    по роли или ботов"), для владельца гильдии отдельного текста нет
    (``rules.md`` § "Роли и права").

    Проверка ``target_id == guild_owner_id`` — **явная и первая**: у владельца может
    не быть спец-роли вообще, тогда сравнение позиций его не защитит, а Discord API
    всё равно откажет — на падение API не полагаемся.
    """
    if data.target_id == data.guild_owner_id:
        return HierarchyBlock.TARGET_IS_OWNER
    if data.target_is_bot:
        return HierarchyBlock.TARGET_IS_BOT
    if data.target_top_role_pos >= data.initiator_top_role_pos:
        return HierarchyBlock.ROLE_NOT_LOWER
    return HierarchyBlock.OK


def is_self_moderation(initiator_id: int, target_id: int) -> bool:
    """Цель — сам инициатор команды.

    Отдельное правило от иерархии (``rules.md`` § "Самомодерация"): для
    ``/mute``/``/ban``/``/kick`` при ``True`` команда отвечает ``Что ты делаешь?``.
    Для ``/unmute``/``/unban`` эта проверка не вызывается — случай покрывается сам.
    """
    return initiator_id == target_id
