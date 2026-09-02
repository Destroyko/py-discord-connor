"""Команды в личных сообщениях боту (см. ``rules.md`` § "Команды в ЛС").

По умолчанию бот **не обрабатывает** команды в ЛС — ни slash, ни ``!``.

- slash: все зарегистрированы guild-only → Discord сам не даёт вызвать их в ЛС,
  в коде проверять не нужно;
- ``!``-команды: Command Permissions в ЛС не действуют, поэтому бот сам смотрит
  ``ctx.guild is None`` и **молча** игнорирует любую ``!``-команду, кроме двух
  пользовательских команд приватных войсов, рассчитанных на вызов из ЛС.
"""

from __future__ import annotations

#: Единственные ``!``-команды, разрешённые в ЛС боту (обе без slash-варианта).
DM_ALLOWED_COMMANDS = frozenset({"vdel", "ban_list"})


def is_allowed_in_dm(command_name: str) -> bool:
    return command_name in DM_ALLOWED_COMMANDS
