-- 0006_give_stats — статистика обработанных заявок на роль «работяга» по
-- модераторам (команда /givestats, см. modStats.md). Одна строка на решение по
-- заявке (☑️/❌ в #реквесты-работяг).
--
-- Авто-выдача чистым аккаунтам не пишется — там нет модератора. Решение
-- терминально: правок и отмены нет. approved = 1 (одобрено) / 0 (отказ);
-- в статистике учитываются оба исхода. decided_at — INTEGER Unix-epoch (UTC).

CREATE TABLE IF NOT EXISTS give_decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    target_id    INTEGER NOT NULL,
    moderator_id INTEGER NOT NULL,
    decided_at   INTEGER NOT NULL,
    approved     INTEGER NOT NULL   -- 1 = одобрено, 0 = отказ
);

CREATE INDEX IF NOT EXISTS ix_give_decisions_mod ON give_decisions (moderator_id, decided_at);
