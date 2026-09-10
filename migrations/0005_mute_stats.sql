-- 0005_mute_stats — статистика выданных мьютов по модераторам (команда
-- /mutestats, см. modStats.md). Одна строка на выданное наказание.
--
-- Обновление длительности мьюта (повторный /mute на уже замьюченном) строк НЕ
-- добавляет и moderator_id не меняет — наказание остаётся за первым выдавшим.
-- Строка перестаёт учитываться (struck_at ставится), когда лог-сообщение бота о
-- муте удаляют из чата одиночным удалением. Естественное истечение и /unmute на
-- счёт не влияют. Отсчёт «за всё время» — с момента этой миграции.
-- Все *_at — INTEGER Unix-epoch секунды (UTC).

CREATE TABLE IF NOT EXISTS mute_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id    INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    created_at   INTEGER NOT NULL,
    message_id   INTEGER,            -- лог-сообщение бота; NULL, если получить не удалось
    channel_id   INTEGER,
    struck_at    INTEGER             -- NULL = считается; иначе момент удаления лога
);

CREATE INDEX IF NOT EXISTS ix_mute_events_mod ON mute_events (moderator_id, created_at);
CREATE INDEX IF NOT EXISTS ix_mute_events_message ON mute_events (message_id);
