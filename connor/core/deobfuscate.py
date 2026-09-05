"""Снятие обфускации текста перед матчем банвордов.

Две формы одной строки (``variants``):

- ``baseline`` — NFKC + casefold, без фолдинга двойников. Эталон «как видит
  Discord»: если банворд читается уже здесь — это не обход (правило AutoMod его
  либо не блокирует по своим настройкам, либо канал/роль в исключениях).
- ``normalize`` — плюс снятие двойников (кириллица и латиница/греческий),
  zero-width и диакритики, лит-цифр, схлопывание повторов буквы. Пробелы
  сохранены: разделители между буквами (``го йда``, ``с.п.а.м``) отрабатывает сам
  матчер в ``automod_mirror`` — банворд ищется с допуском разделителей.

Чистый модуль без зависимости от discord — семантика матча живёт в
``automod_mirror``.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Латиница/греческий/цифры → русская кириллица. Берём пары без конфликта: либо
# уверенный визуальный двойник, либо однозначная транслит-замена. НЕ берём буквы,
# где визуальный и фонетический смысл расходятся (c=с/ц, h=н/х, n=и/н, r=р/г,
# u=у/и) или начертание слабое — они дают ложные совпадения. Полного транслита
# (pidaras→пидарас) здесь нет, для него нужна отдельная таблица. Расширять по
# реальным попыткам из #чек-лист.
_CONFUSABLES: dict[str, str] = {
    # латиница: визуальные двойники + однозначный транслит (d/f/g/l/v/z, s как $)
    "a": "а", "b": "в", "c": "с", "d": "д", "e": "е", "f": "ф", "g": "г",
    "h": "н", "i": "и", "k": "к", "l": "л", "m": "м", "o": "о", "p": "р",
    "s": "с", "t": "т", "v": "в", "x": "х", "y": "у", "z": "з",
    # греческий
    "α": "а", "β": "в", "ε": "е", "ι": "и", "κ": "к",
    "μ": "м", "ν": "н", "ο": "о", "π": "п", "ρ": "р",
    "τ": "т", "υ": "у", "χ": "х",
    # украинская / белорусская кириллица в русскую
    "і": "и", "ї": "и", "ґ": "г", "ў": "у",
    # лит-цифры и символы (частые русские замены)
    "0": "о", "3": "з", "4": "ч", "6": "б", "@": "а", "$": "с",
}
_TRANSLATE = {ord(k): v for k, v in _CONFUSABLES.items()}

# пробельные символы, которые оставляем как границы слова (остальные Cc/Cf режем)
_KEEP_WS = frozenset("\t\n\r\f\v ")

# Кириллические буквы, которые NFKD раскладывает на «база + комбинирующий знак».
# Восстанавливаем их до снятия диакритики, иначе й/и, ё/е, ї/и, ў/у слипаются.
# Ключи строим из NFKD-формы, чтобы не держать комбинирующие знаки в исходнике.
_KEEP_COMPOSED: dict[str, str] = {
    unicodedata.normalize("NFKD", ch): ch for ch in ("й", "ё", "ї", "ў")
}


@lru_cache(maxsize=8)
def _collapse_re(min_run: int) -> re.Pattern[str]:
    n = max(min_run, 2) - 1
    return re.compile(rf"(.)\1{{{n},}}", re.DOTALL)


def _fold_marks(text: str) -> str:
    """NFKD, восстановить й/ё/ї/ў, снять диакритику и невидимые Cf/Cc."""
    d = unicodedata.normalize("NFKD", text)
    for pair, letter in _KEEP_COMPOSED.items():
        if pair in d:
            d = d.replace(pair, letter)
    out: list[str] = []
    for ch in d:
        if ch in _KEEP_WS:
            out.append(ch)
        elif unicodedata.combining(ch):
            continue
        elif unicodedata.category(ch) in ("Cf", "Cc"):
            continue
        else:
            out.append(ch)
    return "".join(out)


def _finish_normalize(base: str, collapse_min: int) -> str:
    s = _fold_marks(base).translate(_TRANSLATE)
    return _collapse_re(collapse_min).sub(r"\1", s)


def baseline(text: str) -> str:
    """NFKC + casefold. Эталон «до обфускации» для сравнения в ``find_bypass``."""
    return unicodedata.normalize("NFKC", text).casefold()


def normalize(text: str, *, collapse_min: int = 3) -> str:
    """``baseline`` + снятие двойников, zero-width, диакритики, лит, повторов.

    Пробелы и переносы сохраняются: разделители между буквами разбирает матчер
    банвордов (см. ``automod_mirror``), а не эта функция.
    """
    return _finish_normalize(baseline(text), collapse_min)


def variants(text: str, *, collapse_min: int = 3) -> tuple[str, str]:
    """``(baseline, normalize)`` одной строки — единый вход."""
    base = baseline(text)
    return base, _finish_normalize(base, collapse_min)
