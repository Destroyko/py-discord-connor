"""Самовыдача роли «работяга» — ``!give`` / ``/give`` (см. ``roleGiver.md``).

Три сценария: чистый аккаунт → мгновенная выдача; подозрительно новый → ручная
проверка модератором (заявка с ☑️/❌ в ``#реквесты-работяг``); анти-работяга →
мгновенный отказ. Решения по заявкам логируются в ``#аудит``.

Заявки персистентны (``RepoGive``), реакции обрабатываются "сырыми" событиями —
переживают рестарт бота.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from enum import Enum
from time import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import utcnow

from connor.core.resolve import EntityResolver
from connor.core.timefmt import fmt_short
from connor.db.repo_anti import RepoAnti
from connor.db.repo_give import RepoGive
from connor.logging_setup import log_action_error

if TYPE_CHECKING:
    from connor.bot import ConnorBot
    from connor.config import RoleGiverConfig

log = logging.getLogger(__name__)

_APPROVE_EMOJIS = frozenset({"☑️", "☑"})  # ☑️
_REFUSE_EMOJIS = frozenset({"❌"})  # ❌
_REACT_APPROVE = "☑️"
_REACT_REFUSE = "❌"

_GRANTED = "Роль выдана."
_PENDING = "Ваш запрос передан на ручную обработку. С Вами свяжутся при необходимости."
_REFUSAL = (
    "Вам отказано в выдаче роли. Вы можете связаться с любым модератором "
    "в чате или через личные сообщения для апелляции."
)
_REVIEW_HEADER = "@here Пользователь {mention} запросил работягу. Причины, по которым я не выдал:"


class GiveReason(Enum):
    NEWREG = "newreg"  # B — аккаунт младше N месяцев
    SHORT_TENURE = "short_tenure"  # C — на сервере меньше N недель
    FAST_JOIN = "fast_join"  # D — < N минут между регистрацией и входом


def evaluate_give(
    *,
    account_created_at: datetime,
    joined_at: datetime | None,
    now: datetime,
    cfg: RoleGiverConfig,
) -> list[GiveReason]:
    """Причины отправить заявку на ручную проверку (пусто → чистый аккаунт).

    Условия B/C/D независимы, объединяются через OR. ``joined_at is None`` → C
    считается сработавшим (не подтвердить стаж).
    """
    reasons: list[GiveReason] = []
    if now - account_created_at < timedelta(days=cfg.account_min_age_days):
        reasons.append(GiveReason.NEWREG)
    if joined_at is None or now - joined_at < timedelta(days=cfg.member_min_tenure_days):
        reasons.append(GiveReason.SHORT_TENURE)
    if joined_at is not None and joined_at - account_created_at < timedelta(
        minutes=cfg.join_after_register_min_minutes
    ):
        reasons.append(GiveReason.FAST_JOIN)
    return reasons


def build_review_message(
    mention: str,
    reasons: list[GiveReason],
    account_created_at: datetime,
    joined_at: datetime | None,
) -> str:
    reg = fmt_short(account_created_at)
    join = fmt_short(joined_at) if joined_at is not None else "неизвестно"
    lines = [_REVIEW_HEADER.format(mention=mention)]
    if GiveReason.NEWREG in reasons:
        lines.append(f"Новорег. Дата регистрации: {reg}")
    if GiveReason.SHORT_TENURE in reasons:
        lines.append("Аккаунт находится на сервере менее 2х недель.")
        lines.append(f"Дата присоединения: {join}")
    if GiveReason.FAST_JOIN in reasons:
        lines.append(
            "Между регистрацией аккаунта и присоединением на сервер прошло меньше 20 минут."
        )
        lines.append(f"Дата регистрации: {reg}; Дата присоединения: {join}")
    return "\n".join(lines)


def build_audit_embed(
    *, mod_name: str, mod_icon: str | None, target_mention: str, approved: bool
) -> discord.Embed:
    if approved:
        colour, verb, title = discord.Color.green(), "обновил", "Выдана роль"
    else:
        colour, verb, title = discord.Color.red(), "отказал", "Отказ в выдаче роли"
    embed = discord.Embed(
        colour=colour, description=f"{mod_name} {verb} {target_mention}\n{title}\n@Работяга"
    )
    embed.set_author(name=mod_name, icon_url=mod_icon)
    return embed


class RoleGiver(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self.give_repo = RepoGive(bot.db)
        self.anti_repo = RepoAnti(bot.db)
        self._resolver = EntityResolver(log)

    # -- helpers -----------------------------------------------------------------

    def _channel(self, channel_id: int, label: str) -> discord.abc.Messageable | None:
        return self._resolver.channel(self.bot, channel_id, label)

    def _rabotyaga(self, guild: discord.Guild) -> discord.Role | None:
        return self._resolver.role(guild, self.bot.config.roles["RABOTYAGA"], 'роль "работяга"')

    # -- /give -----------------------------------------------------------------------

    @commands.hybrid_command(name="give", description="Запросить роль «работяга»")
    @app_commands.guild_only()
    async def give(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        assert guild is not None
        member = ctx.author
        assert isinstance(member, discord.Member)

        if await self.anti_repo.contains(member.id):  # сценарий 3
            await ctx.send(_REFUSAL, allowed_mentions=discord.AllowedMentions.none())
            return

        reasons = evaluate_give(
            account_created_at=member.created_at,
            joined_at=member.joined_at,
            now=utcnow(),
            cfg=self.bot.config.role_giver,
        )

        if not reasons:  # сценарий 1
            if await self._grant(member, reason="give: чистый аккаунт"):
                await ctx.send(_GRANTED, allowed_mentions=discord.AllowedMentions.none())
            # выдача не удалась → тихо, ответ пользователю не шлём (лог уже на сервере)
            return

        # сценарий 2 — ручная проверка
        await ctx.send(_PENDING, allowed_mentions=discord.AllowedMentions.none())
        rekvesty = self._channel(self.bot.config.channels["REKVESTY"], "#реквесты-работяг")
        if rekvesty is None:
            return
        text = build_review_message(member.mention, reasons, member.created_at, member.joined_at)
        msg = await rekvesty.send(
            text, allowed_mentions=discord.AllowedMentions(everyone=True, users=True)
        )
        await msg.add_reaction(_REACT_APPROVE)
        await msg.add_reaction(_REACT_REFUSE)
        await self.give_repo.add(msg.id, member.id, int(time()))

    async def _grant(self, member: discord.Member, *, reason: str) -> bool:
        role = self._rabotyaga(member.guild)
        if role is None:
            log.error('роль "работяга" не найдена — выдача пропущена')
            return False
        try:
            await member.add_roles(role, reason=reason)
        except discord.HTTPException:
            log_action_error(log, "выдать роль работяга", target=member)
            return False
        return True

    # -- реакции на заявку ----------------------------------------------------------

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id != self.bot.config.guild_id:
            return
        if self.bot.user is not None and payload.user_id == self.bot.user.id:
            return  # это бот проставил ☑️/❌
        approved = payload.emoji.name in _APPROVE_EMOJIS
        if not approved and payload.emoji.name not in _REFUSE_EMOJIS:
            return

        request = await self.give_repo.get(payload.message_id)
        if request is None:
            return
        # атомарно «захватываем» заявку — кто первый, тот и решает
        if not await self.give_repo.remove(payload.message_id):
            return

        try:
            await self._resolve(payload, request.user_id, approved=approved)
        except Exception:
            log.exception("roleGiver: сбой обработки решения по заявке %d", payload.message_id)

    async def _resolve(
        self, payload: discord.RawReactionActionEvent, user_id: int, *, approved: bool
    ) -> None:
        guild = self.bot.get_guild(payload.guild_id) if payload.guild_id else None
        if guild is None:
            return

        try:
            member = await guild.fetch_member(user_id)
        except discord.NotFound:
            member = None

        await self._delete_review_msg(payload.channel_id, payload.message_id)

        if member is None:  # запросивший уже ушёл — молча, без ответа в #выдача
            return

        if approved and not await self._grant(member, reason="give: одобрено вручную"):
            # роль физически не выдана (нет роли / отказ API) — тихо: ни в #выдача,
            # ни в #аудит, только серверный лог (_grant уже залогировал)
            return

        vydacha = self._channel(self.bot.config.channels["VYDACHA"], "#выдача-работяг")
        if vydacha is not None:
            body = "роль выдана." if approved else _REFUSAL
            await vydacha.send(
                f"{member.mention}, {body}",
                allowed_mentions=discord.AllowedMentions(users=True),
            )

        await self._audit(guild, payload, member.mention, approved=approved)

    async def _delete_review_msg(self, channel_id: int, message_id: int) -> None:
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            return
        try:
            await channel.get_partial_message(message_id).delete()
        except discord.HTTPException:
            pass

    async def _audit(
        self,
        guild: discord.Guild,
        payload: discord.RawReactionActionEvent,
        target_mention: str,
        *,
        approved: bool,
    ) -> None:
        audit = self._channel(self.bot.config.channels["AUDIT"], "#аудит")
        if audit is None:
            return
        mod = payload.member
        if mod is None:
            try:
                mod = await guild.fetch_member(payload.user_id)
            except discord.NotFound:
                return
        await audit.send(
            embed=build_audit_embed(
                mod_name=mod.display_name,
                mod_icon=mod.display_avatar.url,
                target_mention=target_mention,
                approved=approved,
            )
        )

    @commands.Cog.listener()
    async def on_raw_message_delete(self, payload: discord.RawMessageDeleteEvent) -> None:
        # модератор удалил заявку вручную — снять запись, если она наша
        if payload.channel_id == self.bot.config.channels["REKVESTY"]:
            await self.give_repo.remove(payload.message_id)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleGiver(bot))  # type: ignore[arg-type]
