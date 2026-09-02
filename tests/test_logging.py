"""P0.3 — единый логгер: идемпотентность настройки и контекстный хелпер."""

from __future__ import annotations

import logging

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
