-- 0007_molchun_role_watcher_cursor — курсор опроса audit log для вотчера
-- ручной выдачи/снятия роли «Молчун» владельцем сервера через Discord UI.
-- Отдельная таблица от mute_watcher_cursor: тот вотчер читает member_update
-- (нативный timeout), этот — member_role_update. Один общий курсор терял бы
-- события другого типа.

CREATE TABLE IF NOT EXISTS molchun_role_watcher_cursor (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    last_entry_id INTEGER NOT NULL
);
