"""Загрузка и валидация конфигурации — единственная точка (см.
``development.md`` § "Валидация конфигурации", ``environment.md`` § "Конфигурация").

Два уровня:

1. ``.env`` — всё, без чего бот физически не работает: ID сервера/каналов/категорий/
   ролей, токен, путь к БД.
2. ``config/<module>.toml`` — тюнинговые константы каждого модуля.

Обе части проверяются здесь, до подключения к Discord. Проблемы (отсутствие ключа/
файла, неверный тип/значение) собираются в **один** список и отдаются как
``ConfigError`` — процесс затем завершается ненулевым кодом.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

_REPO_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = _REPO_ROOT / "config"

_MAX_SNOWFLAKE = 2**63 - 1

# Обязательные ключи .env.
_ENV_STR_KEYS: tuple[str, ...] = ("BOT_TOKEN", "DB_PATH")
_ENV_ID_KEYS: tuple[str, ...] = (
    "GUILD_ID",
    # роли, которыми бот управляет
    "ROLE_RABOTYAGA",
    "ROLE_MOLCHUN",
    "ROLE_DUSHA",
    # каналы
    "CH_REKVESTY",
    "CH_BOT_KOMANDY",
    "CH_ANTIRABOTYAGI",
    "CH_AUDIT",
    "CH_VYDACHA",
    "CH_BANY",
    "CH_FLUDISLAVL",
    "CH_CHEKLIST",
    "CH_CHEKLIST2",
    "CH_PREDLOZHKA",
    "CH_TRIGGER_VOICE",
    # категории
    "CAT_RODDOM",
    "CAT_PRIVATE_VOICE",
)

REQUIRED_ENV: tuple[str, ...] = _ENV_STR_KEYS + _ENV_ID_KEYS


class ConfigError(Exception):
    """Проблемы конфигурации, собранные в один список (не первая попавшаяся)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__(f"{len(problems)} проблем(ы) конфигурации")


# --------------------------------------------------------------------------- #
# Типизированные под-конфиги модулей
# --------------------------------------------------------------------------- #


@dataclass(frozen=True, slots=True)
class MuteConfig:
    rules_url: str
    reservation_seconds: int


@dataclass(frozen=True, slots=True)
class RoleGiverConfig:
    account_min_age_days: int
    member_min_tenure_days: int
    join_after_register_min_minutes: int


@dataclass(frozen=True, slots=True)
class VoicesConfig:
    points_mic_muted: int
    points_active: int
    points_stream_bonus: int
    tick_interval_seconds: int
    week_seconds: int
    banlist_limit: int
    banlist_active_window_hours: int
    room_bitrate: int
    room_user_limit: int
    room_slowmode: int
    room_nsfw: bool


@dataclass(frozen=True, slots=True)
class ModerationChatConfig:
    suspicious_words: tuple[str, ...]
    gif_domains: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PurgeConfig:
    soft_limit: int


@dataclass(frozen=True, slots=True)
class Config:
    guild_id: int
    bot_token: str
    db_path: str
    roles: dict[str, int]  # RABOTYAGA / MOLCHUN / DUSHA
    channels: dict[str, int]  # REKVESTY / BOT_KOMANDY / ...
    categories: dict[str, int]  # RODDOM / PRIVATE_VOICE
    mute: MuteConfig
    role_giver: RoleGiverConfig
    voices: VoicesConfig
    moderation_chat: ModerationChatConfig
    purge: PurgeConfig


# --------------------------------------------------------------------------- #
# Сборщик проблем
# --------------------------------------------------------------------------- #


class _Collector:
    def __init__(self) -> None:
        self.problems: list[str] = []

    def add(self, msg: str) -> None:
        self.problems.append(msg)

    # -- .env --

    def env_str(self, key: str) -> str:
        raw = os.environ.get(key, "").strip()
        if not raw:
            self.add(f".env {key}: не задан")
        return raw

    def env_id(self, key: str) -> int:
        raw = os.environ.get(key, "").strip()
        if not raw:
            self.add(f".env {key}: не задан")
            return 0
        try:
            value = int(raw)
        except ValueError:
            self.add(f".env {key}: не целое число (Discord snowflake), получено {raw!r}")
            return 0
        if not (0 < value <= _MAX_SNOWFLAKE):
            self.add(f".env {key}: не похоже на Discord ID (ожидался положительный int), {value}")
            return 0
        return value

    # -- toml --

    def toml_int(self, table: dict, path: str, key: str, *, minimum: int = 1) -> int:
        if key not in table:
            self.add(f"{path}: нет ключа {key!r}")
            return minimum
        value = table[key]
        if isinstance(value, bool) or not isinstance(value, int):
            self.add(f"{path}: {key} должен быть целым числом, получено {value!r}")
            return minimum
        if value < minimum:
            self.add(f"{path}: {key} должен быть >= {minimum}, получено {value}")
            return minimum
        return value

    def toml_str(self, table: dict, path: str, key: str, *, allow_empty: bool) -> str:
        if key not in table:
            self.add(f"{path}: нет ключа {key!r}")
            return ""
        value = table[key]
        if not isinstance(value, str):
            self.add(f"{path}: {key} должен быть строкой, получено {value!r}")
            return ""
        if not allow_empty and not value.strip():
            self.add(f"{path}: {key} не должен быть пустым")
        return value

    def toml_bool(self, table: dict, path: str, key: str) -> bool:
        if key not in table:
            self.add(f"{path}: нет ключа {key!r}")
            return False
        value = table[key]
        if not isinstance(value, bool):
            self.add(f"{path}: {key} должен быть true/false, получено {value!r}")
            return False
        return value

    def toml_str_list(self, table: dict, path: str, key: str) -> tuple[str, ...]:
        if key not in table:
            self.add(f"{path}: нет ключа {key!r}")
            return ()
        value = table[key]
        if not isinstance(value, list) or any(not isinstance(x, str) for x in value):
            self.add(f"{path}: {key} должен быть списком строк, получено {value!r}")
            return ()
        return tuple(value)


