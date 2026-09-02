"""Бан / кик / разбан (см. ``banKick.md``).

Все три — hybrid (``/`` и ``!``), гейт ``default_member_permissions=moderate_members``
(на ``!``-пути реплицируется глобальным чеком, см. ``bot.py``). Иерархия и
самомодерация — общие утилиты. Хранилища нет (источник истины — сам Discord).

Ответ — публичный embed в канале вызова (Command Permissions ограничивают, где
именно можно вызвать: ``#бот-команды`` для кика, ``#баны`` для бана/разбана).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from connor.core.authorship import embed_author_icon, embed_author_name
from connor.core.hierarchy import (
    HierarchyBlock,
    HierarchyInput,
    check_hierarchy,
    is_self_moderation,
)
from connor.core.targets import parse_target_id
from connor.core.texts import ERR_NO_TARGET, REASON_NOT_GIVEN, SELF_MODERATION
from connor.logging_setup import log_action_error

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_KICK_OK = "{mention} кикнут с сервера"
_BAN_OK = "{mention} забанен. Помянем."
_UNBAN_OK = "{mention} разбанен. Возрадуемся!"

_ERR_REASON_REQUIRED = "Укажите причину"
_ERR_ALREADY_BANNED = "Пользователь уже в бане"
_ERR_NOT_BANNED = "Не нашел пользователя {mention} в списке банов"


def hierarchy_reject(verb: str) -> str:
    """``verb`` — «банить» / «кикать»."""
    return f"Вы не можете {verb} старших или эквивалентных по роли или ботов"


def build_mod_embed(
    *, author_name: str, author_icon: str | None, description: str, reason: str
) -> discord.Embed:
    embed = discord.Embed(description=description, color=discord.Color.green())
    embed.set_author(name=author_name, icon_url=author_icon)
    embed.add_field(name="Причина", value=reason, inline=False)
    return embed


class BanKick(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot

    # -- helpers --------------------------------------------------------------

    def _embed_for(self, ctx: commands.Context, description: str, reason: str) -> discord.Embed:
        author = ctx.author
        return build_mod_embed(
            author_name=embed_author_name(author),
            author_icon=embed_author_icon(author),
            description=description,
            reason=reason,
        )

    def _hierarchy_ok(self, ctx: commands.Context, member: discord.Member) -> bool:
        block = check_hierarchy(
            HierarchyInput(
                initiator_top_role_pos=ctx.author.top_role.position,
                target_top_role_pos=member.top_role.position,
                target_is_bot=member.bot,
                target_id=member.id,
                guild_owner_id=ctx.guild.owner_id,
            )
        )
        return block is HierarchyBlock.OK

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingRequiredArgument) and error.param.name == "target":
            await ctx.send(ERR_NO_TARGET)

    # -- /ban --------------------------------------------------------------------

    @commands.hybrid_command(name="ban", description="Забанить участника (причина опциональна)")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(target="Упоминание или id", reason="Причина (опционально)")
    async def ban(self, ctx: commands.Context, target: str, *, reason: str | None = None) -> None:
        guild = ctx.guild
        assert guild is not None

        target_id = parse_target_id(target)
        if target_id is None:
            await ctx.send(ERR_NO_TARGET)
            return

        member = guild.get_member(target_id)
        if member is not None:
            # цель на сервере — обычные проверки
            if is_self_moderation(ctx.author.id, member.id):
                await ctx.send(SELF_MODERATION)
                return
            if not self._hierarchy_ok(ctx, member):
                await ctx.send(hierarchy_reject("банить"))
                return
        else:
            # цель уже покинула сервер — банить можно, если аккаунт Discord существует
            try:
                await self.bot.fetch_user(target_id)
            except discord.NotFound:
                await ctx.send(ERR_NO_TARGET)
                return

        target_obj = discord.Object(id=target_id)
        try:
            await guild.fetch_ban(target_obj)
            await ctx.send(_ERR_ALREADY_BANNED)
            return
        except discord.NotFound:
            pass

        reason_text = reason or REASON_NOT_GIVEN
        try:
            await guild.ban(
                target_obj,
                reason=f"{ctx.author} ({ctx.author.id}): {reason_text}",
                delete_message_seconds=0,
            )
        except discord.Forbidden:
            log_action_error(log, "забанить", invoker=ctx.author, target=target_id)
            return

        description = _BAN_OK.format(mention=f"<@{target_id}>")
        await ctx.send(embed=self._embed_for(ctx, description, reason_text))

    # -- /kick -----------------------------------------------------------------

    @commands.hybrid_command(name="kick", description="Кикнуть участника (причина обязательна)")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(target="Упоминание или id", reason="Причина (обязательна)")
    async def kick(self, ctx: commands.Context, target: str, *, reason: str | None = None) -> None:
        guild = ctx.guild
        assert guild is not None

        target_id = parse_target_id(target)
        if target_id is None:
            await ctx.send(ERR_NO_TARGET)
            return
        member = guild.get_member(target_id)
        if member is None:
            await ctx.send(ERR_NO_TARGET)
            return
        if not reason:
            await ctx.send(_ERR_REASON_REQUIRED)
            return
        if is_self_moderation(ctx.author.id, member.id):
            await ctx.send(SELF_MODERATION)
            return
        if not self._hierarchy_ok(ctx, member):
            await ctx.send(hierarchy_reject("кикать"))
            return

        try:
            await guild.kick(member, reason=f"{ctx.author} ({ctx.author.id}): {reason}")
        except discord.Forbidden:
            log_action_error(log, "кикнуть", invoker=ctx.author, target=member)
            return

        await ctx.send(embed=self._embed_for(ctx, _KICK_OK.format(mention=member.mention), reason))

    # -- /unban ----------------------------------------------------------------

    @commands.hybrid_command(
        name="unban", description="Разбанить пользователя (причина обязательна)"
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(target="Упоминание или id", reason="Причина (обязательна)")
    async def unban(self, ctx: commands.Context, target: str, *, reason: str | None = None) -> None:
        guild = ctx.guild
        assert guild is not None

        target_id = parse_target_id(target)
        if target_id is None:
            await ctx.send(ERR_NO_TARGET)
            return
        if not reason:
            await ctx.send(_ERR_REASON_REQUIRED)
            return

        mention = f"<@{target_id}>"
        try:
            await guild.fetch_ban(discord.Object(id=target_id))
        except discord.NotFound:
            await ctx.send(_ERR_NOT_BANNED.format(mention=mention))
            return

        try:
            await guild.unban(
                discord.Object(id=target_id), reason=f"{ctx.author} ({ctx.author.id}): {reason}"
            )
        except discord.Forbidden:
            log_action_error(log, "разбанить", invoker=ctx.author, target=target_id)
            return

        await ctx.send(embed=self._embed_for(ctx, _UNBAN_OK.format(mention=mention), reason))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(BanKick(bot))  # type: ignore[arg-type]
