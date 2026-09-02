"""Общие фикстуры тестов."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from connor.db import Database


@pytest.fixture
async def db(tmp_path: Path) -> AsyncIterator[Database]:
    database = Database(str(tmp_path / "test.sqlite3"))
    await database.connect()
    try:
        yield database
    finally:
        await database.close()
