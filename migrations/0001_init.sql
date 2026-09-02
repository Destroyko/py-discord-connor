-- 0001_init — вся схема БД Connor (см. IMPLEMENTATION_PLAN.md § "Схема БД").
-- Все DDL идемпотентны (IF NOT EXISTS): повторный прогон безопасен, если процесс
-- упал между executescript и записью версии в schema_version.
-- Все *_ts / *_at — INTEGER Unix-epoch секунды (UTC).

-- Кластер «работяга» -------------------------------------------------------

-- anti.md: чёрный список «анти-работяг». Причина в БД не хранится (только в embed).
CREATE TABLE IF NOT EXISTS anti_list (
    user_id  INTEGER PRIMARY KEY,
    added_at INTEGER NOT NULL,
    added_by INTEGER NOT NULL
);

-- roleGiver.md: заявки !give на ручной проверке. Ключ — id сообщения в #реквесты-работяг.
CREATE TABLE IF NOT EXISTS give_requests (
    message_id INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

-- check.md: deny-overwrite'ы в «предложке», выставленные САМИМ ботом (не модератором).
CREATE TABLE IF NOT EXISTS predlozhka_overwrites (
    user_id INTEGER PRIMARY KEY,
    reason  TEXT NOT NULL,
    set_at  INTEGER NOT NULL
);

-- Voices ----------------------------------------------------------------------

-- Реестр приватных комнат: владелец → его активный канал.
CREATE TABLE IF NOT EXISTS voice_rooms (
    owner_id   INTEGER PRIMARY KEY,
    channel_id INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

-- Персональные бан-листы владельцев комнат (≤100 на владельца — проверяется в коде).
CREATE TABLE IF NOT EXISTS voice_banlist (
    owner_id  INTEGER NOT NULL,
    banned_id INTEGER NOT NULL,
    ts        INTEGER NOT NULL,
    PRIMARY KEY (owner_id, banned_id)
);

-- Недельный опыт по участникам. seq (AUTOINCREMENT) = порядок первого начисления
-- в неделе, нужен для разрешения ничьих: ORDER BY points DESC, seq ASC.
CREATE TABLE IF NOT EXISTS voice_xp_week (
    seq     INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL UNIQUE,
    points  INTEGER NOT NULL DEFAULT 0
);

-- Недельный цикл: ровно одна строка. anchor_ts — точка отсчёта (первый чистый старт),
-- сдвигается на неделю на каждой перевыдаче. current_dusha_id — кому сейчас выдана роль.
CREATE TABLE IF NOT EXISTS voice_cycle (
    id               INTEGER PRIMARY KEY CHECK (id = 1),
    anchor_ts        INTEGER NOT NULL,
    current_dusha_id INTEGER
);
