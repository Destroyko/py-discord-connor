"""Слой БД: SQLite через aiosqlite (см. IMPLEMENTATION_PLAN.md P0.4).

Реализуется в P0.4: открытие соединения с
``PRAGMA journal_mode=WAL / synchronous=NORMAL / foreign_keys=ON / busy_timeout=5000``,
``ping()`` = ``SELECT 1``, применение ``migrations/NNNN_*.sql`` по порядку с таблицей
``schema_version``. Доступ к данным по доменам — ``repo_*.py``.
"""
