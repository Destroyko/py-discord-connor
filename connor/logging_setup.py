"""Единый логгер бота (см. ``development.md`` § "Логирование").

- один ``logging``-логгер на весь процесс, уровни INFO / WARNING / ERROR;
- всегда пишет на stderr (в проде его подхватывает journald);
- при заданном каталоге (``LOG_DIR``, по умолчанию ``<repo>/logs``) — плюс файлы:
  посуточная ротация в полночь UTC, **отдельный файл на уровень**
  (``info.log`` — INFO и ниже, ``warning.log`` — WARNING, ``error.log`` —
  ERROR и выше), хранение ~месяц (``backupCount`` = 30 срезов, старые удаляются
  при очередной ротации);
- формат строки одинаков для stderr и файлов: время, уровень, имя логгера, текст;
- рантайм-ошибки логируются с контекстом того, **что бот пытался сделать**
  (команда, вызвавший, цель) через ``log_action_error(...)`` — не голым traceback;
- ``print`` в рантайме не используется (стартовый список проблем конфига в
  ``__main__`` тоже идёт через логгер).
"""

from __future__ import annotations

import logging
import logging.handlers
import os
from pathlib import Path

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"

#: сколько посуточных срезов держать на диске, прежде чем удалять старые (~месяц).
#: Удаление делает сам ``TimedRotatingFileHandler`` в момент ротации.
_FILE_RETENTION_DAYS = 30

#: имя файла → диапазон уровней ``[low, high)``, которые в него пишутся
#: (``high=None`` — без верхней границы).
_LEVEL_FILES: tuple[tuple[str, int, int | None], ...] = (
    ("info.log", logging.DEBUG, logging.WARNING),
    ("warning.log", logging.WARNING, logging.ERROR),
    ("error.log", logging.ERROR, None),
)


class _LevelRange(logging.Filter):
    """Пропускает запись, только если ``low <= record.levelno < high``."""

    def __init__(self, low: int, high: int | None) -> None:
        super().__init__()
        self._low = low
        self._high = high

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno < self._low:
            return False
        return self._high is None or record.levelno < self._high


def _add_file_handlers(
    root: logging.Logger, log_dir: Path, formatter: logging.Formatter
) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    for name, low, high in _LEVEL_FILES:
        handler = logging.handlers.TimedRotatingFileHandler(
            log_dir / name,
            when="midnight",
            backupCount=_FILE_RETENTION_DAYS,
            encoding="utf-8",
            utc=True,
            delay=True,  # не открывать файл, пока в него реально нечего писать
        )
        handler.setLevel(low)
        handler.addFilter(_LevelRange(low, high))
        handler.setFormatter(formatter)
        root.addHandler(handler)


def setup_logging(
    level: int = logging.INFO, *, log_dir: str | os.PathLike[str] | None = None
) -> None:
    """Настроить корневой логгер один раз (идемпотентно; первый вызов выигрывает).

    Вызывается из ``__main__`` до всего остального. Свой код — на ``level``
    (по умолчанию INFO); ``discord.py`` держим на WARNING, он болтлив на INFO.

    ``log_dir`` — каталог для файлового вывода (обычно из ``LOG_DIR``). Не задан —
    только stderr. Если каталог не создать / в него не писать — предупреждение на
    stderr и работа продолжается: логирование не критично для бота.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    formatter = logging.Formatter(_FORMAT, datefmt=_DATEFMT)

    stream = logging.StreamHandler()  # stderr
    stream.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(stream)

    if log_dir:
        try:
            _add_file_handlers(root, Path(log_dir), formatter)
        except OSError as exc:
            root.warning(
                "файловое логирование отключено: не удалось подготовить %s (%s)", log_dir, exc
            )

    logging.getLogger("discord").setLevel(logging.WARNING)

    _CONFIGURED = True


def _fmt_entity(entity: object) -> str:
    """Короткое представление пользователя/канала/роли: ``name (id)`` при наличии."""
    name = getattr(entity, "name", None) or getattr(entity, "display_name", None)
    entity_id = getattr(entity, "id", None)
    if name is not None and entity_id is not None:
        return f"{name} ({entity_id})"
    if entity_id is not None:
        return str(entity_id)
    return repr(entity)


def log_action_error(
    logger: logging.Logger,
    action: str,
    *,
    invoker: object | None = None,
    target: object | None = None,
    exc: BaseException | None = None,
) -> None:
    """Рантайм-ошибка с контекстом того, что бот пытался сделать.

    Пример::

        log_action_error(log, "выдать роль 'работяга'", invoker=ctx.author,
                         target=member, exc=err)

    → ``ERROR ... не удалось: выдать роль 'работяга' [invoker=enteii (…) target=… (…)]``
    (+ traceback, только если передан ``exc``).
    """
    parts = [f"не удалось: {action}"]
    context: list[str] = []
    if invoker is not None:
        context.append(f"invoker={_fmt_entity(invoker)}")
    if target is not None:
        context.append(f"target={_fmt_entity(target)}")
    if context:
        parts.append(f"[{' '.join(context)}]")
    logger.error(" ".join(parts), exc_info=exc)
