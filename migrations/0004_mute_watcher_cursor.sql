-- 0004_mute_watcher_cursor — курсор опроса audit log для вотчера ручных изменений
-- Discord timeout (мут/анмут через UI, в обход /mute и /unmute), см. mute.md
-- § "Наблюдение за ручными изменениями таймаута". Тот же принцип, что и у
-- anti_watcher_cursor (0003) — отдельная таблица, т.к. это отдельный вотчер со
-- своим типом записей audit log (member_update, не member_role_update).

CREATE TABLE IF NOT EXISTS mute_watcher_cursor (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    last_entry_id INTEGER NOT NULL
);
