"""Мут / анмут (см. ``mute.md``).

Двойной механизм: нативный Discord timeout (реальный блокатор) + роль «Молчун»
(чисто визуальный индикатор). Хранилища нет — источник истины Discord timeout +
факт наличия роли. В памяти живёт только резервация за автором (``MuteState``).

Реконсиляция роли «Молчун» (роль и таймаут — разные состояния, расходятся):
- напр.1 (роль есть, таймаута нет) — чиним на ``on_message`` и на входе в войс;
- напр.2 (таймаут есть, роли нет — после ре-джойна) — чиним на ``on_member_join``.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from time import monotonic
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import utcnow

from connor.core.hierarchy import (
    HierarchyBlock,
    HierarchyInput,
    check_hierarchy,
    is_self_moderation,
)
from connor.core.msg_guard import should_process_message
from connor.core.mute_state import MuteState
from connor.core.targets import parse_target_id
from connor.core.texts import ERR_NO_TARGET, ERR_TARGET_ABSENT, REASON_NOT_GIVEN, SELF_MODERATION
from connor.core.timefmt import format_remaining_coarse, parse_mute_duration
from connor.logging_setup import log_action_error

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_ERR_BAD_TIME = "Время указано некорректно"
_ERR_HIERARCHY = "Вы не можете мутить старших или эквивалентных по роли или ботов"
_ERR_ALREADY_MUTED = "Пользователь уже в муте"
_ERR_NOT_MUTED = "Пользователь не в муте"

_APPEAL = (
    "Для обжалования вы можете обратиться к старшим модераторам или супермодераторам, "
    "перед обращением рекомендуем ознакомиться с разделом правил сервера"
)


def _rules_link(rules_url: str) -> str:
    return f"[Правила сервера]({rules_url})" if rules_url else "Правила сервера"


def build_mute_dm_embed(
    *, server_name: str, time_str: str, reason: str, rules_url: str, updated: bool
) -> discord.Embed:
    if updated:
        first = f'Вам обновили время мута на сервере "{server_name}" продолжительностью {time_str}'
        colour = discord.Color.yellow()
    else:
        first = f'Вы получили мут на сервере "{server_name}" продолжительностью {time_str}'
        colour = discord.Color.green()
    embed = discord.Embed(
        colour=colour,
        description=f"{first}\n\n**Причина**\n{reason}\n\n{_rules_link(rules_url)}\n\n{_APPEAL}",
    )
    return embed


def build_mute_channel_embed(
    *,
    mod_name: str,
    mod_icon: str | None,
    mention: str,
    time_str: str,
    reason: str,
    updated: bool,
    old_time: str | None = None,
) -> discord.Embed:
    if updated:
        description = f"{mention} перемьючен с {old_time or '?'} на {time_str}"
        colour = discord.Color.yellow()
    else:
        description = f"{mention} замьючен на {time_str}"
        colour = discord.Color.green()
    embed = discord.Embed(description=description, colour=colour)
    embed.set_author(name=mod_name, icon_url=mod_icon)
    embed.add_field(name="Причина", value=reason, inline=False)
    return embed


def _has_active_timeout(member: discord.Member) -> bool:
    return member.is_timed_out()


def _remaining_str(member: discord.Member) -> str:
    """Остаток текущего таймаута одним старшим разрядом — фолбэк для ``<old_time>``,
    когда исходная длительность мьюта неизвестна."""
    until = member.timed_out_until
    if until is None:
        return "?"
    return format_remaining_coarse(int((until - utcnow()).total_seconds()))


class Mute(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self.state = MuteState()
        self._molchun_missing_logged = False

    # -- helpers --------------------------------------------------------------

    def _molchun_role(self, guild: discord.Guild) -> discord.Role | None:
        role_id = self.bot.config.roles["MOLCHUN"]
        role = guild.get_role(role_id)
        if role is None and not self._molchun_missing_logged:
            # реконсиляция дёргается на каждом сообщении — логируем один раз
            log.error(
                'роль "Молчун" (ID=%d) не найдена — визуальный индикатор мьюта отключён', role_id
            )
            self._molchun_missing_logged = True
        return role

    def _hierarchy_ok(self, author: discord.Member, member: discord.Member, owner_id: int) -> bool:
        block = check_hierarchy(
            HierarchyInput(
                initiator_top_role_pos=author.top_role.position,
                target_top_role_pos=member.top_role.position,
                target_is_bot=member.bot,
                target_id=member.id,
                guild_owner_id=owner_id,
            )
        )
        return block is HierarchyBlock.OK

    def _audit(self, ctx: commands.Context, what: str) -> str:
        return f"{ctx.author} ({ctx.author.id}): {what}"

    async def _send_dm(self, member: discord.Member, embed: discord.Embed) -> None:
        try:
            await member.send(embed=embed)
        except discord.HTTPException:
            log.info("DM о муте не доставлено (%s, %d): ЛС закрыты", member, member.id)

    async def _send_plain_dm(self, member: discord.Member, text: str) -> None:
        try:
            await member.send(text)
        except discord.HTTPException:
            log.info("DM об анмуте не доставлено (%s, %d): ЛС закрыты", member, member.id)

    async def _reconcile_stale_role(self, member: discord.Member) -> None:
        """Напр.1: роль «Молчун» есть, активного таймаута нет → снять роль."""
        role = self._molchun_role(member.guild)
        if role is None or role not in member.roles or _has_active_timeout(member):
            return
        try:
            await member.remove_roles(role, reason="реконсиляция: таймаут истёк")
        except discord.HTTPException:
            log_action_error(log, "снять роль «Молчун» (реконсиляция)", target=member)
            return
        self.state.end(member.id)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if isinstance(error, commands.MissingRequiredArgument):
            if error.param.name == "target":
                await ctx.send(ERR_NO_TARGET)
            elif error.param.name == "time":
                await ctx.send(_ERR_BAD_TIME)

    # -- /mute -----------------------------------------------------------------

    @commands.hybrid_command(name="mute", description="Выдать мут (таймаут + роль «Молчун»)")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(
        target="Упоминание или id", time="Длительность 60s..28d", reason="Причина (опционально)"
    )
    async def mute(
        self, ctx: commands.Context, target: str, time: str, *, reason: str | None = None
    ) -> None:
        guild = ctx.guild
        assert guild is not None

        target_id = parse_target_id(target)
        if target_id is None:
            await ctx.send(ERR_NO_TARGET)
            return
        member = guild.get_member(target_id)
        if member is None:
            await ctx.send(ERR_TARGET_ABSENT)
            return

        try:
            seconds = parse_mute_duration(time)
        except ValueError:
            await ctx.send(_ERR_BAD_TIME)
            return

        if is_self_moderation(ctx.author.id, member.id):
            await ctx.send(SELF_MODERATION)
            return
        if not self._hierarchy_ok(ctx.author, member, guild.owner_id):
            await ctx.send(_ERR_HIERARCHY)
            return

        reason_text = reason or REASON_NOT_GIVEN
        updated = _has_active_timeout(member)

        if updated and not self.state.can_update(member.id, ctx.author.id, monotonic()):
            await ctx.send(_ERR_ALREADY_MUTED)
            return

        old_time = self.state.last_time(member.id) or _remaining_str(member) if updated else None

        try:
            await member.timeout(timedelta(seconds=seconds), reason=self._audit(ctx, f"мут {time}"))
        except discord.Forbidden:
            log_action_error(log, "наложить таймаут", invoker=ctx.author, target=member)
            return

        if updated:
            self.state.record_update(member.id, time)
        else:
            role = self._molchun_role(guild)
            if role is not None:
                try:
                    await member.add_roles(role, reason=self._audit(ctx, "мут"))
                except discord.HTTPException:
                    log_action_error(log, "выдать роль «Молчун»", invoker=ctx.author, target=member)
            self.state.begin(member.id, ctx.author.id, monotonic(), time)

        await self._send_dm(
            member,
            build_mute_dm_embed(
                server_name=guild.name,
                time_str=time,
                reason=reason_text,
                rules_url=self.bot.config.mute.rules_url,
                updated=updated,
            ),
        )
        await ctx.send(
            embed=build_mute_channel_embed(
                mod_name=ctx.author.display_name,
                mod_icon=ctx.author.display_avatar.url,
                mention=member.mention,
                time_str=time,
                reason=reason_text,
                updated=updated,
                old_time=old_time,
            )
        )

    # -- /unmute -------------------------------------------------------------------

    @commands.hybrid_command(name="unmute", description="Снять мут")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    @app_commands.describe(target="Упоминание или id")
    async def unmute(self, ctx: commands.Context, target: str) -> None:
        guild = ctx.guild
        assert guild is not None

        target_id = parse_target_id(target)
        if target_id is None:
            await ctx.send(ERR_NO_TARGET)
            return
        member = guild.get_member(target_id)
        if member is None:
            await ctx.send(ERR_TARGET_ABSENT)
            return
        if not _has_active_timeout(member):
            await ctx.send(_ERR_NOT_MUTED)  # обычный текст, не embed
            return

        try:
            await member.timeout(None, reason=self._audit(ctx, "снятие мута"))
        except discord.Forbidden:
            log_action_error(log, "снять таймаут", invoker=ctx.author, target=member)
            return

        role = self._molchun_role(guild)
        if role is not None and role in member.roles:
            try:
                await member.remove_roles(role, reason=self._audit(ctx, "снятие мута"))
            except discord.HTTPException:
                pass  # тихий фолбэк — уберёт реконсиляция

        self.state.end(member.id)
        await self._send_plain_dm(member, f'Ограничения на сервере "{guild.name}" сняты')
        await ctx.send(
            embed=discord.Embed(
                description=f"{member.mention} размьючен", colour=discord.Color.green()
            ).set_author(name=ctx.author.display_name, icon_url=ctx.author.display_avatar.url)
        )

    # -- реконсиляция роли «Молчун» ------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not should_process_message(message) or message.guild is None:
            return
        if isinstance(message.author, discord.Member):
            await self._reconcile_stale_role(message.author)

    @commands.Cog.listener()
    async def on_voice_state_update(
        self, member: discord.Member, before: discord.VoiceState, after: discord.VoiceState
    ) -> None:
        if after.channel is not None:
            await self._reconcile_stale_role(member)

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        """Напр.2: таймаут пережил ре-джойн, роль слетела → вернуть роль."""
        if not _has_active_timeout(member):
            return
        role = self._molchun_role(member.guild)
        if role is None or role in member.roles:
            return
        try:
            await member.add_roles(role, reason="реконсиляция: активный таймаут после ре-джойна")
        except discord.HTTPException:
            log_action_error(log, "вернуть роль «Молчун» после ре-джойна", target=member)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Mute(bot))  # type: ignore[arg-type]
