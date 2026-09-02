"""Единый логгер (см. IMPLEMENTATION_PLAN.md P0.3).

**P0.1 (сейчас):** минимальная настройка ``logging`` на stderr, уровень INFO.

**P0.3 расширит:** формат с контекстом (модуль/команда/цель), явные уровни
INFO/WARNING/ERROR по правилам ``development.md`` § "Логирование", запрет ``print``
в рантайме.
"""

from __future__ import annotations

import logging

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Настроить корневой логгер один раз (идемпотентно)."""
    global _CONFIGURED
    if _CONFIGURED:
        return
    logging.basicConfig(level=level, format=_FORMAT, datefmt=_DATEFMT)
    _CONFIGURED = True
