"""``/healthcheck`` — тот же отчёт, что и стартовый preflight, по запросу из Discord
(см. ``development.md`` § "Ручной перезапуск проверки без рестарта бота").

Slash-only (без ``!healthcheck``), ответ ephemeral. Доступ — через штатные Discord
Command Permissions (``default_member_permissions = moderate_members``), без проверки
роли в коде.
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from connor.core import preflight

if TYPE_CHECKING:
    from connor.bot import ConnorBot


class Healthcheck(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot

    @app_commands.command(
        name="healthcheck",
        description="Диагностика бота (роли/каналы/БД/Command Permissions) + аптайм",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    async def healthcheck(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)

        results = await self.bot.run_preflight()
        lines = [r.line for r in results]
        lines.append(preflight.summary_line(results))
        lines.append(_uptime_line(self.bot))

        report = "```\n" + "\n".join(lines) + "\n```"
        await interaction.followup.send(report[:2000], ephemeral=True)


def _uptime_line(bot: ConnorBot) -> str:
    ready_at = getattr(bot, "_ready_at", None)
    if ready_at is None:
        return "Аптайм: н/д"
    return "Аптайм: " + preflight.format_uptime(int(time.monotonic() - ready_at))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Healthcheck(bot))  # type: ignore[arg-type]
