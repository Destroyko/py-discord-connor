"""author-строка embed'ов: username (не серверный ник, не global_name),
глобальный аватар (не серверный)."""

from __future__ import annotations

from types import SimpleNamespace

from connor.core.authorship import embed_author_icon, embed_author_name


def test_author_name_is_username_not_nick_or_global_name() -> None:
    user = SimpleNamespace(name="enteii", global_name="Enteii", display_name="СерверныйНик")
    assert embed_author_name(user) == "enteii"


def test_author_icon_uses_global_avatar_over_guild_avatar() -> None:
    # display_avatar у Member вернул бы guild-специфичный аватар — нам нужен глобальный
    user = SimpleNamespace(
        avatar=SimpleNamespace(url="http://global"),
        default_avatar=SimpleNamespace(url="http://default"),
        display_avatar=SimpleNamespace(url="http://guild-specific"),
    )
    assert embed_author_icon(user) == "http://global"


def test_author_icon_falls_back_to_default_when_no_custom_avatar() -> None:
    user = SimpleNamespace(
        avatar=None,
        default_avatar=SimpleNamespace(url="http://default"),
        display_avatar=SimpleNamespace(url="http://guild-specific"),
    )
    assert embed_author_icon(user) == "http://default"


def test_author_icon_tolerates_bare_object_with_only_display_avatar() -> None:
    # тестовые фейки часто задают лишь display_avatar — не должно падать
    user = SimpleNamespace(display_avatar=SimpleNamespace(url="http://x"))
    assert embed_author_icon(user) == "http://x"
