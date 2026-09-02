"""Самомодерация владельца приватной комнаты (см. ``Voices.md`` § "Управление
своим голосовым каналом").

- ``/vkick`` (+``!``) — в ``#флудиславль``, находясь в своей комнате: запретить
  цели заходить в комнату (deny ``Connect`` + встроенный текст-чат), при
  необходимости выкинуть её сейчас, добавить в личный бан-лист (≤100);
- ``/vreturn`` (+``!``) в ``#флудиславль`` / ``!vdel <id>`` в ЛС — убрать из
  бан-листа и сразу снять deny с активной комнаты, если он там стоит;
- ``/ban_list`` (+``!``, ``!ban_list`` — и в ЛС) — прислать бан-лист в ЛС.

Ответы ``/vkick``/``/vreturn`` — ephemeral для slash (осознанное исключение из
"все ответы публичные"). Никуда не логируются — это самообслуживание.
"""

from __future__ import annotations

import logging
from time import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from connor.core.targets import parse_target_id
from connor.db.repo_voice_banlist import RepoVoiceBanlist
from connor.db.repo_voice_rooms import RepoVoiceRooms
from connor.logging_setup import log_action_error

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_ERR_NO_USER = "Вы не указали пользователя или его нет на сервере"
_ERR_NO_RIGHTS = "У вас нет прав на это действие или вы не находитесь в голосовом канале"
_ERR_LIMIT = (
    "Список забаненных пользователей достиг лимита. Используйте команду banList для подробностей"
)
_ERR_NOT_BANNED = "Пользователь не найден в списке забаненных."
_VKICK_OK = "Пользователь {mention} забанен в ваших комнатах."
_VRETURN_OK = "Пользователь {mention} разбанен."
_BANLIST_SENT = "Информация отправлена в лс"
_BANLIST_DM_FAIL = "Я не могу отправить тебе список. Открой ЛС"

_BANLIST_DESC = (
    "Для удаления используйте команду !vreturn @никнейм в канале #флудиславль "
    "или команду !vdel id в этом личном сообщении"
)


_EMBED_DESC_BUDGET = 3800  # запас под лимит embed.description = 4096


def build_banlist_embeds(banned_ids: list[int]) -> list[discord.Embed]:
    """Бан-лист для ЛС: синяя полоса, нумерация с 1, `` `<@id>` `` + ``id: <id>``.

    До ~100 записей на владельца могут не влезть в один ``description`` (лимит 4096)
    — разбиваем на несколько embed'ов: заголовок только у первого, footer — у
    последнего.
    """
    blocks = [f"**{i}**\n`<@{uid}>`\nid: {uid}" for i, uid in enumerate(banned_ids, 1)]

    chunks: list[list[str]] = [[]]
    used = len(_BANLIST_DESC)
    for block in blocks:
        if chunks[-1] and used + len(block) + 2 > _EMBED_DESC_BUDGET:
            chunks.append([])
            used = 0
        chunks[-1].append(block)
        used += len(block) + 1

    embeds: list[discord.Embed] = []
    for idx, chunk in enumerate(chunks):
        body = "\n".join(chunk)
        desc = f"{_BANLIST_DESC}\n\n{body}" if idx == 0 else body
        embeds.append(
            discord.Embed(
                title="Список забаненных" if idx == 0 else None,
                description=desc or _BANLIST_DESC,
                colour=discord.Color.blue(),
            )
        )
    embeds[-1].set_footer(text="Например !vdel 1234567891011")
    return embeds


