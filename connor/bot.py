"""Bootstrap бота (см. IMPLEMENTATION_PLAN.md P0.5, P1.7).

``ConnorBot`` — ``commands.Bot`` под один сервер:

- intents: default + Guild Members + Message Content + Voice States;
- член-кэш частичный (``MemberCacheFlags(voice=True, joined=False)``,
  ``chunk_guilds_at_startup=False``) — следствия см. P1.0d;
- ``allowed_mentions`` по умолчанию — ничего не пингуем; места, где пинг нужен
  (перевыдача «Души компании», ``@here`` в roleGiver), передают override явно;
- все команды регистрируются guild-scoped на ``GUILD_ID`` (мгновенный синк);
- коги грузятся в ``setup_hook`` из списка ``COGS``;
- ``setup_hook`` подключает БД (прогон миграций) и грузит Command Permissions;
- ``on_ready`` один раз прогоняет ``run_preflight``; при фатальном провале
  (гильдия / intents / БД) бот останавливается с кодом выхода 1.
"""

from __future__ import annotations

import logging
import time

import discord
from discord.ext import commands

from connor.config import Config
from connor.core import preflight
from connor.core.dm_guard import is_allowed_in_dm
from connor.core.permissions import CommandPermissionsCache
from connor.db import Database

log = logging.getLogger(__name__)

#: Пути когов для ``load_extension``. Каждый модуль добавляет себя в своей фазе.
COGS: tuple[str, ...] = (
    "connor.cogs.healthcheck",
    "connor.cogs.ban_kick",
    "connor.cogs.mute",
    "connor.cogs.purge",
    "connor.cogs.moderation_chat",
    "connor.cogs.anti",
    "connor.cogs.check",
    "connor.cogs.role_giver",
    "connor.cogs.voices_rooms",
    "connor.cogs.voices_selfmod",
    "connor.cogs.voices_xp",
    "connor.cogs.voices_ladder",
    "connor.cogs.misc",
)

# --- таблицы для preflight (development.md § "Стартовая диагностика") --------

_GUILD_PERMS: tuple[tuple[str, str], ...] = (
    ("ban_members", "Ban Members"),
    ("kick_members", "Kick Members"),
    ("moderate_members", "Moderate Members"),
    ("manage_roles", "Manage Roles"),
    ("manage_channels", "Manage Channels"),
    ("manage_messages", "Manage Messages"),
    ("view_audit_log", "View Audit Log"),
    ("move_members", "Move Members"),
    ("manage_guild", "Manage Server"),
)

_VSE = (
    ("view_channel", "View"),
    ("send_messages", "Send Messages"),
    ("embed_links", "Embed Links"),
)
_VS = (("view_channel", "View"), ("send_messages", "Send Messages"))

#: config.channels-ключ → (метка, нужные права)
_CHANNEL_PERMS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    (
        "REKVESTY",
        "#реквесты-работяг",
        (*_VS, ("add_reactions", "Add Reactions"), ("mention_everyone", "Mention Everyone")),
    ),
    ("BOT_KOMANDY", "#бот-команды", _VSE),
    ("ANTIRABOTYAGI", "#антиработяги", _VSE),
    ("AUDIT", "#аудит", _VSE),
    ("VYDACHA", "#выдача-работяг", (*_VS, ("bypass_slowmode", "Bypass Slowmode"))),
    ("BANY", "#баны", _VSE),
    ("CHEKLIST", "#чек-лист", _VSE),
    ("CHEKLIST2", "#чек-лист2", _VSE),
    ("FLUDISLAVL", "#флудиславль", _VSE),
    (
        "PREDLOZHKA",
        "#предложка",
        (*_VS, ("manage_messages", "Manage Messages"), ("manage_channels", "Manage Channels")),
    ),
    (
        "TRIGGER_VOICE",
        "войс-триггер «создать свою комнату»",
        (("view_channel", "View"), ("move_members", "Move Members")),
    ),
)
#: config.categories-ключ → (метка, нужные права)
_CATEGORY_PERMS: tuple[tuple[str, str, tuple[tuple[str, str], ...]], ...] = (
    ("RODDOM", "категория «роддом»", (("view_channel", "View"),)),
    (
        "PRIVATE_VOICE",
        "категория приватных войсов",
        (
            ("view_channel", "View"),
            ("manage_channels", "Manage Channels"),
            ("move_members", "Move Members"),
        ),
    ),
)

_MANAGED_ROLES: tuple[tuple[str, str], ...] = (
    ("RABOTYAGA", "работяга"),
    ("MOLCHUN", "Молчун"),
    ("DUSHA", "Душа компании"),
)


