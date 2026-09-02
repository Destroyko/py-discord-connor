"""Стартовая диагностика (см. ``development.md`` § "Стартовая диагностика").

Одна функция ``run_preflight_checks`` (P1.7b) зовётся и из ``on_ready``, и из
``/healthcheck``. Здесь — **чистые** кусочки: тип результата, отдельные проверки
(на примитивах, без ``discord.*``), сборка сводки и вердикт «фатально ли».

Уровни провала:

- ``fatal=True``  — бот не может работать (гильдия / intents / БД) → процесс должен
  завершиться ненулевым кодом;
- ``fatal=False`` — отключается связанный функционал (роль/право/канал/Command
  Permissions API), бот в целом поднимается.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class CheckResult:
    section: str
    label: str
    ok: bool
    detail: str = ""
    fatal: bool = False

    @property
    def line(self) -> str:
        status = "OK" if self.ok else "ОШИБКА"
        tail = f" — {self.detail}" if self.detail else ""
        return f"[startup][{self.section}] {self.label}: {status}{tail}"


def any_fatal(results: list[CheckResult]) -> bool:
    return any(not r.ok and r.fatal for r in results)


def format_uptime(total_seconds: int) -> str:
    """``4д 3ч 12м`` — для строки «Аптайм» в ``/healthcheck``."""
    total_seconds = max(0, total_seconds)
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    return f"{days}д {hours}ч {minutes}м"


def summary_line(results: list[CheckResult]) -> str:
    errors = [r for r in results if not r.ok]
    if not errors:
        return "[startup] ИТОГ: всё в порядке"
    listed = "; ".join(f"{r.section}/{r.label}" for r in errors)
    verdict = (
        "бот НЕ поднят"
        if any(r.fatal for r in errors)
        else "затронутый функционал отключён, остальное работает"
    )
    return f"[startup] ИТОГ: ошибок {len(errors)} ({listed}) — {verdict}"


# --------------------------------------------------------------------------- #
# Отдельные проверки (чистые)
# --------------------------------------------------------------------------- #


def check_guild(*, connected_guild_id: int | None, expected_guild_id: int) -> CheckResult:
    if connected_guild_id == expected_guild_id:
        return CheckResult("гильдия", "ID", ok=True, detail="совпадает")
    return CheckResult(
        "гильдия",
        "ID",
        ok=False,
        fatal=True,
        detail=f"бот не в гильдии {expected_guild_id} (подключён к {connected_guild_id})",
    )


def check_intents(*, members: bool, message_content: bool) -> CheckResult:
    missing = [
        name
        for name, enabled in (("Guild Members", members), ("Message Content", message_content))
        if not enabled
    ]
    if missing:
        return CheckResult(
            "intents",
            "privileged",
            ok=False,
            fatal=True,
            detail=f"не включены: {', '.join(missing)}",
        )
    return CheckResult("intents", "privileged", ok=True, detail="Guild Members, Message Content")


def check_db(*, ping_ok: bool, error: str = "") -> CheckResult:
    if ping_ok:
        return CheckResult("БД", "подключение", ok=True)
    return CheckResult(
        "БД", "подключение", ok=False, fatal=True, detail=error or "SELECT 1 не прошёл"
    )


def check_managed_role(
    *, role_id: int, label: str, role_position: int | None, bot_top_position: int
) -> CheckResult:
    """``role_position=None`` — роль не резолвится по ID из ``.env``."""
    if role_position is None:
        return CheckResult(
            "роли", f'"{label}" ({role_id})', ok=False, detail="не найдена по ID из .env"
        )
    if bot_top_position <= role_position:
        return CheckResult(
            "роли",
            f'"{label}"',
            ok=False,
            detail=(
                f"роль бота не выше (поз. {bot_top_position} ≤ {role_position}) — "
                "выдача/снятие не сработает"
            ),
        )
    return CheckResult("роли", f'"{label}"', ok=True, detail="бот выше в иерархии")


def check_guild_permissions(*, missing: list[str]) -> CheckResult:
    if missing:
        return CheckResult(
            "права", "guild-level", ok=False, detail=f"не хватает: {', '.join(missing)}"
        )
    return CheckResult("права", "guild-level", ok=True)


def check_channel(
    *, channel_id: int, label: str, exists: bool, missing_perms: list[str]
) -> CheckResult:
    section = "каналы"
    if not exists:
        return CheckResult(
            section, f"{label} ({channel_id})", ok=False, detail="не найден по ID из .env"
        )
    if missing_perms:
        return CheckResult(
            section, label, ok=False, detail=f"не хватает прав: {', '.join(missing_perms)}"
        )
    return CheckResult(section, label, ok=True)


def check_command_permissions_api(*, reachable: bool, error: str = "") -> CheckResult:
    if reachable:
        return CheckResult("Command Permissions API", "доступ", ok=True)
    return CheckResult(
        "Command Permissions API",
        "доступ",
        ok=False,
        detail=f"{error or 'недоступно'} — !-команды с гейтом закрыты (fail closed)",
    )
