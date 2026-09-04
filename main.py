"""Запуск из консоли: ``python main.py`` (эквивалент ``python -m connor``).

Держим для локального теста на Windows — оператор запускает бот как обычный скрипт,
не как systemd-сервис.
"""

from connor.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
