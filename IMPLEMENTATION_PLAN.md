# Connor bot — план реализации и чек-лист

> Источник требований — вики `py-discord-connor.wiki` (sibling-каталог). Этот файл — **живой чек-лист**: по мере выполнения задачи её пункт переводится в `[x]` только после того, как выполнена И проверена (способ проверки указан в пункте). Код бота — только в этом репозитории (`py-discord-connor/`), спеку не трогаем.

## Как читать пункты

- `[ ]` не начато · `[~]` в работе · `[x]` сделано и проверено
- **Ref** — раздел вики, откуда берётся поведение (при расхождении кода и вики — правит вики, потом код).
- **Готово когда** — критерий завершения.
- **Проверка** — `unit` (pytest), `preflight` (зелёная строка в `/healthcheck`), `manual` (прогон на живом сервере оператором), `review` (сверка кода со спекой).

---

## Технические решения (по умолчанию — подтвердить перед P0)

| Тема | Решение | Обоснование |
|---|---|---|
| Язык / библиотека | Python 3.12, `discord.py` 2.x, `commands.Bot` + hybrid-команды, по коду — коги (`commands.Cog`) на модуль | `environment.md` § "Технический стек" |
| БД | **SQLite** через `aiosqlite`, один файл, путь из `.env`. Режим: `PRAGMA journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`. Файл — на локальном диске (не сетевой mount). | Единственный процесс = единственный писатель; горячий путь — 1 батч/мин на ~100–300 строк; XP-тик из БД не читает; объём — единицы/десятки МБ. Postgres дал бы только операционные накладные (отдельный сервис на VPS, auth, ещё одна точка отказа при старте). |
| Миграции | Каталог `migrations/NNNN_*.sql`, таблица `schema_version`, применяются по порядку при старте | `development.md` § "стартовая диагностика" ("схема/миграции применены") |
| `.env` | `python-dotenv`; парсинг + валидация в одном модуле `connor/config.py` | `environment.md` § "Конфигурация", `development.md` § "Валидация конфигурации" |
| Конфиг модулей | По файлу на модуль в `config/<module>.toml` (tomllib), грузятся тем же `connor/config.py` | вики: "каждый в собственном файле", "не хардкод" |
| Тесты | `pytest` + `pytest-asyncio`; Discord-вызовы — `unittest.mock`; чистая логика — без объектов discord.py | `development.md` § "Тестирование" |
| Формат/линт | `ruff` (format + lint) | — |
| Тесты — запуск | Локально командой `pytest` (без обязательного CI). Гоняются **на самой машине перед первым стартом** и после каждого обновления кода — не только при деплое. Документируется в `DEPLOY.md`. | Пойнт оператора: возможность прогнать тесты на проде до старта |
| Часовой пояс строк-дат | MSK (UTC+3) фиксировано, отдельная утилита форматирования | `environment.md` § "Технический стек" |
| `default_member_permissions` при регистрации команд | **Все** мод-команды (`/mute`,`/unmute`,`/ban`,`/unban`,`/kick`,`/add`,`/del`,`/healthcheck`) — единый гейт `moderate_members`. Пользовательские (`/ladder`,`/check`,`/vkick`,`/vreturn`,`/ban_list`,`/give`) — без ограничения. Тонкая настройка (конкретные роли/каналы) — оператором через Integrations → Command Permissions после деплоя; тот же гейт реплицируется на `!`-путь (P1.5). **Почему именно `moderate_members`, а не `manage_channels`/`manage_roles`:** бот при создании приватной комнаты выдаёт владельцу per-channel overwrite `View Channel` + `Manage Channels` на его канал (и встроенный текст-чат) — если бы мод-команда гейтилась на `manage_channels`, владелец комнаты мог бы вызвать её из чата своей комнаты (до ручной настройки Command Permissions по каналам). `moderate_members` — guild-level и **никогда** не выдаётся overwrite'ом комнаты (Voices явно не даёт прав модерации), поэтому утечки нет. | `rules.md` § "Роли и права", `Voices.md` § "Создание приватной комнаты" |
| Член-кэш | `MemberCacheFlags(voice=True, joined=False)`, `chunk_guilds_at_startup=False`. `channel.members` работает для тех, кто в войсе; `message.author.roles` — из payload сообщения; всё прочее — `fetch_*` (см. P1.0d). | `environment.md` § "Технический стек" |
| `/anti-bot` (antiBot) | **НЕ разрабатываем.** Модуль в этот план не входит вообще — ни кода, ни кога, ни тестов, ни пункта в фазах. Спека `antiBot.md` остаётся в вики на случай, если решат вернуть позже (тогда — отдельной задачей). | `Home.md`, `antiBot.md` (обе помечают модуль как вне скоупа) |

Решения зафиксированы (оператор подтвердил): SQLite+WAL; конфиги модулей — TOML; CI не заводим, `pytest` гоняется локально/на проде вручную перед стартом; единый гейт мод-команд `moderate_members` (безопасен от прав владельца комнаты).

---

## Раскладка репозитория (создаётся в P0)

```
py-discord-connor/
  pyproject.toml            # зависимости, ruff, pytest
  .env.example              # все обязательные ключи с комментариями
  connor/
    __main__.py             # точка входа: load config -> validate -> start bot
    config.py               # .env + config/*.toml, единая валидация, аггрегация ошибок
    logging_setup.py        # единый logging (INFO/WARNING/ERROR)
    bot.py                  # commands.Bot: intents, MemberCacheFlags, загрузка когов
    db/
      __init__.py           # пул соединений, SELECT 1 ping, применение миграций
      repo_*.py             # доступ к данным по доменам (anti, give, voices, ...)
    core/
      hierarchy.py          # проверка иерархии ролей / self-mod / owner
      targets.py            # разбор target (id|mention), "не на сервере"
      timefmt.py            # MSK-форматирование дат; парсер длительности мьюта
      permissions.py        # реплика Command Permissions API для !-пути
      preflight.py          # run_preflight_checks(guild) -> list[CheckResult]
      dm_guard.py           # игнор !-команд в ЛС кроме !vdel/!ban_list
    cogs/
      healthcheck.py  moderation_chat.py  purge.py  ban_kick.py  mute.py
      anti.py  check.py  role_giver.py
      voices_rooms.py  voices_xp.py  voices_selfmod.py  voices_ladder.py
      misc.py               # !kiss
  config/
    mute.toml  role_giver.toml  voices.toml  moderation_chat.toml  purge.toml
  migrations/
    0001_init.sql ...
  tests/
    test_*.py
  deploy/
    connor.service          # systemd unit
```

---

## Граф зависимостей (что за чем)

```
P0 Фундамент (config, logging, db, bot bootstrap)
        │
P1 Ядро (hierarchy/targets/timefmt utils, preflight+/healthcheck, Command Permissions replication, dm_guard)
        │
        ├── P2 Независимые модули (парал.): moderationChat · purge · banKick · mute
        │
        ├── P3 Кластер «работяга» (по порядку): anti(core) → anti(watcher) → check → roleGiver
        │
        └── P4 Voices (по порядку): rooms(create) → rooms(lifecycle) → selfmod → xp-tick → weekly → ladder
        │
P5 Тесты «зелёные» целиком · P6 Разное (!kiss) + деплой
```

Обоснование порядка:
- **P1 до всего**: каждая команда использует `hierarchy`/`targets`; каждый `!`-путь зависит от реплики Command Permissions (`rules.md` § "Роли и права"); `on_ready` не должен пускать бота дальше без preflight.
- **P3 внутренний порядок**: `check` читает анти-статус и вызывается из `anti./del`; `roleGiver` читает анти-список (`anti.md`, `roleGiver.md` сценарий 3). Значит `anti` первым.
- **P4 внутренний порядок**: реестр комнат нужен `selfmod` (`/vkick`) и минутной сверке; XP-тик от реестра не зависит, но живёт в том же `tasks.loop`; weekly читает недельные очки, ladder — их же.
- **P2 не зависит ни от P3, ни от P4** — можно вести параллельно после P1.

---

## P0 — Фундамент

- [x] **P0.1 Каркас проекта.** `pyproject.toml` (discord.py 2.7, aiosqlite, python-dotenv, ruff, pytest, pytest-asyncio; ruff игнорит RUF001-003 — проект русскоязычный), раскладка каталогов (`connor/{core,cogs,db}`, `config/*.toml`-заготовки, `migrations/`, `deploy/`, `tests/`), `.env.example` со всеми 19 ключами, `__main__.py` со схемой `config → validate → (fail-fast, exit 2) → bot.run`. Конфиг валидируется ДО импорта `discord`. `.venv` создан, `pip install -e ".[dev]"`.
  - Готово когда: `python -m connor` на пустом `.env` → exit 2 + полный список всех недостающих ключей без traceback; на валидном → доходит до заглушки `bot.run`. ✓
  - Проверка: `manual` ✓ (оба пути), `pytest` ✓ (3 теста в `tests/test_config.py`), `ruff check`+`format --check` ✓.
