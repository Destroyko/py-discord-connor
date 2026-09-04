"""Недельный лидерборд — ``/ladder`` / ``!ladder`` (см. ``Voices.md`` § "Лидерборд").

В ``#флудиславль``, доступна любому, без аргументов. До 10 строк в порядке
выборки (``points DESC, seq ASC``); упоминания — **без пинга** (текстовое имя),
при нерезолве ника — сырой id. Никто не набрал очков → обычный текст (не embed).
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from connor.db.repo_voice_xp import RepoVoiceXp

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_EMPTY = "недельный ладдер комнат пуст"
_TITLE = "Недельный ладдер комнат"
_COMMENT = "Диего недоумевает, почему он не в топе"


class VoicesLadder(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self.xp = RepoVoiceXp(bot.db)

    async def _name(self, guild: discord.Guild, uid: int) -> str:
        """Упоминание без пинга (``<@id>`` рендерится как имя); сырой id, если
        аккаунт не резолвится вовсе."""
        if guild.get_member(uid) is not None:
            return f"<@{uid}>"
        try:
            await self.bot.fetch_user(uid)
        except discord.HTTPException:
            return str(uid)
        return f"<@{uid}>"

    @commands.hybrid_command(name="ladder", description="Вывести топ-10 недельных румеров")
    @app_commands.guild_only()
    async def ladder(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        assert guild is not None

        top = (await self.xp.standings())[:10]
        if not top:
            await ctx.send(_EMPTY)
            return

        lines = [f"{i}: {await self._name(guild, uid)}" for i, (uid, _pts) in enumerate(top, 1)]
        embed = discord.Embed(title=_TITLE, description="\n".join(lines))
        embed.set_footer(text=_COMMENT)
        await ctx.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoicesLadder(bot))  # type: ignore[arg-type]
