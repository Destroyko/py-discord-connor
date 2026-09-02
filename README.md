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

На пустом/неполном `.env` бот печатает полный список проблем и выходит с кодом 2.

## Тесты и линт

```
pytest
ruff check .
ruff format --check .
```

`pytest` не требует сети, БД-сервиса и токена — можно прогонять прямо на проде перед стартом.
