"""Иерархия ролей и самомодерация."""

from __future__ import annotations

from connor.core.hierarchy import (
    HierarchyBlock,
    HierarchyInput,
    check_hierarchy,
    is_self_moderation,
)


def _inp(
    *,
    initiator: int = 10,
    target: int = 5,
    is_bot: bool = False,
    target_id: int = 111,
    owner_id: int = 999,
) -> HierarchyInput:
    return HierarchyInput(
        initiator_top_role_pos=initiator,
        target_top_role_pos=target,
        target_is_bot=is_bot,
        target_id=target_id,
        guild_owner_id=owner_id,
    )


def test_target_below_initiator_is_ok() -> None:
    assert check_hierarchy(_inp(initiator=10, target=5)) is HierarchyBlock.OK


def test_equal_top_role_blocks() -> None:
    assert check_hierarchy(_inp(initiator=7, target=7)) is HierarchyBlock.ROLE_NOT_LOWER


def test_higher_top_role_blocks() -> None:
    assert check_hierarchy(_inp(initiator=3, target=9)) is HierarchyBlock.ROLE_NOT_LOWER


def test_bot_target_blocks_even_if_role_lower() -> None:
    got = check_hierarchy(_inp(initiator=10, target=1, is_bot=True))
    assert got is HierarchyBlock.TARGET_IS_BOT


def test_owner_target_blocks_even_if_role_lower() -> None:
    got = check_hierarchy(_inp(initiator=10, target=1, target_id=42, owner_id=42))
    assert got is HierarchyBlock.TARGET_IS_OWNER


def test_owner_check_wins_over_role_and_bot() -> None:
    # владелец с более высокой ролью и помеченный ботом — причина всё равно "owner"
    got = check_hierarchy(_inp(initiator=1, target=99, is_bot=True, target_id=7, owner_id=7))
    assert got is HierarchyBlock.TARGET_IS_OWNER


def test_bot_check_before_role() -> None:
    got = check_hierarchy(_inp(initiator=1, target=99, is_bot=True))
    assert got is HierarchyBlock.TARGET_IS_BOT


def test_self_moderation() -> None:
    assert is_self_moderation(123, 123) is True
    assert is_self_moderation(123, 456) is False
