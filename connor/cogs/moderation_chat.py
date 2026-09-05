"""Пассивный мониторинг сообщений — слова, обход автомода и медиа
(см. ``moderationChat.md``).

Текст: два критерия с приоритетом (в ``#чек-лист`` уходит **один** embed):
- **обход автомода** → красный embed. Банворды бот читает из правил Discord
  AutoMod (тип «keyword», только включённые) по API и ловит сообщения, которые
  проскочили родной фильтр за счёт подмены букв на похожие из другого алфавита
  или разделителей между буквами (``с п а м``, ``го йда``). См. ``core/automod_mirror``;
- **подозрительное слово** → жёлтый embed (список подстрок из конфига).
Медиа — независимо: пересылка вложений (`proxy_url`) + метаданных в ``#чек-лист2``.

Над оригинальным сообщением бот ничего не делает (не удаляет, не реагирует).
"""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Iterable
from typing import TYPE_CHECKING
from urllib.parse import urlsplit

import discord
from discord.ext import commands

from connor.core import deobfuscate
from connor.core.automod_mirror import AutoModKeywords, BypassHit
from connor.core.channels import in_roddom
from connor.core.msg_guard import should_process_message
from connor.core.resolve import EntityResolver

if TYPE_CHECKING:
    from connor.bot import ConnorBot
    from connor.config import ModerationChatConfig

log = logging.getLogger(__name__)

_URL_RE = re.compile(r"https?://\S+")
_TRAILING = ").,!?;\"'>"
_FIELD_MAX = 1024

# CDN Discord отдаёт по одним хостам и вложения, и эмодзи/стикеры/аватары. «Медиа»
# для #чек-лист2 — только вложения (путь /attachments/...): эмодзи из внешнего
# набора Discord подставляет в текст как markdown-ссылку на .webp и это не контент.
_DISCORD_CDN = ("discordapp.com", "discordapp.net")

_SUSPICIOUS_COLOUR = discord.Colour.gold()  # 0xF1C40F — предупреждение
_BYPASS_COLOUR = discord.Colour(0xFF0000)  # обход банворда автомода


def find_suspicious(text: str, words: Iterable[str]) -> str | None:
    """Первое подозрительное слово-подстрока (без учёта регистра, без границ слова)."""
    lowered = text.casefold()
    for word in words:
        if word and word.casefold() in lowered:
            return word
    return None


def _host_matches(host: str, domains: Iterable[str]) -> bool:
    return any(host == d or host.endswith("." + d) for d in domains)


def extract_gif_links(text: str, gif_domains: Iterable[str]) -> list[str]:
    """URL из текста, чей хост входит в список GIF-провайдеров (или его поддомен).

    Для CDN Discord дополнительно требуется путь ``/attachments/`` — иначе сюда
    попадают ссылки на эмодзи/стикеры (не контент сообщения).
    """
    domains = tuple(d.casefold().lstrip(".") for d in gif_domains if d)
    if not domains:
        return []
    found: list[str] = []
    for raw in _URL_RE.findall(text):
        url = raw.rstrip(_TRAILING)
        split = urlsplit(url)
        host = (split.hostname or "").casefold()
        if not host or not _host_matches(host, domains):
            continue
        if _host_matches(host, _DISCORD_CDN) and "/attachments/" not in split.path.casefold():
            continue
        found.append(url)
    return found


def _source_title(channel: discord.abc.GuildChannel | discord.Thread) -> str:
    return f"#{getattr(channel, 'name', 'канал')}"


