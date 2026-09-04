"""P2.A — moderationChat: матчер слов, разбор GIF-ссылок, embed."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord

from connor.cogs.moderation_chat import (
    ModerationChat,
    build_media_meta_embed,
    build_word_embed,
    extract_gif_links,
    find_suspicious,
)

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


def test_build_media_meta_embed() -> None:
    e = build_media_meta_embed(source_title="#игровой", author_mention="<@7>", jump_url="u")
    assert e.title == "#игровой"
    assert [f.name for f in e.fields] == ["Автор", "Ссылка на пост"]
    assert isinstance(e, discord.Embed)


# --- ModerationChat._check_media ------------------------------------------------------


def _cog(*, channel: object) -> ModerationChat:
    config = SimpleNamespace(
        moderation_chat=SimpleNamespace(suspicious_words=(), gif_domains=_GIFS),
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
