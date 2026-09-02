"""P0.3 — единый логгер: идемпотентность настройки, контекстный хелпер,
файловый вывод (посуточная ротация, разбивка по уровням, хранение ~месяц)."""

from __future__ import annotations

import logging
import logging.handlers
import os

import pytest

import connor.logging_setup as ls
from connor.logging_setup import log_action_error, setup_logging


def test_setup_logging_is_idempotent(monkeypatch) -> None:
    monkeypatch.setattr(ls, "_CONFIGURED", False)
    root = logging.getLogger()
    before = len(root.handlers)

    setup_logging()
    setup_logging()
    setup_logging()

    assert len(root.handlers) == before + 1
    assert logging.getLogger("discord").level == logging.WARNING


def test_log_action_error_includes_action_and_context(caplog) -> None:
    log = logging.getLogger("connor.test")

    class _User:
        id = 42
        name = "enteii"

    with caplog.at_level(logging.ERROR, logger="connor.test"):
        log_action_error(log, "выдать роль 'работяга'", invoker=_User(), target=_User())

    (record,) = caplog.records
    assert record.levelno == logging.ERROR
    assert "выдать роль 'работяга'" in record.message
    assert "invoker=enteii (42)" in record.message
    assert "target=enteii (42)" in record.message


def test_log_action_error_attaches_traceback_only_with_exc(caplog) -> None:
    log = logging.getLogger("connor.test")

    with caplog.at_level(logging.ERROR, logger="connor.test"):
        log_action_error(log, "что-то")
        no_exc = caplog.records[-1]
        try:
            raise RuntimeError("boom")
        except RuntimeError as err:
            log_action_error(log, "что-то ещё", exc=err)
        with_exc = caplog.records[-1]

    assert no_exc.exc_info is None
    assert with_exc.exc_info is not None


# --- файловый вывод --------------------------------------------------------------


@pytest.fixture
def fresh_root(monkeypatch):
    """Изолировать корневой логгер: сбросить ``_CONFIGURED``, снять добавленные
    хендлеры после теста (и закрыть файлы, чтобы tmp_path подчистился)."""
    monkeypatch.setattr(ls, "_CONFIGURED", False)
    root = logging.getLogger()
    saved = root.handlers[:]
    saved_level = root.level
    yield root
    for handler in root.handlers[:]:
        if handler not in saved:
            handler.close()
            root.removeHandler(handler)
    root.setLevel(saved_level)


def _file_handlers(root: logging.Logger) -> list[logging.handlers.TimedRotatingFileHandler]:
    return [
        h for h in root.handlers if isinstance(h, logging.handlers.TimedRotatingFileHandler)
    ]


def test_file_handlers_split_by_level(tmp_path, fresh_root) -> None:
    setup_logging(log_dir=tmp_path)

    handlers = _file_handlers(fresh_root)
    assert {os.path.basename(h.baseFilename) for h in handlers} == {
        "info.log",
        "warning.log",
        "error.log",
    }

    log = logging.getLogger("connor.test.route")
    log.info("инфо-строка")
    log.warning("предупреждение-строка")
    log.error("ошибка-строка")
    for handler in handlers:
        handler.flush()

    info_txt = (tmp_path / "info.log").read_text(encoding="utf-8")
    warn_txt = (tmp_path / "warning.log").read_text(encoding="utf-8")
    err_txt = (tmp_path / "error.log").read_text(encoding="utf-8")

    assert "инфо-строка" in info_txt
    assert "предупреждение-строка" not in info_txt and "ошибка-строка" not in info_txt
    assert "предупреждение-строка" in warn_txt
    assert "инфо-строка" not in warn_txt and "ошибка-строка" not in warn_txt
    assert "ошибка-строка" in err_txt
    assert "инфо-строка" not in err_txt and "предупреждение-строка" not in err_txt


def test_file_handlers_rotate_daily_and_keep_a_month(tmp_path, fresh_root) -> None:
    setup_logging(log_dir=tmp_path)

    for handler in _file_handlers(fresh_root):
        assert handler.when == "MIDNIGHT"  # посуточно
        assert handler.utc is True
        assert handler.backupCount == 30  # ~месяц срезов, дальше старые удаляются


def test_log_dir_is_created_if_missing(tmp_path, fresh_root) -> None:
    target = tmp_path / "nested" / "logs"
    assert not target.exists()

    setup_logging(log_dir=target)

    assert target.is_dir()


def test_setup_logging_with_dir_is_idempotent(tmp_path, fresh_root) -> None:
    before = len(fresh_root.handlers)

    setup_logging(log_dir=tmp_path)
    setup_logging(log_dir=tmp_path)

    assert len(fresh_root.handlers) - before == 4  # 1 stderr + 3 файловых, без дублей


def test_unwritable_log_dir_warns_and_keeps_stderr(tmp_path, fresh_root, caplog) -> None:
    blocker = tmp_path / "not-a-dir"
    blocker.write_text("x", encoding="utf-8")  # файл на месте каталога-родителя

    with caplog.at_level(logging.WARNING):
        setup_logging(log_dir=blocker / "logs")

    assert _file_handlers(fresh_root) == []
    assert any("файловое логирование отключено" in r.message for r in caplog.records)
    assert any(isinstance(h, logging.StreamHandler) for h in fresh_root.handlers)