def build_word_embed(
    *,
    source_title: str,
    author_mention: str,
    content: str,
    jump_url: str,
    colour: discord.Colour | None = None,
    matched: str | None = None,
) -> discord.Embed:
    embed = discord.Embed(title=source_title, colour=colour)
    embed.add_field(name="Автор", value=author_mention, inline=False)
    embed.add_field(name="Содержание", value=(content[:_FIELD_MAX] or "—"), inline=False)
    if matched is not None:
        embed.add_field(name="Совпадение", value=(matched[:_FIELD_MAX] or "—"), inline=False)
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
        self._resolver = EntityResolver(log)
        self._automod = AutoModKeywords.empty()
        self._automod_ready = False
        self._exempt_channels: frozenset[int] = frozenset()
        self._exempt_roles: frozenset[int] = frozenset()
        self._sync_lock = asyncio.Lock()

    @property
    def _mc(self) -> ModerationChatConfig:
        return self.bot.config.moderation_chat

    @property
    def _words(self) -> tuple[str, ...]:
        return self._mc.suspicious_words

    @property
    def _gif_domains(self) -> tuple[str, ...]:
        return self._mc.gif_domains

    def _channel(self, channel_id: int, label: str) -> discord.abc.Messageable | None:
        return self._resolver.channel(self.bot, channel_id, label)

    # -- синхронизация банвордов с Discord AutoMod -------------------------------

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        await self._sync_automod()

    @commands.Cog.listener()
    async def on_automod_rule_create(self, rule: discord.AutoModRule) -> None:
        await self._sync_automod()

    @commands.Cog.listener()
    async def on_automod_rule_update(self, rule: discord.AutoModRule) -> None:
        await self._sync_automod()

    @commands.Cog.listener()
    async def on_automod_rule_delete(self, rule: discord.AutoModRule) -> None:
        await self._sync_automod()

    async def _sync_automod(self) -> None:
        if not self._mc.automod_bypass_enabled:
            return
        # события правил могут прийти пачкой одновременно с on_ready — сериализуем,
        # чтобы поздний fetch не перезаписался ранним
        async with self._sync_lock:
            guild = self.bot.get_guild(self.bot.config.guild_id)
            if guild is None:
                return
            try:
                rules = await guild.fetch_automod_rules()
            except discord.HTTPException as exc:
                log.error(
                    "не удалось прочитать правила AutoMod (%s) — детект обхода неактивен "
                    "до следующей синхронизации",
                    exc,
                )
                return

            keyword_filter: list[str] = []
            allow_list: list[str] = []
            regex_patterns: list[str] = []
            exempt_channels: set[int] = set()
            exempt_roles: set[int] = set()
            for rule in rules:
                trigger = rule.trigger
                if not rule.enabled or trigger.type is not discord.AutoModRuleTriggerType.keyword:
                    continue
                keyword_filter += trigger.keyword_filter
                allow_list += trigger.allow_list
                regex_patterns += trigger.regex_patterns
                exempt_channels |= set(rule.exempt_channel_ids)
                exempt_roles |= set(rule.exempt_role_ids)

            self._automod = AutoModKeywords.build(
                keyword_filter,
                allow_list,
                regex_patterns,
                collapse_min=self._mc.collapse_repeats_min,
                ignore=self._mc.automod_bypass_ignore,
            )
            self._exempt_channels = frozenset(exempt_channels)
            self._exempt_roles = frozenset(exempt_roles)
            self._automod_ready = True
            log.info(
                "AutoMod-обход: ключевых слов %d, regex %d",
                self._automod.keyword_count,
                self._automod.regex_count,
            )

    # -- листенер сообщений ------------------------------------------------------

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if not should_process_message(message) or message.guild is None:
            return
        if in_roddom(message.channel, self.bot.config.categories["RODDOM"]):
            return
        await self._check_text(message)
        await self._check_media(message)

    async def _check_text(self, message: discord.Message) -> None:
        content = message.content or ""
        if not content:
            return

        bypass = self._detect_bypass(message, content)
        if bypass is not None:
            await self._forward_text(
                message, colour=_BYPASS_COLOUR, matched=f"{bypass.keyword} · {bypass.form}"
            )
            return

        if find_suspicious(content, self._words) is not None:
            await self._forward_text(message, colour=_SUSPICIOUS_COLOUR, matched=None)

    def _detect_bypass(self, message: discord.Message, content: str) -> BypassHit | None:
        if not (self._mc.automod_bypass_enabled and self._automod_ready):
            return None
        if self._automod.keyword_count == 0 and self._automod.regex_count == 0:
            return None
        channel = message.channel
        if channel.id in self._exempt_channels:
            return None
        if getattr(channel, "parent_id", None) in self._exempt_channels:  # тред → родитель
            return None
        author_role_ids = {getattr(r, "id", 0) for r in getattr(message.author, "roles", ())}
        if author_role_ids & self._exempt_roles:
            return None
        base, norm = deobfuscate.variants(content, collapse_min=self._mc.collapse_repeats_min)
        return self._automod.find_bypass(raw=base, norm=norm)

    async def _forward_text(
        self, message: discord.Message, *, colour: discord.Colour, matched: str | None
    ) -> None:
        channel = self._channel(self.bot.config.channels["CHEKLIST"], "#чек-лист")
        if channel is None:
            return
        await channel.send(
            embed=build_word_embed(
                source_title=_source_title(message.channel),
                author_mention=message.author.mention,
                content=message.content or "",
                jump_url=message.jump_url,
                colour=colour,
                matched=matched,
            )
        )

    async def _check_media(self, message: discord.Message) -> None:
        attachment_refs = [att.proxy_url for att in message.attachments]
        gif_links = extract_gif_links(message.content or "", self._gif_domains)
        if not attachment_refs and not gif_links:
            return
        channel = self._channel(self.bot.config.channels["CHEKLIST2"], "#чек-лист2")
        if channel is None:
            return

        # 1. контент: текст первой строкой (если был) + все ссылки одним сообщением.
        # GIF-пикер Discord кладёт саму ссылку на гифку в message.content — если это
        # весь текст сообщения, комментария автора тут нет, дублировать ссылку не нужно.
        # Ссылка может быть обёрнута в markdown [текст](ссылка) (так Discord вставляет
        # внешний эмодзи) — снимаем обёртку целиком, иначе останется «[текст]()».
        comment = message.content or ""
        for link in gif_links:
            comment = re.sub(
                r"\[[^\]]*\]\(\s*" + re.escape(link) + r"[^)]*\)", "", comment
            )
            comment = comment.replace(link, "")
        comment = comment.strip()

        parts: list[str] = []
        if comment:
            parts.append(comment)
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
