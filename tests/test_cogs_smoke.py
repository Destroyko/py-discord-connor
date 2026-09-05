"""Smoke: каждый ког из ``connor.bot.COGS`` грузится в ``commands.Bot`` без ошибок
(синтаксис, импорты, дерево команд, отсутствие коллизий имён)."""

from __future__ import annotations

from types import SimpleNamespace

import discord
import pytest
from discord.ext import commands

from connor.bot import COGS

_CHANNEL_KEYS = (
    "REKVESTY",
    "BOT_KOMANDY",
    "ANTIRABOTYAGI",
    "AUDIT",
    "VYDACHA",
    "BANY",
    "FLUDISLAVL",
    "CHEKLIST",
    "CHEKLIST2",
    "PREDLOZHKA",
    "TRIGGER_VOICE",
)


def _fake_config() -> SimpleNamespace:
    return SimpleNamespace(
        guild_id=1,
        roles={"RABOTYAGA": 1, "MOLCHUN": 2, "DUSHA": 3},
        channels={k: i for i, k in enumerate(_CHANNEL_KEYS, start=10)},
        categories={"RODDOM": 100, "PRIVATE_VOICE": 101},
        voices=SimpleNamespace(
            points_mic_muted=8,
            points_active=10,
            points_stream_bonus=5,
            tick_interval_seconds=60,
            week_seconds=604800,
            banlist_limit=100,
            banlist_active_window_hours=24,
            room_bitrate=64000,
            room_user_limit=0,
            room_slowmode=0,
            room_nsfw=False,
        ),
        mute=SimpleNamespace(rules_url="", reservation_seconds=60),
        role_giver=SimpleNamespace(
            account_min_age_days=180,
            member_min_tenure_days=14,
            join_after_register_min_minutes=20,
        ),
        moderation_chat=SimpleNamespace(
            suspicious_words=(),
            gif_domains=(),
            automod_bypass_enabled=False,
            automod_bypass_ignore=(),
            collapse_repeats_min=3,
        ),
        purge=SimpleNamespace(soft_limit=300),
    )


async def test_all_cogs_load_without_collisions() -> None:
    intents = discord.Intents.none()
    intents.guilds = True
    bot = commands.Bot(command_prefix="!", intents=intents)
    bot.config = _fake_config()  # type: ignore[attr-defined]
    bot.db = SimpleNamespace()  # type: ignore[attr-defined]

    try:
        for ext in COGS:
            await bot.load_extension(ext)

        names = [c.name for c in bot.commands]
        assert sorted(n for n in names if names.count(n) > 1) == []  # нет дублей
        # ключевые команды Voices зарегистрированы
        assert {"vkick", "vreturn", "vdel", "ban_list", "ladder"} <= set(names)
    finally:
        for cog in list(bot.cogs):
            await bot.remove_cog(cog)
        await bot.close()


@pytest.mark.parametrize("path", COGS)
def test_cog_module_has_setup(path: str) -> None:
    import importlib

    mod = importlib.import_module(path)
    assert callable(mod.setup)
