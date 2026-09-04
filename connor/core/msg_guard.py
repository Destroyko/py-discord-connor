"""Единый фильтр входящих сообщений.

Любой ``on_message``-потребитель (moderationChat, реконсиляция мьюта, ленивый
запрет в «предложке», ``!kiss``, разбор префиксных команд) сначала зовёт
``should_process_message`` — так исключаются петли обратной связи и сообщения от
ботов/вебхуков.
"""

from __future__ import annotations

from typing import Protocol


class _MessageLike(Protocol):
    webhook_id: int | None

    @property
    def author(self) -> object: ...


def should_process_message(message: _MessageLike) -> bool:
    """``False`` для сообщений от ботов и вебхуков (в т.ч. самого себя).

    Проверяем и ``author.bot``, и ``webhook_id`` — у сообщения из вебхука
    (сторонние логгеры вроде MEE6) ``author.bot`` не гарантированно выставлен.
    """
    if getattr(message, "webhook_id", None) is not None:
        return False
    return not getattr(message.author, "bot", False)
