"""Автор для author-строки embed'ов — общий для mute / banKick / anti / roleGiver /
purge (см. ``rules.md`` § "author-строка embed'ов").

В author-строку идёт **username** аккаунта (``user.name``) и **глобальный аватар**
аккаунта. Так строка одинаково идентифицирует человека в любом логе и не
«протухает» при смене серверного ника/аватара.

Это про **людей**. Для сообщений от самого бота author-строка не ставится.
"""

from __future__ import annotations

import discord


def embed_author_name(user: discord.User | discord.Member) -> str:
    return user.name


def embed_author_icon(user: discord.User | discord.Member) -> str:
    """URL глобального аватара аккаунта (или дефолтного) — без серверного."""
    asset = getattr(user, "avatar", None) or getattr(user, "default_avatar", None)
    return asset.url if asset is not None else user.display_avatar.url
