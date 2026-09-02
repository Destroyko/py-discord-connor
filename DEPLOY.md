# Развёртывание Connor на VPS

Бот рассчитан на **один сервер Discord**, работает как systemd-сервис, хранит
состояние в одном файле SQLite. Спека — GitHub Wiki (`py-discord-connor.wiki`),
чек-лист реализации — [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

---

## 1. Настройка на стороне Discord (до установки)

Делается вручную через интерфейс Discord, **не** через `.env`. Полностью описано в
[README.md](README.md) § "Настройка на стороне Discord"; кратко:

1. **Privileged intents** (Developer Portal → Bot): включить **Server Members** и
   **Message Content**. Без них gateway не пустит бота — он залогирует это
   отдельной строкой и выйдет с кодом 1.
2. **Позиция роли бота** — выше ролей «работяга», «Молчун», «Душа компании».
3. **Права роли бота** — курируемый набор без `Administrator` (список —
   `environment.md` § "Права бота на сервере").
4. **Command Permissions** (Настройки сервера → Интеграции → Connor) — по каждой
   команде задать роли и каналы. Это слой только для slash; бот реплицирует его на
   `!`-путь, читая через API. Ориентиры по каналам — в README.
5. **Кастом-эмодзи `:pudge:`** — для ответа `!purge` (не критично, если нет).

Собрать заранее 19 ID (сервер, 3 роли, 11 каналов, 2 категории, +триггер-войс):
Discord → Настройки → Расширенные → **Режим разработчика**, затем ПКМ →
«Копировать ID».

---

## 2. Установка на сервере

```bash
sudo useradd --system --home /opt/connor --shell /usr/sbin/nologin connor
sudo mkdir -p /opt/connor
sudo chown connor:connor /opt/connor

sudo -u connor git clone <repo-url> /opt/connor
cd /opt/connor

sudo -u connor python3.13 -m venv .venv
sudo -u connor .venv/bin/pip install -e ".[dev]"   # dev — чтобы прогнать pytest на месте
```

Конфигурация:

```bash
sudo -u connor cp .env.example .env
sudo -u connor $EDITOR .env          # заполнить все 19 ключей
```

- `DB_PATH` — путь к файлу SQLite. По умолчанию `./connor.sqlite3` (→
  `/opt/connor/connor.sqlite3`). **Диск должен быть локальным**, не сетевой mount
  (WAL по NFS ненадёжен). Каталог должен быть доступен пользователю `connor` на
  запись.
- `config/*.toml` (5 файлов) уже лежат в репозитории с рабочими значениями —
  правятся вручную при необходимости, изменения подхватываются рестартом.

---

## 3. Прогон тестов ДО первого старта — обязательный gate

`pytest` не требует сети, БД-сервиса и токена (используется временный файл SQLite
и фейки Discord), запускается одной командой из чистого клона:

```bash
cd /opt/connor
sudo -u connor .venv/bin/pytest -q
sudo -u connor .venv/bin/ruff check .
sudo -u connor .venv/bin/ruff format --check .
```

**Если тесты красные — не запускать бота.** Разобрать причину (несовместимая
версия библиотеки, недокатанная правка, битый `config/*.toml`), починить, прогнать
снова. Зелёный `pytest` — условие запуска, а не формальность: он ловит регрессии
до того, как они станут инцидентом на живом сервере.

Тот же прогон повторяется после **каждого** обновления кода (см. §6).

---

## 4. systemd

```bash
sudo cp /opt/connor/deploy/connor.service /etc/systemd/system/connor.service
sudo $EDITOR /etc/systemd/system/connor.service   # проверить User/Group/пути
sudo systemctl daemon-reload
sudo systemctl enable --now connor
```

Юнит (`deploy/connor.service`):

- `Restart=on-failure`, `RestartSec=10` — перезапуск после падения, но не мгновенно.
- `StartLimitIntervalSec=300` / `StartLimitBurst=5` — не больше 5 неудачных стартов
  за 5 минут, дальше systemd уводит юнит в `failed` (защита от busy-loop и
  рейт-лимита на токен). Снять после починки: `sudo systemctl reset-failed connor`.
- `RestartPreventExitStatus=2` — **код выхода 2 = невалидный конфиг**; рестартить
  бессмысленно, юнит просто садится в `failed` до ручного `systemctl restart`.
  Код 1 (сбой входа / БД / фатальный preflight) — рестартится под StartLimit.

---

## 5. Проверка после старта

```bash
journalctl -u connor -f
```

В логе при старте — построчная диагностика с префиксом `[startup]` (гильдия,
intents, БД, роли, права, каналы, Command Permissions API) и строка `ИТОГ`.
Фатальные провалы (не та гильдия / нет intents / БД недоступна) → бот выходит с
кодом 1. Нефатальные (нет одного канала/роли) → соответствующий модуль отключён,
бот работает.

В Discord: `/healthcheck` (ephemeral) — тот же отчёт + аптайм, без доступа к VPS.

---

## 6. Обновление кода

```bash
cd /opt/connor
sudo -u connor git pull
sudo -u connor .venv/bin/pip install -e ".[dev]"   # если менялись зависимости
sudo -u connor .venv/bin/pytest -q                 # ← ОБЯЗАТЕЛЬНО, красный = не рестартим
sudo systemctl restart connor
journalctl -u connor -n 50
```

Миграции БД (`migrations/NNNN_*.sql`) применяются автоматически при старте, по
порядку, повторный прогон — no-op. Ошибка миграции = бот не поднялся (exit 1).

---

## 7. Бэкап БД

Один файл + WAL-сайдкары. Безопасный горячий бэкап — средствами SQLite:

```bash
sudo -u connor .venv/bin/python - <<'PY'
import sqlite3, os
src = os.environ.get("DB_PATH", "/opt/connor/connor.sqlite3")
dst = src + ".bak"
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
print("ok:", dst)
PY
```

Либо `systemctl stop connor` → скопировать `connor.sqlite3` (+ `-wal`, `-shm`) →
`systemctl start connor`.

---

## 8. Траблшутинг

| Симптом | Причина | Что делать |
|---|---|---|
| exit 2, юнит в `failed`, не рестартится | битый `.env` / `config/*.toml` — в логе полный список проблем | починить конфиг, `systemctl restart connor` |
| exit 1 сразу после старта | неверный `BOT_TOKEN`, не включены intents, недоступна БД, фатальный preflight | смотреть строку в логе, исправить, `systemctl restart` |
| юнит в `failed` после серии рестартов | сработал StartLimit | устранить причину, `systemctl reset-failed connor && systemctl start connor` |
| `!`-команды молчат | Command Permissions не прогрузились (fail closed) или не настроены на сервере | проверить строку `[startup][Command Permissions API]`, настроить права команд в Интеграциях |
| кириллица кракозябрами в логах | не-UTF-8 локаль | journalctl обычно UTF-8; при ручном запуске — `PYTHONUTF8=1` |
