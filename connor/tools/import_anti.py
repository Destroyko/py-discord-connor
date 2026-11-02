"""ОДНОРАЗОВАЯ миграция анти-списка со старого бота (после миграции удалить весь
пакет ``connor/tools`` и ветку ``import-anti`` в ``connor/__main__.py``).

Читает историю канала старого бота («Конорыч») через REST, разбирает его эмбеды
«Добавление» / «Удаление», сворачивает события в итоговое состояние (последний
эмбед по пользователю) и пишет артефакты для ручной сверки и заливки в БД Connor::

    python -m connor import-anti --old-bot-id <id> [--channel-id <id>] [--after <msg_id>]
                                 [--before <msg_id>] [--out-dir DIR] [--delay 1.5]
                                 [--resume | --fresh] [--reset]

Токен и канал по умолчанию (``#антиработяги``) берутся из ``.env`` Connor. Gateway не
открывается (только ``GET /channels/{id}/messages``), бот не отвечает на команды.
Нужны права View Channel + Read Message History и включённый Message Content intent
в Developer Portal (без него Discord отдаёт чужие сообщения пустыми и по REST).

Артефакты (в ``--out-dir``, по умолчанию ``./import_anti_out``):
``anti_list.sql``, ``anti_list.json``, ``events_log.csv``, ``warnings.log``.
Применение: ``sqlite3 connor.sqlite3 < anti_list.sql``.

Источник истины по статусу — только эмбеды. Сообщения-команды читаются исключительно
ради ``added_by`` (автор ближайшей предшествующей ``!add`` с тем же id; не нашли — 0).
"""

from __future__ import annotations

import asyncio
import csv
import json
import re
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiohttp
import discord

_MENTION_RE = re.compile(r"<@!?(\d{15,20})>")
# «Пользователь 123…» / «Пользователь: 123…» — голое число рядом со словом
_BARE_RE = re.compile(r"Пользовател\w*[^\d<]{0,10}(\d{15,20})", re.IGNORECASE)

_TITLES = {"добавление": "add", "удаление": "del"}
#: сколько последних сообщений-команд помнить для поиска автора
_RECENT_CMDS = 50
#: команда старше эмбеда больше чем на столько секунд автором не считается
_AUTHOR_WINDOW_SECONDS = 300
_PAGE = 100


# --------------------------------------------------------------------------- #
# Чистая логика разбора
# --------------------------------------------------------------------------- #


def classify_title(title: str | None) -> str | None:
    """``"add"`` / ``"del"`` по заголовку эмбеда, иначе ``None`` (чужой эмбед)."""
    return _TITLES.get((title or "").strip().casefold())


def extract_user_id(description: str | None) -> tuple[int | None, str]:
    """``(id, "")`` либо ``(None, причина)``. Только описание: в поле «Причина» могут
    лежать любые упоминания, они к статусу не относятся."""
    text = description or ""
    ids = set(_MENTION_RE.findall(text)) or set(_BARE_RE.findall(text))
    if not ids:
        return None, "id пользователя не найден в описании эмбеда"
    if len(ids) > 1:
        return None, f"в описании несколько id: {sorted(ids)}"
    return int(next(iter(ids))), ""


@dataclass(frozen=True, slots=True)
class Event:
    message_id: int
    ts: int
    action: str  # "add" | "del"
    user_id: int
    added_by: int  # 0 — не восстановлен / не add
    footer_raw: str


@dataclass(slots=True)
class Command:
    message_id: int
    ts: int
    author_id: int
    content: str


def find_author(recent: deque[Command] | list[Command], user_id: int, embed: Event | Any) -> int:
    """Автор ближайшей предшествующей ``!add`` с этим id, иначе 0.

    ``embed`` — всё с ``message_id`` и ``ts``. Совпадение по id обязательно: ответа
    (reference) у старого бота нет, а между командой и эмбедом могут встрять чужие
    сообщения.
    """
    needle = re.compile(rf"(?<!\d){user_id}(?!\d)")
    for cmd in reversed(recent):
        if cmd.message_id >= embed.message_id:
            continue
        if embed.ts - cmd.ts > _AUTHOR_WINDOW_SECONDS:
            break
        if needle.search(cmd.content):
            return cmd.author_id
    return 0


