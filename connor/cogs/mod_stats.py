"""``/mutestats`` и ``/givestats`` — статистика по модераторам.

Доки: ``mute.md`` и ``roleGiver.md``, раздел «Статистика».

Slash-only, ответ ephemeral, доступ через штатные Command Permissions
(``default_member_permissions = moderate_members``). Один эфемерный embed с
выпадающим фильтром периода (30 дней … за всё время) и кнопками пред/след
страницы; управлять панелью может только вызвавший. Окно живёт 5 минут, затем
элементы гаснут. Смена периода сбрасывает на первую страницу.

В список попадают только модераторы, которые сейчас резолвятся как участники
сервера и имеют право ``moderate_members`` — выбывшие отсеиваются.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

import discord
from discord import app_commands
from discord.ext import commands
from discord.utils import utcnow

from connor.db.repo_give_stats import RepoGiveStats
from connor.db.repo_mute_stats import RepoMuteStats

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_PAGE = 20
_VIEW_TIMEOUT = 300.0
_NOT_YOURS = "Панелью управляет только тот, кто вызвал команду."
_VIEW_ERROR = "Что-то пошло не так. Откройте команду заново."

_MUTE_TITLE = "Муты по модераторам"
_MUTE_EMPTY = "За выбранный период мутов нет"
_GIVE_TITLE = "Обработка заявок на работягу по модераторам"
_GIVE_EMPTY = "За выбранный период обработанных заявок нет"

# value выпадашки — число дней; "0" = за всё время
_PERIODS: tuple[tuple[str, str], ...] = (
    ("Последние 30 дней", "30"),
    ("Последние 3 месяца", "90"),
    ("Последние полгода", "180"),
    ("Последний год", "365"),
    ("За всё время", "0"),
)
_PERIOD_FOOTER = {
    "30": "за 30 дней",
    "90": "за 3 месяца",
    "180": "за полгода",
    "365": "за год",
    "0": "за всё время",
}
_DEFAULT_PERIOD = "30"

_Row = tuple[discord.Member, str]
#: (guild, нижняя граница по времени, кэш резолва id → участник) → строки ладдера
_ResolveCache = dict[int, discord.Member | None]
_Fetch = Callable[[discord.Guild, int, _ResolveCache], Awaitable[list[_Row]]]


def _since_ts(period: str) -> int:
    """Нижняя граница ``created_at``/``decided_at`` по выбранному периоду;
    скользящее окно от «сейчас». ``"0"`` (за всё время) → ``0``."""
    days = int(period)
    return 0 if days == 0 else int(utcnow().timestamp()) - days * 86400


async def _active_moderator(
    guild: discord.Guild, user_id: int, cache: _ResolveCache
) -> discord.Member | None:
    """Участник сервера с правом ``moderate_members`` — иначе ``None`` (выбыл,
    удалил аккаунт или лишён прав модерации).

    Член-кэш у бота частичный (см. bot.py) — ``get_member`` почти всегда ``None``,
    поэтому фолбэк на ``fetch_member`` (запрос к API). Результат резолва кэшируется
    на время жизни панели: пагинация и смена периода не дёргают API повторно."""
    if user_id not in cache:
        member = guild.get_member(user_id)
        if member is None:
            try:
                member = await guild.fetch_member(user_id)
            except discord.HTTPException:
                member = None
        cache[user_id] = member
    member = cache[user_id]
    if member is None or not member.guild_permissions.moderate_members:
        return None
    return member


class _StatsView(discord.ui.View):
    def __init__(
        self, *, invoker_id: int, guild: discord.Guild, title: str, empty: str, fetch: _Fetch
    ) -> None:
        super().__init__(timeout=_VIEW_TIMEOUT)
        self._invoker_id = invoker_id
        self._guild = guild
        self._title = title
        self._empty = empty
        self._fetch = fetch
        self._period = _DEFAULT_PERIOD
        self._page = 0
        self._rows: list[_Row] = []
        self._resolved: _ResolveCache = {}
        self.message: discord.Message | None = None

    async def start(self, interaction: discord.Interaction) -> None:
        """Вызывается после ``interaction.response.defer(ephemeral=True)`` —
        резолв модераторов ходит в API, в 3 c ответа можно не уложиться."""
        await self._reload()
        self.message = await interaction.followup.send(
            embed=self._embed(),
            view=self,
            ephemeral=True,
            wait=True,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self._invoker_id:
            await interaction.response.send_message(_NOT_YOURS, ephemeral=True)
            return False
        return True

    async def on_timeout(self) -> None:
        self._pick_period.disabled = True
        self._prev.disabled = True
        self._next.disabled = True
        if self.message is not None:
            try:
                await self.message.edit(view=self)
            except discord.HTTPException:
                pass

    async def on_error(
        self, interaction: discord.Interaction, error: Exception, item: discord.ui.Item
    ) -> None:
        """Русский fallback вместо служебного «This interaction failed» Discord."""
        log.error("mod_stats: сбой обработки %r", item, exc_info=error)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(_VIEW_ERROR, ephemeral=True)
            else:
                await interaction.response.send_message(_VIEW_ERROR, ephemeral=True)
        except discord.HTTPException:
            pass

    # -- данные ----------------------------------------------------------------

    async def _reload(self) -> None:
        self._rows = await self._fetch(self._guild, _since_ts(self._period), self._resolved)
        self._page = 0
        self._sync_buttons()

    @property
    def _pages(self) -> int:
        return max(1, math.ceil(len(self._rows) / _PAGE))

    def _sync_buttons(self) -> None:
        self._prev.disabled = self._page <= 0
        self._next.disabled = self._page >= self._pages - 1

    def _embed(self) -> discord.Embed:
        if not self._rows:
            return discord.Embed(title=self._title, description=self._empty)
        start = self._page * _PAGE
        lines = [
            f"{start + i}. {member.mention} - {metric}"
            for i, (member, metric) in enumerate(self._rows[start : start + _PAGE], 1)
        ]
        embed = discord.Embed(title=self._title, description="\n".join(lines))
        embed.set_footer(
            text=f"{_PERIOD_FOOTER[self._period]} · стр. {self._page + 1}/{self._pages} "
            f"· модераторов: {len(self._rows)}"
        )
        return embed

    async def _rerender(self, interaction: discord.Interaction) -> None:
        # кнопки отвечают сразу (edit_message); смена периода сначала делает defer
        # под резолв модераторов — тогда правим уже через edit_original_response
        if interaction.response.is_done():
            await interaction.edit_original_response(
                embed=self._embed(),
                view=self,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        else:
            await interaction.response.edit_message(
                embed=self._embed(),
                view=self,
                allowed_mentions=discord.AllowedMentions.none(),
            )

    # -- элементы ------------------------------------------------------------------

    @discord.ui.select(
        placeholder="Период",
        row=0,
        options=[
            discord.SelectOption(label=label, value=value, default=value == _DEFAULT_PERIOD)
            for label, value in _PERIODS
        ],
    )
    async def _pick_period(
        self, interaction: discord.Interaction, select: discord.ui.Select
    ) -> None:
        self._period = select.values[0]
        for opt in select.options:
            opt.default = opt.value == self._period
        await interaction.response.defer()  # резолв может ходить в API
        await self._reload()
        await self._rerender(interaction)

    @discord.ui.button(label="◀", style=discord.ButtonStyle.secondary, row=1)
    async def _prev(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self._page = max(0, self._page - 1)
        self._sync_buttons()
        await self._rerender(interaction)

    @discord.ui.button(label="▶", style=discord.ButtonStyle.secondary, row=1)
    async def _next(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        self._page = min(self._pages - 1, self._page + 1)
        self._sync_buttons()
        await self._rerender(interaction)


class ModStats(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self.mute_stats = RepoMuteStats(bot.db)
        self.give_stats = RepoGiveStats(bot.db)

    @app_commands.command(name="mutestats", description="Статистика выданных мьютов по модераторам")
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    async def mutestats(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True)
        await _StatsView(
            invoker_id=interaction.user.id,
            guild=interaction.guild,
            title=_MUTE_TITLE,
            empty=_MUTE_EMPTY,
            fetch=self._mute_rows,
        ).start(interaction)

    async def _mute_rows(
        self, guild: discord.Guild, since: int, cache: _ResolveCache
    ) -> list[_Row]:
        rows: list[_Row] = []
        for mod_id, count in await self.mute_stats.ladder(since):
            member = await _active_moderator(guild, mod_id, cache)
            if member is not None:
                rows.append((member, str(count)))
        return rows

    @app_commands.command(
        name="givestats",
        description="Статистика обработанных заявок на работягу по модераторам",
    )
    @app_commands.guild_only()
    @app_commands.default_permissions(moderate_members=True)
    async def givestats(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        await interaction.response.defer(ephemeral=True)
        await _StatsView(
            invoker_id=interaction.user.id,
            guild=interaction.guild,
            title=_GIVE_TITLE,
            empty=_GIVE_EMPTY,
            fetch=self._give_rows,
        ).start(interaction)

    async def _give_rows(
        self, guild: discord.Guild, since: int, cache: _ResolveCache
    ) -> list[_Row]:
        rows: list[_Row] = []
        for tally in await self.give_stats.ladder(since):
            member = await _active_moderator(guild, tally.moderator_id, cache)
            if member is not None:
                rows.append((member, f"{tally.total} ({tally.approved}/{tally.refused})"))
        return rows


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModStats(bot))  # type: ignore[arg-type]
