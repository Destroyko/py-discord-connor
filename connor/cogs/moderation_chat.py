"""Пассивный мониторинг сообщений — слова и медиа (см. ``moderationChat.md``).

Два независимых критерия, каждый проверяется сам по себе:
- **слова** → пересылка embed в ``#чек-лист`` (только текст сообщения);
- **медиа** → пересылка вложений (`proxy_url`) + метаданных в ``#чек-лист2``.

Над оригинальным сообщением бот ничего не делает (не удаляет, не реагирует).
Автономный модуль: своё состояние — конфиг-файл со списками слов и GIF-доменов.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import discord
from discord.ext import commands

from connor.core.channels import in_roddom
from connor.core.msg_guard import should_process_message

if TYPE_CHECKING:
    from connor.bot import ConnorBot

log = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")
_TRAILING = ").,!?;\"'>"
_FIELD_MAX = 1024


def find_suspicious(text: str, words: Iterable[str]) -> str | None:
    """Первое подозрительное слово-подстрока (без учёта регистра, без границ слова)."""
    lowered = text.casefold()
    for word in words:
        if word and word.casefold() in lowered:
            return word
    return None


def extract_gif_links(text: str, gif_domains: Iterable[str]) -> list[str]:
    """URL из текста, чей хост входит в список GIF-провайдеров (или его поддомен)."""
    domains = tuple(d.casefold().lstrip(".") for d in gif_domains if d)
    if not domains:
        return []
    found: list[str] = []
    for raw in _URL_RE.findall(text):
        url = raw.rstrip(_TRAILING)
        host = (urlsplit(url).hostname or "").casefold()
        if host and any(host == d or host.endswith("." + d) for d in domains):
            found.append(url)
    return found


def _source_title(channel: discord.abc.GuildChannel | discord.Thread) -> str:
    return f"#{getattr(channel, 'name', 'канал')}"


def build_word_embed(
    *, source_title: str, author_mention: str, content: str, jump_url: str
) -> discord.Embed:
    embed = discord.Embed(title=source_title)
    embed.add_field(name="Автор", value=author_mention, inline=False)
    embed.add_field(name="Содержание", value=(content[:_FIELD_MAX] or "—"), inline=False)
    embed.add_field(name="Ссылка на пост", value=jump_url, inline=False)
    return embed


def build_media_meta_embed(
    *, source_title: str, author_mention: str, jump_url: str
) -> discord.Embed:
    embed = discord.Embed(title=source_title)
    embed.add_field(name="Автор", value=author_mention, inline=False)
    embed.add_field(name="Ссылка на пост", value=jump_url, inline=False)
    return embed


class ModerationChat(commands.Cog):
    def __init__(self, bot: ConnorBot) -> None:
        self.bot = bot
        self._missing_logged: set[int] = set()

    @property
    def _words(self) -> tuple[str, ...]:
        return self.bot.config.moderation_chat.suspicious_words

    @property
    def _gif_domains(self) -> tuple[str, ...]:
        return self.bot.config.moderation_chat.gif_domains

    def _channel(self, channel_id: int) -> discord.abc.Messageable | None:
        channel = self.bot.get_channel(channel_id)
        if channel is None and channel_id not in self._missing_logged:
            log.error("канал ID=%d не найден — пересылка moderationChat пропущена", channel_id)
            self._missing_logged.add(channel_id)
        return channel

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not should_process_message(message) or message.guild is None:
            return
        if in_roddom(message.channel, self.bot.config.categories["RODDOM"]):
            return
        await self._check_words(message)
        await self._check_media(message)

    async def _check_words(self, message: discord.Message) -> None:
        if find_suspicious(message.content or "", self._words) is None:
            return
        channel = self._channel(self.bot.config.channels["CHEKLIST"])
        if channel is None:
            return
        await channel.send(
            embed=build_word_embed(
                source_title=_source_title(message.channel),
                author_mention=message.author.mention,
                content=message.content or "",
                jump_url=message.jump_url,
            )
        )

    async def _check_media(self, message: discord.Message) -> None:
        attachment_refs = [att.proxy_url for att in message.attachments]
        gif_links = extract_gif_links(message.content or "", self._gif_domains)
        if not attachment_refs and not gif_links:
            return
        channel = self._channel(self.bot.config.channels["CHEKLIST2"])
        if channel is None:
            return

        # 1. контент: текст первой строкой (если был) + все ссылки одним сообщением
        parts: list[str] = []
        if message.content:
            parts.append(message.content)
        parts.extend(attachment_refs + gif_links)
        await channel.send("\n".join(parts))

        # 2. отдельным сообщением — метаданные
        await channel.send(
            embed=build_media_meta_embed(
                source_title=_source_title(message.channel),
                author_mention=message.author.mention,
                jump_url=message.jump_url,
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ModerationChat(bot))  # type: ignore[arg-type]
