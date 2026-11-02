"""Экспоненциальный откат для периодических опросов Discord API.

Опросы audit log крутятся каждые несколько секунд. Если пропало право
(``View Audit Log``) или токен отозван, без отката каждый тик шлёт заведомо
обречённый запрос — Discord считает это спамом невалидными запросами
(лимит ~10 000 ответов 401/403/429 за 10 минут на IP) и может сбросить токен.

``PollBackoff`` оборачивает тело тика: после ошибки следующие тики пропускаются
(30 с → 1 мин → 2 мин → … → максимум 10 мин), при первом успехе откат
сбрасывается. В лог идёт одна строка ERROR на начало серии сбоев и одна INFO
на восстановление — не по строке на каждый тик.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from time import monotonic

BASE_DELAY_SECONDS = 30
MAX_DELAY_SECONDS = 600


class PollBackoff:
    def __init__(
        self,
        label: str,
        logger: logging.Logger,
        *,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._label = label
        self._log = logger
        self._clock = clock
        self._failures = 0
        self._next_allowed = 0.0

    @property
    def failures(self) -> int:
        return self._failures

    def should_skip(self) -> bool:
        """``True`` — идёт пауза после сбоя, тик нужно пропустить без запросов."""
        return self._clock() < self._next_allowed

    def success(self) -> None:
        if self._failures:
            self._log.info(
                "%s: опрос восстановился после %d сбоев подряд", self._label, self._failures
            )
        self._failures = 0
        self._next_allowed = 0.0

    def failure(self, exc: BaseException) -> None:
        self._failures += 1
        delay = min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * 2 ** (self._failures - 1))
        self._next_allowed = self._clock() + delay
        if self._failures == 1:
            self._log.error(
                "%s: сбой опроса (%s: %s) — запросы приостановлены с откатом до %d с",
                self._label,
                type(exc).__name__,
                exc,
                MAX_DELAY_SECONDS,
                exc_info=exc,
            )
        else:
            self._log.warning(
                "%s: сбой №%d подряд (%s) — следующая попытка через %d с",
                self._label,
                self._failures,
                type(exc).__name__,
                delay,
            )
