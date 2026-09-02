"""Загрузка и валидация конфигурации.

**P0.1 (сейчас):** минимальная проверка — все обязательные ключи ``.env`` присутствуют
и непусты; проблемы собираются в один список (не первая попавшаяся) и отдаются как
``ConfigError``.

**P0.2 (следующий шаг) расширит:** типизацию ID в snowflake (int), проверку лимитов
модулей (``60s–28d`` mute, ``100`` бан-лист, ``300`` purge), загрузку ``config/*.toml``
на модуль, единую точку валидации до подключения к Discord.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

try:  # P0.1: удобство для голого скелета; P0.2 сделает python-dotenv жёсткой зависимостью
    from dotenv import load_dotenv
except ModuleNotFoundError:  # pragma: no cover

    def load_dotenv(*_args: object, **_kwargs: object) -> bool:
        return False


# Обязательные ключи .env (см. IMPLEMENTATION_PLAN.md P0.2).
REQUIRED_ENV: tuple[str, ...] = (
    # база
    "GUILD_ID",
    "BOT_TOKEN",
    "DB_PATH",
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


class ConfigError(Exception):
    """Проблемы конфигурации, собранные в один список (не первая попавшаяся)."""

    def __init__(self, problems: list[str]) -> None:
        self.problems = problems
        super().__init__(f"{len(problems)} проблем(ы) конфигурации")


@dataclass(frozen=True, slots=True)
class Config:
    """Сырой снимок ``.env``.

    P0.1: значения — строки как есть. Типизированные поля (snowflake int, пути,
    per-module конфиги) появятся в P0.2.
    """

    values: dict[str, str]

    def __getitem__(self, key: str) -> str:
        return self.values[key]

    def get(self, key: str, default: str | None = None) -> str | None:
        return self.values.get(key, default)


def load_config(env_path: str | os.PathLike[str] | None = None) -> Config:
    """Прочитать ``.env`` и проверить наличие обязательных ключей.

    Бросает ``ConfigError`` со списком всех отсутствующих/пустых ключей сразу.
    """
    load_dotenv(env_path)

    problems: list[str] = []
    values: dict[str, str] = {}
    for key in REQUIRED_ENV:
        raw = os.environ.get(key, "").strip()
        if not raw:
            problems.append(f"{key}: не задан в .env")
        else:
            values[key] = raw

    if problems:
        raise ConfigError(problems)
    return Config(values=values)
