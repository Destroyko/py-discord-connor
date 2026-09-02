"""Единый None-guard для конфиг-сущностей в рантайме (см. IMPLEMENTATION_PLAN.md
P1.0b).

``guild.get_channel(ID)`` / ``guild.get_role(ID)`` вне preflight могут вернуть
``None`` — канал/роль удалили уже после старта. Каждый такой резолв обязан:
логировать ERROR **один раз на id** (реконсиляция/листенеры дёргаются часто),
вернуть ``None`` вызывающему, действие которого он затем пропускает — без
исключения.

``EntityResolver`` держит множество уже залогированных id, поэтому создаётся
один на ког (в ``__init__``).
"""

from __future__ import annotations

import logging
from typing import Protocol, TypeVar

T = TypeVar("T")


class _ChannelSource(Protocol):
    def get_channel(self, channel_id: int, /) -> object | None: ...


class _RoleSource(Protocol):
    def get_role(self, role_id: int, /) -> object | None: ...


class EntityResolver:
    def __init__(self, logger: logging.Logger) -> None:
        self._log = logger
        self._logged: set[int] = set()

    def channel(self, source: _ChannelSource, channel_id: int, label: str) -> object | None:
        return self._guard(source.get_channel(channel_id), channel_id, label)

    def role(self, source: _RoleSource, role_id: int, label: str) -> object | None:
        return self._guard(source.get_role(role_id), role_id, label)

    def _guard(self, entity: T | None, entity_id: int, label: str) -> T | None:
        if entity is None and entity_id not in self._logged:
            self._log.error("%s (ID=%d) не найден(а) — действие пропущено", label, entity_id)
            self._logged.add(entity_id)
        return entity
