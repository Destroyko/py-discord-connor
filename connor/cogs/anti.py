"""Анти-работяга — чёрный список на самовыдачу роли «работяга» (см. ``anti.md``).

``/add`` / ``/del`` (+``!``): добавить/убрать из анти-списка, изъять/вернуть роль
«работяга», при необходимости поставить/снять точечный запрет писать в «предложку».
Наблюдение за ручными изменениями роли — отдельный механизм (P3.2).
"""

from __future__ import annotations

import logging
from time import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

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
_ROLE_REMOVE_FAILED = "Я не смог изъять роль так как пользователь не найден или не имеет такой роли"
_ROLE_RETURNED = "Роль возвращена"
_FOOTER = "Claptrap желает вам приятного дня"

_ROLE_REMOVED_DESC = (
    "{mention}\n"
    "**изъяли роль**\n"
    "Работяга\n\n"
    "Подробности в журнале аудита.\n"
    "Добавить в список антиработяг можно через команду !add id/квот причина"
)


def build_add_embed(mention: str, reason: str, added_at: int) -> discord.Embed:
    embed = discord.Embed(description=f"Пользователь {mention} добавлен в список антиработяг")
    embed.add_field(name="Причина", value=reason, inline=False)
    embed.add_field(name="Дата добавления", value=fmt_full(added_at), inline=False)
    embed.set_footer(text=f"{_FOOTER} • {fmt_full_minute(added_at)}")
    return embed


def build_del_embed(mention: str, reason: str) -> discord.Embed:
    embed = discord.Embed(description=f"Пользователь {mention} удалён из списка антиработяг")
    embed.add_field(name="Причина", value=reason, inline=False)
    embed.set_footer(text=f"{_FOOTER} • {fmt_full_minute(int(time()))}")
    return embed


def build_role_removed_embed(
    mention: str, *, moderator: discord.abc.User | discord.Member | None = None
) -> discord.Embed:
    embed = discord.Embed(description=_ROLE_REMOVED_DESC.format(mention=mention))
    if moderator is not None:
        embed.set_author(name=moderator.display_name, icon_url=moderator.display_avatar.url)
    return embed


class Anti(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self.anti_repo = RepoAnti(bot.db)
        self.pred_repo = RepoPredlozhka(bot.db)

    # -- helpers -----------------------------------------------------------------

    def _rabotyaga_role(self, guild: discord.Guild) -> discord.Role | None:
        return guild.get_role(self.bot.config.roles["RABOTYAGA"])

    def _predlozhka(self, guild: discord.Guild) -> discord.abc.GuildChannel | None:
        return guild.get_channel(self.bot.config.channels["PREDLOZHKA"])

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

        await self.anti_repo.remove(target_id)  # no-op, если записи не было
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Anti(bot))  # type: ignore[arg-type]
