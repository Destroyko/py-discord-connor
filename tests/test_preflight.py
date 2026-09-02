"""P1.7a — стартовая диагностика: отдельные проверки, сводка, вердикт."""

from __future__ import annotations

from connor.core.preflight import (
    CheckResult,
    any_fatal,
    check_channel,
    check_command_permissions_api,
    check_db,
    check_guild,
    check_guild_permissions,
    check_intents,
    check_managed_role,
    summary_line,
)


def test_line_format() -> None:
    ok = CheckResult("роли", '"Молчун"', ok=True, detail="бот выше в иерархии")
    assert ok.line == '[startup][роли] "Молчун": OK — бот выше в иерархии'
    bad = CheckResult("каналы", "#аудит", ok=False, detail="не хватает прав: Send Messages")
    assert bad.line == "[startup][каналы] #аудит: ОШИБКА — не хватает прав: Send Messages"
    bare = CheckResult("права", "guild-level", ok=True)
    assert bare.line == "[startup][права] guild-level: OK"


def test_guild_check() -> None:
    assert check_guild(connected_guild_id=5, expected_guild_id=5).ok is True
    bad = check_guild(connected_guild_id=None, expected_guild_id=5)
    assert bad.ok is False and bad.fatal is True


def test_intents_check() -> None:
    assert check_intents(members=True, message_content=True).ok is True
    bad = check_intents(members=True, message_content=False)
    assert bad.ok is False and bad.fatal is True
    assert "Message Content" in bad.detail


def test_db_check() -> None:
    assert check_db(ping_ok=True).ok is True
    bad = check_db(ping_ok=False, error="connection refused")
    assert bad.ok is False and bad.fatal is True and "connection refused" in bad.detail


def test_managed_role_check() -> None:
    assert (
        check_managed_role(role_id=1, label="работяга", role_position=3, bot_top_position=9).ok
        is True
    )

    not_found = check_managed_role(
        role_id=1, label="работяга", role_position=None, bot_top_position=9
    )
    assert not_found.ok is False and not_found.fatal is False
    assert "не найдена" in not_found.detail

    too_low = check_managed_role(role_id=1, label="работяга", role_position=9, bot_top_position=9)
    assert too_low.ok is False and too_low.fatal is False  # equal position also fails


def test_guild_permissions_check() -> None:
    assert check_guild_permissions(missing=[]).ok is True
    bad = check_guild_permissions(missing=["Move Members", "View Audit Log"])
    assert bad.ok is False and "Move Members" in bad.detail


def test_channel_check() -> None:
    assert check_channel(channel_id=1, label="#аудит", exists=True, missing_perms=[]).ok is True

    gone = check_channel(channel_id=1, label="#аудит", exists=False, missing_perms=[])
    assert gone.ok is False and "не найден" in gone.detail

    noperm = check_channel(channel_id=1, label="#аудит", exists=True, missing_perms=["Embed Links"])
    assert noperm.ok is False and noperm.fatal is False and "Embed Links" in noperm.detail


def test_command_permissions_api_check_not_fatal() -> None:
    assert check_command_permissions_api(reachable=True).ok is True
    bad = check_command_permissions_api(reachable=False, error="503")
    assert bad.ok is False and bad.fatal is False
    assert "fail closed" in bad.detail


def test_any_fatal_and_summary() -> None:
    ok_only = [check_db(ping_ok=True), check_guild(connected_guild_id=1, expected_guild_id=1)]
    assert any_fatal(ok_only) is False
    assert summary_line(ok_only) == "[startup] ИТОГ: всё в порядке"

    with_warn = [
        check_db(ping_ok=True),
        check_managed_role(
            role_id=1, label="Душа компании", role_position=None, bot_top_position=9
        ),
    ]
    assert any_fatal(with_warn) is False
    assert "отключён" in summary_line(with_warn)
    assert "роли/" in summary_line(with_warn)

    with_fatal = [
        check_db(ping_ok=False),
        check_guild(connected_guild_id=None, expected_guild_id=1),
    ]
    assert any_fatal(with_fatal) is True
    assert "НЕ поднят" in summary_line(with_fatal)
