"""P2.B — purge: разбор аргументов, матчер, роддом, embed."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import discord
import pytest

from connor.cogs.purge import (
    MsgView,
    Purge,
    PurgeError,
    PurgeSpec,
    build_purge_log_embed,
    message_matches,
    parse_purge_args,
)

# --- parse_purge_args --------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (["50"], PurgeSpec("all", 50)),
        (["links", "10"], PurgeSpec("links", 10)),
        (["images", "5"], PurgeSpec("images", 5)),
        (["text", "1"], PurgeSpec("text", 1)),
        (["user", "<@123>", "20"], PurgeSpec("user", 20, user_id=123)),
        (["user", "123", "20"], PurgeSpec("user", 20, user_id=123)),
        (["match", "hello", "10"], PurgeSpec("match", 10, text="hello")),
        (["match", "hello", "world", "10"], PurgeSpec("match", 10, text="hello world")),
        (["not", "spam", "7"], PurgeSpec("not", 7, text="spam")),
        (["1000"], PurgeSpec("all", 1000)),  # мягкий лимит режется в раннере, не тут
    ],
)
def test_parse_ok(args: list[str], expected: PurgeSpec) -> None:
    assert parse_purge_args(args) == expected


@pytest.mark.parametrize(
    "args",
    [
        [],  # count missing
        ["abc"],  # not a number
        ["0"],
        ["-5"],
        ["3.5"],
        ["links"],  # count missing
        ["text"],
        ["match"],  # только ключевое слово
        ["match", "hello"],  # count missing / не число
        ["user", "<@1>"],  # count missing
    ],
)
def test_parse_bad_count(args: list[str]) -> None:
    assert parse_purge_args(args) is PurgeError.BAD_COUNT


@pytest.mark.parametrize(
    "args",
    [
        ["50", "extra"],  # лишний аргумент к <count>
        ["frobnicate", "10"],  # неизвестный режим
        ["links", "10", "extra"],
        ["user", "notanid", "10"],  # не id/mention
        ["user", "<@1>", "10", "extra"],
        ["match", "10"],  # count есть, текста нет
    ],
)
def test_parse_bad_syntax(args: list[str]) -> None:
    assert parse_purge_args(args) is PurgeError.BAD_SYNTAX


def test_error_texts() -> None:
    assert PurgeError.BAD_COUNT.text == "Количество указано не верно"
    assert PurgeError.BAD_SYNTAX.text == "Команда указана не верно."


# --- message_matches -----------------------------------------------------------


def _v(*, author=1, text="", link=False, image=False, attach=False) -> MsgView:
    return MsgView(
        author_id=author, text=text, has_link=link, has_image=image, has_attachment=attach
    )


def test_match_all() -> None:
    assert message_matches(PurgeSpec("all", 1), _v(text="anything")) is True


def test_match_user() -> None:
    assert message_matches(PurgeSpec("user", 1, user_id=5), _v(author=5)) is True
    assert message_matches(PurgeSpec("user", 1, user_id=5), _v(author=6)) is False


def test_match_substring_case_insensitive() -> None:
    assert message_matches(PurgeSpec("match", 1, text="Spam"), _v(text="this is SPAMMY")) is True
    assert message_matches(PurgeSpec("not", 1, text="Spam"), _v(text="this is SPAMMY")) is False
    assert message_matches(PurgeSpec("not", 1, text="spam"), _v(text="clean")) is True


def test_match_links_images_text() -> None:
    assert message_matches(PurgeSpec("links", 1), _v(link=True)) is True
    assert message_matches(PurgeSpec("images", 1), _v(image=True, attach=True)) is True
    assert (
        message_matches(PurgeSpec("images", 1), _v(link=True)) is False
    )  # ссылка на картинку != images
    assert message_matches(PurgeSpec("text", 1), _v(text="hi")) is True
    assert message_matches(PurgeSpec("text", 1), _v(text="hi", attach=True)) is False
    assert message_matches(PurgeSpec("text", 1), _v(text="see http://x", link=True)) is False


# --- embed ------------------------------------------------------------------------


def test_build_purge_log_embed() -> None:
    embed = build_purge_log_embed(
        author_username="mod_username",
        author_icon="http://a",
        mention="<@5>",
        raw_args="text 1",
        channel="#флудиславль",
    )
    assert embed.author.name == "mod_username"  # username, не серверный ник
    assert embed.description == "<@5> использовал :pudge: text 1 в канале #флудиславль"
    assert isinstance(embed, discord.Embed)


# --- Purge.purge (cog, фейковый Discord) --------------------------------------------


async def _history(*_a: object, **_kw: object):
    return
    yield  # pragma: no cover — пустая история, async generator


def _cog_and_ctx(*, bot_komandy: object | None = None) -> tuple[Purge, SimpleNamespace]:
    config = SimpleNamespace(
        categories={"RODDOM": 999},
        channels={"BOT_KOMANDY": 111},
        purge=SimpleNamespace(soft_limit=300),
    )
    bot = SimpleNamespace(config=config, get_channel=lambda _cid: bot_komandy)
    cog = Purge(bot)  # type: ignore[arg-type]

    channel = SimpleNamespace(
        category_id=1,  # не «роддом»
        permissions_for=lambda _m: SimpleNamespace(manage_messages=True),
        history=_history,
        delete_messages=AsyncMock(),
        mention="#канал",
    )
    ctx = SimpleNamespace(
        channel=channel,
        author=SimpleNamespace(
            id=5,
            mention="<@5>",
            display_name="enteii",
            name="enteii",
            avatar=None,
            display_avatar=SimpleNamespace(url="http://a"),
        ),
        message=SimpleNamespace(delete=AsyncMock()),
        send=AsyncMock(),
    )
    return cog, ctx


async def test_purge_deletes_invocation_message() -> None:
    cog, ctx = _cog_and_ctx()
    await Purge.purge.callback(cog, ctx, "5")
    ctx.message.delete.assert_awaited_once()
    ctx.send.assert_awaited_once_with(":pudge:")


async def test_purge_logs_clickable_mention_in_bot_komandy() -> None:
    bot_komandy = SimpleNamespace(send=AsyncMock())
    cog, ctx = _cog_and_ctx(bot_komandy=bot_komandy)
    await Purge.purge.callback(cog, ctx, "5")

    bot_komandy.send.assert_awaited_once()
    embed = bot_komandy.send.await_args.kwargs["embed"]
    assert embed.description == "<@5> использовал :pudge: 5 в канале #канал"


async def test_purge_parse_error_does_not_delete_invocation_message() -> None:
    cog, ctx = _cog_and_ctx()
    await Purge.purge.callback(cog, ctx, "not-a-number")
    ctx.message.delete.assert_not_awaited()