def is_add_command(content: str) -> bool:
    return content.lstrip().casefold().startswith("!add")


def reduce_events(events: list[Event]) -> list[Event]:
    """Итоговые ``add`` — те пользователи, у кого последнее по времени событие ``add``."""
    last: dict[int, Event] = {}
    for ev in sorted(events, key=lambda e: (e.ts, e.message_id)):
        last[ev.user_id] = ev
    return sorted((e for e in last.values() if e.action == "add"), key=lambda e: e.ts)


# --------------------------------------------------------------------------- #
# Вывод артефактов
# --------------------------------------------------------------------------- #


def render_sql(final: list[Event], *, generated_at: datetime, reset: bool) -> str:
    lines = [
        f"-- generated {generated_at.isoformat(timespec='seconds')}; records: {len(final)}",
        "BEGIN;",
    ]
    if reset:
        lines.append("DELETE FROM anti_list;")
    lines += [
        f"INSERT OR IGNORE INTO anti_list (user_id, added_at, added_by) "
        f"VALUES ({e.user_id}, {e.ts}, {e.added_by});"
        for e in final
    ]
    lines.append("COMMIT;")
    return "\n".join(lines) + "\n"


def render_json(final: list[Event]) -> str:
    rows = [{"user_id": e.user_id, "added_at": e.ts, "added_by": e.added_by} for e in final]
    return json.dumps(rows, ensure_ascii=False, indent=2) + "\n"


def write_events_csv(path: Path, events: list[Event]) -> None:
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["message_id", "ts", "iso_utc", "action", "user_id", "added_by", "footer_raw"])
        for e in sorted(events, key=lambda e: (e.ts, e.message_id)):
            iso = datetime.fromtimestamp(e.ts, UTC).isoformat()
            w.writerow([e.message_id, e.ts, iso, e.action, e.user_id, e.added_by, e.footer_raw])


# --------------------------------------------------------------------------- #
# Сбор истории
# --------------------------------------------------------------------------- #


class StateExistsError(Exception):
    """Есть состояние прошлого прогона, а режим (--resume / --fresh) не выбран."""


@dataclass(slots=True)
class Stats:
    messages: int = 0
    old_bot_messages: int = 0
    embeds: int = 0
    adds: int = 0
    dels: int = 0
    warnings: int = 0


@dataclass(slots=True)
class _State:
    cursor: int = 0
    recent: list[Command] = field(default_factory=list)
    stats: Stats = field(default_factory=Stats)


def _embed_footer_raw(embed: Any) -> str:
    footer = getattr(getattr(embed, "footer", None), "text", None) or ""
    date_field = next(
        (
            f.value
            for f in getattr(embed, "fields", ())
            if (f.name or "").strip().casefold() == "дата добавления"
        ),
        "",
    )
    return " | ".join(p for p in (footer, date_field) if p)


def _state_to_json(st: _State) -> str:
    return json.dumps(
        {
            "cursor": st.cursor,
            "recent": [asdict(c) for c in st.recent],
            "stats": asdict(st.stats),
        },
        ensure_ascii=False,
    )


def _load_state(path: Path) -> _State:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return _State(
        cursor=raw["cursor"],
        recent=[Command(**c) for c in raw["recent"]],
        stats=Stats(**raw["stats"]),
    )


def _atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


async def _fetch_page(channel: Any, cursor: int, throttle: list[float]) -> list[Any]:
    """Одна страница (≤100) строго после ``cursor``. Страницу не пропускаем: сетевые
    ошибки, 5xx и 429 — ретрай с растущей паузой; 403/404 — фатально."""
    attempt = 0
    while True:
        try:
            return [
                m
                async for m in channel.history(
                    limit=_PAGE, after=discord.Object(id=cursor), oldest_first=True
                )
            ]
        except (discord.Forbidden, discord.NotFound):
            raise
        except (discord.HTTPException, aiohttp.ClientError, OSError, TimeoutError) as exc:
            attempt += 1
            status = getattr(exc, "status", None)
            wait = min(300.0, 5.0 * 2**attempt)
            if status == 429:
                wait = max(wait, 30.0)
                throttle[0] = min(10.0, throttle[0] * 2)  # дальше ходим реже
            print(f"  ошибка запроса ({type(exc).__name__}: {exc}); повтор через {wait:.0f} с")
            await asyncio.sleep(wait)


