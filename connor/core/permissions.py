"""Реплика Discord Command Permissions на префиксный (``!``) путь.

Discord фильтрует по этому слою только slash-вызовы. Для ``!команда`` бот обязан
проверять те же ограничения сам (``rules.md`` § "Роли и права",
``development.md`` § "Command Permissions API").

Здесь — **чистая** часть: разбор ответа API в структуры и резолв «можно ли вызвать»
по тому же приоритету, что у Discord::

    канал (disable абсолютен) → оверрайд по user → оверрайды по ролям (allow > deny)
    → @everyone → default_member_permissions команды

``CommandPermissionsCache`` держит разобранную конфигурацию, грузит её живым GET на
старте и обновляет по gateway-событию ``on_raw_app_command_permissions_update``.
Пока кэш не прогружен — ``allows()`` возвращает ``False`` для всего (fail closed).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

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


# --------------------------------------------------------------------------- #
# Рантайм-кэш
# --------------------------------------------------------------------------- #


class _PermsHTTP(Protocol):
    async def get_guild_application_command_permissions(
        self, application_id: int, guild_id: int
    ) -> list[dict]: ...


class CommandPermissionsCache:
    """Разобранные Command Permissions гильдии + карта имя команды → id.

    ``load`` — живой GET на старте; ``apply_update`` — по gateway-событию.
    ``allows`` fail-closed: пока не прогружено (или сброшено ``invalidate``) — ``False``.
    """

    def __init__(self, *, application_id: int, guild_id: int) -> None:
        self._application_id = application_id
        self._guild_id = guild_id
        self._resolved: ResolvedPermissions | None = None
        self._name_to_id: dict[str, int] = {}

    @property
    def ready(self) -> bool:
        return self._resolved is not None

    def known_command_names(self) -> frozenset[str]:
        """Имена команд, которые есть в синкнутом дереве (для которых имеет смысл
        консультироваться с этим кэшем). Префикс-only команды сюда не попадают."""
        return frozenset(self._name_to_id)

    async def load(self, http: _PermsHTTP, *, command_ids: dict[str, int]) -> None:
        raw = await http.get_guild_application_command_permissions(
            self._application_id, self._guild_id
        )
        self._name_to_id = dict(command_ids)
        self._resolved = parse_guild_command_permissions(
            list(raw), application_id=self._application_id
        )

    def invalidate(self) -> None:
        self._resolved = None

    def apply_update(self, *, target_id: int, overwrites: list[tuple[int, int, bool]]) -> None:
        """Обновить одну команду (или app-level дефолт, если ``target_id`` == app id).

        ``overwrites``: список ``(id, type_value, permission)``; ``type_value`` —
        1 роль / 2 user / 3 канал. Пустой список = оверрайды сняты → команда
        выпадает из ``per_command`` (падает на app-level дефолт).
        """
        if self._resolved is None:
            return  # прилетит при следующем load

        if target_id == self._application_id:
            app_default = (
                CommandPerms.from_overwrites(_as_dicts(overwrites)) if overwrites else None
            )
            self._resolved = ResolvedPermissions(self._resolved.per_command, app_default)
            return

        per_command = dict(self._resolved.per_command)
        if overwrites:
            per_command[target_id] = CommandPerms.from_overwrites(_as_dicts(overwrites))
        else:
            per_command.pop(target_id, None)
        self._resolved = ResolvedPermissions(per_command, self._resolved.app_default)

    def allows(
        self,
        *,
        command_name: str,
        member_role_ids: frozenset[int],
        member_id: int,
        channel_id: int,
        has_default_perms: bool,
    ) -> bool:
        if self._resolved is None:
            return False  # fail closed
        command_id = self._name_to_id.get(command_name)
        perms = (
            self._resolved.for_command(command_id)
            if command_id is not None
            else self._resolved.app_default
        )
        return can_run_prefix(
            perms=perms,
            member_role_ids=member_role_ids,
            member_id=member_id,
            channel_id=channel_id,
            guild_id=self._guild_id,
            has_default_perms=has_default_perms,
        )


def _as_dicts(overwrites: list[tuple[int, int, bool]]) -> list[dict]:
    return [{"id": i, "type": t, "permission": p} for i, t, p in overwrites]
