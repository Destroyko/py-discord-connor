"""Автор для author-строки embed'ов — общий для mute / banKick / anti / roleGiver /
purge (см. ``rules.md`` § "Ответы бота").

В author-строку идёт **username** аккаунта (``user.name`` — глобальный хэндл, «то,
что видно в профиле», напр. ``.destroyko``), а НЕ серверный никнейм
(``member.nick``/``member.display_name`` — настраивается под каждый сервер и у
одного человека на разных серверах разный) и НЕ аккаунтный display-name
(``global_name`` — тоже произвольно меняется). Аватар — глобальный аватар
аккаунта, не серверный (guild avatar).

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
