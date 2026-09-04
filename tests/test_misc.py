"""!kiss: ответ и глобальный кулдаун 5 минут."""

from __future__ import annotations

from time import monotonic
from types import SimpleNamespace
from unittest.mock import AsyncMock

from connor.cogs.misc import _KISS_COOLDOWN_SECONDS, _KISS_REPLY, Misc


def _cog() -> Misc:
    return Misc(SimpleNamespace())  # type: ignore[arg-type]


def _ctx() -> SimpleNamespace:
    return SimpleNamespace(send=AsyncMock())


async def test_kiss_replies_first_time() -> None:
    cog, ctx = _cog(), _ctx()
    await Misc.kiss.callback(cog, ctx)
    ctx.send.assert_awaited_once_with(_KISS_REPLY)


async def test_kiss_silent_within_cooldown() -> None:
    cog, ctx = _cog(), _ctx()
    await Misc.kiss.callback(cog, ctx)
    ctx.send.reset_mock()

    await Misc.kiss.callback(cog, ctx)
    ctx.send.assert_not_awaited()


async def test_kiss_replies_again_after_cooldown() -> None:
    cog, ctx = _cog(), _ctx()
    await Misc.kiss.callback(cog, ctx)
    ctx.send.reset_mock()

    # окно кулдауна истекло
    cog._last_kiss = monotonic() - _KISS_COOLDOWN_SECONDS - 1
    await Misc.kiss.callback(cog, ctx)
    ctx.send.assert_awaited_once_with(_KISS_REPLY)


async def test_kiss_spam_does_not_extend_window() -> None:
    cog, ctx = _cog(), _ctx()
    await Misc.kiss.callback(cog, ctx)
    first_ts = cog._last_kiss
    await Misc.kiss.callback(cog, ctx)  # на кулдауне — молчим и НЕ обновляем окно
    assert cog._last_kiss == first_ts
