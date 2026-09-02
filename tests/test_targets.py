"""P1.3 — разбор target."""

from __future__ import annotations

import pytest

from connor.core.targets import parse_target_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("569878391927341056", 569878391927341056),
        ("<@569878391927341056>", 569878391927341056),
        ("<@!569878391927341056>", 569878391927341056),
        ("  <@!42>  ", 42),
        ("1", 1),
        (str(2**63 - 1), 2**63 - 1),
    ],
)
def test_valid(raw: str, expected: int) -> None:
    assert parse_target_id(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "abc",
        "12abc",
        "<@&42>",  # роль-mention
        "<#42>",  # канал-mention
        "<@42> hi",  # хвост после mention
        "42 43",
        "0",
        "-5",
        str(2**63),  # вне диапазона snowflake
        "@enteii",  # текстовое имя, не id/mention
    ],
)
def test_invalid_returns_none(raw: str | None) -> None:
    assert parse_target_id(raw) is None
