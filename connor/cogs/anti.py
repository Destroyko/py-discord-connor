"""Анти-работяга — чёрный список на самовыдачу роли «работяга» (см. ``anti.md``).

``/add`` / ``/del`` (+``!``): добавить/убрать из анти-списка, изъять/вернуть роль
«работяга», при необходимости поставить/снять точечный запрет писать в «предложку».

Наблюдение за ручными изменениями роли (``on_member_update`` + журнал аудита с
задержкой): снятие роли вручную модератором → лог в ``#антиработяги`` (как у
``/add``, но с author-модератором); выдача роли вручную анти-работяге → авто-снятие
анти-статуса + лог (как у ``/del``). Изменения, сделанные самим ботом внутри
``/add``/``/del``, watcher игнорирует (команда уже отчиталась).
"""

from __future__ import annotations

import asyncio
import logging
from time import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from connor.core.resolve import EntityResolver
from connor.core.targets import parse_target_id
from connor.core.texts import ERR_NO_TARGET, REASON_NOT_GIVEN
from connor.core.timefmt import fmt_full, fmt_full_minute
from connor.db.repo_anti import RepoAnti
from connor.db.repo_predlozhka import RepoPredlozhka
from connor.logging_setup import log_action_error
from connor.predlozhka import apply_deny, clear_deny

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_ERR_ALREADY = "Пользователь {mention} уже существует в списке антиработяг"
_ERR_NOT_IN_LIST = "Пользователь не в списке антиработяг"
_ROLE_REMOVE_FAILED = "Я не смог изъять роль так как пользователь не найден или не имеет такой роли"
_ROLE_RETURNED = "Роль возвращена"
_FOOTER = "Claptrap желает вам приятного дня"

# журнал аудита появляется в API не сразу после события (~4–5 c, см. anti.md);
# смотрим быстро, потом ретраим ~30 c
_AUDIT_FIRST_DELAY = 1
_AUDIT_RETRY_INTERVAL = 5
_AUDIT_ATTEMPTS = 7  # 1 c + 6×5 c ≈ 31 c
_MANUAL_GRANT_REASON = "роль «работяга» выдана вручную"

_ROLE_REMOVED_DESC = (
    "{mention}\n"
    "**изъяли роль**\n"
    "Работяга\n\n"
    "Подробности в журнале аудита.\n"
    "Добавить в список антиработяг можно через команду !add id/квот причина"
)


def build_add_embed(mention: str, reason: str, added_at: int) -> discord.Embed:
    embed = discord.Embed(
        description=f"Пользователь {mention} добавлен в список антиработяг",
        colour=discord.Color.red(),
    )
    embed.add_field(name="Причина", value=reason, inline=False)
    embed.add_field(name="Дата добавления", value=fmt_full(added_at), inline=False)
    embed.set_footer(text=f"{_FOOTER} • {fmt_full_minute(added_at)}")
    return embed


def build_del_embed(mention: str, reason: str) -> discord.Embed:
    embed = discord.Embed(
        description=f"Пользователь {mention} удалён из списка антиработяг",
        colour=discord.Color.green(),
    )
    embed.add_field(name="Причина", value=reason, inline=False)
    embed.set_footer(text=f"{_FOOTER} • {fmt_full_minute(int(time()))}")
    return embed


def build_role_removed_embed(
    mention: str, *, moderator: discord.abc.User | discord.Member | None = None
) -> discord.Embed:
    embed = discord.Embed(
        description=_ROLE_REMOVED_DESC.format(mention=mention), colour=discord.Color.red()
    )
    if moderator is not None:
        embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
    return embed