class ConnorBot(commands.Bot):
    def __init__(self, config: Config) -> None:
        self.config = config

        intents = discord.Intents.default()
        intents.members = True
        intents.message_content = True
        intents.voice_states = True

        super().__init__(
            command_prefix="!",
            intents=intents,
            member_cache_flags=discord.MemberCacheFlags(voice=True, joined=False),
            chunk_guilds_at_startup=False,
            help_command=None,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        self._guild = discord.Object(id=config.guild_id)
        self.db = Database(config.db_path)
        #: реплика Command Permissions для !-пути (создаётся в setup_hook)
        self.command_perms: CommandPermissionsCache | None = None

        self._preflight_done = False
        self._ready_at: float | None = None
        self._exit_code = 0

        self.add_check(_dm_guard_check)
        self.add_check(_command_perms_check)

    async def on_command_error(
        self, context: commands.Context, exception: commands.CommandError
    ) -> None:
        # Молчим на неизвестную команду и на любой заблокированный вызов
        # (DM-guard, Command Permissions на !-пути) — так требует rules.md.
        # UserInputError (не хватает/битый аргумент) модули ловят сами (cog_command_error)
        # и отвечают точным текстом из спеки — глобально по нему тоже молчим.
        if isinstance(
            exception,
            commands.CommandNotFound | commands.CheckFailure | commands.UserInputError,
        ):
            return
        # Сюда попадает только неожиданное — логируем с контекстом, не голым traceback.
        log.error(
            "ошибка команды %s (вызвал %s в %s): %s",
            context.command,
            context.author,
            context.channel,
            exception,
            exc_info=exception,
        )

    async def setup_hook(self) -> None:
        await self.db.connect()  # прогон миграций; ошибка здесь = бот не поднялся (exit 1)

        for ext in COGS:
            await self.load_extension(ext)
            log.info("ког загружен: %s", ext)

        self.tree.copy_global_to(guild=self._guild)
        synced = await self.tree.sync(guild=self._guild)
        log.info(
            "slash-дерево синкнуто на гильдию %d: команд %d", self.config.guild_id, len(synced)
        )

        # Command Permissions: живой GET на старте; при неудаче !-путь с гейтом
        # остаётся закрытым (fail closed) до успешной загрузки/обновления.
        assert self.application_id is not None
        self.command_perms = CommandPermissionsCache(
            application_id=self.application_id, guild_id=self.config.guild_id
        )
        try:
            await self.command_perms.load(
                self.http, command_ids={cmd.name: cmd.id for cmd in synced}
            )
            log.info("Command Permissions загружены с API")
        except discord.HTTPException as exc:
            log.error(
                "не удалось загрузить Command Permissions на старте (%s) — "
                "гейт !-команд закрыт (fail closed) до обновления по gateway",
                exc,
            )

    async def close(self) -> None:
        await self.db.close()
        await super().close()

    async def on_raw_app_command_permissions_update(
        self, payload: discord.RawAppCommandPermissionsUpdateEvent
    ) -> None:
        if (
            self.command_perms is None
            or payload.application_id != self.application_id
            or payload.guild.id != self.config.guild_id
        ):
            return
        self.command_perms.apply_update(
            target_id=payload.target_id,
            overwrites=[(p.id, p.type.value, p.permission) for p in payload.permissions],
        )
        log.info("Command Permissions обновлены (target_id=%d)", payload.target_id)

    async def on_ready(self) -> None:
        if self.user is not None:
            log.info("вошёл как %s (%d)", self.user, self.user.id)
        if self._preflight_done:  # on_ready может прийти повторно (реконнекты) — P1.0f
            return
        self._preflight_done = True
        self._ready_at = time.monotonic()

        results = await self.run_preflight()
        for r in results:
            level = log.info if r.ok else (log.error if r.fatal else log.warning)
            level("%s", r.line)
        log.info("%s", preflight.summary_line(results))

        if preflight.any_fatal(results):
            log.error("критические проверки провалены — бот останавливается")
            self._exit_code = 1
            await self.close()

    async def run_preflight(self) -> list[preflight.CheckResult]:
        """Единый прогон стартовой диагностики (``on_ready`` и ``/healthcheck``)."""
        results: list[preflight.CheckResult] = []
        gid = self.config.guild_id
        guild = self.get_guild(gid)

        results.append(
            preflight.check_guild(
                connected_guild_id=guild.id if guild else None, expected_guild_id=gid
            )
        )
        results.append(
            preflight.check_intents(
                members=self.intents.members, message_content=self.intents.message_content
            )
        )
        results.append(await self._check_db())

        if guild is None:
            return results  # без гильдии остальное не проверить

        me = guild.me
        bot_top = me.top_role.position

        for key, label in _MANAGED_ROLES:
            rid = self.config.roles[key]
            role = guild.get_role(rid)
            results.append(
                preflight.check_managed_role(
                    role_id=rid,
                    label=label,
                    role_position=role.position if role else None,
                    bot_top_position=bot_top,
                )
            )

        gp = me.guild_permissions
        results.append(
            preflight.check_guild_permissions(
                missing=[lbl for attr, lbl in _GUILD_PERMS if not getattr(gp, attr)]
            )
        )

        for key, label, needed in _CHANNEL_PERMS:
            results.append(self._check_channel(guild, self.config.channels[key], label, needed))
        for key, label, needed in _CATEGORY_PERMS:
            results.append(self._check_channel(guild, self.config.categories[key], label, needed))

        afk = guild.afk_channel
        results.append(
            preflight.CheckResult(
                "войс",
                "AFK-канал",
                ok=True,
                detail=f"{afk.name} ({afk.id})" if afk else "в гильдии не задан",
            )
        )

        results.append(await self._check_command_permissions_api(gid))
        return results

    async def _check_db(self) -> preflight.CheckResult:
        try:
            await self.db.ping()
        except Exception as exc:  # любой сбой БД = фатально, деталь пишем в отчёт
            return preflight.check_db(ping_ok=False, error=str(exc))
        return preflight.check_db(ping_ok=True)

    def _check_channel(
        self,
        guild: discord.Guild,
        channel_id: int,
        label: str,
        needed: tuple[tuple[str, str], ...],
    ) -> preflight.CheckResult:
        channel = guild.get_channel(channel_id)
        if channel is None:
            return preflight.check_channel(
                channel_id=channel_id, label=label, exists=False, missing_perms=[]
            )
        perms = channel.permissions_for(guild.me)
        return preflight.check_channel(
            channel_id=channel_id,
            label=label,
            exists=True,
            missing_perms=[lbl for attr, lbl in needed if not getattr(perms, attr)],
        )

    async def _check_command_permissions_api(self, guild_id: int) -> preflight.CheckResult:
        try:
            await self.http.get_guild_application_command_permissions(self.application_id, guild_id)
        except discord.HTTPException as exc:
            return preflight.check_command_permissions_api(reachable=False, error=str(exc))
        return preflight.check_command_permissions_api(reachable=True)


async def _dm_guard_check(context: commands.Context) -> bool:
    """Глобальный чек: в ЛС проходят только ``!vdel`` / ``!ban_list``, остальное —
    ``CheckFailure`` (гасится в ``on_command_error`` без ответа). В гильдии — пропускаем.
    """
    if context.guild is not None:
        return True
    return bool(context.command) and is_allowed_in_dm(context.command.name)


def meets_default_permissions(
    default_perms: discord.Permissions | None, member_perms: discord.Permissions
) -> bool:
    """Удовлетворяет ли участник ``default_member_permissions`` команды в этом канале.

    ``None`` (у команды нет ограничения) → да; Administrator → да; иначе член должен
    иметь все биты ``default_perms``.
    """
    if default_perms is None:
        return True
    if member_perms.administrator:
        return True
    return member_perms.is_superset(default_perms)


async def _command_perms_check(context: commands.Context) -> bool:
    """Реплика Discord Command Permissions на префиксный путь (``rules.md`` § "Роли и права").

    Slash Discord фильтрует сам; в ЛС этот слой не действует (там — ``_dm_guard_check``).
    Для префикс-only команд (``!purge``/``!kiss``/…) — свой гейт в коге, здесь пропуск.
    Пока кэш не прогружен — fail closed.
    """
    if context.interaction is not None or context.guild is None or context.command is None:
        return True

    bot = context.bot
    if not isinstance(bot, ConnorBot) or bot.command_perms is None:
        return False  # fail closed
    name = context.command.name
    if name not in bot.command_perms.known_command_names():
        return True  # префикс-only: гейт (или его отсутствие) — в коге команды

    app_command = getattr(context.command, "app_command", None)
    default_perms = getattr(app_command, "default_permissions", None)
    member_perms = context.channel.permissions_for(context.author)

    return bot.command_perms.allows(
        command_name=name,
        member_role_ids=frozenset(r.id for r in context.author.roles),
        member_id=context.author.id,
        channel_id=context.channel.id,
        has_default_perms=meets_default_permissions(default_perms, member_perms),
    )


def run_bot(config: Config) -> int:
    """Запустить бота. Возвращает код выхода процесса."""
    bot = ConnorBot(config)
    try:
        bot.run(config.bot_token, log_handler=None)  # логирование у нас своё
    except discord.LoginFailure:
        log.error("не удалось войти: неверный BOT_TOKEN")
        return 1
    except discord.PrivilegedIntentsRequired:
        log.error(
            "не удалось подключиться: не включены privileged intents "
            "(Guild Members и/или Message Content). Включи их в Developer Portal → "
            "Bot → Privileged Gateway Intents."
        )
        return 1
    except Exception:
        log.exception("бот остановлен из-за необработанной ошибки")
        return 1
    return bot._exit_code
