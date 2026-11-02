-- 0008_ban_watcher_cursor — курсоры опроса audit log для вотчера ручных
-- банов/разбанов/киков через Discord UI (в обход /ban, /unban и /kick).
-- По строке на тип записи (ban / unban / kick): у них разные action-фильтры
-- audit log, один общий курсор терял бы события другого типа (как в 0007).

CREATE TABLE IF NOT EXISTS ban_watcher_cursor (
    kind          TEXT PRIMARY KEY CHECK (kind IN ('ban', 'unban', 'kick')),
    last_entry_id INTEGER NOT NULL
);
