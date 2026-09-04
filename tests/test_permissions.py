"""P1.5a — разбор Command Permissions и приоритет резолва для !-пути."""

from __future__ import annotations

from connor.core.permissions import (
    CommandPermissionsCache,
    CommandPerms,
    can_run_prefix,
    parse_guild_command_permissions,
)

GUILD = 1000
APP = 5000
EVERYONE = GUILD  # id роли @everyone == id гильдии
ALL_CHANNELS = GUILD - 1


# --------------------------------------------------------------------------- #
# Разбор
# --------------------------------------------------------------------------- #


def test_parse_routes_types_and_detects_app_default() -> None:
    raw = [
        {
            "id": str(APP),
            "permissions": [{"id": str(EVERYONE), "type": 1, "permission": False}],
        },
        {
            "id": "777",
            "permissions": [
                {"id": "10", "type": 1, "permission": True},  # роль
                {"id": "20", "type": 2, "permission": False},  # user
                {"id": "30", "type": 3, "permission": True},  # канал
            ],
        },
    ]

    resolved = parse_guild_command_permissions(raw, application_id=APP)

    assert set(resolved.per_command) == {777}
    assert resolved.app_default is not None
    assert resolved.app_default.role == {EVERYONE: False}
    cmd = resolved.per_command[777]
    assert cmd.role == {10: True}
    assert cmd.user == {20: False}
    assert cmd.channel == {30: True}


def test_for_command_falls_back_to_app_default() -> None:
    resolved = parse_guild_command_permissions(
        [{"id": str(APP), "permissions": [{"id": "9", "type": 2, "permission": True}]}],
        application_id=APP,
    )
    assert resolved.for_command(777) is resolved.app_default
    assert resolved.for_command(777).user == {9: True}


# --------------------------------------------------------------------------- #
# Приоритет
# --------------------------------------------------------------------------- #


def _run(
    perms: CommandPerms | None,
    *,
    roles: frozenset[int] = frozenset(),
    member: int = 1,
    channel: int = 42,
    default: bool = False,
) -> bool:
    return can_run_prefix(
        perms=perms,
        member_role_ids=roles,
        member_id=member,
        channel_id=channel,
        guild_id=GUILD,
        has_default_perms=default,
    )


def test_no_overrides_uses_default_member_permissions() -> None:
    assert _run(None, default=True) is True
    assert _run(None, default=False) is False


def test_channel_disable_is_absolute() -> None:
    perms = CommandPerms(user={1: True}, channel={42: False})
    assert _run(perms, member=1, channel=42) is False  # даже при user=allow


def test_all_channels_disable() -> None:
    perms = CommandPerms(user={1: True}, channel={ALL_CHANNELS: False})
    assert _run(perms, member=1, channel=42) is False


def test_all_channels_disable_but_this_channel_reenabled() -> None:
    perms = CommandPerms(user={1: True}, channel={ALL_CHANNELS: False, 42: True})
    assert _run(perms, member=1, channel=42) is True


def test_single_channel_allow_without_sentinel_denies_other_channels() -> None:
    """Реальные данные Discord: одна запись ``{канал: True}`` без sentinel'а
    ``ALL_CHANNELS`` — это тоже белый список, не "разрешено везде плюс этот
    канал". Discord прячет slash-команду везде, кроме перечисленных каналов,
    даже без явного ``ALL_CHANNELS: False``."""
    perms = CommandPerms(channel={42: True})
    assert _run(perms, channel=42, default=True) is True
    assert _run(perms, channel=99, default=True) is False


def test_no_channel_overrides_at_all_does_not_restrict() -> None:
    perms = CommandPerms(role={10: True})
    assert _run(perms, channel=99, default=False) is False  # role/default решает, не канал
    assert _run(perms, roles=frozenset({10}), channel=99, default=False) is True


def test_user_allow_overrides_everything() -> None:
    perms = CommandPerms(user={1: True}, role={10: False})
    assert _run(perms, roles=frozenset({10}), member=1, default=False) is True


def test_user_deny_overrides_role_allow() -> None:
    perms = CommandPerms(user={1: False}, role={10: True})
    assert _run(perms, roles=frozenset({10}), member=1, default=True) is False


def test_role_allow_wins_over_role_deny() -> None:
    perms = CommandPerms(role={10: True, 20: False})
    assert _run(perms, roles=frozenset({10, 20}), default=False) is True


def test_role_deny_only() -> None:
    perms = CommandPerms(role={10: False})
    assert _run(perms, roles=frozenset({10}), default=True) is False


