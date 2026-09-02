# py-discord-connor

Discord-бот модерации для одного сервера. Спека — в GitHub Wiki (`py-discord-connor.wiki`).
План реализации и чек-лист — [IMPLEMENTATION_PLAN.md](IMPLEMENTATION_PLAN.md).

## Требования

- Python 3.13+

## Установка (dev)

```
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -e ".[dev]"
copy .env.example .env            # затем заполнить
```

## Запуск

```
python main.py          # или: python -m connor
```

На пустом/неполном `.env` или битом `config/*.toml` бот печатает **полный список**
проблем и выходит с кодом 2.

## Тесты и линт

```
pytest
ruff check .
ruff format --check .
```

`pytest` не требует сети, БД-сервиса и токена — можно прогонять прямо на проде перед стартом.

## Конфигурация

- **`.env`** — то, без чего бот не работает: ID сервера/каналов/категорий/ролей, токен,
  путь к БД. Шаблон — [.env.example](.env.example).
- **`config/*.toml`** — тюнинговые константы каждого модуля (очки за тик, пороги
  анти-твинка, лимиты и т.п.). Файлы обязаны существовать; меняются вручную + рестарт.

## Настройка на стороне Discord (вручную, не через `.env`)

Часть настроек живёт в самом Discord и при разворачивании делается через штатный
интерфейс — см. `py-discord-connor.wiki/rules.md` § "Роли и права",
`environment.md` § "Права бота на сервере".

1. **Privileged intents** — Developer Portal → приложение → Bot → Privileged Gateway
   Intents: включить **Server Members Intent** и **Message Content Intent**. Без них
   gateway не пустит бота (бот залогирует это отдельной строкой).
2. **Позиция роли бота** — роль бота на сервере должна стоять **выше** всех ролей,
   которыми он управляет («работяга», «Молчун», «Душа компании»), и достаточно высоко,
   чтобы модерировать нужных участников. Иерархия наказаний берётся из порядка ролей
   Discord, отдельного конфига у бота нет.
3. **Права роли бота** — курируемый набор без `Administrator` (полный список —
   `environment.md`). Ключевые: Manage Roles, Manage Channels, Kick/Ban Members,
   Moderate Members (timeout), Move Members, Manage Messages, View Audit Log,
   Manage Server, Send Messages/Embed Links, Add Reactions, Mention Everyone.
4. **Command Permissions** — Настройки сервера → Интеграции → Connor → у каждой
   команды «Изменить права на использование команд»: задать разрешённые роли и каналы.
   Это отдельный слой прав **только для slash-команд**; бот реплицирует те же
   ограничения на префиксный (`!`) путь, читая их через API. Ориентиры по каналам:
   `/mute`,`/unmute`,`/kick` → `#бот-команды`; `/ban`,`/unban` → `#баны`;
   `/add`,`/del` → `#антиработяги`; `/give` → `#выдача-работяг`;
   `/check`,`/vkick`,`/vreturn`,`/ladder` → `#флудиславль`.
5. **Кастом-эмодзи `:pudge:`** — нужен для ответа `!purge`; должен существовать на
   сервере, у бота — право Use External Emojis. Если эмодзи нет — ответ отрендерится
   как текст `:pudge:` (не критично).

Полный чек-лист деплоя (systemd, прогон тестов на машине, обновление, бэкап БД,
траблшутинг) — [DEPLOY.md](DEPLOY.md).
