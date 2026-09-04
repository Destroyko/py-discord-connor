"""Фильтр входящих сообщений."""

from __future__ import annotations

from types import SimpleNamespace

from connor.core.msg_guard import should_process_message


def _msg(*, bot: bool = False, webhook_id: int | None = None) -> SimpleNamespace:
    return SimpleNamespace(author=SimpleNamespace(bot=bot), webhook_id=webhook_id)


def test_human_message_passes() -> None:
    assert should_process_message(_msg()) is True


def test_bot_author_blocked() -> None:
    assert should_process_message(_msg(bot=True)) is False


def test_webhook_blocked_even_if_author_not_bot() -> None:
    assert should_process_message(_msg(bot=False, webhook_id=42)) is False
