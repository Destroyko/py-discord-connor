"""Разрешение канала → категория, общее для нескольких модулей.

Модераторская категория «роддом» исключается сразу в moderationChat и purge
(``moderationChat.md`` § "Общие правила фильтрации", ``purge.md`` § "Ограничение
по каналам") — сравнение по ``channel.category_id`` с ID из ``.env``, без
перечисления конкретных каналов. У треда прямого ``category_id`` нет — берём у
родительского канала.
"""

from __future__ import annotations


def in_roddom(channel: object, roddom_category_id: int) -> bool:
    """Канал (или его родитель для тредов) лежит в категории «роддом»."""
    category_id = getattr(channel, "category_id", None)
    if category_id is None:
        parent = getattr(channel, "parent", None)
        category_id = getattr(parent, "category_id", None)
    return category_id == roddom_category_id