- [x] **P0.2 `connor/config.py` — загрузка и валидация.** Ref: `environment.md` § "Конфигурация", `development.md` § "Валидация конфигурации".
  - `.env` (19 ключей): `BOT_TOKEN`,`DB_PATH` — непустые строки; `GUILD_ID` + `ROLE_*`/`CH_*`/`CAT_*` — целые snowflake `0 < id ≤ 2^63-1`. Возвращаются как `Config.roles/channels/categories` (dict без префикса).
  - `config/*.toml` (5 файлов) грузятся `tomllib`, каждый в типизированный под-конфиг (`MuteConfig`/`RoleGiverConfig`/`VoicesConfig`/`ModerationChatConfig`/`PurgeConfig`). **Файл обязан существовать**, каждый документированный ключ обязан присутствовать и иметь верный тип/диапазон — иначе проблема в общий список. Границы мьюта `60s–28d` — константы в коде (P1.4), не в конфиге.
  - Все проблемы (env + все конфиги) — в один `ConfigError.problems`, `__main__` печатает и выходит с кодом 2.
  - Готово когда: битый `.env`/конфиг → полный список проблем; корректный → типизированный `Config`. ✓
  - Проверка: `unit` ✓ (`tests/test_config.py`, 10 тестов: пропуски env, не-int/0/отрицательный ID, отсутствующий toml-файл, отсутствующий ключ, неверный тип, отрицательное значение, bool-тип, аггрегация env+toml, валидность shipped-конфигов); `manual` ✓ (битый `.env` → точные сообщения).
- [x] **P0.3 `logging_setup.py`.** `setup_logging(level, *, log_dir)` — `StreamHandler` на stderr, формат `время LEVEL логгер сообщение`, идемпотентно (первый вызов выигрывает); `discord` придушен до WARNING. При `log_dir` (из `LOG_DIR`, дефолт `<repo>/logs`, подтягивается через ранний `load_dotenv` в `__main__`) — плюс три `TimedRotatingFileHandler` (`when="midnight"`, `utc`, `backupCount=30`, `delay`): `info.log` (`[DEBUG, WARNING)`), `warning.log` (`[WARNING, ERROR)`), `error.log` (`[ERROR, ∞)`) — разбивка уровней через `_LevelRange`-фильтр. Каталог не создать → `warning` на stderr, бот жив. `log_action_error(logger, action, *, invoker, target, exc)` — рантайм-ошибка с контекстом (что бот пытался сделать + кто/над кем + traceback только при `exc`). `print` вычищен: список проблем конфига в `__main__` идёт через логгер. Ref: `development.md` § "Логирование".
  - Проверка: `unit` ✓ (`tests/test_logging.py`: идемпотентность, контекст в сообщении, traceback только с `exc`, создание каталога, 3 файла и маршрутизация уровней, параметры ротации, идемпотентность с `log_dir`); `manual` ✓ (битый `.env` → лог-строки ERROR, exit 2).
- [x] **P0.4 Слой БД.** `connor/db/__init__.py` — `Database(path)` c `connect()` (PRAGMA `journal_mode=WAL / synchronous=NORMAL / foreign_keys=ON / busy_timeout=5000` → миграции), `ping()` (`SELECT 1`), `close()`, `db.conn` для репо, `db.applied_migrations` (что применилось на последнем заходе — для preflight). `connor/db/migrations.py` — `apply_migrations(conn, dir)`: `migrations/NNNN_*.sql` по порядку, `schema_version(version, applied_at)`, повтор — no-op; проверка на дубли номеров. `migrations/0001_init.sql` — 7 таблиц, все DDL `IF NOT EXISTS`, timestamp-колонки — INTEGER epoch, `voice_xp_week` c `seq AUTOINCREMENT` для тай-брейка, `voice_cycle` c `CHECK(id=1)`.
  - Готово когда: на чистом файле миграции применяются, `ping()` OK, повторный `connect()` → `applied_migrations == []`. ✓
  - Проверка: `unit` ✓ (`tests/test_db.py`, 5: применение+schema_version, ping, PRAGMA, идемпотентность reconnect, тай-брейк `voice_xp_week` = порядок вставки); `manual` ✓ (реальный файл, `CHECK(id=1)` ловится, WAL-сайдкары чистятся на close); `preflight` — в P1.7.
- [x] **P0.5 `bot.py` bootstrap.** `ConnorBot(commands.Bot)`: `command_prefix="!"`, intents default + Guild Members + Message Content + Voice States; `member_cache_flags=MemberCacheFlags(voice=True, joined=False)`, `chunk_guilds_at_startup=False` (следствия — P1.0d); `help_command=None`; `allowed_mentions=AllowedMentions.none()` по умолчанию (пингующие места — override явно). `setup_hook`: грузит коги из `COGS` (пусто на P0.5, модули добавляют себя в своих фазах), `tree.copy_global_to(guild)` + `tree.sync(guild=GUILD_ID)` (guild-scoped, мгновенный синк). `on_ready`: identity + проверка, что бот в гильдии из `.env` (полный preflight — P1.7). Мод-команды при регистрации получат `default_member_permissions=moderate_members`, префикс-only (`!purge`/`!vdel`/`!ban_list`/`!kiss`) — обычные `commands.command` с ручной репликой Command Permissions (кроме `!kiss` и `!purge`) — это в фазах модулей. `run_bot`: `LoginFailure`→«неверный BOT_TOKEN», `PrivilegedIntentsRequired`→сообщение про Developer Portal, прочее→`log.exception`; всё → exit 1, чистый выход → 0.
  - Готово когда: `run_bot` маппит ошибки входа на код выхода; фейк-токен → `LoginFailure` → exit 1. ✓
  - Проверка: `unit` ✓ (`tests/test_bot.py`, 7: intents, частичный кэш, безопасные дефолты, маппинг LoginFailure/PrivilegedIntents/прочего/чистого выхода); `manual` ✓ (фейк-токен → «неверный BOT_TOKEN», exit 1). **Ждёт ручного теста с реальным токеном:** `setup_hook` (синк дерева) и `on_ready` (проверка гильдии) — после P1.7 / первого кога.
  - Примечание: discord.py на старте пишет 2 WARNING «PyNaCl/davey … voice will NOT be supported» — это про передачу аудио самим ботом; Connor в войс не заходит (только читает войс-стейты, создаёт/двигает каналы), PyNaCl не нужен, предупреждения безвредны.
- [x] **P0.6 `.env.example` + README-заметка.** `.env.example` — 19 ключей с пояснениями + шапка про «Режим разработчика → Копировать ID» и указатель на ручную настройку Discord. `README.md` § "Настройка на стороне Discord": privileged intents (Server Members + Message Content), позиция роли бота выше управляемых, курируемый набор прав без `Administrator`, Command Permissions по командам с ориентирами по каналам, кастом-эмодзи `:pudge:`. Ref: `rules.md` § "Роли и права", `environment.md` § "Права бота на сервере".
  - Проверка: `review` ✓. Исчерпывающий деплой-чек-лист — `DEPLOY.md` в P6.4.

### Схема БД (единая, миграция 0001)

| Таблица | Поля (суть) | Модуль |
|---|---|---|
| `anti_list` | `user_id PK`, `added_at`, `added_by` | anti / roleGiver |
| `give_requests` | `message_id PK`, `user_id`, `created_at` | roleGiver |
| `predlozhka_overwrites` | `user_id PK`, `reason`, `set_at` — только те, что поставил **бот** | check |
| `voice_rooms` | `owner_id PK`, `channel_id`, `created_at` | Voices (реестр) |
| `voice_banlist` | `owner_id`, `banned_id`, `ts`, PK(`owner_id`,`banned_id`); ≤100 на владельца | Voices |
| `voice_xp_week` | `seq INTEGER PK AUTOINCREMENT`, `user_id UNIQUE`, `points`. Тай-брейк ничьих = `ORDER BY points DESC, seq ASC` (seq = порядок первого начисления в неделе). Явный `seq`, т.к. при `user_id INTEGER PK` он стал бы алиасом rowid и порядок вставки бы потерялся. | Voices |
| `voice_cycle` | ровно одна строка (`id INTEGER PK CHECK(id=1)`): `anchor_ts`, `current_dusha_id NULLABLE` | Voices |
| `mute_reservation` | **в памяти** (dict в коге mute, P2.D4) — переживать рестарт не обязано, таблицы нет | mute |

Все timestamp-колонки (`added_at`, `created_at`, `ts`, `set_at`, `anchor_ts`) — `INTEGER` Unix-epoch (UTC); форматирование в MSK — при выводе (P1.4).

---

## P1 — Ядро (общее для всех команд)

### P1.0 Сквозная устойчивость (обязательно во всех когах)

- [x] **P1.0a Все фоновые циклы отказоустойчивы.** Тело каждой итерации `tasks.loop` (минутный тик Voices и любой другой) обёрнуто в `try/except Exception` → лог ERROR с контекстом → **цикл продолжается**; дополнительно навешан `@loop.error`. Недельная перевыдача выполняется внутри такого же барьера — исключение в ней не должно убивать минутный цикл. Причина: `discord.py` `tasks.loop` при необработанном исключении **молча останавливается**. **Сделано:** `cogs/voices_xp.py::tick` — всё тело в `try/except Exception` → `log.exception`; `@tick.error` — второй барьер; недельная перевыдача (`_maybe_weekly`/`_run_weekly`) вызывается внутри того же тела.
  - Проверка: `unit` ✓ (`test_voices_xp_cog.py::test_tick_iteration_swallows_exception` — исключение в `_accrue` не пробрасывается из `tick.coro`).
