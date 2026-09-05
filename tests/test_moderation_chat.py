"""moderationChat: матчер слов, разбор GIF-ссылок, embed."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from connor.cogs.moderation_chat import (
    _BYPASS_COLOUR,
    _SUSPICIOUS_COLOUR,
    ModerationChat,
    build_media_meta_embed,
    build_word_embed,
    extract_gif_links,
    find_suspicious,
)
from connor.core.automod_mirror import AutoModKeywords

_WORDS = ("казино", "промокод", "http://scam")
_GIFS = ("tenor.com", "media.tenor.com")


# --- find_suspicious ---------------------------------------------------------------


def test_word_substring_case_insensitive() -> None:
    assert find_suspicious("зайди в КАЗИНО срочно", _WORDS) == "казино"
    assert find_suspicious("мой промокодик тут", _WORDS) == "промокод"  # часть слова тоже ловится


def test_word_none_when_clean() -> None:
    assert find_suspicious("обычное сообщение", _WORDS) is None
    assert find_suspicious("", _WORDS) is None
    assert find_suspicious("что угодно", ()) is None


def test_word_empty_entries_ignored() -> None:
    assert find_suspicious("hello", ("", "  ")) is None


# --- extract_gif_links -----------------------------------------------------------


def test_gif_links_by_domain_and_subdomain() -> None:
    text = "смотри https://tenor.com/view/cat-12345 и https://media.tenor.com/x.gif"
    assert extract_gif_links(text, _GIFS) == [
        "https://tenor.com/view/cat-12345",
        "https://media.tenor.com/x.gif",
    ]


def test_gif_subdomain_matches_parent_in_list() -> None:
    assert extract_gif_links("https://c.tenor.com/y.gif", ("tenor.com",)) == [
        "https://c.tenor.com/y.gif"
    ]


def test_gif_links_ignores_other_domains_and_trailing_punct() -> None:
    assert extract_gif_links("см. https://example.com/a.gif", _GIFS) == []
    assert extract_gif_links("(https://tenor.com/view/x).", _GIFS) == ["https://tenor.com/view/x"]


def test_gif_links_empty_domain_list() -> None:
    assert extract_gif_links("https://tenor.com/x", ()) == []


_DISCORD_GIFS = ("tenor.com", "discordapp.net", "discordapp.com")


def test_gif_links_discord_cdn_attachment_matches() -> None:
    for url in (
        "https://cdn.discordapp.com/attachments/1/2/pic.png?ex=abc",
        "https://media.discordapp.net/attachments/1/2/clip.mp4",
    ):
        assert extract_gif_links(f"вот {url} смотри", _DISCORD_GIFS) == [url]


def test_gif_links_discord_cdn_non_attachment_ignored() -> None:
    # эмодзи из внешнего набора: Discord вставляет markdown-ссылку на .webp
    emoji = (
        "[aryujinconcerned](https://cdn.discordapp.com/emojis/"
        "691140376798691350.webp?size=48&animated=true&name=aryujinconcerned&lossless=true)"
    )
    assert extract_gif_links(emoji, _DISCORD_GIFS) == []
    assert extract_gif_links("https://cdn.discordapp.com/avatars/1/abc.png", _DISCORD_GIFS) == []


# --- embeds --------------------------------------------------------------------------


def test_build_word_embed() -> None:
    e = build_word_embed(
        source_title="#dota-2",
        author_mention="<@5>",
        content="зайди в казино",
        jump_url="https://discord.com/channels/1/2/3",
    )
    assert e.title == "#dota-2"
    names = [f.name for f in e.fields]
    assert names == ["Автор", "Содержание", "Ссылка на пост"]
    assert e.fields[0].value == "<@5>"
    assert e.fields[1].value == "зайди в казино"
    assert e.fields[2].value == "https://discord.com/channels/1/2/3"


def test_build_word_embed_truncates_and_handles_empty() -> None:
    e = build_word_embed(source_title="#x", author_mention="<@1>", content="a" * 5000, jump_url="u")
    assert len(e.fields[1].value) == 1024
    e2 = build_word_embed(source_title="#x", author_mention="<@1>", content="", jump_url="u")
    assert e2.fields[1].value == "—"


def test_build_word_embed_colour_and_matched() -> None:
    e = build_word_embed(
        source_title="#x",
        author_mention="<@1>",
        content="c",
        jump_url="u",
        colour=_BYPASS_COLOUR,
        matched="спам · подмена символов",
    )
    assert e.colour == _BYPASS_COLOUR
    assert [f.name for f in e.fields] == ["Автор", "Содержание", "Совпадение", "Ссылка на пост"]
    assert e.fields[2].value == "спам · подмена символов"


def test_build_media_meta_embed() -> None:
    e = build_media_meta_embed(source_title="#игровой", author_mention="<@7>", jump_url="u")
    assert e.title == "#игровой"
    assert [f.name for f in e.fields] == ["Автор", "Ссылка на пост"]
    assert isinstance(e, discord.Embed)


# --- ModerationChat._check_media ------------------------------------------------------


def _cog(*, channel: object, gif_domains: tuple[str, ...] = _GIFS) -> ModerationChat:
    config = SimpleNamespace(
        moderation_chat=SimpleNamespace(suspicious_words=(), gif_domains=gif_domains),
        channels={"CHEKLIST2": 999},
    )
    bot = SimpleNamespace(config=config, get_channel=lambda cid: channel if cid == 999 else None)
    return ModerationChat(bot)  # type: ignore[arg-type]


def _message(*, content: str, attachments: list[object] | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        content=content,
        attachments=attachments or [],
        channel=SimpleNamespace(name="общий"),
        author=SimpleNamespace(mention="<@1>"),
        jump_url="https://discord.com/channels/1/2/3",
    )


async def test_check_media_gif_picker_link_not_duplicated() -> None:
    # весь GIF-пикер кладёт ссылку в message.content — без отдельного текста-комментария
    # ссылка не должна попадать в пересылку дважды (как "текст" и как "ссылка")
    channel = SimpleNamespace(send=AsyncMock())
    cog = _cog(channel=channel)

    await cog._check_media(_message(content="https://tenor.com/view/cat-12345"))

    content_msg = channel.send.await_args_list[0].args[0]
    assert content_msg == "https://tenor.com/view/cat-12345"


async def test_check_media_keeps_comment_text_alongside_link() -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _cog(channel=channel)

    await cog._check_media(_message(content="ору с этого https://tenor.com/view/cat-12345"))

    content_msg = channel.send.await_args_list[0].args[0]
    assert content_msg == "ору с этого\nhttps://tenor.com/view/cat-12345"


async def test_check_media_external_emoji_link_not_forwarded() -> None:
    # внешний эмодзи (markdown-ссылка на .webp) — не медиа, в #чек-лист2 не уходит
    channel = SimpleNamespace(send=AsyncMock())
    cog = _cog(channel=channel, gif_domains=("tenor.com", "discordapp.com", "discordapp.net"))

    await cog._check_media(
        _message(
            content="[aryujinconcerned](https://cdn.discordapp.com/emojis/"
            "691140376798691350.webp?size=48&name=aryujinconcerned)"
        )
    )

    channel.send.assert_not_awaited()


async def test_check_media_strips_markdown_link_wrapper() -> None:
    # ссылка обёрнута в markdown [текст](ссылка) — не должно остаться «[текст]()»
    channel = SimpleNamespace(send=AsyncMock())
    cog = _cog(channel=channel)

    await cog._check_media(
        _message(content="[смотри](https://tenor.com/view/cat-12345) ору")
    )

    content_msg = channel.send.await_args_list[0].args[0]
    assert content_msg == "ору\nhttps://tenor.com/view/cat-12345"


# --- ModerationChat._check_text (обход автомода + подозрительные слова) --------------


def _text_cog(
    *,
    channel: object,
    suspicious: tuple[str, ...] = (),
    automod: AutoModKeywords | None = None,
    bypass_enabled: bool = True,
    ignore: tuple[str, ...] = (),
) -> ModerationChat:
    config = SimpleNamespace(
        guild_id=1,
        moderation_chat=SimpleNamespace(
            suspicious_words=suspicious,
            gif_domains=(),
            automod_bypass_enabled=bypass_enabled,
            automod_bypass_ignore=ignore,
            collapse_repeats_min=3,
        ),
        channels={"CHEKLIST": 777},
    )
    bot = SimpleNamespace(
        config=config,
        get_channel=lambda cid: channel if cid == 777 else None,
        get_guild=lambda gid: None,
    )
    cog = ModerationChat(bot)  # type: ignore[arg-type]
    if automod is not None:
        cog._automod = automod
        cog._automod_ready = True
    return cog


def _kw_rule(
    keywords: list[str],
    *,
    enabled: bool = True,
    trigger_type: object | None = None,
    exempt_channels: tuple[int, ...] = (),
    exempt_roles: tuple[int, ...] = (),
) -> object:
    return SimpleNamespace(
        enabled=enabled,
        trigger=SimpleNamespace(
            type=trigger_type or discord.AutoModRuleTriggerType.keyword,
            keyword_filter=keywords,
            allow_list=[],
            regex_patterns=[],
        ),
        exempt_channel_ids=list(exempt_channels),
        exempt_role_ids=list(exempt_roles),
    )


def _text_message(
    content: str,
    *,
    channel_id: int = 1,
    parent_id: int | None = None,
    role_ids: tuple[int, ...] = (),
) -> object:
    return SimpleNamespace(
        content=content,
        channel=SimpleNamespace(id=channel_id, name="общий", parent_id=parent_id),
        author=SimpleNamespace(mention="<@1>", roles=[SimpleNamespace(id=r) for r in role_ids]),
        jump_url="https://discord.com/channels/1/2/3",
    )


def _banwords(*words: str) -> AutoModKeywords:
    return AutoModKeywords.build(list(words), [], [], collapse_min=3)


async def test_text_obfuscated_banword_forwarded_red() -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _text_cog(channel=channel, automod=_banwords("спам"))

    await cog._check_text(_text_message("налетай сп@м"))

    channel.send.assert_awaited_once()
    embed = channel.send.await_args.kwargs["embed"]
    assert embed.colour == _BYPASS_COLOUR
    assert any(f.name == "Совпадение" for f in embed.fields)


async def test_text_spaced_banword_forwarded_red() -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _text_cog(channel=channel, automod=_banwords("спам"))

    await cog._check_text(_text_message("смотри с п а м"))

    assert channel.send.await_args.kwargs["embed"].colour == _BYPASS_COLOUR


async def test_text_plain_banword_is_not_bypass_but_hits_suspicious() -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _text_cog(channel=channel, suspicious=("спам",), automod=_banwords("спам"))

    await cog._check_text(_text_message("это просто спам"))

    embed = channel.send.await_args.kwargs["embed"]
    assert embed.colour == _SUSPICIOUS_COLOUR
    assert not any(f.name == "Совпадение" for f in embed.fields)


async def test_text_cooccurrence_sends_single_red_embed() -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _text_cog(channel=channel, suspicious=("казино",), automod=_banwords("спам"))

    await cog._check_text(_text_message("сп@м и казино рядом"))

    channel.send.assert_awaited_once()
    assert channel.send.await_args.kwargs["embed"].colour == _BYPASS_COLOUR


async def test_text_clean_message_is_silent() -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _text_cog(channel=channel, suspicious=("казино",), automod=_banwords("спам"))

    await cog._check_text(_text_message("совершенно обычный текст"))

    channel.send.assert_not_awaited()


async def test_text_bypass_disabled_skips_detection() -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _text_cog(
        channel=channel, suspicious=("спам",), automod=_banwords("спам"), bypass_enabled=False
    )

    await cog._check_text(_text_message("с п а м"))  # обход не проверяется вообще

    channel.send.assert_not_awaited()


async def test_text_exempt_channel_skips_bypass() -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _text_cog(channel=channel, automod=_banwords("спам"))
    cog._exempt_channels = frozenset({55})

    await cog._check_text(_text_message("сп@м", channel_id=55))

    channel.send.assert_not_awaited()


async def test_text_exempt_role_skips_bypass() -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _text_cog(channel=channel, automod=_banwords("спам"))
    cog._exempt_roles = frozenset({99})

    await cog._check_text(_text_message("сп@м", role_ids=(1, 99)))

    channel.send.assert_not_awaited()


async def test_text_thread_of_exempt_channel_skips_bypass() -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _text_cog(channel=channel, automod=_banwords("спам"))
    cog._exempt_channels = frozenset({500})

    await cog._check_text(_text_message("сп@м", channel_id=9001, parent_id=500))

    channel.send.assert_not_awaited()


async def test_text_empty_ruleset_is_silent() -> None:
    channel = SimpleNamespace(send=AsyncMock())
    cog = _text_cog(channel=channel, automod=AutoModKeywords.empty())

    await cog._check_text(_text_message("с п а м"))

    channel.send.assert_not_awaited()


async def test_sync_automod_filters_rules_and_applies_ignore() -> None:
    async def fake_fetch() -> list[object]:
        return [
            _kw_rule(["спам", "🇷🇺"], exempt_channels=(42,), exempt_roles=(7,)),
            _kw_rule(["казино"], enabled=False),  # disabled — игнор
            _kw_rule([], trigger_type=discord.AutoModRuleTriggerType.spam),  # не keyword
        ]

    channel = SimpleNamespace(send=AsyncMock())
    cog = _text_cog(channel=channel, ignore=("🇷🇺",))
    cog.bot.get_guild = lambda gid: SimpleNamespace(fetch_automod_rules=fake_fetch)

    await cog._sync_automod()

    assert cog._automod_ready is True
    assert cog._automod.keyword_count == 1  # "спам"; "🇷🇺" в игноре, "казино" в disabled
    assert cog._exempt_channels == frozenset({42})
    assert cog._exempt_roles == frozenset({7})
    assert cog._detect_bypass(_text_message("сп@м"), "сп@м") is not None
    assert cog._detect_bypass(_text_message("флаг 🇷🇺"), "флаг 🇷🇺") is None
