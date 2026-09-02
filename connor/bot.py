"""Bootstrap бота (см. IMPLEMENTATION_PLAN.md P0.5).

**P0.1 (сейчас):** заглушка. ``run_bot`` только сообщает, что bootstrap ещё не
реализован, и возвращает ненулевой код — чтобы happy-path ``python -m connor``
не притворялся рабочим.

**P0.5 реализует:** ``commands.Bot`` с intents (Guild Members / Message Content /
Voice States / Guilds), ``MemberCacheFlags(voice=True, joined=False)``,
``chunk_guilds_at_startup=False``, загрузку когов, guild-scoped hybrid-команды с
``default_member_permissions = moderate_members`` для мод-команд, guild-only slash.
"""

from __future__ import annotations

import logging

from connor.config import Config

log = logging.getLogger(__name__)


def run_bot(config: Config) -> int:
    log.error("bot bootstrap ещё не реализован (IMPLEMENTATION_PLAN.md P0.5)")
    return 1
