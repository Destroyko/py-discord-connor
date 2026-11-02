-- 0008_ban_watcher_cursor — курсор опроса audit log для вотчера ручных киков через
-- Discord UI (в обход /kick). Баны/разбаны бот не логирует: их пишет отдельный
-- вебхук Discord.
-- Строка на тип записи audit log (сейчас только kick): курсор каждого типа отдельный,
-- как в 0007 — один общий терял бы события другого типа.

CREATE TABLE IF NOT EXISTS ban_watcher_cursor (
    kind          TEXT PRIMARY KEY CHECK (kind IN ('kick')),
    last_entry_id INTEGER NOT NULL
);
