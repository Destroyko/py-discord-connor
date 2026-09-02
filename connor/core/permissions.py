"""Реплика Discord Command Permissions на префиксный (``!``) путь.

Discord фильтрует по этому слою только slash-вызовы. Для ``!команда`` бот обязан
проверять те же ограничения сам (``rules.md`` § "Роли и права",
``development.md`` § "Command Permissions API").

Здесь — **чистая** часть: разбор ответа API в структуры и резолв «можно ли вызвать»
по тому же приоритету, что у Discord::

    канал (disable абсолютен) → оверрайд по user → оверрайды по ролям (allow > deny)
    → @everyone → default_member_permissions команды

Загрузка с API, кэш и обновление по gateway-событию — ``CommandPermissionsCache``
(P1.5b), не тестируется юнитами.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# discord ApplicationCommandPermissionType
_TYPE_ROLE = 1
_TYPE_USER = 2
_TYPE_CHANNEL = 3


@dataclass(frozen=True, slots=True)
class CommandPerms:
    """Оверрайды прав одной команды (или app-level дефолта «все команды»).

    В ``role`` ключ, равный ``guild_id``, — это ``@everyone``.
    В ``channel`` ключ, равный ``guild_id - 1``, — это «все каналы».
    """

    user: dict[int, bool] = field(default_factory=dict)
    role: dict[int, bool] = field(default_factory=dict)
    channel: dict[int, bool] = field(default_factory=dict)

    @classmethod
    def from_overwrites(cls, overwrites: list[dict]) -> CommandPerms:
        user: dict[int, bool] = {}
        role: dict[int, bool] = {}
        channel: dict[int, bool] = {}
        buckets = {_TYPE_ROLE: role, _TYPE_USER: user, _TYPE_CHANNEL: channel}
        for ow in overwrites:
            bucket = buckets.get(ow["type"])
            if bucket is not None:
                bucket[int(ow["id"])] = bool(ow["permission"])
        return cls(user=user, role=role, channel=channel)


@dataclass(frozen=True, slots=True)
class ResolvedPermissions:
    """Вся конфигурация Command Permissions гильдии: по командам + app-level дефолт."""

    per_command: dict[int, CommandPerms]
    app_default: CommandPerms | None

    def for_command(self, command_id: int) -> CommandPerms | None:
        """Оверрайды конкретной команды, иначе app-level дефолт, иначе ``None``."""
        return self.per_command.get(command_id, self.app_default)


def parse_guild_command_permissions(raw: list[dict], *, application_id: int) -> ResolvedPermissions:
    """Ответ ``GET /applications/{app}/guilds/{guild}/commands/permissions`` → структуры.

    Запись с ``id == application_id`` — это app-level дефолт «все команды».
    """
    per_command: dict[int, CommandPerms] = {}
    app_default: CommandPerms | None = None
    for entry in raw:
        perms = CommandPerms.from_overwrites(entry.get("permissions", []))
        if int(entry["id"]) == application_id:
            app_default = perms
        else:
            per_command[int(entry["id"])] = perms
    return ResolvedPermissions(per_command=per_command, app_default=app_default)


def _channel_enabled(perms: CommandPerms, channel_id: int, guild_id: int) -> bool:
    if channel_id in perms.channel:
        return perms.channel[channel_id]
    all_channels = guild_id - 1
    if all_channels in perms.channel:
        return perms.channel[all_channels]
    return True


def _member_allowed(
    perms: CommandPerms,
    member_role_ids: frozenset[int],
    member_id: int,
    guild_id: int,
    has_default_perms: bool,
) -> bool:
    if member_id in perms.user:
        return perms.user[member_id]

    applicable = [perms.role[rid] for rid in ({guild_id, *member_role_ids}) if rid in perms.role]
    if any(applicable):  # хотя бы один allow — allow побеждает deny
        return True
    if applicable:  # были только deny
        return False
    return has_default_perms  # ролевых оверрайдов нет → default_member_permissions


def can_run_prefix(
    *,
    perms: CommandPerms | None,
    member_role_ids: frozenset[int],
    member_id: int,
    channel_id: int,
    guild_id: int,
    has_default_perms: bool,
) -> bool:
    """Разрешён ли ``!``-вызов команды этим участником в этом канале.

    ``perms`` — оверрайды команды (``ResolvedPermissions.for_command(...)``); ``None``
    означает «оверрайдов нет вообще» → решает только ``has_default_perms``
    (удовлетворяет ли участник ``default_member_permissions`` команды — считает
    вызывающий по ``channel.permissions_for(member)``, с учётом Administrator).
    """
    if perms is None:
        return has_default_perms
    if not _channel_enabled(perms, channel_id, guild_id):
        return False
    return _member_allowed(perms, member_role_ids, member_id, guild_id, has_default_perms)
