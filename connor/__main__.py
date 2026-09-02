"""Точка входа: ``python -m connor``.

Порядок (см. IMPLEMENTATION_PLAN.md P0.1): настроить логирование → загрузить и
провалидировать конфиг → при проблемах напечатать полный список и выйти с кодом 2 →
иначе запустить бота.

Конфиг проверяется ДО импорта ``connor.bot`` (и, значит, ``discord``): битый ``.env``
должен падать осмысленно даже без установленных зависимостей бота.
"""

from __future__ import annotations

import sys


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

    from connor.config import ConfigError, load_config
    from connor.logging_setup import setup_logging

    setup_logging()

    try:
        config = load_config()
    except ConfigError as exc:
        print("Ошибка конфигурации — бот не запущен:", file=sys.stderr)
        for problem in exc.problems:
            print(f"  - {problem}", file=sys.stderr)
        return 2

    from connor.bot import run_bot

    return run_bot(config)


if __name__ == "__main__":
    raise SystemExit(main())
