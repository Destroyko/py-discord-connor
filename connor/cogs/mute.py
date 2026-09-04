"""Мут / анмут (см. ``mute.md``).

Двойной механизм: нативный Discord timeout (реальный блокатор) + роль «Молчун»
(чисто визуальный индикатор). Хранилища нет — источник истины Discord timeout +
факт наличия роли. В памяти живёт только резервация за автором (``MuteState``).

Реконсиляция роли «Молчун» (роль и таймаут — разные состояния, расходятся):
- напр.1 (роль есть, таймаута нет) — чиним на ``on_message`` и на входе в войс;
- напр.2 (таймаут есть, роли нет — после ре-джойна) — чиним на ``on_member_join``.

Отложенный мут: ``/mute`` по цели, которой уже нет на сервере (Discord timeout
не выдать не-участнику), кладётся в ``pending_mutes`` и применяется при
возвращении (``on_member_join`` + разовая сверка на старте). Не вернулся за
``pending_mute_retention_days`` — запись удаляет часовой sweep.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from time import monotonic
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands, tasks
from discord.utils import utcnow

from connor.core.authorship import embed_author_icon, embed_author_name
from connor.core.hierarchy import (
    HierarchyBlock,
    HierarchyInput,
    check_hierarchy,
    is_self_moderation,
)
from connor.core.members import fetch_member
from connor.core.msg_guard import should_process_message
from connor.core.mute_state import MuteState
from connor.core.resolve import EntityResolver
from connor.core.targets import parse_target_id
from connor.core.texts import ERR_NO_TARGET, ERR_TARGET_ABSENT, REASON_NOT_GIVEN, SELF_MODERATION
from connor.core.timefmt import fmt_full, format_remaining_coarse, parse_mute_duration
from connor.db.repo_mute_watcher import RepoMuteWatcher
from connor.db.repo_pending_mute import RepoPendingMute
from connor.logging_setup import log_action_error

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_ERR_BAD_TIME = "Время указано некорректно"
_ERR_HIERARCHY = "Вы не можете мутить старших или эквивалентных по роли или ботов"
_ERR_ALREADY_MUTED = "Пользователь уже в муте"
_ERR_NOT_MUTED = "Пользователь не в муте"
_PENDING_QUEUED = (
    "Пользователь ливнул с сервера. Если он вернётся до {date}, "
    "наказание будет выдано автоматически."
)
_PENDING_CANCELLED = "Отложенный мут для {mention} отменён"

_PENDING_SWEEP_INTERVAL_HOURS = 1

# см. anti.py: журнал аудита появляется в API не сразу (~4-5 c) — это и есть
# реальный потолок задержки, не интервал опроса; опрашивать чаще бессмысленно
_MANUAL_POLL_INTERVAL_SECONDS = 3

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


def build_unmute_channel_embed(
    *, mod_name: str, mod_icon: str | None, mention: str
) -> discord.Embed:
    embed = discord.Embed(description=f"{mention} размьючен", colour=discord.Color.green())
    embed.set_author(name=mod_name, icon_url=mod_icon)
    return embed


def build_pending_mute_embed(*, until_ts: int) -> discord.Embed:
    """Ответ модератору, когда цель уже вышла с сервера и мут поставлен в очередь.
    Синяя полоса слева, без author-иконки."""
    return discord.Embed(
        description=_PENDING_QUEUED.format(date=fmt_full(until_ts)),
        colour=discord.Color.blue(),
    )


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
        self.pending_repo = RepoPendingMute(bot.db)
        self.watcher_repo = RepoMuteWatcher(bot.db)
        self._resolver = EntityResolver(log)  # реконсиляция дёргается часто — лог 1 раз на id
        self._pending_startup_done = False

    async def cog_load(self) -> None:
        self._sweep_pending.start()
        self._poll_manual_changes.start()

    async def cog_unload(self) -> None:
        self._sweep_pending.cancel()
        self._poll_manual_changes.cancel()

    # -- helpers --------------------------------------------------------------

    def _molchun_role(self, guild: discord.Guild) -> discord.Role | None:
        return self._resolver.role(guild, self.bot.config.roles["MOLCHUN"], 'роль "Молчун"')

    def _bot_komandy(self) -> discord.abc.Messageable | None:
        return self._resolver.channel(
            self.bot, self.bot.config.channels["BOT_KOMANDY"], "#бот-команды"
        )

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

        try:
            seconds = parse_mute_duration(time)
        except ValueError:
            await ctx.send(_ERR_BAD_TIME)
            return

        member = await fetch_member(guild, target_id)
        if member is None:
            # цель уже вышла с сервера — Discord timeout ей не выдать; кладём в
            # очередь и применим при возвращении (см. mute.md § "Отложенный мут")
            await self._queue_pending_mute(ctx, target_id, time, reason)
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

        old_time = (self.state.last_time(member.id) or _remaining_str(member)) if updated else None

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
                mod_name=embed_author_name(ctx.author),
                mod_icon=embed_author_icon(ctx.author),
                mention=member.mention,
                time_str=time,
                reason=reason_text,
                updated=updated,
                old_time=old_time,
            )
        )

    # -- отложенный мут (цель вышла до наказания) ----------------------------

    async def _queue_pending_mute(
        self, ctx: commands.Context, target_id: int, time_str: str, reason: str | None
    ) -> None:
        try:
            await self.bot.fetch_user(target_id)  # id вообще валиден? (мусор/typo → отказ)
        except discord.HTTPException:
            await ctx.send(ERR_TARGET_ABSENT)
            return

        now = int(utcnow().timestamp())
        await self.pending_repo.upsert(
            target_id,
            duration=time_str,
            reason=reason or REASON_NOT_GIVEN,
            moderator_id=ctx.author.id,
            queued_at=now,
        )
        retention = self.bot.config.mute.pending_mute_retention_days
        await ctx.send(embed=build_pending_mute_embed(until_ts=now + retention * 86400))

    async def _apply_pending_mute(self, member: discord.Member) -> bool:
        """Есть отложенная запись на ``member`` → выдать мут как обычный (без
        намёка на отложенность), уведомить, снять запись. ``True`` — что-то сделали."""
        entry = await self.pending_repo.get(member.id)
        if entry is None:
            return False
        try:
            seconds = parse_mute_duration(entry.duration)
        except ValueError:
            log.error(
                "отложенный мут %d: битая длительность %r — запись удалена",
                member.id,
                entry.duration,
            )
            await self.pending_repo.remove(member.id)
            return False

        guild = member.guild
        try:
            await member.timeout(
                timedelta(seconds=seconds),
                reason=f"отложенный мут (поставил {entry.moderator_id})",
            )
        except discord.HTTPException:
            log_action_error(log, "выдать отложенный мут", target=member)
            return False  # запись не трогаем — попробуем при следующем заходе / на старте

        role = self._molchun_role(guild)
        if role is not None and role not in member.roles:
            try:
                await member.add_roles(role, reason="отложенный мут")
            except discord.HTTPException:
                log_action_error(log, "выдать роль «Молчун» (отложенный мут)", target=member)

        self.state.begin(member.id, entry.moderator_id, monotonic(), entry.duration)
        await self.pending_repo.remove(member.id)

        await self._send_dm(
            member,
            build_mute_dm_embed(
                server_name=guild.name,
                time_str=entry.duration,
                reason=entry.reason,
                rules_url=self.bot.config.mute.rules_url,
                updated=False,
            ),
        )
        actor = await self._resolve_actor(guild, entry.moderator_id)
        channel = self._bot_komandy()
        if channel is not None:
            await channel.send(
                embed=build_mute_channel_embed(
                    mod_name=(
                        embed_author_name(actor)
                        if actor is not None
                        else str(entry.moderator_id)
                    ),
                    mod_icon=(embed_author_icon(actor) if actor is not None else None),
                    mention=member.mention,
                    time_str=entry.duration,
                    reason=entry.reason,
                    updated=False,
                )
            )
        return True

    async def _resolve_actor(
        self, guild: discord.Guild, user_id: int
    ) -> discord.User | discord.Member | None:
        """Модератор, поставивший отложенный мут — резолвим на момент выдачи (ник и
        аватар текущие, не снимок 20-дневной давности; снимок к тому же протух бы —
        CDN-ссылка на старый аватар отдаёт 404).

        get_member (в кэше) → guild.fetch_member (на сервере, но не в кэше — вернёт
        Member с серверным ником/аватаром) → bot.fetch_user (модератор ушёл с
        сервера — глобальный ник/аватар) → None (совсем не резолвится — в embed
        пойдёт голый id без иконки).
        """
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.HTTPException:
            pass
        try:
            return await self.bot.fetch_user(user_id)
        except discord.HTTPException:
            return None

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        """Разовая сверка: пользователь мог вернуться, пока бот лежал — тогда
        ``on_member_join`` мы пропустили."""
        if self._pending_startup_done:
            return
        self._pending_startup_done = True
        try:
            guild = self.bot.get_guild(self.bot.config.guild_id)
            if guild is None:
                return
            for entry in await self.pending_repo.all():
                try:
                    member = guild.get_member(entry.user_id) or await guild.fetch_member(
                        entry.user_id
                    )
                except discord.HTTPException:
                    continue  # всё ещё не на сервере — ждём on_member_join / истечения
                await self._apply_pending_mute(member)
        except Exception:
            log.exception("отложенные муты: сбой стартовой сверки")

    @tasks.loop(hours=_PENDING_SWEEP_INTERVAL_HOURS)
    async def _sweep_pending(self) -> None:
        try:
            retention = self.bot.config.mute.pending_mute_retention_days
            cutoff = int(utcnow().timestamp()) - retention * 86400
            removed = await self.pending_repo.purge_older_than(cutoff)
            if removed:
                log.info("отложенные муты: удалено просроченных записей: %d", removed)
        except Exception:
            log.exception("sweep отложенных мутов: сбой итерации — цикл продолжается")

    @_sweep_pending.before_loop
    async def _before_sweep(self) -> None:
        await self.bot.wait_until_ready()

    @_sweep_pending.error
    async def _on_sweep_error(self, exc: BaseException) -> None:
        log.exception("sweep отложенных мутов: ошибка вне тела итерации", exc_info=exc)

    # -- наблюдение за ручными изменениями Discord timeout (опрос audit log) -----
    #
    # По аналогии с anti.py: gateway-событие on_member_update discord.py диспатчит
    # только участникам, уже сидящим в member-кэше (у нас он частичный), поэтому
    # мут/анмут, наложенные модератором напрямую через Discord UI (в обход
    # /mute и /unmute), отслеживаются периодическим опросом журнала аудита.

    @tasks.loop(seconds=_MANUAL_POLL_INTERVAL_SECONDS)
    async def _poll_manual_changes(self) -> None:
        try:
            guild = self.bot.get_guild(self.bot.config.guild_id)
            if guild is None:
                return
            await self._poll_manual_once(guild)
        except Exception:
            log.exception("вотчер мута: сбой опроса audit log — цикл продолжается")

    @_poll_manual_changes.before_loop
    async def _before_poll_manual(self) -> None:
        await self.bot.wait_until_ready()

    @_poll_manual_changes.error
    async def _on_poll_manual_error(self, exc: BaseException) -> None:
        log.exception("вотчер мута: ошибка вне тела итерации", exc_info=exc)

    async def _poll_manual_once(self, guild: discord.Guild) -> None:
        cursor = await self.watcher_repo.get_cursor()

        if cursor is None:
            # первый чистый старт — не разбираем всю историю аудита, только
            # фиксируем точку отсчёта на «сейчас» (тот же принцип, что у anti.py)
            newest_id = await self._latest_entry_id(guild)
            if newest_id is not None:
                await self.watcher_repo.set_cursor(newest_id)
            return

        async for entry in guild.audit_logs(
            action=discord.AuditLogAction.member_update,
            after=discord.Object(id=cursor),
            oldest_first=True,
            limit=None,
        ):
            try:
                await self._handle_manual_entry(entry)
            except Exception:
                log.exception("вотчер мута: сбой обработки записи %d", entry.id)
            await self.watcher_repo.set_cursor(entry.id)

    async def _latest_entry_id(self, guild: discord.Guild) -> int | None:
        async for entry in guild.audit_logs(limit=1):
            return entry.id
        return None

    async def _handle_manual_entry(self, entry: discord.AuditLogEntry) -> None:
        if self.bot.user is not None and entry.user_id == self.bot.user.id:
            return  # таймаут поставил/снял сам бот (/mute, /unmute, отложенный мут) — уже отчитался

        target = entry.target
        if target is None:
            return
        actor = entry.user
        if actor is None:
            log.warning(
                "вотчер мута: не нашёл автора изменения у записи %d (цель %d)",
                entry.id,
                target.id,
            )
            return

        before_until = getattr(entry.before, "timed_out_until", None)
        after_until = getattr(entry.after, "timed_out_until", None)

        if before_until is None and after_until is not None:
            await self._on_manual_mute(
                target=target, actor=actor, until=after_until, reason=entry.reason
            )
        elif before_until is not None and after_until is None:
            await self._on_manual_unmute(target=target, actor=actor)

    async def _on_manual_mute(
        self,
        *,
        target: discord.Member | discord.User | discord.Object,
        actor: discord.User | discord.Member,
        until: datetime,
        reason: str | None,
    ) -> None:
        channel = self._bot_komandy()
        if channel is None:
            return
        remaining = int((until - utcnow()).total_seconds())
        await channel.send(
            embed=build_mute_channel_embed(
                mod_name=embed_author_name(actor),
                mod_icon=embed_author_icon(actor),
                mention=f"<@{target.id}>",
                time_str=format_remaining_coarse(remaining),
                reason=reason or REASON_NOT_GIVEN,
                updated=False,
            )
        )

    async def _on_manual_unmute(
        self,
        *,
        target: discord.Member | discord.User | discord.Object,
        actor: discord.User | discord.Member,
    ) -> None:
        channel = self._bot_komandy()
        if channel is None:
            return
        await channel.send(
            embed=build_unmute_channel_embed(
                mod_name=embed_author_name(actor),
                mod_icon=embed_author_icon(actor),
                mention=f"<@{target.id}>",
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
        member = await fetch_member(guild, target_id)
        if member is None:
            # цели нет на сервере — но на неё мог висеть отложенный мут: отменяем его
            if await self.pending_repo.remove(target_id):
                await ctx.send(
                    _PENDING_CANCELLED.format(mention=f"<@{target_id}>"),
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            else:
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
            embed=build_unmute_channel_embed(
                mod_name=embed_author_name(ctx.author),
                mod_icon=embed_author_icon(ctx.author),
                mention=member.mention,
            )
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
        # отложенный мут: цель ливнула до наказания и вот вернулась
        if await self._apply_pending_mute(member):
            return
        # Напр.2: таймаут пережил ре-джойн, роль слетела → вернуть роль.
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
