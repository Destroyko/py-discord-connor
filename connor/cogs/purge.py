"""Массовое удаление сообщений — ``!purge`` (см. ``purge.md``).

**Только префиксная** (``/purge``/``?purge`` — это Dyno, другой бот). Не hybrid,
не в дереве команд → глобальный гейт Command Permissions её не трогает; собственный
гейт — эффективное право ``Manage Messages`` у вызвавшего в этом канале.

Запасной контур на случай отказа Dyno. Хранилища нет.

Удаляются сообщения любых авторов, включая самого бота и другие боты. Возраст
сообщения не ограничивает: свежие (моложе 14 дней) уходят пачками bulk-delete, более
старые Discord bulk-ом не принимает — их бот удаляет по одному (медленно, упирается в
rate limit, поэтому на время работы в канале горит «печатает…»).
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

from connor.core.authorship import embed_author_icon, embed_author_name
from connor.core.channels import in_roddom
from connor.core.targets import parse_target_id

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_BULK_DELETE_MAX = 100
_BULK_DELETE_AGE_DAYS = 14
#: запас к 14-дневной границе bulk-delete: сообщение, собранное «почти двухнедельным»,
#: к моменту удаления (скан мог идти долго) уже не должно уйти в bulk — Discord отклонит
#: всю пачку целиком
_BULK_DELETE_MARGIN = timedelta(minutes=10)
#: потолок просмотренных сообщений за один вызов. Возраст больше не ограничивает скан,
#: и без потолка редкий фильтр (``user``/``match``) обошёл бы всю историю канала —
#: тысячи запросов к API ради нескольких совпадений
_SCAN_MAX = 10_000

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
    *, author_username: str, author_icon: str | None, mention: str, raw_args: str, channel: str
) -> discord.Embed:
    embed = discord.Embed(
        description=f"{mention} использовал :pudge: {raw_args} в канале {channel}"
    )
    embed.set_author(name=author_username, icon_url=author_icon)
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
        try:
            await ctx.message.delete()
        except discord.HTTPException:
            pass
        await ctx.send(":pudge:")
        await self._log(ctx, list(args))

    async def _run_purge(self, ctx: commands.Context, spec: PurgeSpec) -> None:
        limit = min(spec.count, self.bot.config.purge.soft_limit)

        # долго: скан до _SCAN_MAX сообщений + поштучное удаление старых
        async with ctx.channel.typing():
            collected: list[discord.Message] = []
            async for message in ctx.channel.history(
                limit=_SCAN_MAX, before=ctx.message, oldest_first=False
            ):
                if message_matches(spec, _view(message)):
                    collected.append(message)
                    if len(collected) >= limit:
                        break

            # граница считается после скана — он мог занять минуты
            bulk_cutoff = utcnow() - timedelta(days=_BULK_DELETE_AGE_DAYS) + _BULK_DELETE_MARGIN
            fresh = [m for m in collected if m.created_at > bulk_cutoff]
            old = [m for m in collected if m.created_at <= bulk_cutoff]

            for start in range(0, len(fresh), _BULK_DELETE_MAX):
                chunk = fresh[start : start + _BULK_DELETE_MAX]
                if len(chunk) == 1:
                    await chunk[0].delete()
                else:
                    await ctx.channel.delete_messages(chunk)

            # старше 14 дней bulk-delete недоступен — по одному; rate limit гасит discord.py
            for message in old:
                try:
                    await message.delete()
                except discord.NotFound:
                    pass  # уже удалено (вручную / другим ботом) — цель достигнута

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
            author_username=embed_author_name(author),
            author_icon=embed_author_icon(author),
            mention=author.mention,
            raw_args=" ".join(args),
            channel=ctx.channel.mention,
        )
        await channel.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Purge(bot))  # type: ignore[arg-type]
