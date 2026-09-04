"""Начисление опыта в войсе и недельная перевыдача роли «Душа компании» (см.
``Voices.md`` § "Начисление опыта" / "Перевыдача и недельный цикл",
``development.md`` § "Тик начисления опыта").

Один центральный ``tasks.loop`` (интервал из ``config/voices.toml``), на каждой
итерации:

1. сверка реестра комнат — запись, чей канал удалён вручную, убирается;
2. проверка недельного цикла — если точка отсчёта истекла, разовая перевыдача
   (догон ровно одного пропущенного цикла на старте после offline);
3. тик начисления — проход по всем войс-каналам области подсчёта, батч-запись
   ненулевого прироста в БД, без единого обращения к Discord API.

Всё тело итерации в ``try/except`` + ``@tick.error`` — цикл ``tasks.loop`` при
необработанном исключении молча останавливается.
"""

from __future__ import annotations

import logging
from time import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands, tasks

from connor.core.resolve import EntityResolver
from connor.core.voice_cycle import is_cycle_expired, next_anchor, pick_winner
from connor.core.voice_xp import VoiceMemberState, accrue_tick, is_counted_channel
from connor.db.repo_voice_rooms import RepoVoiceRooms
from connor.db.repo_voice_xp import RepoVoiceXp, VoiceCycle
from connor.logging_setup import log_action_error

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_PREV_NOT_FOUND = (
    "Я не нашёл на сервере предыдущего топ-1 пользователя, забрать роль необходимо вручную."
)
_CYCLE_DONE = 'Переназначение роли "Душа компании" и сброс экспы прошёл успешно.'


def _state_of(member: discord.Member) -> VoiceMemberState:
    v = member.voice
    return VoiceMemberState(
        user_id=member.id,
        is_bot=member.bot,
        deaf=bool(v and (v.self_deaf or v.deaf)),
        mic_muted=bool(v and (v.self_mute or v.mute)),
        streaming=bool(v and (v.self_stream or v.self_video)),
    )


