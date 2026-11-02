"""Одноразовая миграция анти-списка: разбор эмбедов, автор, свёртка, сбор истории."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest

from connor.tools.import_anti import (
    Command,
    Event,
    StateExistsError,
    classify_title,
    extract_user_id,
    find_author,
    reduce_events,
    render_sql,
    run_import,
)

_OLD_BOT = 777
_U1 = 1540102610177097728
_U2 = 277825416503230464


# --- разбор эмбеда ----------------------------------------------------------------


def test_classify_title() -> None:
    assert classify_title("Добавление") == "add"
    assert classify_title(" удаление ") == "del"
    assert classify_title("изъяли роль") is None
    assert classify_title(None) is None


def test_extract_id_from_mention() -> None:
    desc = f"Пользователь <@{_U1}> добавлен в список антиработяг"
    assert extract_user_id(desc) == (_U1, "")


def test_extract_id_bare_number_near_word() -> None:
    assert extract_user_id(f"Пользователь {_U2} удален из списка антиработяг") == (_U2, "")
    assert extract_user_id(f"Пользователь: {_U2} удален") == (_U2, "")


def test_extract_id_missing_or_ambiguous() -> None:
    assert extract_user_id("Пользователь @evil_dyadich удален")[0] is None
    assert extract_user_id(f"<@{_U1}> и <@{_U2}>")[0] is None
    assert extract_user_id(None)[0] is None


# --- автор команды ----------------------------------------------------------------


def _cmd(mid: int, ts: int, author: int, content: str) -> Command:
    return Command(mid, ts, author, content)


def test_find_author_matches_by_id_not_just_proximity() -> None:
    recent = [
        _cmd(10, 100, 1, f"!add {_U1} п15"),
        _cmd(11, 101, 2, f"!add {_U2} другое"),  # чужая команда между ними
    ]
    embed = SimpleNamespace(message_id=12, ts=102)
    assert find_author(recent, _U1, embed) == 1
    assert find_author(recent, _U2, embed) == 2


def test_find_author_picks_latest_preceding() -> None:
    recent = [_cmd(10, 100, 1, f"!add {_U1} a"), _cmd(11, 101, 2, f"!add {_U1} b")]
    assert find_author(recent, _U1, SimpleNamespace(message_id=12, ts=102)) == 2


def test_find_author_ignores_too_old_or_later_commands() -> None:
    old = [_cmd(10, 100, 1, f"!add {_U1}")]
    assert find_author(old, _U1, SimpleNamespace(message_id=12, ts=100 + 301)) == 0
    later = [_cmd(20, 100, 1, f"!add {_U1}")]
    assert find_author(later, _U1, SimpleNamespace(message_id=12, ts=100)) == 0


def test_find_author_does_not_match_id_inside_longer_number() -> None:
    recent = [_cmd(10, 100, 1, f"!add 9{_U1}")]
    assert find_author(recent, _U1, SimpleNamespace(message_id=12, ts=101)) == 0


# --- свёртка ----------------------------------------------------------------------


def _ev(mid: int, ts: int, action: str, uid: int, by: int = 0) -> Event:
    return Event(mid, ts, action, uid, by, "")


def test_reduce_keeps_last_status_and_last_add_data() -> None:
    events = [
        _ev(1, 100, "add", 5, 11),
        _ev(2, 200, "del", 5),
        _ev(3, 300, "add", 5, 22),  # повторный add после del — данные последнего
        _ev(4, 150, "add", 6, 33),
        _ev(5, 250, "del", 6),  # итог: удалён
    ]
    final = reduce_events(events)
    assert [(e.user_id, e.ts, e.added_by) for e in final] == [(5, 300, 22)]


def test_reduce_tie_broken_by_message_id() -> None:
    events = [_ev(2, 100, "del", 5), _ev(1, 100, "add", 5, 9)]
    assert reduce_events(events) == []  # del (id 2) позже add (id 1) при равном ts


def test_render_sql() -> None:
    now = datetime(2026, 11, 2, tzinfo=UTC)
    text = render_sql([_ev(1, 1697040000, "add", 123, 456)], generated_at=now, reset=False)
    lines = text.splitlines()
    assert lines[0].startswith("-- generated 2026-11-02") and "records: 1" in lines[0]
    insert = "INSERT OR IGNORE INTO anti_list (user_id, added_at, added_by)"
    assert f"{insert} VALUES (123, 1697040000, 456);" in lines
    assert "DELETE FROM anti_list;" not in lines
    assert "DELETE FROM anti_list;" in render_sql([], generated_at=now, reset=True)


# --- сбор истории по фейковому каналу ----------------------------------------------


def _embed(title: str, description: str, *, footer: str = "Коннорыч • сегодня", date: str = ""):
    fields = [SimpleNamespace(name="Дата добавления", value=date)] if date else []
    return SimpleNamespace(
        title=title, description=description, footer=SimpleNamespace(text=footer), fields=fields
    )


def _msg(mid: int, ts: int, *, author: int, bot: bool = False, content: str = "", embeds=()):
    return SimpleNamespace(
        id=mid,
        created_at=datetime.fromtimestamp(ts, UTC),
        author=SimpleNamespace(id=author, bot=bot),
        content=content,
        embeds=list(embeds),
    )


class _FakeChannel:
    def __init__(self, messages: list[SimpleNamespace]) -> None:
        self._messages = sorted(messages, key=lambda m: m.id)
        self.calls = 0

    def history(self, *, limit: int, after: discord.Object, oldest_first: bool):
        assert oldest_first
        self.calls += 1
        batch = [m for m in self._messages if m.id > after.id][:limit]

        async def gen():
            for m in batch:
                yield m

        return gen()


async def _no_sleep(_: float) -> None:
    return None


def _history() -> list[SimpleNamespace]:
    return [
        _msg(1, 1000, author=11, content=f"!add {_U1} п15"),
        _msg(
            2,
            1001,
            author=_OLD_BOT,
            bot=True,
            embeds=[_embed("Добавление", f"Пользователь <@{_U1}> добавлен", date="01-11-2026")],
        ),
        # follow-up про роль: чужой заголовок + текст с «!add id/квот» от бота
        _msg(
            3,
            1002,
            author=_OLD_BOT,
            bot=True,
            embeds=[_embed("изъяли роль", f"<@{_U1}> Добавить можно через !add id/квот")],
        ),
        _msg(4, 2000, author=12, content=f"!add {_U2} x"),
        _msg(
            5,
            2001,
            author=_OLD_BOT,
            bot=True,
            embeds=[_embed("Добавление", f"Пользователь <@{_U2}> добавлен")],
        ),
        _msg(6, 3000, author=13, content=f"!del {_U2} отсидел"),
        _msg(
            7,
            3001,
            author=_OLD_BOT,
            bot=True,
            embeds=[_embed("Удаление", f"Пользователь <@{_U2}> удален")],
        ),
        # эмбед другого бота с тем же заголовком — игнорируется
        _msg(
            8, 3002, author=999, bot=True, embeds=[_embed("Добавление", f"Пользователь <@{_U2}>")]
        ),
    ]


async def test_run_import_end_to_end(tmp_path: Path) -> None:
    channel = _FakeChannel(_history())
    stats = await run_import(
        channel, old_bot_id=_OLD_BOT, out_dir=tmp_path, delay=0, sleep=_no_sleep
    )

    assert (stats.adds, stats.dels) == (2, 1)
    rows = json.loads((tmp_path / "anti_list.json").read_text("utf-8"))
    assert rows == [{"user_id": _U1, "added_at": 1001, "added_by": 11}]  # _U2 удалён
    sql = (tmp_path / "anti_list.sql").read_text("utf-8")
    assert f"VALUES ({_U1}, 1001, 11);" in sql and str(_U2) not in sql
    csv_text = (tmp_path / "events_log.csv").read_text("utf-8")
    assert csv_text.splitlines()[0] == "message_id,ts,iso_utc,action,user_id,added_by,footer_raw"
    assert len(csv_text.splitlines()) == 4  # шапка + 3 события
    assert "ИТОГ" in (tmp_path / "warnings.log").read_text("utf-8")


async def test_missing_author_falls_back_to_zero_with_warning(tmp_path: Path) -> None:
    channel = _FakeChannel(
        [_msg(5, 2001, author=_OLD_BOT, bot=True, embeds=[_embed("Добавление", f"<@{_U1}>")])]
    )
    await run_import(channel, old_bot_id=_OLD_BOT, out_dir=tmp_path, delay=0, sleep=_no_sleep)
    rows = json.loads((tmp_path / "anti_list.json").read_text("utf-8"))
    assert rows[0]["added_by"] == 0
    assert "не найден автор" in (tmp_path / "warnings.log").read_text("utf-8")


async def test_unparsable_embed_is_skipped_with_warning(tmp_path: Path) -> None:
    channel = _FakeChannel(
        [_msg(5, 2001, author=_OLD_BOT, bot=True, embeds=[_embed("Добавление", "без id")])]
    )
    stats = await run_import(
        channel, old_bot_id=_OLD_BOT, out_dir=tmp_path, delay=0, sleep=_no_sleep
    )
    assert stats.adds == 0
    assert "id пользователя не найден" in (tmp_path / "warnings.log").read_text("utf-8")


async def test_paginates_over_more_than_one_page(tmp_path: Path) -> None:
    msgs = [_msg(i, 1000 + i, author=50) for i in range(1, 251)]  # 250 пустых сообщений
    msgs.append(
        _msg(300, 5000, author=_OLD_BOT, bot=True, embeds=[_embed("Добавление", f"<@{_U1}>")])
    )
    channel = _FakeChannel(msgs)
    stats = await run_import(
        channel, old_bot_id=_OLD_BOT, out_dir=tmp_path, delay=0, sleep=_no_sleep
    )
    assert stats.messages == 251 and stats.adds == 1
    assert channel.calls == 3  # 100 + 100 + 51


async def test_before_and_after_limit_range(tmp_path: Path) -> None:
    channel = _FakeChannel(_history())
    stats = await run_import(
        channel, old_bot_id=_OLD_BOT, out_dir=tmp_path, after=3, before=6, delay=0, sleep=_no_sleep
    )
    assert stats.adds == 1 and stats.dels == 0  # только сообщения 4 и 5


async def test_resume_continues_from_cursor_and_keeps_events(tmp_path: Path) -> None:
    history = _history()
    first = _FakeChannel([m for m in history if m.id <= 4])  # «прерванный» прогон
    await run_import(first, old_bot_id=_OLD_BOT, out_dir=tmp_path, delay=0, sleep=_no_sleep)

    full = _FakeChannel(history)
    stats = await run_import(
        full, old_bot_id=_OLD_BOT, out_dir=tmp_path, delay=0, sleep=_no_sleep, resume=True
    )
    # !add _U2 (msg 4) уже был виден в первом прогоне → автор находится и после resume
    assert (stats.adds, stats.dels) == (2, 1)
    assert json.loads((tmp_path / "anti_list.json").read_text("utf-8")) == [
        {"user_id": _U1, "added_at": 1001, "added_by": 11}
    ]


async def test_fresh_flag_discards_previous_state(tmp_path: Path) -> None:
    await run_import(
        _FakeChannel(_history()), old_bot_id=_OLD_BOT, out_dir=tmp_path, delay=0, sleep=_no_sleep
    )
    stats = await run_import(
        _FakeChannel(_history()),
        old_bot_id=_OLD_BOT,
        out_dir=tmp_path,
        delay=0,
        sleep=_no_sleep,
        fresh=True,
    )
    assert stats.adds == 2  # не удвоилось


async def test_existing_state_without_flag_refuses_and_keeps_state(tmp_path: Path) -> None:
    await run_import(
        _FakeChannel(_history()), old_bot_id=_OLD_BOT, out_dir=tmp_path, delay=0, sleep=_no_sleep
    )
    before = (tmp_path / ".state.json").read_text("utf-8")
    channel = _FakeChannel(_history())

    with pytest.raises(StateExistsError):
        await run_import(channel, old_bot_id=_OLD_BOT, out_dir=tmp_path, delay=0, sleep=_no_sleep)

    assert channel.calls == 0  # к API не ходили
    assert (tmp_path / ".state.json").read_text("utf-8") == before  # состояние цело


async def test_resume_after_completed_run_fetches_only_new_messages(tmp_path: Path) -> None:
    await run_import(
        _FakeChannel(_history()), old_bot_id=_OLD_BOT, out_dir=tmp_path, delay=0, sleep=_no_sleep
    )
    newer = [
        *_history(),
        _msg(20, 9000, author=14, content=f"!add {_U2} снова"),
        _msg(21, 9001, author=_OLD_BOT, bot=True, embeds=[_embed("Добавление", f"<@{_U2}>")]),
    ]
    stats = await run_import(
        _FakeChannel(newer),
        old_bot_id=_OLD_BOT,
        out_dir=tmp_path,
        delay=0,
        sleep=_no_sleep,
        resume=True,
    )
    assert stats.messages == len(newer)  # старые учтены из состояния, новые докачаны
    rows = json.loads((tmp_path / "anti_list.json").read_text("utf-8"))
    assert {r["user_id"]: (r["added_at"], r["added_by"]) for r in rows} == {
        _U1: (1001, 11),
        _U2: (9001, 14),  # _U2 был удалён, потом добавлен заново
    }


async def test_duplicate_page_after_crash_does_not_duplicate_events(tmp_path: Path) -> None:
    await run_import(
        _FakeChannel(_history()), old_bot_id=_OLD_BOT, out_dir=tmp_path, delay=0, sleep=_no_sleep
    )
    # имитация падения между записью событий и курсора: событие дописано повторно
    jsonl = tmp_path / ".events.jsonl"
    lines = jsonl.read_text("utf-8").splitlines()
    jsonl.write_text("\n".join([*lines, lines[0]]) + "\n", encoding="utf-8")

    stats = await run_import(
        _FakeChannel(_history()),
        old_bot_id=_OLD_BOT,
        out_dir=tmp_path,
        delay=0,
        sleep=_no_sleep,
        resume=True,
    )
    assert (stats.adds, stats.dels) == (2, 1)
    assert len((tmp_path / "events_log.csv").read_text("utf-8").splitlines()) == 4