def _collect_ids(collector: _Collector, prefix: str) -> dict[str, int]:
    return {
        name.removeprefix(prefix): collector.env_id(name)
        for name in _ENV_ID_KEYS
        if name.startswith(prefix)
    }


def _load_toml(collector: _Collector, name: str, config_dir: Path) -> dict:
    path = config_dir / name
    if not path.is_file():
        collector.add(f"config/{name}: файл не найден ({path})")
        return {}
    try:
        with path.open("rb") as fh:
            return tomllib.load(fh)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        collector.add(f"config/{name}: не удалось прочитать TOML — {exc}")
        return {}


# --------------------------------------------------------------------------- #
# Точка входа
# --------------------------------------------------------------------------- #


def load_config(
    env_path: str | os.PathLike[str] | None = None,
    config_dir: str | os.PathLike[str] | None = None,
) -> Config:
    """Прочитать ``.env`` и ``config/*.toml``, проверить всё.

    Бросает ``ConfigError`` со списком **всех** проблем сразу.
    """
    load_dotenv(env_path)
    cdir = Path(config_dir) if config_dir is not None else _CONFIG_DIR
    c = _Collector()

    guild_id = c.env_id("GUILD_ID")
    bot_token = c.env_str("BOT_TOKEN")
    db_path = c.env_str("DB_PATH")

    roles = _collect_ids(c, "ROLE_")
    channels = _collect_ids(c, "CH_")
    categories = _collect_ids(c, "CAT_")

    mt = _load_toml(c, "mute.toml", cdir)
    mute = MuteConfig(
        rules_url=c.toml_str(mt, "config/mute.toml", "rules_url", allow_empty=True),
        reservation_seconds=c.toml_int(mt, "config/mute.toml", "reservation_seconds"),
    )

    rg = _load_toml(c, "role_giver.toml", cdir)
    role_giver = RoleGiverConfig(
        account_min_age_days=c.toml_int(rg, "config/role_giver.toml", "account_min_age_days"),
        member_min_tenure_days=c.toml_int(rg, "config/role_giver.toml", "member_min_tenure_days"),
        join_after_register_min_minutes=c.toml_int(
            rg, "config/role_giver.toml", "join_after_register_min_minutes"
        ),
    )

    vc = _load_toml(c, "voices.toml", cdir)
    p = "config/voices.toml"
    voices = VoicesConfig(
        points_mic_muted=c.toml_int(vc, p, "points_mic_muted"),
        points_active=c.toml_int(vc, p, "points_active"),
        points_stream_bonus=c.toml_int(vc, p, "points_stream_bonus"),
        tick_interval_seconds=c.toml_int(vc, p, "tick_interval_seconds"),
        week_seconds=c.toml_int(vc, p, "week_seconds"),
        banlist_limit=c.toml_int(vc, p, "banlist_limit"),
        banlist_active_window_hours=c.toml_int(vc, p, "banlist_active_window_hours"),
        room_bitrate=c.toml_int(vc, p, "room_bitrate", minimum=8000),
        room_user_limit=c.toml_int(vc, p, "room_user_limit", minimum=0),
        room_slowmode=c.toml_int(vc, p, "room_slowmode", minimum=0),
        room_nsfw=c.toml_bool(vc, p, "room_nsfw"),
    )

    mc = _load_toml(c, "moderation_chat.toml", cdir)
    moderation_chat = ModerationChatConfig(
        suspicious_words=c.toml_str_list(mc, "config/moderation_chat.toml", "suspicious_words"),
        gif_domains=c.toml_str_list(mc, "config/moderation_chat.toml", "gif_domains"),
    )

    pg = _load_toml(c, "purge.toml", cdir)
    purge = PurgeConfig(soft_limit=c.toml_int(pg, "config/purge.toml", "soft_limit"))

    if c.problems:
        raise ConfigError(c.problems)

    return Config(
        guild_id=guild_id,
        bot_token=bot_token,
        db_path=db_path,
        roles=roles,
        channels=channels,
        categories=categories,
        mute=mute,
        role_giver=role_giver,
        voices=voices,
        moderation_chat=moderation_chat,
        purge=purge,
    )
