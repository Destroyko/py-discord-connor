"""P1.0b — EntityResolver: None-guard с логом один раз на id."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from connor.core.resolve import EntityResolver


def _source(mapping: dict[int, object]) -> SimpleNamespace:
    return SimpleNamespace(
        get_channel=lambda cid: mapping.get(cid),
        get_role=lambda rid: mapping.get(rid),
    )


def test_returns_entity_when_present() -> None:
    sentinel = object()
    r = EntityResolver(logging.getLogger("t"))
    assert r.channel(_source({5: sentinel}), 5, "#канал") is sentinel
    assert r.role(_source({7: sentinel}), 7, "роль") is sentinel


def test_missing_returns_none_and_logs_once(caplog) -> None:
    r = EntityResolver(logging.getLogger("connor.test.resolve"))
    src = _source({})

    with caplog.at_level(logging.ERROR, logger="connor.test.resolve"):
        assert r.channel(src, 42, "#канал") is None
        assert r.channel(src, 42, "#канал") is None  # второй раз — молча
        assert r.channel(src, 99, "#другой") is None  # другой id — снова лог

    errors = [rec for rec in caplog.records if rec.levelno == logging.ERROR]
    assert len(errors) == 2
    assert "42" in errors[0].message and "99" in errors[1].message


def test_channel_and_role_share_the_logged_set() -> None:
    r = EntityResolver(logging.getLogger("connor.test.resolve2"))
    src = _source({})
    r.channel(src, 1, "a")
    r.role(src, 1, "b")  # тот же id — уже залогирован, без второго ERROR
    assert 1 in r._logged
