"""Массовое удаление сообщений — ``!purge`` (см. ``purge.md``).

**Только префиксная** (``/purge``/``?purge`` — это Dyno, другой бот). Не hybrid,
не в дереве команд → глобальный гейт Command Permissions её не трогает; собственный
гейт — эффективное право ``Manage Messages`` у вызвавшего в этом канале.

Запасной контур на случай отказа Dyno. Хранилища нет.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import timedelta
from enum import Enum
from typing import TYPE_CHECKING

import discord
from discord.ext import commands
from discord.utils import utcnow

from connor.core.channels import in_roddom
from connor.core.targets import parse_target_id

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_BULK_DELETE_MAX = 100
_BULK_DELETE_AGE_DAYS = 14

_MODES = frozenset({"user", "match", "not", "links", "images", "text"})
_SIMPLE_MODES = frozenset({"links", "images", "text"})  # <mode> <count>

_LINK_RE = re.compile(r"https?://\S+", re.IGNORECASE)


class PurgeError(Enum):
    BAD_COUNT = "Количество указано не верно"
    BAD_SYNTAX = "Команда указана не верно."

    @property
    def text(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class PurgeSpec:
    mode: str  # all / user / match / not / links / images / text
    count: int
    text: str = ""
    user_id: int = 0


@dataclass(frozen=True, slots=True)
class MsgView:
    author_id: int
    text: str
    has_link: bool
    has_image: bool
    has_attachment: bool


def _parse_count(token: str) -> int | None:
    if not token.isdigit():  # отсекает "-5", "3.5", "+5", "abc", ""
        return None
    value = int(token)
    return value if value > 0 else None


def parse_purge_args(args: list[str]) -> PurgeSpec | PurgeError:
    """Разбор аргументов ``!purge`` (без учёта прав/канала — это раньше по коду)."""
    if not args:
        return PurgeError.BAD_COUNT

    head = args[0].lower()

    if head not in _MODES:
        # !purge <count>
        if len(args) != 1:
            return PurgeError.BAD_SYNTAX
        count = _parse_count(args[0])
        return PurgeSpec("all", count) if count is not None else PurgeError.BAD_COUNT

    if head in _SIMPLE_MODES:
        if len(args) < 2:
            return PurgeError.BAD_COUNT
        if len(args) > 2:
            return PurgeError.BAD_SYNTAX
        count = _parse_count(args[1])
        return PurgeSpec(head, count) if count is not None else PurgeError.BAD_COUNT

    if head == "user":
        if len(args) < 2:
            return PurgeError.BAD_COUNT  # только "user"
        user_id = parse_target_id(args[1])
        if user_id is None:
            return PurgeError.BAD_SYNTAX
        if len(args) < 3:
            return PurgeError.BAD_COUNT  # count отсутствует
        if len(args) > 3:
            return PurgeError.BAD_SYNTAX
        count = _parse_count(args[2])
        return (
            PurgeSpec("user", count, user_id=user_id) if count is not None else PurgeError.BAD_COUNT
        )

    # match / not: <mode> <текст...> <count>
    if len(args) < 2:
        return PurgeError.BAD_COUNT
    count = _parse_count(args[-1])
    if count is None:
        return PurgeError.BAD_COUNT
    text = " ".join(args[1:-1])
    if not text:
        return PurgeError.BAD_SYNTAX
    return PurgeSpec(head, count, text=text)


def message_matches(spec: PurgeSpec, view: MsgView) -> bool:
    match spec.mode:
        case "all":
            return True
        case "user":
            return view.author_id == spec.user_id
        case "match":
            return spec.text.casefold() in view.text.casefold()
        case "not":
            return spec.text.casefold() not in view.text.casefold()
        case "links":
            return view.has_link
        case "images":
            return view.has_image
        case "text":
            return not view.has_link and not view.has_attachment
        case _:
            return False


def _view(message: discord.Message) -> MsgView:
    text = message.content or ""
    return MsgView(
        author_id=message.author.id,
        text=text,
        has_link=bool(_LINK_RE.search(text)),
        has_image=any((att.content_type or "").startswith("image/") for att in message.attachments),
        has_attachment=len(message.attachments) > 0,
    )


def build_purge_log_embed(
    *, author_global_name: str, author_icon: str | None, nick_text: str, raw_args: str, channel: str
) -> discord.Embed:
    embed = discord.Embed(
        description=f"{nick_text} использовал :pudge: {raw_args} в канале {channel}"
    )
    embed.set_author(name=author_global_name, icon_url=author_icon)
    return embed


class Purge(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self._bot_commands_missing_logged = False

    @commands.command(name="purge")
    @commands.guild_only()
    async def purge(self, ctx: commands.Context, *args: str) -> None:
        # 1. право — эффективное Manage Messages в этом канале; нет → тихо
        if not ctx.channel.permissions_for(ctx.author).manage_messages:
            return
        # 2. категория «роддом» → тихо
        if in_roddom(ctx.channel, self.bot.config.categories["RODDOM"]):
            return
        # 3. разбор
        result = parse_purge_args(list(args))
        if isinstance(result, PurgeError):
            await ctx.send(result.text)
            return

        await self._run_purge(ctx, result)
        await ctx.send(":pudge:")
        await self._log(ctx, list(args))

    async def _run_purge(self, ctx: commands.Context, spec: PurgeSpec) -> None:
        limit = min(spec.count, self.bot.config.purge.soft_limit)
        cutoff = utcnow() - timedelta(days=_BULK_DELETE_AGE_DAYS)

        collected: list[discord.Message] = []
        async for message in ctx.channel.history(
            limit=None, before=ctx.message, after=cutoff, oldest_first=False
        ):
            if message.author.bot:  # чужих ботов (в т.ч. Dyno) не трогаем
                continue
            if message_matches(spec, _view(message)):
                collected.append(message)
                if len(collected) >= limit:
                    break

        for start in range(0, len(collected), _BULK_DELETE_MAX):
            chunk = collected[start : start + _BULK_DELETE_MAX]
            if len(chunk) == 1:
                await chunk[0].delete()
            else:
                await ctx.channel.delete_messages(chunk)

    async def _log(self, ctx: commands.Context, args: list[str]) -> None:
        channel_id = self.bot.config.channels["BOT_KOMANDY"]
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            if not self._bot_commands_missing_logged:
                log.error("канал #бот-команды (ID=%d) не найден — лог !purge пропущен", channel_id)
                self._bot_commands_missing_logged = True
            return
        author = ctx.author
        embed = build_purge_log_embed(
            author_global_name=author.global_name or author.name,
            author_icon=author.display_avatar.url,
            nick_text=author.display_name,
            raw_args=" ".join(args),
            channel=ctx.channel.mention,
        )
        await channel.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Purge(bot))  # type: ignore[arg-type]