async def run_import(
    channel: Any,
    *,
    old_bot_id: int,
    out_dir: Path,
    after: int = 0,
    before: int | None = None,
    delay: float = 1.5,
    resume: bool = False,
    fresh: bool = False,
    reset: bool = False,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> Stats:
    # одноразовый CLI: блокирующий файловый ввод-вывод здесь допустим (цикла событий,
    # которому он мешал бы, нет — между страницами он всё равно простаивает)
    out_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
    state_path = out_dir / ".state.json"
    jsonl_path = out_dir / ".events.jsonl"
    warn_path = out_dir / "warnings.log"

    has_state = state_path.exists() and jsonl_path.exists()
    if has_state and not resume and not fresh:
        # случайный повторный запуск без флага не должен молча стереть часовой прогон
        raise StateExistsError(
            f"в {out_dir} остался прогон (курсор {_load_state(state_path).cursor}). "
            "Укажите --resume, чтобы продолжить (после завершённого прогона — докачать только "
            "новые сообщения), или --fresh, чтобы начать заново и стереть прошлое состояние."
        )

    if resume and has_state:
        state = _load_state(state_path)
        print(f"продолжаю с message_id {state.cursor} (уже сообщений: {state.stats.messages})")
    else:
        state = _State(cursor=after)
        for p in (state_path, jsonl_path, warn_path):
            p.unlink(missing_ok=True)
        jsonl_path.touch()
    warn_path.touch()

    recent: deque[Command] = deque(state.recent, maxlen=_RECENT_CMDS)
    stats = state.stats
    throttle = [delay]  # изменяемо: 429 увеличивает паузу

    def warn(line: str) -> None:
        stats.warnings += 1
        with warn_path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    done = False
    while not done:
        page = await _fetch_page(channel, state.cursor, throttle)
        if not page:
            break
        new_events: list[Event] = []
        for msg in page:
            if before is not None and msg.id >= before:
                done = True
                break
            stats.messages += 1
            state.cursor = msg.id
            ts = int(msg.created_at.timestamp())
            author = msg.author

            if not getattr(author, "bot", False):
                content = msg.content or ""
                if is_add_command(content):
                    recent.append(Command(msg.id, ts, author.id, content))
                continue
            if author.id != old_bot_id:
                continue
            stats.old_bot_messages += 1

            for embed in msg.embeds:
                action = classify_title(embed.title)
                if action is None:
                    continue
                stats.embeds += 1
                user_id, problem = extract_user_id(embed.description)
                if user_id is None:
                    warn(f"msg {msg.id}: пропущен эмбед «{embed.title}»: {problem}")
                    continue
                added_by = 0
                probe = Event(msg.id, ts, action, user_id, 0, "")
                if action == "add":
                    added_by = find_author(recent, user_id, probe)
                    if added_by == 0:
                        warn(f"msg {msg.id}: не найден автор !add для {user_id} (added_by=0)")
                footer = _embed_footer_raw(embed)
                if not footer:
                    warn(f"msg {msg.id}: у эмбеда нет футера/даты (для сверки)")
                new_events.append(Event(msg.id, ts, action, user_id, added_by, footer))
                if action == "add":
                    stats.adds += 1
                else:
                    stats.dels += 1

        with jsonl_path.open("a", encoding="utf-8") as fh:
            for e in new_events:
                fh.write(json.dumps(asdict(e), ensure_ascii=False) + "\n")
        state.recent = list(recent)
        _atomic_write(state_path, _state_to_json(state))
        print(f"  сообщений {stats.messages}, add {stats.adds}, del {stats.dels}")
        if len(page) < _PAGE:
            break
        await sleep(throttle[0])

    # страница, обработанная дважды (падение между записью событий и курсора + --resume),
    # даёт дубли строк: схлопываем по (сообщение, действие, пользователь)
    unique = {
        (e.message_id, e.action, e.user_id): e
        for e in (Event(**json.loads(ln)) for ln in jsonl_path.read_text("utf-8").splitlines())
    }
    events = list(unique.values())
    stats.adds = sum(e.action == "add" for e in events)
    stats.dels = sum(e.action == "del" for e in events)
    final = reduce_events(events)

    if stats.old_bot_messages and not events:
        warn(
            "эмбеды старого бота есть, но ни один не распознан — проверьте Message Content "
            "intent в Developer Portal (без него content/embeds приходят пустыми)"
        )

    write_events_csv(out_dir / "events_log.csv", events)
    now = datetime.now(UTC)
    (out_dir / "anti_list.sql").write_text(
        render_sql(final, generated_at=now, reset=reset), encoding="utf-8"
    )
    (out_dir / "anti_list.json").write_text(render_json(final), encoding="utf-8")

    summary = (
        f"ИТОГ: сообщений {stats.messages}; сообщений старого бота {stats.old_bot_messages}; "
        f"эмбедов {stats.embeds} (add {stats.adds}, del {stats.dels}); "
        f"итоговых add {len(final)}; предупреждений {stats.warnings}"
    )
    with warn_path.open("a", encoding="utf-8") as fh:
        fh.write(summary + "\n")
    print(summary)
    return stats


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


async def _amain(args: Any, *, token: str, channel_id: int) -> int:
    # Только REST: login без connect, intents не нужны клиенту (Message Content
    # определяется настройкой приложения в Developer Portal)
    client = discord.Client(intents=discord.Intents.none())
    await client.login(token)
    try:
        try:
            channel = await client.fetch_channel(channel_id)
        except (discord.Forbidden, discord.NotFound) as exc:
            print(f"нет доступа к каналу {channel_id}: {exc}")
            return 1
        await run_import(
            channel,
            old_bot_id=args.old_bot_id,
            out_dir=Path(args.out_dir),
            after=args.after,
            before=args.before,
            delay=args.delay,
            resume=args.resume,
            fresh=args.fresh,
            reset=args.reset,
        )
    except StateExistsError as exc:
        print(exc)
        return 2
    except (discord.Forbidden, discord.NotFound) as exc:
        print(f"Discord отклонил запрос: {exc}")
        return 1
    finally:
        await client.close()
    return 0


def main(argv: list[str]) -> int:
    import argparse

    from dotenv import load_dotenv

    parser = argparse.ArgumentParser(
        prog="python -m connor import-anti",
        description="Разовая миграция анти-списка из истории старого бота (см. docstring).",
    )
    parser.add_argument("--old-bot-id", type=int, required=True, help="user id старого бота")
    parser.add_argument(
        "--channel-id", type=int, help="канал с историей (по умолчанию #антиработяги)"
    )
    parser.add_argument("--after", type=int, default=0, help="начать после этого message_id")
    parser.add_argument("--before", type=int, help="остановиться перед этим message_id")
    parser.add_argument("--out-dir", default="import_anti_out")
    parser.add_argument("--delay", type=float, default=1.5, help="пауза между страницами, с")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="продолжить с сохранённого курсора (прерванный прогон или докачка новых сообщений)",
    )
    parser.add_argument(
        "--fresh", action="store_true", help="начать заново, стерев состояние прошлого прогона"
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="в anti_list.sql первой командой очистить таблицу (только пока Connor не запущен)",
    )
    args = parser.parse_args(argv)

    load_dotenv()
    from connor.config import ConfigError, load_config

    try:
        config = load_config()
    except ConfigError as exc:
        print(f"конфигурация невалидна ({len(exc.problems)} проблем):")
        for problem in exc.problems:
            print(f"  {problem}")
        return 2

    channel_id = args.channel_id or config.channels["ANTIRABOTYAGI"]
    return asyncio.run(_amain(args, token=config.bot_token, channel_id=channel_id))
