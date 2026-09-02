"""P0.1 / P0.2 — валидация конфигурации."""

from __future__ import annotations

import pytest

from connor.config import REQUIRED_ENV, Config, ConfigError, load_config


def _set_all_env(monkeypatch: pytest.MonkeyPatch, value: str = "1") -> None:
    for key in REQUIRED_ENV:
        monkeypatch.setenv(key, value)


def test_empty_env_reports_every_missing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ConfigError) as excinfo:
        load_config(env_path="/nonexistent/.env")

    problems = excinfo.value.problems
    assert len(problems) == len(REQUIRED_ENV)
    assert all(any(key in p for p in problems) for key in REQUIRED_ENV)


def test_blank_value_counts_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_all_env(monkeypatch)
    monkeypatch.setenv("BOT_TOKEN", "   ")

    with pytest.raises(ConfigError) as excinfo:
        load_config(env_path="/nonexistent/.env")

    assert excinfo.value.problems == ["BOT_TOKEN: не задан в .env"]


def test_full_env_loads(monkeypatch: pytest.MonkeyPatch) -> None:
    _set_all_env(monkeypatch, "123456789012345678")

    config = load_config(env_path="/nonexistent/.env")

    assert isinstance(config, Config)
    assert config["GUILD_ID"] == "123456789012345678"
    assert config.get("MISSING") is None
