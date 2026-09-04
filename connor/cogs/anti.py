"""Анти-работяга — чёрный список на самовыдачу роли «работяга» (см. ``anti.md``).

``/add`` / ``/del`` (+``!``): добавить/убрать из анти-списка, изъять/вернуть роль
«работяга», при необходимости поставить/снять точечный запрет писать в «предложку».

Наблюдение за ручными изменениями роли: периодический опрос журнала аудита (не
gateway-событие ``on_member_update`` — оно диспатчится discord.py, только если
участник уже в member-кэше; на частичном кэше это почти никогда не срабатывало,
а полный кэш неприемлем по памяти на больших гильдиях, см. environment.md).
Снятие роли вручную модератором → лог в ``#антиработяги`` (как у ``/add``, но с
author-модератором); выдача роли вручную анти-работяге → авто-снятие анти-статуса
+ лог (как у ``/del``). Изменения, сделанные самим ботом внутри ``/add``/``/del``,
watcher игнорирует (команда уже отчиталась).
"""

from __future__ import annotations

import logging
from time import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks

from connor.core.authorship import embed_author_icon, embed_author_name
from connor.core.members import fetch_member
from connor.core.resolve import EntityResolver
from connor.core.targets import parse_target_id
from connor.core.texts import ERR_NO_TARGET, REASON_NOT_GIVEN
from connor.core.timefmt import fmt_full, fmt_full_minute
from connor.db.repo_anti import RepoAnti
from connor.db.repo_anti_watcher import RepoAntiWatcher
from connor.db.repo_predlozhka import RepoPredlozhka
from connor.logging_setup import log_action_error
from connor.predlozhka import apply_deny, clear_deny

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_ERR_ALREADY = "Пользователь {mention} уже существует в списке антиработяг"
_ERR_NOT_IN_LIST = "Пользователь не в списке антиработяг"
_ROLE_REMOVE_FAILED = "Я не смог изъять роль так как пользователь не найден или не имеет такой роли"
_ROLE_RETURN_FAILED = "Я не смог вернуть роль так как пользователь не найден на сервере"
_FOOTER = "Claptrap желает вам приятного дня"

# журнал аудита появляется в API не сразу после события (~4–5 c, см. anti.md) —
# это и есть реальный потолок задержки, не интервал опроса; короче через опрос
# всё равно не получить, поэтому отдельных ретраев нет — просто короткий интервал
_POLL_INTERVAL_SECONDS = 3
_MANUAL_GRANT_REASON = "роль «работяга» выдана вручную"

_ROLE_REMOVED_DESC = "{mention}\n**изъяли роль**\nРаботяга"
_ROLE_RETURNED_DESC = "{mention}\n**вернули роль**\nРаботяга"


def build_add_embed(mention: str, reason: str, added_at: int) -> discord.Embed:
    embed = discord.Embed(
        title="Добавление",
        description=f"Пользователь {mention} добавлен в список антиработяг",
        colour=discord.Color.red(),
    )
    embed.add_field(name="Причина", value=reason, inline=False)
    embed.add_field(name="Дата добавления", value=fmt_full(added_at), inline=False)
    embed.set_footer(text=f"{_FOOTER} • {fmt_full_minute(added_at)}")
    return embed


def build_del_embed(mention: str, reason: str) -> discord.Embed:
    embed = discord.Embed(
        title="Удаление",
        description=f"Пользователь {mention} удалён из списка антиработяг",
        colour=discord.Color.green(),
    )
    embed.add_field(name="Причина", value=reason, inline=False)
    embed.set_footer(text=f"{_FOOTER} • {fmt_full_minute(int(time()))}")
    return embed


def _role_change_embed(
    description: str,
    *,
    colour: discord.Colour,
    moderator: discord.abc.User | discord.Member | None,
    target_avatar_url: str | None,
) -> discord.Embed:
    embed = discord.Embed(description=description, colour=colour)
    if moderator is not None:
        embed.set_author(name=embed_author_name(moderator), icon_url=embed_author_icon(moderator))
    if target_avatar_url:
        embed.set_thumbnail(url=target_avatar_url)
    return embed


def build_role_removed_embed(
    mention: str,
    *,
    moderator: discord.abc.User | discord.Member | None = None,
    target_avatar_url: str | None = None,
) -> discord.Embed:
    return _role_change_embed(
        _ROLE_REMOVED_DESC.format(mention=mention),
        colour=discord.Color.red(),
        moderator=moderator,
        target_avatar_url=target_avatar_url,
    )


def build_role_returned_embed(
    mention: str,
    *,
    moderator: discord.abc.User | discord.Member | None = None,
    target_avatar_url: str | None = None,
) -> discord.Embed:
    return _role_change_embed(
        _ROLE_RETURNED_DESC.format(mention=mention),
        colour=discord.Color.green(),
        moderator=moderator,
        target_avatar_url=target_avatar_url,
    )