class VoicesSelfmod(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self.rooms = RepoVoiceRooms(bot.db)
        self.banlist = RepoVoiceBanlist(bot.db)

    # -- helpers -----------------------------------------------------------------

    def _guild(self, ctx: commands.Context) -> discord.Guild | None:
        return ctx.guild or self.bot.get_guild(self.bot.config.guild_id)

    async def _active_room(
        self, guild: discord.Guild, owner_id: int
    ) -> discord.abc.GuildChannel | None:
        room = await self.rooms.get_by_owner(owner_id)
        if room is None:
            return None
        channel = guild.get_channel(room.channel_id)
        if channel is None:
            await self.rooms.remove_by_owner(owner_id)  # запись есть, канала нет
            return None
        return channel

    async def _clear_room_deny(self, channel: discord.abc.GuildChannel, target_id: int) -> None:
        overwrite = channel.overwrites_for(discord.Object(id=target_id))
        if overwrite.connect is not False and overwrite.send_messages is not False:
            return  # deny не стоял — снимать нечего
        try:
            await self.bot.http.delete_channel_permissions(
                channel.id, target_id, reason="снят бан приватного войса"
            )
        except discord.HTTPException:
            log.warning("не удалось снять deny комнаты %d для %d", channel.id, target_id)

    async def cog_command_error(self, ctx: commands.Context, error: commands.CommandError) -> None:
        if not isinstance(error, commands.MissingRequiredArgument):
            return
        name = ctx.command.name if ctx.command else ""
        if name == "vkick":
            await ctx.send(_ERR_NO_USER)
        elif name == "vreturn" or (name == "vdel" and ctx.guild is None):
            await ctx.send(_ERR_NOT_BANNED)

    # -- /vkick ----------------------------------------------------------------------

    @commands.hybrid_command(
        name="vkick", description="Кикнуть %username% из приватного войс канала"
    )
    @app_commands.guild_only()
    @app_commands.describe(target="Упоминание или id")
    async def vkick(self, ctx: commands.Context, target: str) -> None:
        guild = ctx.guild
        assert guild is not None
        author = ctx.author
        assert isinstance(author, discord.Member)

        channel = await self._active_room(guild, author.id)
        in_own_room = (
            channel is not None
            and author.voice is not None
            and author.voice.channel is not None
            and author.voice.channel.id == channel.id
        )
        if not in_own_room or channel is None:
            await ctx.send(_ERR_NO_RIGHTS, ephemeral=True)
            return

        target_id = parse_target_id(target)
        if target_id is None:
            await ctx.send(_ERR_NO_USER, ephemeral=True)
            return
        try:
            member = await guild.fetch_member(target_id)
        except discord.HTTPException:  # NotFound и прочее — «нет на сервере»
            await ctx.send(_ERR_NO_USER, ephemeral=True)
            return

        already = await self.banlist.contains(author.id, member.id)
        limit = self.bot.config.voices.banlist_limit
        if not already and await self.banlist.count(author.id) >= limit:
            await ctx.send(_ERR_LIMIT, ephemeral=True)
            return

        # deny на комнату: запрет подключения + встроенного текст-чата; видимость не трогаем
        try:
            overwrite = channel.overwrites_for(member)
            overwrite.connect = False
            overwrite.send_messages = False
            await channel.set_permissions(
                member, overwrite=overwrite, reason=f"vkick by {author} ({author.id})"
            )
        except discord.HTTPException:
            log_action_error(log, "vkick: overwrite комнаты", invoker=author, target=member)

        # disconnect — только если цель прямо сейчас в комнате вызывающего
        if (
            member.voice is not None
            and member.voice.channel is not None
            and member.voice.channel.id == channel.id
        ):
            try:
                await member.move_to(None, reason=f"vkick by {author} ({author.id})")
            except discord.HTTPException:
                pass

        await self.banlist.upsert(author.id, member.id, int(time()))
        await ctx.send(
            _VKICK_OK.format(mention=member.mention),
            ephemeral=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    # -- /vreturn + !vdel ------------------------------------------------------------

    @commands.hybrid_command(
        name="vreturn", description="Разбанить %username% в приватном войс канале"
    )
    @app_commands.guild_only()
    @app_commands.describe(target="Упоминание или id")
    async def vreturn(self, ctx: commands.Context, target: str) -> None:
        text = await self._unban(invoker_id=ctx.author.id, guild=ctx.guild, raw_target=target)
        await ctx.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none())

    @commands.command(name="vdel")
    async def vdel(self, ctx: commands.Context, target: str) -> None:
        if ctx.guild is not None:
            return  # только в ЛС с ботом
        text = await self._unban(
            invoker_id=ctx.author.id, guild=self._guild(ctx), raw_target=target
        )
        await ctx.send(text, allowed_mentions=discord.AllowedMentions.none())

    async def _unban(self, *, invoker_id: int, guild: discord.Guild | None, raw_target: str) -> str:
        target_id = parse_target_id(raw_target)
        if target_id is None:
            return _ERR_NOT_BANNED
        if not await self.banlist.remove(invoker_id, target_id):
            return _ERR_NOT_BANNED
        if guild is not None:
            channel = await self._active_room(guild, invoker_id)
            if channel is not None:
                await self._clear_room_deny(channel, target_id)
        return _VRETURN_OK.format(mention=f"<@{target_id}>")

    # -- /ban_list ----------------------------------------------------------------

    @commands.hybrid_command(name="ban_list", description="Управление бан-списком приваток")
    async def ban_list(self, ctx: commands.Context) -> None:
        entries = await self.banlist.list_for(ctx.author.id)
        try:
            for embed in build_banlist_embeds([e.banned_id for e in entries]):
                await ctx.author.send(embed=embed)
        except discord.HTTPException:
            await ctx.send(_BANLIST_DM_FAIL)
            return
        await ctx.send(_BANLIST_SENT)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoicesSelfmod(bot))  # type: ignore[arg-type]
