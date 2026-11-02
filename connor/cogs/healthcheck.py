"""``/healthcheck`` — тот же отчёт, что и стартовый preflight, по запросу из Discord
(см. ``development.md`` § "Ручной перезапуск проверки без рестарта бота").

Slash-only (без ``!healthcheck``), ответ ephemeral. Доступ — через штатные Discord
Command Permissions (``default_member_permissions = moderate_members``), без проверки
роли в коде.

В отличие от стартового прогона, команда делает **живую** проверку: права каналов
считаются по свежим данным REST, а не по кэшу, плюс проба чтения журнала аудита.
Ответ — embed: зелёная полоса, если всё в порядке; красная — если есть проблемы,
со списком, чего именно не хватает.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands

from connor.core.preflight import CheckResult
from connor.core.timefmt import format_hms

if TYPE_CHECKING:
    from connor.bot import ConnorBot

_OK = "✅"
_FAIL = "❌"
_MIN_INTERVAL_SECONDS = 10  # живая проверка = десяток REST-запросов: не чаще раза в 10 с
_FIELD_MAX = 1024

#: раздел preflight → заголовок поля в embed'е (порядок — по первому появлению)
_SECTION_TITLES: dict[str, str] = {
    "гильдия": "Базовое",
    "intents": "Базовое",
    "БД": "Базовое",
    "роли": "Роли",
    "права": "Права сервера",
    "каналы": "Каналы и категории",
    "войс": "Войс",
    "Command Permissions API": "Command Permissions API",
}


def _result_line(r: CheckResult) -> str:
    if r.ok:
        tail = f" — {r.detail}" if r.detail else ""
        return f"{_OK} {r.label}{tail}"
    return f"{_FAIL} **{r.label}** — {r.detail or 'ошибка'}"


def build_report_embed(results: list[CheckResult], *, uptime: str) -> discord.Embed:
    problems = [r for r in results if not r.ok]
    if problems:
        embed = discord.Embed(
            title="Диагностика бота",
            colour=discord.Colour.red(),
            description=f"{_FAIL} **Найдено проблем: {len(problems)}**",
        )
    else:
        embed = discord.Embed(
            title="Диагностика бота",
            colour=discord.Colour.green(),
            description=f"{_OK} **Всё в порядке**",
        )

    grouped: dict[str, list[str]] = {}
    for r in results:
        title = _SECTION_TITLES.get(r.section, r.section)
        grouped.setdefault(title, []).append(_result_line(r))
    for title, lines in grouped.items():
        value = "\n".join(lines)
        if len(value) > _FIELD_MAX:
            value = value[: _FIELD_MAX - 1] + "…"
        embed.add_field(name=title, value=value, inline=False)

    if problems:
        verdict = (
            "бот НЕ поднят"
            if any(r.fatal for r in problems)
            else "затронутый функционал отключён, остальное работает"
        )
        embed.add_field(name="Итог", value=verdict, inline=False)
    embed.set_footer(text=uptime)
    return embed


class Healthcheck(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self._lock = asyncio.Lock()
        self._last_run = 0.0

    @app_commands.command(
        name="healthcheck",
        description="Диагностика бота (роли/каналы/права/БД/Command Permissions) + аптайм",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    async def healthcheck(self, interaction: discord.Interaction) -> None:
        if self._lock.locked() or time.monotonic() - self._last_run < _MIN_INTERVAL_SECONDS:
            await interaction.response.send_message(
                "Проверка только что выполнялась. Подождите несколько секунд.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        async with self._lock:
            results = await self.bot.run_preflight(live=True)
            self._last_run = time.monotonic()

        embed = build_report_embed(results, uptime=_uptime_line(self.bot))
        await interaction.followup.send(embed=embed, ephemeral=True)


def _uptime_line(bot: ConnorBot) -> str:
    ready_at = getattr(bot, "_ready_at", None)
    if ready_at is None:
        return "Аптайм: н/д"
    return "Аптайм: " + format_hms(int(time.monotonic() - ready_at))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Healthcheck(bot))  # type: ignore[arg-type]
