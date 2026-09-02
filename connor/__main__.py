"""Точка входа: ``python -m connor``.

Порядок (см. IMPLEMENTATION_PLAN.md P0.1): настроить логирование → загрузить и
провалидировать конфиг → при проблемах напечатать полный список и выйти с кодом 2 →
иначе запустить бота.

Конфиг проверяется ДО импорта ``connor.bot`` (и, значит, ``discord``): битый ``.env``
должен падать осмысленно даже без установленных зависимостей бота.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

#: куда писать файловые логи, если не задан ``LOG_DIR`` — каталог ``logs/`` в корне
#: репозитория (для systemd это ``WorkingDirectory``, т.е. ``/opt/connor/logs``).
_DEFAULT_LOG_DIR = Path(__file__).resolve().parent.parent / "logs"


def _force_utf8_streams() -> None:
    """Логи/ошибки бота — на русском. Windows-консоль по умолчанию не UTF-8, из-за чего
    кириллица превращается в кракозябры при локальном запуске (``python main.py``).
    Прод (Linux/journalctl) и так UTF-8. Альтернатива без кода — ``set PYTHONUTF8=1``.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except (ValueError, OSError):  # поток уже закрыт/перенаправлен
                pass


def main() -> int:
    _force_utf8_streams()

    # .env в окружение до setup_logging, чтобы LOG_DIR можно было задать и там
    # (не только реальной переменной окружения). Полная валидация конфига — ниже,
    # в load_config; здесь только подтягиваем значения. Повторный load_dotenv в
    # load_config не переопределяет уже выставленное.
    from dotenv import load_dotenv

    load_dotenv()

    from connor.config import ConfigError, load_config
    from connor.logging_setup import setup_logging

    setup_logging(log_dir=os.environ.get("LOG_DIR") or str(_DEFAULT_LOG_DIR))
    log = logging.getLogger("connor.startup")

    try:
        config = load_config()
    except ConfigError as exc:
        log.error("конфигурация невалидна, бот не запущен (%d проблем):", len(exc.problems))
        for problem in exc.problems:
            log.error("  %s", problem)
        return 2

    from connor.bot import run_bot

    return run_bot(config)


if __name__ == "__main__":
    raise SystemExit(main())