- [x] **P1.0b None-guard на конфиг-сущности в рантайме.** Любой `guild.get_channel(ID)`/`guild.get_role(ID)` вне preflight проверяется на `None`: лог ERROR (`<сущность> ID=<...> не найдена — <действие> пропущено`), действие пропускается, исключение не бросается. Канал/роль могли удалить после старта. **Сделано:** `core/resolve.py::EntityResolver` — `channel(source, id, label)` / `role(source, id, label)`, лог ERROR **один раз на id** (общее множество), возврат `None`. Один экземпляр на ког (`self._resolver`). Адаптированы `anti`, `check`, `moderation_chat`, `mute`, `role_giver`, `voices_rooms`, `voices_xp` — их хелперы `_channel`/`_role` теперь делегируют резолверу (call-site не тронуты). Стартовый preflight (`_check_channel`, `check_managed_role`) продолжает свой None-guard.
  - Проверка: `unit` ✓ (`test_resolve.py` — возврат сущности / None + лог один раз на id / общее множество channel+role); `review` ✓ по call-site адаптированных когов.
- [x] **P1.0c Единый guard `on_message`.** `core/msg_guard.should_process_message(message)` → `False` для ботов и вебхуков (`author.bot` OR `webhook_id is not None`). Первый потребитель — реконсиляция мьюта (P2.D); `moderationChat` / `check`-предложка / `!kiss` подключат его в своих фазах.
  - Проверка: `unit` ✓ (`tests/test_msg_guard.py`).
- [x] **P1.0d `fetch_member`/`fetch_user` для произвольных пользователей.** Член-кэш намеренно частичный — `guild.get_member(id)` вернёт `None` для того, кто не в войсе и не автор текущей команды, даже если он на сервере. Через REST `fetch_member`/`fetch_user` (с `except discord.NotFound`) идут: недельная перевыдача (снять роль с прежней «Души», спуск по списку победителей), резолв ников в `/ladder`, матчинг цели в аудит-логе `anti`, `/del` на удалённом аккаунте. Пути редкие — рейт-лимит не проблема. **Сделано в P4:** `voices_xp.py::_resolve_member` (get_member → fetch_member) для прежней «Души» и спуска по списку; `voices_ladder.py::_name` (get_member → fetch_user → сырой id); `voices_selfmod.py::/vkick` — `guild.fetch_member` для цели. `anti` (`_audit_actor`, `/del`) — сделано в P3.
  - Проверка: `review` ✓; `unit` ✓ (`test_voices_ladder.py`, `test_voices_xp_cog.py` — ветки «ушёл с сервера»); `manual` — ждёт токена.
- [x] **P1.0e `on_voice_state_update` — быстрый ранний выход.** Событие частое на большом сервере: хендлер сперва дёшево отсекает всё, что не про канал-триггер и не про отслеживаемые комнаты из реестра; REST — только для релевантных случаев. **Сделано:** `voices_rooms.py::on_voice_state_update` — сразу `return` на `before==after==None` и на «тот же канал» (mute/deaf/stream toggle); дальше только сравнения id и точечные обращения к реестру по каналу; REST (`create/move/delete`) — лишь в релевантных ветках. `mute.py` (реконсиляция роли «Молчун») и `anti.py`/`voices` — свои дешёвые ранние выходы.
  - Проверка: `review` ✓.
- [x] **P1.0f `on_ready` идемпотентен.** Флаг `_preflight_done` — preflight и `_ready_at` ставятся один раз; синк команд/загрузка когов/Command Permissions — в `setup_hook` (по определению один раз до первого коннекта). Сделано в P1.7b.
  - Проверка: `review` ✓.
- [x] **P1.0g Отсутствующие «мягкие» сущности — не падение.** `guild.afk_channel is None`, «категория роддом не резолвится» и т.п. в отборе каналов XP-тика трактуются как «нет такого исключения», а не ошибка. **Сделано:** `core/voice_xp.py::is_counted_channel` — `afk_channel_id=None` / `category_id=None` просто не срабатывают как исключения; `voices_xp.py::_accrue` берёт `guild.afk_channel.id if ... else None`.
  - Проверка: `unit` ✓ (`test_voice_xp.py::test_no_afk_configured_is_fine`).

- [x] **P1.1 `core/hierarchy.py`.** `check_hierarchy(HierarchyInput) -> HierarchyBlock` (`OK` / `TARGET_IS_OWNER` / `TARGET_IS_BOT` / `ROLE_NOT_LOWER`). Вход — dataclass примитивов (позиции топ-ролей, `target_is_bot`, `target_id`, `guild_owner_id`), без `discord.*`. Порядок: owner (явно, первым) → bot → `target_pos ≥ initiator_pos`. Причина — для лога; текст отказа выбирает команда. Ref: `rules.md` § "Роли и права".
  - Проверка: `unit` ✓ (`tests/test_hierarchy.py`: ниже/равно/выше по роли, бот, owner, owner-побеждает-роль-и-бота, порядок bot-до-роли).
- [x] **P1.2 `core/hierarchy.py` — self-mod.** `is_self_moderation(initiator_id, target_id) -> bool` — отдельный предикат (для `/mute`/`/ban`/`/kick` → `Что ты делаешь?`; `/unmute`/`/unban` его не зовут). Ref: `rules.md` § "Самомодерация".
  - Проверка: `unit` ✓.
- [x] **P1.3 `core/targets.py`.** `parse_target_id(raw) -> int | None` — чистый: `123` / `<@123>` / `<@!123>` → id; пусто/мусор/`<@&…>`(роль)/`<#…>`(канал)/вне snowflake → `None`. Резолв в member/user и проверку присутствия делает команда. Общие тексты `ERR_NO_TARGET` (`Укажите пользователя или id`), `ERR_TARGET_ABSENT` (`… Также возможно пользователь уже отсутствует на сервере`) — здесь же. Reply-на-сообщение не поддерживается. Ref: `mute.md`, `banKick.md`, `anti.md`.
  - Проверка: `unit` ✓ (`tests/test_targets.py`: raw/mention/nick-mention/whitespace, роль/канал-mention, хвост после mention, `0`/отрицательное/вне диапазона, текстовое имя).
- [x] **P1.4 `core/timefmt.py`.** Даты: `fmt_full` → `16-08-2026 18:49:30` (тире, 4-зн. год, anti), `fmt_short` → `13.12.25 19:21:36` (точки, 2-зн. год, roleGiver); оба принимают `datetime`/epoch, наивный `datetime` = UTC, вывод в MSK (UTC+3), от таймзоны хоста не зависит. Длительность: `parse_duration("<n><s|m|h|d>") -> сек` (`ValueError` на составной/дробный/мусор), `parse_mute_duration` = `parse_duration` + диапазон `60s..28d` (тот же `ValueError` на формат и на выход за границы). `MUTE_MIN/MAX_SECONDS` — константы. Ref: `mute.md`, `environment.md` § "Технический стек".
  - Проверка: `unit` ✓ (`tests/test_timefmt.py`: оба формата, epoch int/float, наивный dt, независимость от tz входа; парсер — границы, `1h30m`/`1.5h`, мусор, диапазон 59s/29d).
