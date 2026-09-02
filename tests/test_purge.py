"""P2.B — purge: разбор аргументов, матчер, роддом, embed."""

from __future__ import annotations

import discord
import pytest

from connor.cogs.purge import (
    MsgView,
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
        author_global_name=".destroyko",
        author_icon="http://a",
        nick_text="enteii",
        raw_args="text 1",
        channel="#флудиславль",
    )
    assert embed.author.name == ".destroyko"
    assert embed.description == "enteii использовал :pudge: text 1 в канале #флудиславль"
    assert isinstance(embed, discord.Embed)
