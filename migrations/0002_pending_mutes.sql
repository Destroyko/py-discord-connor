-- 0002_pending_mutes — отложенный мут (см. mute.md § "Отложенный мут").
-- Цель вышла с сервера до наложения таймаута → команда модератора запоминается и
-- применяется при возвращении пользователя. Одна запись на пользователя.
-- Все *_at — INTEGER Unix-epoch секунды (UTC), как и в 0001.

CREATE TABLE IF NOT EXISTS pending_mutes (
    user_id      INTEGER PRIMARY KEY,   -- кому выдать при возвращении
    duration     TEXT    NOT NULL,      -- как ввёл модератор ("24h") — для embed и повторного парса
    reason       TEXT    NOT NULL,      -- причина (либо "Причина не указана")
    moderator_id INTEGER NOT NULL,      -- кто поставил в очередь (для author эмбеда при выдаче)
    queued_at    INTEGER NOT NULL       -- момент постановки; по нему TTL-очистка
);