class VoicesXp(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self.xp = RepoVoiceXp(bot.db)
        self.rooms = RepoVoiceRooms(bot.db)
        self._resolver = EntityResolver(log)
        #: channel_id → момент, когда комнату впервые увидели пустой (для бэкстопа
        #: удаления). Живёт между тиками, чистится в _reconcile_rooms.
        self._empty_since: dict[int, int] = {}
        self.tick.change_interval(seconds=bot.config.voices.tick_interval_seconds)

    async def cog_load(self) -> None:
        self.tick.start()

    async def cog_unload(self) -> None:
        self.tick.cancel()

    # -- центральный цикл ---------------------------------------------------------

    @tasks.loop(seconds=60)
    async def tick(self) -> None:
        try:
            guild = self.bot.get_guild(self.bot.config.guild_id)
            if guild is None:
                return
            await self._reconcile_rooms(guild)
            await self._maybe_weekly(guild)
            await self._accrue(guild)
        except Exception:
            log.exception("voices tick: сбой итерации — цикл продолжается")

    @tick.before_loop
    async def _before(self) -> None:
        await self.bot.wait_until_ready()
        await self.xp.ensure_cycle(int(time()))  # первый чистый старт — ставим anchor

    @tick.error
    async def _on_error(self, exc: BaseException) -> None:
        log.exception("voices tick: ошибка вне тела итерации", exc_info=exc)

    # -- сверка реестра комнат -------------------------------------------------

    async def _reconcile_rooms(self, guild: discord.Guild) -> None:
        now = int(time())
        grace = self.bot.config.voices.tick_interval_seconds
        still_empty: dict[int, int] = {}
        for room in await self.rooms.all():
            channel = guild.get_channel(room.channel_id)
            if channel is None:
                await self.rooms.remove_by_owner(room.owner_id)
                log.info(
                    "реестр комнат: канал %d (владелец %d) не найден — запись убрана",
                    room.channel_id,
                    room.owner_id,
                )
                continue
            if getattr(channel, "members", []):
                continue  # есть кто-то — комната живёт
            # бэкстоп на пропущенное событие ухода: удаляем, только если комнату
            # видели пустой уже ≥ grace (т.е. как минимум прошлый тик тоже) — а не
            # просто «прошло grace с создания»
            since = self._empty_since.get(room.channel_id, now)
            if now - since >= grace:
                try:
                    await channel.delete(reason="реестр: комната простояла пустой")
                except discord.HTTPException:
                    pass
                await self.rooms.remove_by_owner(room.owner_id)
            else:
                still_empty[room.channel_id] = since
        self._empty_since = still_empty

    # -- тик начисления --------------------------------------------------------

    async def _accrue(self, guild: discord.Guild) -> None:
        cfg = self.bot.config.voices
        afk_id = guild.afk_channel.id if guild.afk_channel is not None else None
        trigger_id = self.bot.config.channels["TRIGGER_VOICE"]
        roddom_id = self.bot.config.categories["RODDOM"]

        deltas: dict[int, int] = {}
        for channel in guild.voice_channels:  # guild.voice_channels уже без Stage
            if not is_counted_channel(
                channel_id=channel.id,
                category_id=channel.category_id,
                is_stage=False,
                roddom_category_id=roddom_id,
                afk_channel_id=afk_id,
                trigger_channel_id=trigger_id,
            ):
                continue
            states = [_state_of(m) for m in channel.members]
            for uid, pts in accrue_tick(states, cfg).items():
                deltas[uid] = deltas.get(uid, 0) + pts

        await self.xp.add_points(deltas)

    # -- недельная перевыдача ----------------------------------------------------

    async def _maybe_weekly(self, guild: discord.Guild) -> None:
        cfg = self.bot.config.voices
        cycle = await self.xp.get_cycle()
        if cycle is None:
            cycle = await self.xp.ensure_cycle(int(time()))
        now = int(time())
        if is_cycle_expired(now=now, anchor_ts=cycle.anchor_ts, week_seconds=cfg.week_seconds):
            await self._run_weekly(guild, cycle, now)

    async def _run_weekly(self, guild: discord.Guild, cycle: VoiceCycle, now: int) -> None:
        cfg = self.bot.config.voices
        standings = await self.xp.standings()
        new_anchor = next_anchor(now=now, anchor_ts=cycle.anchor_ts, week_seconds=cfg.week_seconds)

        role = self._resolver.role(guild, self.bot.config.roles["DUSHA"], 'роль "Душа компании"')
        bot_komandy = self._resolver.channel(
            self.bot, self.bot.config.channels["BOT_KOMANDY"], "#бот-команды"
        )
        fludislavl = self._resolver.channel(
            self.bot, self.bot.config.channels["FLUDISLAVL"], "#флудиславль"
        )

        # первый присутствующий на сервере сверху списка — победитель
        present: set[int] = set()
        for uid, _pts in standings:
            if await self._resolve_member(guild, uid) is not None:
                present.add(uid)
                break
        awardee_id, margin = pick_winner(standings, present)

        prev_id = cycle.current_dusha_id
        prev_member = await self._resolve_member(guild, prev_id) if prev_id is not None else None

        if awardee_id is not None:
            awardee = await self._resolve_member(guild, awardee_id)
            same_holder = awardee_id == prev_id

            # снять роль с прежнего — только если лидер сменился
            if not same_holder and prev_member is not None and role is not None:
                if role in prev_member.roles:
                    try:
                        await prev_member.remove_roles(role, reason="еженедельная перевыдача роли")
                    except discord.HTTPException:
                        log_action_error(log, "снять роль «Душа компании»", target=prev_member)
            if not same_holder and prev_id is not None and prev_member is None and bot_komandy:
                await bot_komandy.send(_PREV_NOT_FOUND)

            # выдать/подтвердить роль у победителя. add_roles идемпотентен (роль уже
            # есть → no-op); не опираемся на awardee.roles — локальный кэш после
            # remove_roles синхронно не обновляется, и при same_holder был бы устаревшим.
            if role is not None and awardee is not None:
                try:
                    await awardee.add_roles(role, reason="еженедельная перевыдача — лидер недели")
                except discord.HTTPException:
                    log_action_error(log, "выдать роль «Душа компании»", target=awardee)

            if fludislavl is not None and awardee is not None:
                await fludislavl.send(
                    f"Роль @Душа компании получает {awardee.mention}, "
                    f"разница со вторым местом составила {margin} экспы",
                    allowed_mentions=discord.AllowedMentions(users=[awardee]),
                )
            new_dusha: int | None = awardee_id
        else:
            new_dusha = prev_id  # никто не набрал / все ушли — роль не трогаем

        if bot_komandy is not None:
            await bot_komandy.send(_CYCLE_DONE)

        await self.xp.reset_week()
        await self.xp.set_cycle(anchor_ts=new_anchor, current_dusha_id=new_dusha)

    async def _resolve_member(self, guild: discord.Guild, uid: int | None) -> discord.Member | None:
        if uid is None:
            return None
        member = guild.get_member(uid)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(uid)
        except discord.HTTPException:
            return None


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoicesXp(bot))  # type: ignore[arg-type]
