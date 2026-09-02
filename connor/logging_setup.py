"""Единый логгер бота (см. ``development.md`` § "Логирование").

- один ``logging``-логгер на весь процесс, уровни INFO / WARNING / ERROR;
- формат с временем, уровнем и именем логгера;
- рантайм-ошибки логируются с контекстом того, **что бот пытался сделать**
  (команда, вызвавший, цель) через ``log_action_error(...)`` — не голым traceback;
- ``print`` в рантайме не используется (стартовый список проблем конфига в
  ``__main__`` тоже идёт через логгер).
"""

from __future__ import annotations

import logging

_CONFIGURED = False

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    """Настроить корневой логгер один раз (идемпотентно).

    Вызывается из ``__main__`` до всего остального. Свой код — на ``level``
    (по умолчанию INFO); ``discord.py`` держим на WARNING, он болтлив на INFO.
    """
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler()  # stderr
    handler.setFormatter(logging.Formatter(_FORMAT, datefmt=_DATEFMT))

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)

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
