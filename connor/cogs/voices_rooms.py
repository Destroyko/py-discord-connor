"""Приватные войс-комнаты: создание и жизненный цикл (см. ``Voices.md`` §
"Создание приватной комнаты" / "Жизненный цикл комнаты").

- вход в статичный войс-триггер → бот создаёт голосовой канал в фиксированной
  категории, переносит владельца внутрь, выдаёт ему точечный overwrite
  (``View Channel`` + ``Manage Channels`` — и **только** их);
- повторный вход в триггер при живой комнате → перенос в неё, второй канал не
  создаётся; запись есть, а канала нет → считаем комнату закрытой, создаём новую;
- комната живёт, пока в ней есть хоть кто-то; на событии ухода последнего
  участника (в т.ч. перенос в AFK / модератором) — канал и запись удаляются;
- забаненный владельцем (``/vkick``) по «неактивной» записи бан-листа при попытке
  зайти получает реактивный disconnect + обновление ``ts``.

Минутная сверка реестра (канал удалён вручную) — в ``voices_xp.py`` (общий цикл).
"""

from __future__ import annotations

import logging
from time import time
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from connor.core.resolve import EntityResolver
from connor.db.repo_voice_banlist import RepoVoiceBanlist
from connor.db.repo_voice_rooms import RepoVoiceRooms
from connor.logging_setup import log_action_error

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_OWNER_OVERWRITE = discord.PermissionOverwrite(view_channel=True, manage_channels=True)


class VoicesRooms(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self.rooms = RepoVoiceRooms(bot.db)
        self.banlist = RepoVoiceBanlist(bot.db)
        self._resolver = EntityResolver(log)

    # -- event ---------------------------------------------------------------

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        before_ch = before.channel
        after_ch = after.channel
        if before_ch is None and after_ch is None:
            return
        if before_ch is not None and after_ch is not None and before_ch.id == after_ch.id:
            return  # mute/deaf/stream внутри того же канала — не наше событие

        trigger_id = self.bot.config.channels["TRIGGER_VOICE"]
        moved_back_to: int | None = None

        if after_ch is not None and after_ch.id == trigger_id:
            moved_back_to = await self._handle_trigger(member)
        elif after_ch is not None:
            await self._maybe_reactive_block(member, after_ch)

        # если владельца тут же вернули в его же комнату (повторный вход в триггер) —
        # «уход» из неё транзитный, комнату не закрываем (кэш ещё не отразил возврат)
        if (
            before_ch is not None
            and (after_ch is None or after_ch.id != before_ch.id)
            and before_ch.id != moved_back_to
        ):
            await self._maybe_close_room(before_ch, left=member)

    # -- создание ----------------------------------------------------------------

    async def _handle_trigger(self, member: discord.Member) -> int | None:
        """Возвращает id комнаты, в которую владельца **вернули** (существующая
        активная комната), иначе ``None`` (создана новая / ничего)."""
        guild = member.guild
        existing = await self.rooms.get_by_owner(member.id)
        if existing is not None:
            channel = guild.get_channel(existing.channel_id)
            if channel is not None:
                try:
                    await member.move_to(channel, reason="повторный вход в триггер")
                except discord.HTTPException:
                    pass
                return channel.id
            await self.rooms.remove_by_owner(member.id)  # запись есть, канала нет — закрыта

        await self._create_room(member)
        return None

    async def _create_room(self, member: discord.Member) -> None:
        guild = member.guild
        category = self._resolver.channel(
            guild, self.bot.config.categories["PRIVATE_VOICE"], "категория приватных войсов"
        )
        if not isinstance(category, discord.CategoryChannel):
            return

        cfg = self.bot.config.voices
        now = int(time())

        # владельцу — ровно View + Manage Channels; проактивно — deny для «активных»
        # записей бан-листа (окно 24 ч). Всё одним overwrites при создании канала.
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            member: _OWNER_OVERWRITE
        }
        window = cfg.banlist_active_window_hours * 3600
        deny = discord.PermissionOverwrite(connect=False, send_messages=False)
        for banned_id in await self.banlist.active_ids(member.id, since_ts=now - window):
            overwrites[discord.Object(id=banned_id)] = deny

        try:
            channel = await category.create_voice_channel(
                name=member.name,  # username, не отображаемое имя
                bitrate=cfg.room_bitrate,
                user_limit=cfg.room_user_limit,
                nsfw=cfg.room_nsfw,
                overwrites=overwrites,
                reason=f"приватная комната для {member} ({member.id})",
            )
        except discord.HTTPException:
            log_action_error(log, "создать приватную комнату", target=member)
            return

        # slowmode не принимается create_voice_channel — правим отдельно, если задан
        if cfg.room_slowmode:
            try:
                await channel.edit(slowmode_delay=cfg.room_slowmode)
            except discord.HTTPException:
                log.warning("не удалось выставить slowmode комнате %d", channel.id)

        try:
            await member.move_to(channel, reason="перенос владельца в новую комнату")
        except discord.HTTPException:
            # владелец отключился до переноса — пустых комнат в категории не оставляем
            try:
                await channel.delete(reason="перенос владельца не удался")
            except discord.HTTPException:
                pass
            return

        await self.rooms.upsert(member.id, channel.id, now)

    # -- жизненный цикл --------------------------------------------------------

    async def _maybe_close_room(
        self, channel: discord.abc.GuildChannel, *, left: discord.Member
    ) -> None:
        room = await self.rooms.get_by_channel(channel.id)
        if room is None:
            return
        members = getattr(channel, "members", [])
        if any(m.id != left.id for m in members):
            return  # ещё есть гости — комната живёт
        try:
            await channel.delete(reason="комната опустела")
        except discord.HTTPException:
            pass
        await self.rooms.remove_by_owner(room.owner_id)

    async def _maybe_reactive_block(
        self, member: discord.Member, channel: discord.abc.GuildChannel
    ) -> None:
        room = await self.rooms.get_by_channel(channel.id)
        if room is None or room.owner_id == member.id:
            return
        if not await self.banlist.contains(room.owner_id, member.id):
            return

        # запись была «неактивной» (overwrite не переносился); раз пытался зайти —
        # активен: disconnect + постоянный overwrite + обновление ts («самоисцеление»)
        try:
            await member.move_to(None, reason="забанен владельцем комнаты (реактивный блок)")
        except discord.HTTPException:
            pass
        try:
            overwrite = channel.overwrites_for(member)
            overwrite.connect = False
            overwrite.send_messages = False
            await channel.set_permissions(
                member, overwrite=overwrite, reason="реактивный блок бан-листа"
            )
        except discord.HTTPException:
            pass
        await self.banlist.upsert(room.owner_id, member.id, int(time()))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoicesRooms(bot))  # type: ignore[arg-type]
