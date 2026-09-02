"""Мелкие некатегорийные команды (не модерация).

Пока одна — шуточная ``!kiss`` (см. ``Home.md``): только префиксная (slash-варианта
нет), без канальных ограничений, но с **глобальным** кулдауном 5 минут на весь
сервер — не чаще одного ответа в 5 минут независимо от того, кто и где вызвал.
"""

from __future__ import annotations

from time import monotonic
from typing import TYPE_CHECKING

from discord.ext import commands

if TYPE_CHECKING:
    from connor.bot import ConnorBot

_KISS_REPLY = "Дядь, ты дурак?"
_KISS_COOLDOWN_SECONDS = 5 * 60


class Misc(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self._last_kiss: float | None = None  # monotonic() последнего ОТВЕТА

    @commands.command(name="kiss")
    async def kiss(self, ctx: commands.Context) -> None:
        now = monotonic()
        if self._last_kiss is not None and now - self._last_kiss < _KISS_COOLDOWN_SECONDS:
            return  # ещё на кулдауне — молчим, окно не продлеваем
        self._last_kiss = now
        await ctx.send(_KISS_REPLY)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Misc(bot))  # type: ignore[arg-type]