- [x] **P1.5 `core/permissions.py` — реплика Command Permissions.**
  - **P1.5a (чистое):** `CommandPerms` (dict'ы user/role/channel; role-ключ `guild_id` = @everyone, channel-ключ `guild_id-1` = все каналы), `parse_guild_command_permissions(raw, application_id) -> ResolvedPermissions` (per_command + app_default; `.for_command(id)` падает на app_default), `can_run_prefix(...)` — приоритет: канал (disable абсолютен) → user → роли (allow>deny) → @everyone → `default_member_permissions`.
  - **P1.5b (рантайм):** `CommandPermissionsCache(application_id, guild_id)` — `load(http, command_ids)` (живой `http.get_guild_application_command_permissions`), `apply_update(target_id, overwrites)` (по `on_raw_app_command_permissions_update`; пустой список = оверрайды сняты → падение на app_default), `invalidate()`, `known_command_names()`, `allows(command_name, …)` — **fail closed** (`False`), пока не прогружено. Подключено в `bot.py`: `setup_hook` грузит после синка (при `HTTPException` — лог + гейт закрыт), listener `on_raw_app_command_permissions_update` (фильтр по своей гильдии/приложению), **глобальный чек `_command_perms_check`** на invocation-time (slash/ЛС пропускает; префикс-only — пропускает, свой гейт в коге; иначе `cache.allows(...)` + `meets_default_permissions` от `default_permissions` команды и `channel.permissions_for(author)`; отказ → `CheckFailure` → молча). `meets_default_permissions(default, member)` — `None`/Administrator → да, иначе superset.
  - `default_member_permissions` мод-команд = `moderate_members`, проверяется как эффективное право в канале вызова — `Manage Channels` владельца комнаты `moderate_members` не даёт, `!mute` из его комнаты не проходит.
  - Проверка: `unit` ✓ (`tests/test_permissions.py`, 21: разбор+типы+app_default, весь приоритет, кэш — fail-closed/load/lookup-by-name/apply_update add-clear-app-level/before-load-noop/invalidate); `manual` — канальные оверрайды на живом боте (после токена).
- [x] **P1.6 `core/dm_guard.py`.** `DM_ALLOWED_COMMANDS = {"vdel", "ban_list"}`, `is_allowed_in_dm(name)`. В `bot.py`: глобальный чек `_dm_guard_check` (в гильдии → пропуск; в ЛС → только whitelist, иначе `CheckFailure`); `on_command_error` молчит на `CommandNotFound`/`CheckFailure` (покрывает и DM-guard, и будущий гейт Command Permissions на `!`-пути), прочее — `log.error` с контекстом (не голый traceback; ошибки разбора аргументов модули ловят сами). Ref: `rules.md` § "Команды в ЛС".
  - Проверка: `unit` ✓ (`tests/test_dm_guard.py`, 4: `is_allowed_in_dm` + `_dm_guard_check` — гильдия/whitelist/блок/нет команды).
- [x] **P1.7 `core/preflight.py` + ког `healthcheck`.**
  - **P1.7a (чистое):** `CheckResult(section,label,ok,detail,fatal)` c `.line` (`[startup][<раздел>] <label>: OK|ОШИБКА — <деталь>`); `any_fatal`, `summary_line` (`[startup] ИТОГ: …`), `format_uptime` (`4д 3ч 12м`); отдельные проверки `check_guild`/`check_intents`/`check_db` (fatal), `check_managed_role` (резолв + позиция бота строго выше, `None` = не найдена), `check_guild_permissions`, `check_channel` (не найден / не хватает прав), `check_command_permissions_api` (не fatal — fail closed). Всё на примитивах.
  - **P1.7b (оркестратор + подключение):** `ConnorBot.run_preflight()` собирает входы и зовёт `check_*`: гильдия по ID, intents (`self.intents`), БД `ping()`, 3 управляемые роли (позиция vs `guild.me.top_role`), guild-level права (9 из таблицы `development.md`), 11 каналов + 2 категории из `.env` (резолв + `permissions_for(guild.me)` по таблице), AFK-канал (инфо, `None` — не ошибка), Command Permissions API (живой `get_guild_application_command_permissions`). `on_ready` — один раз (флаг, P1.0f), логирует построчно (OK→INFO, warn→WARNING, fatal→ERROR) + ИТОГ; при `any_fatal` → `_exit_code=1` + `close()`; `run_bot` возвращает `_exit_code`. БД подключается в `setup_hook` (ошибка миграций = бот не поднялся, exit 1), закрывается в `close()`. Ког `cogs/healthcheck.py` — slash-only, ephemeral, `default_permissions(moderate_members=True)`, зовёт `bot.run_preflight()` + `Аптайм: …` (от `on_ready`, не персистентно).
  - Проверка: `unit` ✓ (`tests/test_preflight.py`, 11: формат строки, каждая `check_*`, `any_fatal`/`summary_line`/`format_uptime`); `manual` ✓ (offline-прогон `run_preflight` без коннекта → гильдия ОШИБКА fatal, intents OK, БД OK, ИТОГ «бот НЕ поднят», `any_fatal=True`); **ждёт токена:** роль/право/канал-проверки на живой гильдии + `/healthcheck` в Discord.

---

## P2 — Независимые модули (после P1, между собой параллельны)

### P2.A moderationChat — `moderation_chat.py` · Ref: `moderationChat.md`

- [x] **P2.A1–A5 `cogs/moderation_chat.py` + `core/channels.py`.**
  - **Вход:** `on_message` listener → `should_process_message` (P1.0c: не бот, не вебхук) + `message.guild is not None`; edit не слушаем.
  - **Исключение «роддом»:** `core.channels.in_roddom(message.channel, RODDOM_id)` (вынесено из purge; резолв тред→`parent.category_id`).
  - **Слова → `#чек-лист`:** `find_suspicious(text, config.moderation_chat.suspicious_words)` — первая подстрока `casefold`, без границ слова; embed (`title`=`#<канал>`, поля «Автор»=`mention`, «Содержание»=`content[:1024]` или `—`, «Ссылка на пост»=`jump_url`). Над оригиналом — ничего.
  - **Медиа → `#чек-лист2`:** `[att.proxy_url for att in message.attachments]` + `extract_gif_links(text, gif_domains)` (URL, чей host == домен из списка или его поддомен; обрезка хвостовой пунктуации). Триггер если непусто. Сообщение №1: текст (если был) первой строкой + все ссылки; сообщение №2: embed-метаданные (`#<канал>`, «Автор», «Ссылка на пост»). `proxy_url`, не скачивание; оригинал не трогаем.
  - **Пересечение:** `_check_words` и `_check_media` вызываются независимо — сообщение может уйти в оба.
  - **None-guard** каналов `#чек-лист`/`#чек-лист2` — лог 1 раз на канал (`_missing_logged`).
  - Проверка: `unit` ✓ (`test_moderation_chat.py` 10 — матчер слов вкл. часть слова/пустые записи, GIF-ссылки по домену/поддомену/хвост-пунктуация/чужой домен/пустой список, оба embed вкл. усечение 1024; `test_channels.py` 3); smoke ✓ (все 5 когов грузятся); `manual` — реальная пересылка, GIF из пикера, текст+картинка, тред.

### P2.B purge — `purge.py` · Ref: `purge.md`

- [x] **P2.B1–B4 `cogs/purge.py`.** `!purge` — обычный `commands.command` (не hybrid, не в дереве → глоб. Command-Permissions-гейт не трогает), `guild_only`.
  - **Разбор** `parse_purge_args(args) -> PurgeSpec | PurgeError`: `<count>` | `user <id> <count>` | `match/not <текст…> <count>` | `links/images/text <count>`. `_parse_count` = `isdigit()` + `> 0`. `BAD_COUNT` (`Количество указано не верно`) для отсутствующего/не-числа/0/отриц. count; `BAD_SYNTAX` (`Команда указана не верно.`) для неизвестного режима / лишних аргументов / не-id в `user` / пустого текста в `match/not`.
  - **Гейт**: эффективное `Manage Messages` в канале (нет → тихо); `in_roddom(channel, RODDOM_id)` с резолвом тред→родитель (внутри → тихо). Тексты ошибок разбора — только когда право есть и канал разрешён.
  - **Отбор** `message_matches(spec, MsgView)`: `all`→всё; `user`→по id; `match/not`→подстрока `casefold`; `links`→`https?://`; `images`→attachment `image/*`; `text`→нет ссылок и вложений. Чужих ботов пропускаем всегда. Скан `channel.history(before=ctx.message, after=utcnow()-14d, oldest_first=False)` — граница 14 дней сама останавливает; набираем `min(count, soft_limit=300)` совпадений; удаление пачками ≤100 (`delete_messages`, 1 шт → `.delete()`).
  - **Ответ**: `:pudge:` в канал вызова + embed в `#бот-команды` (None-guard, лог 1 раз): author = `global_name`+аватар; тело `<ник-без-пинга> использовал :pudge: <raw args> в канале <#канал>`; число удалённых не пишется.
  - Проверка: `unit` ✓ (`tests/test_purge.py`, 25: разбор всех форм + BAD_COUNT/BAD_SYNTAX кейсы, `message_matches` все режимы, `in_roddom` канал/тред/без категории, embed); smoke ✓ (ког грузится, префикс-only); `manual` — реальное удаление, граница 14 дней, лимит 300, `:pudge:`.

### P2.C banKick — `ban_kick.py` · Ref: `banKick.md`

- [x] **P2.C1–C3 `cogs/ban_kick.py`.** Три hybrid-команды `ban`/`kick`/`unban` (`/`+`!`), `default_permissions(moderate_members=True)` + `guild_only`, `target: str` (`parse_target_id`), `reason` через consume-rest. `kick`/`unban` — причина обязательна (нет → `Укажите причину`), `ban` — опциональна (`Причина не указана`). Порядок проверок `/ban`: no-target → не на сервере (`ERR_TARGET_ABSENT`) → self (`Что ты делаешь?`) → иерархия (`hierarchy_reject("банить")`) → уже в бане (`fetch_ban`→`Пользователь уже в бане`) → `guild.ban(delete_message_seconds=0)` → embed. `kick`: no-target → member нет (`ERR_NO_TARGET`) → нет причины → self → иерархия (`hierarchy_reject("кикать")`) → `guild.kick` → embed. `unban`: no-target → нет причины → не в бане (`fetch_ban`→`Не нашел пользователя <@…> в списке банов`) → `guild.unban` → embed (без иерархии/self — снятие наказания). Embed: зелёная полоса, `set_author` = `display_name`+аватар, поле «Причина», текст `@… кикнут с сервера` / `@… забанен. Помянем.` / `@… разбанен. Возрадуемся!`; ответ в канал вызова (`ctx.send`). `Forbidden` в рантайме → лог + `Не удалось выполнить…`. `cog_command_error` → `MissingRequiredArgument(target)` = `ERR_NO_TARGET`. DM/хранилища нет.
  - Проверка: `unit` ✓ (`tests/test_ban_kick.py`, 9: тексты отказа, embed, весь порядок веток `/ban` + дефолтная причина); smoke ✓ (коги грузятся, 3+3 команды, гейт = бит `moderate_members`); `manual` — реальные ban/kick/unban, `!`-позиционка, `#баны`/`#бот-команды`, `cog_command_error`.

### P2.D mute — `mute.py` · Ref: `mute.md`

- [x] **P2.D1–D6 `cogs/mute.py` + `core/mute_state.py` + `core/msg_guard.py` (P1.0c).**
  - **`/mute` (+`!`), валидация:** `target` (`parse_target_id`) → `ERR_NO_TARGET` / member нет → `ERR_TARGET_ABSENT`; `time` (`parse_mute_duration`, `ValueError` → `Время указано некорректно`); self → `Что ты делаешь?`; иерархия → `Вы не можете мутить старших…`. `!mute` позиционка `<target> <time> [reason]`; `cog_command_error`: missing `target`→`ERR_NO_TARGET`, missing `time`→`Время указано некорректно`.
  - **Первое наложение:** `member.timeout(timedelta(seconds))` + роль «Молчун» (None-guard, лог 1 раз) + DM-embed (зелёный, «Вы получили мут…», `**Причина**`, `[Правила сервера](rules_url)` из `config/mute.toml` или plain при пустом, абзац обжалования) + embed в канал вызова (зелёный, `@… замьючен на <time>`, поле «Причина»). `state.begin(...)`. DM-фейл (`HTTPException`) — `log.info`, не блокирует. `timeout` `Forbidden` в рантайме → лог, тихо.
  - **Обновление (цель уже `is_timed_out()`):** только если `MuteState.can_update` (нет цикла / окно 60 c истекло / вызывающий = владелец), иначе `Пользователь уже в муте`. `timeout` пересчитывается от now; жёлтый DM + жёлтый канал-embed `@… перемьючен с <old_time> на <new>` (`old_time` = `state.last_time` или остаток таймаута `format_hms`). `state.record_update`.
  - **`MuteState`** (в памяти, рестарт не переживает): `begin`/`record_update`/`can_update(target,mod,now)`/`last_time`/`end`; окно фиксировано от `first_applied_at`, не продлевается премутами; запись живёт весь цикл (нужна для `old_time`).
  - **`/unmute` (+`!`):** не `is_timed_out()` → `Пользователь не в муте` (обычный текст). Иначе `timeout(None)` + снять роль (фейл — тихо, уберёт реконсиляция) + `state.end` + plain-DM `Ограничения на сервере "…" сняты` + зелёный embed `@… размьючен` (⚠️ спека не задаёт канал-ответ для успешного `/unmute`, но slash нужен ответ — см. вопрос).
  - **Реконсиляция «Молчун»:** напр.1 (роль есть, `not is_timed_out()`) — `on_message` (через `should_process_message`) + `on_voice_state_update` (вход в войс) → снять роль + `state.end`; напр.2 (`is_timed_out()`, роли нет) — `on_member_join` → вернуть роль.
  - **`core/msg_guard.should_process_message`** (P1.0c): `False` для ботов и вебхуков (`author.bot` OR `webhook_id`).
  - Проверка: `unit` ✓ (`test_mute_state.py` 7 — окно/владелец/премут-не-продлевает/`end`/orphan; `test_mute.py` 11 — `_rules_link`, оба DM-embed, оба канал-embed, порядок веток `/mute` + резервация-блок; `test_msg_guard.py` 3); smoke ✓ (коги грузятся, gate `moderate_members`); `manual` — реальные timeout/роль/DM, обе реконсиляции, `!`-позиционка.

---

## P3 — Кластер «работяга» (строго по порядку)

### P3.1 anti — ядро — `anti.py` · Ref: `anti.md`

- [x] **P3.1a–c `cogs/anti.py` + `db/repo_anti.py` + `db/repo_predlozhka.py` + `predlozhka.py`.**
  - **`RepoAnti`**: `add(user_id, added_at, added_by) -> bool` (`False` если уже есть — INSERT + `IntegrityError`; заодно покрывает гонку `/add`), `remove -> bool`, `contains`, `get`. Причина не хранится.
  - **`RepoPredlozhka`** + **`connor/predlozhka.py`**: `apply_deny(channel, member, repo, reason)` — персональный overwrite `send_messages=False` + отметка в БД; `clear_deny(...)` — снимает **только** бот-овый deny (по БД), убирает overwrite целиком если пуст, не трогает ручные модераторские.
  - **`/add` (+`!`)**: `parse_target_id` → `ERR_NO_TARGET`; `fetch_user` NotFound → `ERR_NO_TARGET`; `repo.add` `False` → `Пользователь <@…> уже существует в списке антиработяг`. Иначе: если `member` в гильдии и `permissions_for(member).send_messages` → `apply_deny`; снять роль «работяга» (если есть). Два сообщения в `#антиработяги` (= канал вызова): embed «Добавление» (описание, поля «Причина»/«Дата добавления» `fmt_full`, footer `Claptrap желает вам приятного дня • <fmt_full_minute>`) + embed «изъяли роль»/`Работяга`/`!add id/квот причина` при успехе снятия, иначе `Я не смог изъять роль…`.
  - **`/del` (+`!`)**: `parse_target_id` → `ERR_NO_TARGET`; `fetch_user` NotFound (удалённый аккаунт) → тихо `repo.remove` + `ERR_NO_TARGET`, без embed'ов. Не в анти-списке → `Пользователь не в списке антиработяг` (текст, не embed; роль не возвращается) **+ страховочная реконсиляция**: `clear_deny` (снимает висящий бот-овый deny в «предложке», если он остался; ручные overwrite не трогает). Иначе: `repo.remove`, `clear_deny`, **безусловно** вернуть роль (add_roles если её нет), embed «Удаление» (без «Даты удаления») + текст `Роль возвращена`.
  - **Гейт**: `default_permissions(moderate_members)`; `cog_command_error` missing `target` → `ERR_NO_TARGET`. `Forbidden` в рантайме → лог, тихо.
  - Проверка: `unit` ✓ (`test_repo_anti.py` 2, `test_repo_predlozhka.py` 1, `test_anti.py` 20 — embed'ы + порядок веток `/add`/`/del` вкл. предложка-deny, удалённый аккаунт, «не в списке» со снятием stale-overwrite, вотчер; на реальной БД + фейках Discord); smoke ✓.
  - **wiki:** `anti.md` дописан — `/del` на «не в списке» (текст `Пользователь не в списке антиработяг` + снятие stale bot-overwrite) в §"Логика работы" п.5 и таблице ошибок; цвета embed'ов anti (красный add/изъятие, зелёный del) — спека их по-прежнему не задаёт, оставлено на усмотрение реализации.

### P3.2 anti — вотчер ручных изменений роли — `anti.py` · Ref: `anti.md` § "Наблюдение…"

- [x] **P3.2a–b Watcher в `cogs/anti.py` (`on_member_update`).** Быстрый выход, если членство в роли «работяга» не менялось. Иначе: `asyncio.sleep(5)` → `guild.audit_logs(limit=10, action=member_role_update)`, матч по `entry.target.id` + роль в `entry.after.roles` (выдача) / `entry.before.roles` (снятие); не найдено → `log.warning`, без падения; весь блок в `try/except` + `log.exception` (P1.0a). Автор == `bot.user` → ничего (команда уже отчиталась).
  - **Снятие вручную** → `#антиработяги`: `build_role_removed_embed(mention, moderator=actor)` — тот же формат, что у `/add`, но с author-модератором; независимо от анти-статуса.
  - **Выдача вручную анти-работяге** (`anti_repo.contains`) → `anti_repo.remove` + `clear_deny` в «предложке» + `#антиработяги`: embed «Удаление» (причина `роль «работяга» выдана вручную`) + `Роль возвращена`. Не в списке → тихо.
  - Проверка: `unit` ✓ (`test_anti.py` +6 — не-релевантный update, снятие модератором/ботом, выдача анти/не-анти, актор не найден; `asyncio.sleep` замокан); smoke ✓ (listener `on_member_update` зарегистрирован).

### P3.3 check — `check.py` · Ref: `check.md` (зависит от anti)

- [x] **P3.3a–c `cogs/check.py`.** (Механика overwrite — `RepoPredlozhka` + `connor/predlozhka.py` — сделана в P3.1.)
  - **`/check` (+`!`)** — hybrid, `guild_only`, **без** `default_permissions` (пользовательская, описание `Проверить доступ в предложку`). Читает анти-статус (`RepoAnti`), берёт `#предложка` (None-guard → лог 1 раз → `Недостаточно прав`). Реконсиляция: `not is_anti and pred_repo.contains(id)` → `clear_deny`. Ответ: `permissions_for(member).send_messages AND not is_anti` → `Доступ открыт`, иначе `Недостаточно прав`.
  - **Ленивая простановка** — `on_message` listener (через `should_process_message`): канал == `#предложка` И `anti_repo.contains(author)` → `message.delete()` (тихо на фейле) + `apply_deny` (персональный `send_messages=False`, `View` не трогается, отметка в `RepoPredlozhka`).
  - **Снятие**: основной путь — `/del` (P3.1); подстраховка — реконсиляция в `/check` выше. `clear_deny` снимает только бот-овый deny (по БД), ручные модераторские overwrite не трогает.
  - Проверка: `unit` ✓ (`test_check.py` 8 — все 4 ветки ответа, реконсиляция stale-overwrite, нет канала, ленивый deny для анти/не-анти/другой канал); smoke ✓ (7 когов, `/check` gate `None`).

### P3.4 roleGiver — `role_giver.py` · Ref: `roleGiver.md` (зависит от anti)

- [x] **P3.4a–f `cogs/role_giver.py` + `db/repo_give.py`.**
  - **`evaluate_give(account_created_at, joined_at, now, cfg) -> list[GiveReason]`** — чистая: B (`now-created < account_min_age_days`), C (`now-joined < member_min_tenure_days` или `joined is None`), D (`joined-created < join_after_register_min_minutes`); независимо, OR; порядок B→C→D. Пороги из `config/role_giver.toml`.
  - **`/give` (+`!`)** — hybrid, `guild_only`, без `default_permissions`. Сц.3: `anti_repo.contains` → `_REFUSAL` (без пинга). Сц.1: `reasons == []` → `_grant` (add_roles «работяга», None-guard/`Forbidden` → лог) → `Роль выдана.` Сц.2: `Ваш запрос передан на ручную обработку…` + `build_review_message` (`@here` + строки B/C/D + `fmt_short`) в `#реквесты-работяг` (`AllowedMentions(everyone,users)`), реакции ☑️/❌, `give_repo.add(msg.id, user_id, ts)` (персистентно). Повторный `!give` не блокируется.
  - **`RepoGive`**: `add` (INSERT OR REPLACE), `remove -> bool` (**атомарный захват заявки**), `get`.
  - **`on_raw_reaction_add`** (сырое, переживает рестарт): фильтр по гильдии/боту/эмодзи; `get` заявку → `remove` (кто первый вернул `True` — тот решает, гонка) → `_resolve`: `fetch_member` (`NotFound` → ушёл → удалить заявку-сообщение, без ответа) → ☑️ выдать роль; удалить сообщение заявки (`get_partial_message().delete()`); ответ в `#выдача-работяг` `@…, роль выдана.` / `@…, <_REFUSAL>` (пинг `users`); `#аудит` embed (`payload.member` / `fetch_member`). Весь `_resolve` в `try/except` + `log.exception`.
  - **`on_raw_message_delete`** в `#реквесты-работяг` → `give_repo.remove` (модератор удалил заявку вручную; бот-овое удаление в `_resolve` — no-op, запись уже снята).
  - **`build_audit_embed`**: одобрено → зелёный, `<mod> обновил <target>` / `Выдана роль` / `@Работяга`; отказано → красный, `<mod> отказал …` / `Отказ в выдаче роли`. Сц.1 и 3 не логируются.
  - Проверка: `unit` ✓ (`test_repo_give.py` 1, `test_role_giver.py` 17 — B/C/D все комбинации + `joined=None`, текст заявки B+C и D, аудит-embed, три сценария `/give`, `on_raw_reaction_add` одобрение+лог/гонка-второй-noop/бот-и-неизвестный-эмодзи, `on_raw_message_delete`); smoke ✓ (8 когов, listeners `on_raw_reaction_add`+`on_raw_message_delete`).
  - wiki: Home.md ✅→☑️ (совпадение с roleGiver.md).

---

## P4 — Voices (строго по порядку) · Ref: `components/Voices.md`

### P4.1 Создание комнат — `voices_rooms.py` · Ref: § "Создание приватной комнаты"

- [x] **P4.1a Триггер.** `on_voice_state_update`: `after.channel == CH_TRIGGER_VOICE`. Создать голосовой канал в `CAT_PRIVATE_VOICE` со стандартными параметрами (`config/voices.toml`): имя = `user.name` (не display/nick), тип 2, битрейт 64000, user_limit 0, NSFW снят, slowmode 0. Переместить владельца внутрь. Персональный overwrite на канал: **ровно** `View Channel` + `Manage Channels` = allow, ничего больше (никаких `Moderate/Mute/Deafen/Move Members`) — Voices явно не даёт прав модерации; этот минимализм — ещё и то, на что опирается выбор гейта мод-команд (`moderate_members`, см. таблицу решений).
  - **Сделано:** `cogs/voices_rooms.py` — `_create_room`. Раннее отсечение по каналу-триггеру/отслеживаемым комнатам (P1.0e). Overwrite владельца — модульная константа `_OWNER_OVERWRITE` (`view_channel` + `manage_channels`), передаётся в `create_voice_channel(overwrites=)` вместе с deny активных банов (P4.3c). `slowmode_delay` не принимается `create_voice_channel` в discord.py 2.7 — ставится отдельным `channel.edit`, только если `room_slowmode` задан.
  - Проверка: `review` ✓; `unit` ✓ (`test_voices_rooms.py` — параметры создания, overwrites); `manual` (сверка по аудит-логу — ждёт токена).
- [x] **P4.1b Реестр.** Запись `voice_rooms` (owner_id→channel_id). Неудачный перенос (владелец уже отключился) → **сразу удалить** созданный канал.
  - **Сделано:** `db/repo_voice_rooms.py` (`RepoVoiceRooms`: `upsert`/`get_by_owner`/`get_by_channel`/`remove_by_owner`/`all`). `_create_room` ловит `HTTPException` на `member.move_to` → `channel.delete` + без записи в реестр.
  - Проверка: `unit` ✓ (`test_repo_voice.py`, `test_voices_rooms.py::test_trigger_move_fail_deletes_channel`); `manual` — ждёт токена.
- [x] **P4.1c Повторный вход в триггер.** Есть активная запись → перенести в существующий канал; запись есть, но канала нет → считать закрытой, создать новый.
  - **Сделано:** `_handle_trigger` — `get_by_owner` → `guild.get_channel`; есть канал → `move_to`; нет → `remove_by_owner` + `_create_room`. **Ревью-фикс:** `_handle_trigger` возвращает id комнаты, куда владельца вернули; `on_voice_state_update` пропускает `_maybe_close_room(before_ch)`, если `before_ch.id == moved_back_to` — иначе владелец, один в своей комнате и зашедший в триггер, удалял бы её (кэш `channel.members` ещё не отразил возврат → комната «пустая»).
  - Проверка: `unit` ✓ (`test_trigger_with_live_room_moves_there`, `test_trigger_with_stale_registry_creates_new`, `test_owner_alone_reentering_trigger_keeps_room`); `manual` — ждёт токена.

### P4.2 Жизненный цикл — `voices_rooms.py` · Ref: § "Жизненный цикл комнаты"

- [x] **P4.2a Удаление при опустении.** Любой уход из канала комнаты (полный disconnect / перенос Discord в AFK / перетаскивание модератором) = событие `on_voice_state_update` с уходом; как только в канале никого — удалить канал + запись. Владелец в AFK, гостей нет → комната удаляется.
  - **Сделано:** `_maybe_close_room(before_ch, left=member)` — срабатывает на любом уходе из отслеживаемой комнаты (`before_ch.id != after_ch.id`); фильтр `m.id != left.id` на случай, если кэш ещё не отразил уход; пусто → `channel.delete` + `remove_by_owner`.
  - Проверка: `unit` ✓ (`test_empty_room_deleted_on_last_leave`, `test_room_with_guests_survives`); `manual` (AFK-кейс) — ждёт токена.
- [x] **P4.2b Сверка реестра.** Минутный `tasks.loop` (общий с XP-тиком, P4.4): запись, чей канал не существует (удалён вручную) — убрать.
  - **Сделано:** `cogs/voices_xp.py::_reconcile_rooms` — `guild.get_channel is None` → `remove_by_owner`. Плюс бэкстоп: пустая комната старше одного тика (пропущенное событие / рестарт при пустой) — удалить канал + запись.
  - Проверка: `unit` ✓ (`test_voices_xp_cog.py`: missing-channel / stale-empty / fresh-empty-kept).

### P4.3 Самомодерация — `voices_selfmod.py` · Ref: § "Управление своим голосовым каналом"

- [x] **P4.3a `/vkick` (+`!`) в `#флудиславль`.** Проверка: вызвавший — владелец **бот-комнаты** из реестра и сейчас в ней (иначе `У вас нет прав… или вы не находитесь в голосовом канале`). На общие/предустановленные войсы не распространяется. Цель: обязана быть на сервере (`Вы не указали пользователя или его нет на сервере`), присутствие в войсе не требуется. Действия: disconnect **только** если цель в комнате вызвавшего (в другом канале — не трогать); в любом случае — deny `Connect` overwrite на комнату + снять доступ к встроенному текст-чату + запись в `voice_banlist` (`ts`=now). Лимит **100** → `Список забаненных пользователей достиг лимита. Используйте команду banList для подробностей`. Успех → `Пользователь @… забанен в ваших комнатах.` Ответ ephemeral для slash. Описание Discord: `Кикнуть %username% из приватного войс канала`.
  - **Сделано:** `db/repo_voice_banlist.py` (`RepoVoiceBanlist`: `upsert`/`remove`/`contains`/`count`/`list_for`/`active_ids`). `/vkick` hybrid, без `default_permissions`, `guild_only`; цель через `guild.fetch_member` (P1.0d); overwrite `connect=False` + `send_messages=False` (встроенный текст-чат; видимость канала не трогаем); disconnect только при совпадении канала; лимит блокирует лишь **новую** запись (повторный `/vkick` по уже забаненному проходит). Ответ `ephemeral=True` (для `!` игнорируется Discord).
  - Проверка: `unit` ✓ (`test_voices_selfmod.py` — не-владелец / не-в-своей-комнате / нет цели / цель не на сервере / лимит 100 блок / уже забанен обходит лимит / disconnect при совпадении канала / без disconnect в чужом канале); `manual` — ждёт токена.
- [x] **P4.3b `/vreturn` (+`!`) / `!vdel` (ЛС).** Без проверки владения/присутствия. Убрать из `voice_banlist`; если у вызвавшего есть активная комната и на ней стоит deny `Connect` для этого id — **сразу снять**. Успех → `Пользователь @… разбанен.`; нет в списке → `Пользователь не найден в списке забаненных.` `%username%`-описания зафиксированы в вики.
  - **Сделано:** общий `_unban(invoker_id, guild, raw_target)`. `/vreturn` — hybrid `guild_only`, ephemeral. `!vdel` — `commands.command` (prefix-only), в гильдии молча выходит, в ЛС резолвит гильдию через `bot.get_guild`; обе в `DM_ALLOWED_COMMANDS` (P1.6). Снятие overwrite — `bot.http.delete_channel_permissions` по сырому id (у ушедшего с сервера нет `Member`, а `set_permissions` его не принимает); только если deny реально стоял.
  - Проверка: `unit` ✓ (`test_voices_selfmod.py` — нет в списке / снятие deny с активной комнаты / без активной комнаты / `!vdel` в гильдии игнор / `!vdel` в ЛС); `manual` — ждёт токена.
- [x] **P4.3c Пересоздание комнаты + 24ч-окно.** При новом создании переносить deny-overwrite только для «активных» записей (`ts` в пределах 24ч). Старые — лениво: попытка подключения забаненного → реактивный disconnect + обновить `ts`=now (после этого запись «самоисцеляется»).
  - **Сделано:** `_create_room` — `banlist.active_ids(owner, since_ts=now - 24ч*3600)` → deny в `overwrites=` при создании канала. `voices_rooms.py::_maybe_reactive_block` — вход в отслеживаемую комнату + `banlist.contains(owner, joiner)` → `move_to(None)` + постоянный overwrite + `upsert(..., ts=now)`.
  - Проверка: `unit` ✓ (`test_voice_xp.py`-предикат окна в `RepoVoiceBanlist.active_ids`; `test_voices_rooms.py::test_active_bans_transferred_on_create`, `test_reactive_block_for_banned_joiner`, `test_non_banned_joiner_ignored`); `manual` — ждёт токена.
- [x] **P4.3d `/ban_list` / `!ban_list`.** Всегда шлёт список в ЛС (embed: синяя полоса, заголовок `Список забаненных`, описание с `!vreturn`/`!vdel`, записи с `` `<@id>` `` + `id: <id>`, footer-пример). В месте вызова: `Информация отправлена в лс` / `Я не могу отправить тебе список. Открой ЛС`. `!ban_list` доступен и в ЛС боту. Описание Discord: `Управление бан-списком приваток`.
  - **Сделано:** `build_banlist_embeds` — 100 записей не влезают в один `description` (лимит 4096), поэтому список бьётся на несколько embed'ов (заголовок — у первого, footer — у последнего, сквозная нумерация); каждый уходит отдельным DM. `ban_list` hybrid без `guild_only` (работает и как `!ban_list` в ЛС; slash guild-scoped сам не появляется в ЛС).
  - Проверка: `unit` ✓ (`test_voices_selfmod.py` — структура embed / разбиение на >1 при 100 записях / DM ок + подтверждение / DM закрыт); `manual` — ждёт токена.

### P4.4 XP-тик — `voices_xp.py` · Ref: § "Начисление опыта", `development.md` § "Тик начисления опыта"

- [x] **P4.4a Отбор каналов.** Единый `tasks.loop(minutes=1)`. Область = `guild.voice_channels` минус: канал внутри `CAT_RODDOM` (по `category_id`), `guild.afk_channel`, `CH_TRIGGER_VOICE`; Stage-каналы не входят. Только локальный кэш, без REST.
  - **Сделано:** `cogs/voices_xp.py` — один `tasks.loop(seconds=tick_interval_seconds)`; тело в `try/except` + `@tick.error` (P1.0a); `before_loop` = `wait_until_ready` + `ensure_cycle`. `core/voice_xp.py::is_counted_channel` — чистый предикат (`is_stage` параметром для теста; `guild.voice_channels` Stage и так не отдаёт). Порядок итерации: сверка реестра → недельная проверка → начисление.
  - Проверка: `unit` ✓ (`test_voice_xp.py` — роддом/AFK/триггер/Stage/обычный/без-AFK; `test_voices_xp_cog.py::test_accrue_skips_excluded_channels`).
- [x] **P4.4b Начисление за тик (self-accrual).** Исключён (сам 0 и не «сосед»): deaf (self/server) или бот. Не исключён: очки себе только если в канале есть ≥1 другой не исключённый; мут микрофона (self **или** server, без deafen) → +8; без мута → +10; стрим экрана/вебка при выполнении условия → +5 (разово). Батч-запись в `voice_xp_week` (UPSERT по user_id), нулевой прирост не пишется; порядок вставки (rowid) = момент первого начисления в неделе, на нём держатся ничьи.
  - **Сделано:** `core/voice_xp.py::accrue_tick(list[VoiceMemberState], cfg) -> {uid: очки}` — чистая. `db/repo_voice_xp.py::add_points` — `executemany` UPSERT `points = points + excluded.points`; `standings()` = `WHERE points > 0 ORDER BY points DESC, seq ASC`. `_state_of` сворачивает `member.voice` (self/server deaf+mute, self_stream|self_video).
  - Проверка: `unit` ✓ (`test_voice_xp.py` — один в канале / стрим в одиночку / +10 / +8 / +8 при server-mute / +5 бонус / +8+5 / deaf-сосед не считается / бот-сосед / 1 актив + 2 deaf / deaf + 2 актива; `test_voices_xp_cog.py::test_accrue_writes_batch`).

### P4.5 Недельная перевыдача — `voices_xp.py` · Ref: § "Перевыдача и недельный цикл"

- [x] **P4.5a Точка отсчёта.** При первом чистом старте (нет строки в `voice_cycle`) — записать now. Проверка «цикл истёк» = `now - anchor >= 7д`.
  - **Сделано:** `RepoVoiceXp.ensure_cycle` (`INSERT OR IGNORE`, вызывается из `before_loop`); `core/voice_cycle.py::is_cycle_expired(now, anchor_ts, week_seconds)`.
  - Проверка: `unit` ✓ (`test_voice_cycle.py`, `test_repo_voice.py::test_cycle_ensure_is_idempotent`).
- [x] **P4.5b Догон.** На старте, если цикл истёк за время offline — выполнить перевыдачу **один раз**, затем сдвинуть anchor (ровно на один цикл, не по разу за неделю).
  - **Сделано:** `core/voice_cycle.py::next_anchor` — сдвиг на **целое** число прошедших циклов сразу за `now`: после одной перевыдачи цикл перестаёт быть истёкшим независимо от длительности offline (одна догоняющая перевыдача, дальше — недельная каденция по той же фазе). При штатной работе = +1 неделя.
  - Проверка: `unit` ✓ (`test_voice_cycle.py::test_long_offline_catches_up_once` + штатный сдвиг).
- [x] **P4.5c Выбор лидера + ничьи.** Выборка `voice_xp_week` `ORDER BY points DESC, rowid ASC`. Победитель — первая строка. Снять роль с `current_dusha_id` (если задан и на сервере); нет/ушёл → сообщение в `#бот-команды` `Я не нашёл на сервере предыдущего топ-1 пользователя…`, роль новому всё равно. Победитель ушёл с сервера → спускаться по списку до присутствующего. Никто не набрал / список пуст → роль не трогать, `#флудиславль` молчит, но anchor сдвинуть, счёт сбросить, в `#бот-команды` штатное `Переназначение роли … прошёл успешно.`
  - **Сделано:** `core/voice_cycle.py::pick_winner(standings, present)` — чистая (первый из `present` сверху списка; разница = его очки минус очки следующей строки, 0 если он последний). `_run_weekly` спускается по списку через `_resolve_member` (`get_member` → `fetch_member`, P1.0d), останавливаясь на первом присутствующем. Снятие роли с прежнего + предупреждение в `#бот-команды` — **только** при реальной перевыдаче (есть новый лидер); при `prev_id is None` (первый цикл) предупреждение не шлётся. Никто не набрал → `new_dusha = prev_id` (роль не тронута), `#флудиславль` молчит, anchor сдвинут, счёт сброшен, штатное сообщение в `#бот-команды`.
  - **Ревью-фикс:** тот же победитель, что и на прошлой неделе (`awardee_id == prev_id`) → снятие роли **не** вызывается; `add_roles` вызывается всегда (идемпотентно подтверждает роль, чинит случай «потерял роль среди недели»). Причина: `remove_roles`/`add_roles` не обновляют локальный кэш `member.roles` синхронно — прежний `role not in awardee.roles` после `remove_roles` на том же объекте был устаревшим и `add_roles` пропускался → повторный лидер оставался **без** роли.
  - Проверка: `unit` ✓ (`test_voice_cycle.py` — пустой / топ+разница / один участник / топ ушёл (спуск) / никого нет / ничья по порядку; `test_voices_xp_cog.py` — перевыдача+сброс / повторный лидер подтверждает роль без снятия / победитель ушёл→спуск / никто не набрал / прежний обладатель ушёл→предупреждение но выдаём / не истёк→noop); `manual` — ждёт токена.
- [x] **P4.5d Уведомления.** `#флудиславль`: `Роль @Душа компании получает @упоминание, разница со вторым местом составила <N> экспы` — упоминание нового обладателя **с реальным пингом**; `@Душа компании` — просто текст роли, роль не пинговать; нет второго места → `<N>=0`. `#бот-команды`: `Переназначение роли "Душа компании" и сброс экспы прошёл успешно.` Затем сброс `voice_xp_week`, обновление `current_dusha_id`.
  - **Сделано:** `_run_weekly` — `fludislavl.send(..., allowed_mentions=AllowedMentions(users=[awardee]))` (пинг только новому); `@Душа компании` — литерал в тексте (роль не `<@&…>`). Затем `reset_week()` + `set_cycle(anchor_ts=new_anchor, current_dusha_id=new_dusha)`. Все каналы под None-guard.
  - Проверка: `unit` ✓ (текст с разницей 20 / разницей 0 / `#флудиславль` молчит когда никто не набрал — `test_voices_xp_cog.py`); `manual` — ждёт токена.

### P4.6 `/ladder` — `voices_ladder.py` · Ref: § "Лидерборд"

- [x] **P4.6a `/ladder` / `!ladder` в `#флудиславль`, любому.** До 10 строк в порядке выборки (`points DESC, rowid ASC`); упоминания **без пинга**, при нерезолве ника — сырой id. <10 с опытом → показать сколько есть, нулевые не включать. Никто → обычный текст `недельный ладдер комнат пуст` (не embed). Строка-комментарий. Заголовок embed `Недельный ладдер комнат` (фиксирован). Описание Discord: `Вывести топ-10 недельных румеров`.
  - **Сделано:** `cogs/voices_ladder.py` — hybrid `guild_only`, без `default_permissions`. `standings()[:10]`; `_name` = `<@id>` при `get_member`/`fetch_user` (P1.0d), сырой id при `NotFound`. Пусто → `ctx.send("недельный ладдер комнат пуст")` (текст). Иначе embed `Недельный ладдер комнат` + footer-комментарий, `allowed_mentions=none()`.
  - Проверка: `unit` ✓ (`test_voices_ladder.py` — пусто=текст / список из кэша / сырой id при нерезолве / усечение до 10); `manual` — ждёт токена.

---

## P5 — Полный прогон тестов (gate деплоя)

Ref: `development.md` § "Тестирование" — тесты обязаны проходить до деплоя.

- [x] **P5.1** Все `unit`-пункты выше реализованы отдельными чистыми функциями/классами (без реальных `discord.*` объектов на входе). **Проверено:** вся правило-логика — в `connor/core/*` (hierarchy, targets, timefmt, permissions, msg_guard, dm_guard, mute_state, channels, preflight, resolve, voice_xp, voice_cycle) и в чистых функциях когов (`evaluate_give`, `build_*` embed'ы, `parse_purge_args`/`message_matches`, `find_suspicious`/`extract_gif_links`, `accrue_tick`, `pick_winner`, `is_cycle_expired`/`next_anchor`, `is_counted_channel`). Тесты когов используют `MagicMock(spec=discord.*)` + фейки, не реальные объекты.
- [x] **P5.2** `pytest` зелёный (**360 тестов**); покрыты все перечисленные в `development.md` пункты: парсер времени мьюта (`test_timefmt`), иерархия (`test_hierarchy`), выбор сценария `!give` B/C/D (`test_role_giver`), XP-тик (`test_voice_xp`), недельный цикл Voices (`test_voice_cycle` + `test_voices_xp_cog`), лимит 100 бан-листа (`test_voices_selfmod`), лимит 300 + 14 дней purge (`test_purge`), разбор Command Permissions API (`test_permissions`).
- [x] **P5.3** `ruff check` + `ruff format --check` — чисто.
- [x] **P5.4** `pytest` не тянет сеть/боевые креды и запускается одной командой из чистого клона: `conftest.py` даёт временный файл SQLite (`tmp_path`), Discord везде замокан, токен не нужен. Порядок запуска на VPS до первого старта + правило «красный → не стартуем» — `DEPLOY.md` § 3.

---

## P6 — Разное и деплой

- [x] **P6.1 `!kiss`.** Только `!`, без канальных ограничений, глобальный кулдаун 5 мин на весь сервер, ответ `Дядь, ты дурак?`. Ref: `Home.md`. **Сделано:** `cogs/misc.py::Misc` — `@commands.command` (prefix-only, не в дереве → глоб. гейт не трогает); ручной кулдаун (`monotonic()` последнего **ответа**, окно не продлевается спамом); `kiss` не в `DM_ALLOWED_COMMANDS` → в ЛС молча игнор.
  - Проверка: `unit` ✓ (`test_misc.py` — первый ответ / молчит в окне / снова после окна / спам не продлевает окно); smoke ✓ (13 когов грузятся); `manual` — ждёт токена.
- [ ] **P6.2 `/healthcheck`** — финальная сверка формата отчёта с `development.md` (уже реализован в P1.7, здесь только проверка на живом сервере).
  - Проверка: `manual` (ждёт токена).
- [x] **P6.3 systemd `deploy/connor.service`.** `Restart=on-failure`, ненулевой `RestartSec`, `StartLimitBurst`/`StartLimitIntervalSec` против busy-loop. Ref: `environment.md` § "Развёртывание". **Сделано:** `deploy/connor.service` — `Restart=on-failure` / `RestartSec=10`; `StartLimitIntervalSec=300` + `StartLimitBurst=5` в `[Unit]`; `RestartPreventExitStatus=2` (битый конфиг = exit 2 → не рестартить, сидеть в `failed`); `EnvironmentFile=.env`, `ExecStart=.venv/bin/python -m connor`; опциональное усиление (`NoNewPrivileges`, `ProtectSystem` и т.п.).
  - Проверка: `review` ✓; `manual` (падение при битом `.env` не уходит в цикл) — ждёт VPS.
- [x] **P6.4 `.env.example` + `DEPLOY.md`.** `.env.example` — 19 ключей с пояснениями + указатель на README (Discord-настройка). `DEPLOY.md` (новый): Discord-настройка (intents, позиция роли бота, Command Permissions по каждой команде с ориентирами по каналам, курируемые права), установка на VPS (user/venv/`.env`, локальный диск под БД), **§ 3 — обязательный прогон `pytest`/`ruff` до первого `systemctl start` + «красный → не стартуем»**, systemd (коды выхода 1/2), проверка после старта (`[startup]`, `/healthcheck`), обновление кода (снова `pytest`), горячий бэкап SQLite, таблица траблшутинга. `deploy/README.md` — короткий указатель на юнит + `DEPLOY.md`.
  - Проверка: `review` ✓.

> **antiBot / `/anti-bot` — ПРОПУСКАЕМ, не разрабатываем.** В этот план модуль не входит: ни кога `antibot.py`, ни конфига, ни команды, ни тестов. Причина — помечен как вне скоупа в `Home.md` и `antiBot.md`. Если понадобится позже — заводится отдельной фазой по спеке `antiBot.md` (`guild.edit(invites_disabled_until=…)`, уведомления в `#бот-команды`, автоспад 24ч, право `Manage Server` — оно уже есть в курируемом списке и в таблице preflight как резерв).

---

## Сводный трекер прогресса

| Фаза | Пунктов | Готово |
|---|---|---|
| P0 Фундамент | 6 | 6 ✅ |
| P1 Ядро (P1.0 сквозное + P1.1–1.7) | 7+7 | 14 ✅ (P1.0a–g, P1.1–1.7) |
| P2 Независимые (A/B/C/D) | 5+4+3+6 | 18 ✅ (P1.0c сделан) |
| P3 Кластер «работяга» | 3+2+3+6 | 14 ✅ (anti, check, roleGiver) |
| P4 Voices | 3+2+4+2+4+1 | 16 ✅ (rooms, lifecycle, selfmod, xp-тик, weekly, ladder — unit ✓, manual ждёт токена) |
| P5 Тесты | 4 | 4 ✅ (360 тестов зелёные, ruff чисто, гермётично) |
| P6 Разное/деплой | 4 | 3 ✅ (P6.1 !kiss, P6.3 systemd, P6.4 DEPLOY.md); P6.2 — сверка на живом сервере |

Обновлять после каждой закрытой задачи.