def test_everyone_role_allow() -> None:
    perms = CommandPerms(role={EVERYONE: True})
    assert _run(perms, roles=frozenset(), default=False) is True


def test_no_matching_role_falls_to_default() -> None:
    perms = CommandPerms(role={99: True})  # у участника такой роли нет
    assert _run(perms, roles=frozenset({7}), default=True) is True
    assert _run(perms, roles=frozenset({7}), default=False) is False


def test_channel_enabled_then_member_check() -> None:
    perms = CommandPerms(role={10: True}, channel={42: True})
    assert _run(perms, roles=frozenset({10}), channel=42) is True
    assert _run(perms, roles=frozenset({8}), channel=42, default=False) is False


# --------------------------------------------------------------------------- #
# CommandPermissionsCache
# --------------------------------------------------------------------------- #


class _FakeHTTP:
    def __init__(self, raw: list[dict]) -> None:
        self._raw = raw

    async def get_guild_application_command_permissions(
        self, application_id: int, guild_id: int
    ) -> list[dict]:
        return self._raw


def _allows(
    cache: CommandPermissionsCache,
    *,
    name: str = "mute",
    roles=frozenset(),
    member=1,
    channel=42,
    default=False,
) -> bool:
    return cache.allows(
        command_name=name,
        member_role_ids=roles,
        member_id=member,
        channel_id=channel,
        has_default_perms=default,
    )


async def _loaded_cache(raw: list[dict]) -> CommandPermissionsCache:
    cache = CommandPermissionsCache(application_id=APP, guild_id=GUILD)
    await cache.load(_FakeHTTP(raw), command_ids={"mute": 777, "ban": 888})
    return cache


async def test_cache_not_ready_is_fail_closed() -> None:
    cache = CommandPermissionsCache(application_id=APP, guild_id=GUILD)
    assert cache.ready is False
    assert _allows(cache, default=True) is False  # даже если участник прошёл бы по default


async def test_cache_load_and_lookup_by_name() -> None:
    cache = await _loaded_cache(
        [{"id": "777", "permissions": [{"id": "10", "type": 1, "permission": True}]}]
    )
    assert cache.ready is True
    assert _allows(cache, name="mute", roles=frozenset({10})) is True
    assert _allows(cache, name="mute", roles=frozenset({99}), default=False) is False


async def test_cache_unknown_command_uses_app_default() -> None:
    cache = await _loaded_cache(
        [{"id": str(APP), "permissions": [{"id": str(EVERYONE), "type": 1, "permission": True}]}]
    )
    assert _allows(cache, name="ladder") is True  # нет в name_to_id -> app_default (everyone allow)


async def test_cache_apply_update_adds_command() -> None:
    cache = await _loaded_cache([])
    assert _allows(cache, name="mute", roles=frozenset({10}), default=False) is False
    cache.apply_update(target_id=777, overwrites=[(10, 1, True)])
    assert _allows(cache, name="mute", roles=frozenset({10}), default=False) is True


async def test_cache_apply_update_clear_falls_back_to_app_default() -> None:
    cache = await _loaded_cache(
        [
            {
                "id": str(APP),
                "permissions": [{"id": str(EVERYONE), "type": 1, "permission": False}],
            },
            {"id": "777", "permissions": [{"id": "10", "type": 1, "permission": True}]},
        ]
    )
    assert _allows(cache, name="mute", roles=frozenset({10})) is True
    cache.apply_update(target_id=777, overwrites=[])  # сняли все оверрайды команды
    assert _allows(cache, name="mute", roles=frozenset({10})) is False  # теперь app_default (deny)


async def test_cache_apply_update_app_level() -> None:
    cache = await _loaded_cache([])
    assert _allows(cache, name="ladder", default=False) is False
    cache.apply_update(target_id=APP, overwrites=[(EVERYONE, 1, True)])
    assert _allows(cache, name="ladder", default=False) is True


async def test_cache_apply_update_before_load_is_noop() -> None:
    cache = CommandPermissionsCache(application_id=APP, guild_id=GUILD)
    cache.apply_update(target_id=777, overwrites=[(10, 1, True)])
    assert cache.ready is False


async def test_cache_invalidate_reverts_to_fail_closed() -> None:
    cache = await _loaded_cache(
        [{"id": "777", "permissions": [{"id": "10", "type": 1, "permission": True}]}]
    )
    cache.invalidate()
    assert cache.ready is False
    assert _allows(cache, name="mute", roles=frozenset({10})) is False