class Anti(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self.anti_repo = RepoAnti(bot.db)
        self.pred_repo = RepoPredlozhka(bot.db)
        self._resolver = EntityResolver(log)

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
        member = guild.get_member(target_id)
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
            await ctx.send(embed=build_role_removed_embed(mention))
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
            member = guild.get_member(target_id)
            predlozhka = self._predlozhka(guild)
            if member is not None and predlozhka is not None:
                await clear_deny(predlozhka, member, self.pred_repo)
            await ctx.send(_ERR_NOT_IN_LIST)
            return
        await self.anti_repo.remove(target_id)
        reason_text = reason or REASON_NOT_GIVEN
        member = guild.get_member(target_id)
        mention = f"<@{target_id}>"

        # снять бот-овый запрет в предложке (основной путь снятия)
        predlozhka = self._predlozhka(guild)
        if member is not None and predlozhka is not None:
            await clear_deny(predlozhka, member, self.pred_repo)

        # вернуть роль «работяга» безусловно
        role = self._rabotyaga_role(guild)
        if member is not None and role is not None and role not in member.roles:
            try:
                await member.add_roles(
                    role, reason=f"{ctx.author} ({ctx.author.id}): снят анти-статус"
                )
            except discord.HTTPException:
                log_action_error(log, "вернуть роль работяга", invoker=ctx.author, target=member)

        await ctx.send(embed=build_del_embed(mention, reason_text))
        await ctx.send(_ROLE_RETURNED)

    # -- наблюдение за ручными изменениями роли «работяга» --------------------

    @commands.Cog.listener()
    async def on_member_update(self, before: discord.Member, after: discord.Member) -> None:
        role_id = self.bot.config.roles["RABOTYAGA"]
        had = any(r.id == role_id for r in before.roles)
        has = any(r.id == role_id for r in after.roles)
        if had == has:
            return  # роль «работяга» не менялась

        granted = has
        try:
            actor = await self._await_audit_actor(after.guild, after.id, granted=granted)
            if actor is None:
                log.warning(
                    "не нашёл в журнале аудита, кто %s роль «работяга» у %s (%d)",
                    "выдал" if granted else "снял",
                    after,
                    after.id,
                )
                return
            if self.bot.user is not None and actor.id == self.bot.user.id:
                return  # изменил сам бот в рамках /add или /del — уже отчитались
            if granted:
                await self._on_manual_grant(after, actor)
            else:
                await self._on_manual_removal(after, actor)
        except Exception:
            log.exception("watcher роли «работяга»: сбой обработки для %s (%d)", after, after.id)

    async def _await_audit_actor(
        self, guild: discord.Guild, target_id: int, *, granted: bool
    ) -> discord.User | discord.Member | None:
        """Смотрим журнал аудита быстро, потом ретраим (~1 c + 5 c × ≈30 c)."""
        await asyncio.sleep(_AUDIT_FIRST_DELAY)
        for attempt in range(_AUDIT_ATTEMPTS):
            actor = await self._audit_actor(guild, target_id, granted=granted)
            if actor is not None:
                return actor
            if attempt < _AUDIT_ATTEMPTS - 1:
                await asyncio.sleep(_AUDIT_RETRY_INTERVAL)
        return None

    async def _audit_actor(
        self, guild: discord.Guild, target_id: int, *, granted: bool
    ) -> discord.User | discord.Member | None:
        role_id = self.bot.config.roles["RABOTYAGA"]
        async for entry in guild.audit_logs(
            limit=10, action=discord.AuditLogAction.member_role_update
        ):
            if entry.target is None or entry.target.id != target_id:
                continue
            side = entry.after.roles if granted else entry.before.roles
            if any(getattr(r, "id", None) == role_id for r in (side or [])):
                return entry.user
        return None

    def _antirabotyagi(self, guild: discord.Guild) -> discord.abc.Messageable | None:
        return self._resolver.channel(
            guild, self.bot.config.channels["ANTIRABOTYAGI"], "#антиработяги"
        )

    async def _on_manual_removal(
        self, member: discord.Member, actor: discord.User | discord.Member
    ) -> None:
        # публикуется независимо от анти-статуса цели
        channel = self._antirabotyagi(member.guild)
        if channel is not None:
            await channel.send(embed=build_role_removed_embed(member.mention, moderator=actor))

    async def _on_manual_grant(
        self, member: discord.Member, actor: discord.User | discord.Member
    ) -> None:
        if not await self.anti_repo.contains(member.id):
            return  # не в анти-списке — не событие для бота
        await self.anti_repo.remove(member.id)

        predlozhka = self._predlozhka(member.guild)
        if predlozhka is not None:
            await clear_deny(predlozhka, member, self.pred_repo)

        channel = self._antirabotyagi(member.guild)
        if channel is not None:
            await channel.send(embed=build_del_embed(member.mention, _MANUAL_GRANT_REASON))
            await channel.send(_ROLE_RETURNED)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Anti(bot))  # type: ignore[arg-type]
