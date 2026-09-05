"""Валидация конфигурации: типизация .env (snowflake), per-module TOML,
единый аггрегированный список проблем.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from connor.config import _CONFIG_DIR, REQUIRED_ENV, Config, ConfigError, load_config

_VALID_ID = "123456789012345678"
_NO_ENV_FILE = "/nonexistent/.env"


def _set_valid_env(mp: pytest.MonkeyPatch) -> None:
    for key in REQUIRED_ENV:
        mp.setenv(key, _VALID_ID)
    mp.setenv("BOT_TOKEN", "test-token")
    mp.setenv("DB_PATH", "./test.sqlite3")


@pytest.fixture
def cfgdir(tmp_path: Path) -> Path:
    """Копия реальных config/*.toml во временный каталог — можно портить по одному."""
    dst = tmp_path / "config"
    shutil.copytree(_CONFIG_DIR, dst)
    return dst


def _load(cfgdir: Path | None) -> Config:
    return load_config(env_path=_NO_ENV_FILE, config_dir=cfgdir)


# --------------------------------------------------------------------------- #


def test_shipped_configs_load_with_valid_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Реальные config/*.toml + валидный .env → типизированный Config."""
    _set_valid_env(monkeypatch)

    config = _load(None)  # config_dir=None → реальный каталог config/

    assert isinstance(config, Config)
    assert config.guild_id == int(_VALID_ID)
    assert config.bot_token == "test-token"
    assert config.roles["MOLCHUN"] == int(_VALID_ID)
    assert "FLUDISLAVL" in config.channels
    assert "RODDOM" in config.categories
    assert config.voices.points_active == 10
    assert config.purge.soft_limit == 300
    assert isinstance(config.moderation_chat.gif_domains, tuple)
    assert config.moderation_chat.automod_bypass_enabled is True
    assert config.moderation_chat.automod_bypass_ignore == ("ru", "ua")
    assert config.moderation_chat.collapse_repeats_min == 3
    assert config.voices.room_nsfw is False


def test_all_env_missing_lists_every_key(monkeypatch: pytest.MonkeyPatch, cfgdir: Path) -> None:
    for key in REQUIRED_ENV:
        monkeypatch.delenv(key, raising=False)

    with pytest.raises(ConfigError) as exc:
        _load(cfgdir)

    problems = exc.value.problems
    assert all(any(key in p for p in problems) for key in REQUIRED_ENV)


def test_env_id_not_integer(monkeypatch: pytest.MonkeyPatch, cfgdir: Path) -> None:
    _set_valid_env(monkeypatch)
    monkeypatch.setenv("GUILD_ID", "not-a-number")

    with pytest.raises(ConfigError) as exc:
        _load(cfgdir)

    assert any("GUILD_ID" in p and "не целое" in p for p in exc.value.problems)


def test_env_id_zero_rejected(monkeypatch: pytest.MonkeyPatch, cfgdir: Path) -> None:
    _set_valid_env(monkeypatch)
    monkeypatch.setenv("ROLE_MOLCHUN", "0")

    with pytest.raises(ConfigError) as exc:
        _load(cfgdir)

    assert any("ROLE_MOLCHUN" in p for p in exc.value.problems)


def test_missing_toml_file(monkeypatch: pytest.MonkeyPatch, cfgdir: Path) -> None:
    _set_valid_env(monkeypatch)
    (cfgdir / "voices.toml").unlink()

    with pytest.raises(ConfigError) as exc:
        _load(cfgdir)

    assert any("config/voices.toml" in p and "не найден" in p for p in exc.value.problems)


def test_toml_missing_key(monkeypatch: pytest.MonkeyPatch, cfgdir: Path) -> None:
    _set_valid_env(monkeypatch)
    (cfgdir / "purge.toml").write_text("# пусто\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        _load(cfgdir)

    assert any("purge.toml" in p and "soft_limit" in p for p in exc.value.problems)


def test_toml_negative_value(monkeypatch: pytest.MonkeyPatch, cfgdir: Path) -> None:
    _set_valid_env(monkeypatch)
    text = (cfgdir / "voices.toml").read_text(encoding="utf-8")
    (cfgdir / "voices.toml").write_text(
        text.replace("points_active = 10", "points_active = -1"), encoding="utf-8"
    )

    with pytest.raises(ConfigError) as exc:
        _load(cfgdir)

    assert any("points_active" in p and ">= 1" in p for p in exc.value.problems)


def test_toml_wrong_type(monkeypatch: pytest.MonkeyPatch, cfgdir: Path) -> None:
    _set_valid_env(monkeypatch)
    (cfgdir / "purge.toml").write_text('soft_limit = "300"\n', encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        _load(cfgdir)

    assert any("soft_limit" in p and "целым числом" in p for p in exc.value.problems)


def test_toml_bool_type(monkeypatch: pytest.MonkeyPatch, cfgdir: Path) -> None:
    _set_valid_env(monkeypatch)
    text = (cfgdir / "voices.toml").read_text(encoding="utf-8")
    (cfgdir / "voices.toml").write_text(
        text.replace("room_nsfw = false", 'room_nsfw = "yes"'), encoding="utf-8"
    )

    with pytest.raises(ConfigError) as exc:
        _load(cfgdir)

    assert any("room_nsfw" in p and "true/false" in p for p in exc.value.problems)


def test_aggregation_env_and_toml(monkeypatch: pytest.MonkeyPatch, cfgdir: Path) -> None:
    _set_valid_env(monkeypatch)
    monkeypatch.delenv("BOT_TOKEN")
    (cfgdir / "purge.toml").write_text("# пусто\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        _load(cfgdir)

    problems = exc.value.problems
    assert any("BOT_TOKEN" in p for p in problems)
    assert any("purge.toml" in p for p in problems)