class Anti(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self.anti_repo = RepoAnti(bot.db)
        self.pred_repo = RepoPredlozhka(bot.db)
        self.watcher_repo = RepoAntiWatcher(bot.db)
        self._resolver = EntityResolver(log)

    async def cog_load(self) -> None:
        self._poll_role_changes.start()

    async def cog_unload(self) -> None:
        self._poll_role_changes.cancel()

    # -- helpers -----------------------------------------------------------------

    def _rabotyaga_role(self, guild: discord.Guild) -> discord.Role | None:
        return self._resolver.role(guild, self.bot.config.roles["RABOTYAGA"], 'роль "работяга"')

    def _predlozhka(self, guild: discord.Guild) -> discord.abc.GuildChannel | None:
        return self._resolver.channel(guild, self.bot.config.channels["PREDLOZHKA"], "#предложка")

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingRequiredArgument) and error.param.name == "target":
            await ctx.send(ERR_NO_TARGET)

    # -- /add ------------------------------------------------------------------------

    @commands.hybrid_command(name="add", description="Добавить в список анти-работяг + изъять роль")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(target="Упоминание или id", reason="Причина (опционально)")
    async def add(self, ctx: commands.Context, target: str, *, reason: str | None = None) -> None:
        guild = ctx.guild
        assert guild is not None

        target_id = parse_target_id(target)
        if target_id is None:
            await ctx.send(ERR_NO_TARGET)
            return
        try:
            await self.bot.fetch_user(target_id)
        except discord.NotFound:
            await ctx.send(ERR_NO_TARGET)
            return

        now = int(time())
        if not await self.anti_repo.add(target_id, added_at=now, added_by=ctx.author.id):
            await ctx.send(_ERR_ALREADY.format(mention=f"<@{target_id}>"))
            return

        reason_text = reason or REASON_NOT_GIVEN
        member = await fetch_member(guild, target_id)
        mention = f"<@{target_id}>"

        # предложка: если доступ на запись уже есть (донат-роль) — сразу deny
        predlozhka = self._predlozhka(guild)
        if (
            member is not None
            and predlozhka is not None
            and predlozhka.permissions_for(member).send_messages
        ):
            await apply_deny(predlozhka, member, self.pred_repo, reason="анти-работяга")

        # роль «работяга»
        role = self._rabotyaga_role(guild)
        removed = False
        if member is not None and role is not None and role in member.roles:
            try:
                await member.remove_roles(
                    role, reason=f"{ctx.author} ({ctx.author.id}): анти-работяга"
                )
                removed = True
            except discord.HTTPException:
                log_action_error(log, "изъять роль работяга", invoker=ctx.author, target=member)

        await ctx.send(embed=build_add_embed(mention, reason_text, now))
        if removed:
            assert member is not None
            await ctx.send(
                embed=build_role_removed_embed(
                    mention, moderator=ctx.author, target_avatar_url=member.display_avatar.url
                )
            )
        else:
            await ctx.send(_ROLE_REMOVE_FAILED)

    # -- /del ------------------------------------------------------------------------

    @commands.hybrid_command(name="del", description="Убрать из списка анти-работяг + вернуть роль")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(target="Упоминание или id", reason="Причина (опционально)")
    async def del_(self, ctx: commands.Context, target: str, *, reason: str | None = None) -> None:
        guild = ctx.guild
        assert guild is not None

        target_id = parse_target_id(target)
        if target_id is None:
            await ctx.send(ERR_NO_TARGET)
            return
        try:
            await self.bot.fetch_user(target_id)
        except discord.NotFound:
            # аккаунт удалён на стороне Discord — тихо чистим запись, если она есть
            await self.anti_repo.remove(target_id)
            await ctx.send(ERR_NO_TARGET)
            return

        if not await self.anti_repo.contains(target_id):
            # записи в анти-списке нет, но бот-овый deny в «предложке» мог остаться
            # (не снялся ранее по сбою API) — на всякий случай снимаем его тут же
            member = await fetch_member(guild, target_id)
            predlozhka = self._predlozhka(guild)
            if member is not None and predlozhka is not None:
                await clear_deny(predlozhka, member, self.pred_repo)
            await ctx.send(_ERR_NOT_IN_LIST)
            return
        await self.anti_repo.remove(target_id)
        reason_text = reason or REASON_NOT_GIVEN
        member = await fetch_member(guild, target_id)
        mention = f"<@{target_id}>"

        # снять бот-овый запрет в предложке (основной путь снятия)
        predlozhka = self._predlozhka(guild)
        if member is not None and predlozhka is not None:
            await clear_deny(predlozhka, member, self.pred_repo)

        # вернуть роль «работяга» безусловно
        role = self._rabotyaga_role(guild)
        returned = False
        if member is not None and role is not None:
            if role in member.roles:
                returned = True
            else:
                try:
                    await member.add_roles(
                        role, reason=f"{ctx.author} ({ctx.author.id}): снят анти-статус"
                    )
                    returned = True
                except discord.HTTPException:
                    log_action_error(
                        log, "вернуть роль работяга", invoker=ctx.author, target=member
                    )

        await ctx.send(embed=build_del_embed(mention, reason_text))
        if returned:
            assert member is not None
            await ctx.send(
                embed=build_role_returned_embed(
                    mention, moderator=ctx.author, target_avatar_url=member.display_avatar.url
                )
            )
        else:
            await ctx.send(_ROLE_RETURN_FAILED)

    # -- наблюдение за ручными изменениями роли «работяга» (опрос audit log) -----

    @tasks.loop(seconds=_POLL_INTERVAL_SECONDS)
    async def _poll_role_changes(self) -> None:
        try:
            guild = self.bot.get_guild(self.bot.config.guild_id)
            if guild is None:
                return
            await self._poll_once(guild)
        except Exception:
            log.exception("вотчер роли «работяга»: сбой опроса audit log — цикл продолжается")

    @_poll_role_changes.before_loop
    async def _before_poll(self) -> None:
        await self.bot.wait_until_ready()

    @_poll_role_changes.error
    async def _on_poll_error(self, exc: BaseException) -> None:
        log.exception("вотчер роли «работяга»: ошибка вне тела итерации", exc_info=exc)

    async def _poll_once(self, guild: discord.Guild) -> None:
        role_id = self.bot.config.roles["RABOTYAGA"]
        cursor = await self.watcher_repo.get_cursor()

        if cursor is None:
            # первый чистый старт — не разбираем всю историю аудита, только
            # фиксируем точку отсчёта на «сейчас» (тот же принцип, что у anchor_ts
            # в voice_cycle: не годится ни задним числом реагировать на историю
            # аудита, ни требовать её отдельной ручной очистки)
            newest_id = await self._latest_entry_id(guild)
            if newest_id is not None:
                await self.watcher_repo.set_cursor(newest_id)
            return

        async for entry in guild.audit_logs(
            action=discord.AuditLogAction.member_role_update,
            after=discord.Object(id=cursor),
            oldest_first=True,
            limit=None,
        ):
            try:
                await self._handle_entry(guild, entry, role_id)
            except Exception:
                log.exception("вотчер роли «работяга»: сбой обработки записи %d", entry.id)
            await self.watcher_repo.set_cursor(entry.id)

    async def _latest_entry_id(self, guild: discord.Guild) -> int | None:
        async for entry in guild.audit_logs(limit=1):
            return entry.id
        return None

    async def _handle_entry(
        self, guild: discord.Guild, entry: discord.AuditLogEntry, role_id: int
    ) -> None:
        if self.bot.user is not None and entry.user_id == self.bot.user.id:
            return  # изменил сам бот в рамках /add или /del — уже отчитался

        target = entry.target
        if target is None:
            return
        actor = entry.user
        if actor is None:
            log.warning(
                "вотчер роли «работяга»: не нашёл автора изменения у записи %d (цель %d)",
                entry.id,
                target.id,
            )
            return

        mention = f"<@{target.id}>"
        avatar_url = getattr(getattr(target, "display_avatar", None), "url", None)
        removed_ids = {r.id for r in getattr(entry.before, "roles", [])}
        added_ids = {r.id for r in getattr(entry.after, "roles", [])}

        if role_id in removed_ids:
            await self._on_manual_removal(
                guild, mention=mention, avatar_url=avatar_url, actor=actor
            )
        if role_id in added_ids:
            await self._on_manual_grant(
                guild, target=target, mention=mention, avatar_url=avatar_url, actor=actor
            )

    def _antirabotyagi(self, guild: discord.Guild) -> discord.abc.Messageable | None:
        return self._resolver.channel(
            guild, self.bot.config.channels["ANTIRABOTYAGI"], "#антиработяги"
        )

    async def _on_manual_removal(
        self,
        guild: discord.Guild,
        *,
        mention: str,
        avatar_url: str | None,
        actor: discord.User | discord.Member,
    ) -> None:
        # публикуется независимо от анти-статуса цели
        channel = self._antirabotyagi(guild)
        if channel is not None:
            await channel.send(
                embed=build_role_removed_embed(
                    mention, moderator=actor, target_avatar_url=avatar_url
                )
            )

    async def _on_manual_grant(
        self,
        guild: discord.Guild,
        *,
        target: discord.Member | discord.User | discord.Object,
        mention: str,
        avatar_url: str | None,
        actor: discord.User | discord.Member,
    ) -> None:
        if not await self.anti_repo.contains(target.id):
            return  # не в анти-списке — не событие для бота
        await self.anti_repo.remove(target.id)

        predlozhka = self._predlozhka(guild)
        if predlozhka is not None and isinstance(target, discord.abc.User):
            await clear_deny(predlozhka, target, self.pred_repo)

        channel = self._antirabotyagi(guild)
        if channel is not None:
            await channel.send(embed=build_del_embed(mention, _MANUAL_GRANT_REASON))
            await channel.send(
                embed=build_role_returned_embed(
                    mention, moderator=actor, target_avatar_url=avatar_url
                )
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Anti(bot))  # type: ignore[arg-type]
