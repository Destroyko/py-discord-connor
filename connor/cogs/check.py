"""Проверка доступа в «предложку» — ``/check`` / ``!check`` (см. ``check.md``).

Доступ на **запись** в «предложку» закрывается анти-работягам точечным per-user
overwrite (``connor/predlozhka.py``). Этот модуль:
- отвечает пользователю, есть ли у него доступ (только факт, без причины);
- лениво ставит запрет: анти-работяга написал в «предложку» → удалить + deny;
- на ``/check`` чинит рассинхрон (устаревший бот-овый overwrite при снятом
  анти-статусе).

Читает анти-статус (``RepoAnti``), сам анти-список не держит.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from connor.core.msg_guard import should_process_message
from connor.core.resolve import EntityResolver
from connor.db.repo_anti import RepoAnti
from connor.db.repo_predlozhka import RepoPredlozhka
from connor.predlozhka import apply_deny, clear_deny

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_ACCESS_OPEN = "Доступ открыт"
_ACCESS_DENIED = "Недостаточно прав"


class Check(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self.anti_repo = RepoAnti(bot.db)
        self.pred_repo = RepoPredlozhka(bot.db)
        self._resolver = EntityResolver(log)

    def _predlozhka(self, guild: discord.Guild) -> discord.abc.GuildChannel | None:
        return self._resolver.channel(guild, self.bot.config.channels["PREDLOZHKA"], "#предложка")

    @commands.hybrid_command(name="check", description="Проверить доступ в предложку")
    @app_commands.guild_only()
    async def check(self, ctx: commands.Context) -> None:
        guild = ctx.guild
        assert guild is not None
        member = ctx.author
        assert isinstance(member, discord.Member)

        is_anti = await self.anti_repo.contains(member.id)
        predlozhka = self._predlozhka(guild)
        if predlozhka is None:
            await ctx.reply(_ACCESS_DENIED)
            return

        # реконсиляция: бот-овый deny висит, а анти-статуса уже нет — снять
        if not is_anti and await self.pred_repo.contains(member.id):
            await clear_deny(predlozhka, member, self.pred_repo)

        has_access = predlozhka.permissions_for(member).send_messages
        await ctx.reply(_ACCESS_OPEN if (has_access and not is_anti) else _ACCESS_DENIED)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Ленивая простановка запрета: анти-работяга написал в «предложку»."""
        if not should_process_message(message) or message.guild is None:
            return
        if message.channel.id != self.bot.config.channels["PREDLOZHKA"]:
            return
        if not await self.anti_repo.contains(message.author.id):
            return

        try:
            await message.delete()
        except discord.HTTPException:
            pass
        if isinstance(message.author, discord.Member):
            await apply_deny(
                message.channel,  # type: ignore[arg-type]
                message.author,
                self.pred_repo,
                reason="анти-работяга: сообщение в предложке",
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Check(bot))  # type: ignore[arg-type]
