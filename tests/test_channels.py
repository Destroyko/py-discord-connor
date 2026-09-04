"""core/channels — резолв категории «роддом»."""

from __future__ import annotations

from types import SimpleNamespace

from connor.core.channels import in_roddom


def test_direct_channel() -> None:
    ch = SimpleNamespace(category_id=777)
    assert in_roddom(ch, 777) is True
    assert in_roddom(ch, 111) is False


def test_thread_resolves_parent() -> None:
    thread = SimpleNamespace(category_id=None, parent=SimpleNamespace(category_id=777))
    assert in_roddom(thread, 777) is True


def test_no_category() -> None:
    assert in_roddom(SimpleNamespace(category_id=None, parent=None), 777) is False
