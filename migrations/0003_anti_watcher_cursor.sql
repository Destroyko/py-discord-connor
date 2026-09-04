-- 0003_anti_watcher_cursor — курсор опроса audit log для вотчера ручных изменений
-- роли «работяга» (см. anti.md § "Наблюдение за ручными изменениями роли").
-- Вотчер перешёл с gateway-события on_member_update (которое discord.py диспатчит
-- только участникам, уже сидящим в member-кэше) на периодический опрос audit log —
-- это не зависит от размера кэша и не требует MemberCacheFlags.all() на больших
-- гильдиях. Курсор — id последней уже обработанной записи журнала аудита.

CREATE TABLE IF NOT EXISTS anti_watcher_cursor (
    id            INTEGER PRIMARY KEY CHECK (id = 1),
    last_entry_id INTEGER NOT NULL
);
