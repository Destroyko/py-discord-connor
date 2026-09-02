"""Bootstrap бота (см. IMPLEMENTATION_PLAN.md P0.5).

``ConnorBot`` — ``commands.Bot`` под один сервер:

- intents: default + Guild Members + Message Content + Voice States;
- член-кэш частичный (``MemberCacheFlags(voice=True, joined=False)``,
  ``chunk_guilds_at_startup=False``) — следствия см. P1.0d;
- ``allowed_mentions`` по умолчанию — ничего не пингуем; места, где пинг нужен
  (перевыдача «Души компании», ``@here`` в roleGiver), передают override явно;
- все команды регистрируются guild-scoped на ``GUILD_ID`` (мгновенный синк);
- коги грузятся в ``setup_hook`` из списка ``COGS`` (пополняется по мере готовности
  модулей, P2+).

Полная стартовая диагностика (preflight) подключается в ``on_ready`` в P1.7 —
сейчас здесь только проверка «бот в нужной гильдии».
"""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from connor.config import Config
from connor.core.permissions import CommandPermissionsCache

log = logging.getLogger(__name__)

#: Пути когов для ``load_extension``. Пусто на P0.5 — каждый модуль добавляет себя
#: в своей фазе (P2: cogs.moderation_chat / cogs.purge / cogs.ban_kick / cogs.mute; и т.д.).
COGS: tuple[str, ...] = ()


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
        #: реплика Command Permissions для !-пути (создаётся в setup_hook)
        self.command_perms: CommandPermissionsCache | None = None

    async def setup_hook(self) -> None:
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
        guild = self.get_guild(self.config.guild_id)
        if guild is None:
            log.error(
                "бот не состоит в гильдии из .env (GUILD_ID=%d) — полная диагностика в P1.7",
                self.config.guild_id,
            )
        else:
            log.info("гильдия: %s (%d)", guild.name, guild.id)


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
    return 0
