"""Снятие обфускации текста перед матчем банвордов.

Три варианта одной строки (``variants``):

- ``baseline`` — NFKC + casefold, без фолдинга двойников. Эталон «как видит
  Discord»: если банворд читается уже здесь — это не обход (правило AutoMod его
  либо не блокирует по своим настройкам, либо канал/роль в исключениях).
- ``normalize`` — плюс снятие двойников (кириллица и латиница/греческий), zero-width
  и диакритики, лит-цифр, схлопывание повторов буквы. Пробелы сохранены.
- ``deobfuscate_spacing`` поверх ``normalize`` — склейка букв, разнесённых
  разделителями (``с п а м`` в ``спам``, ``х.у.й`` в ``хуй``).

Чистый модуль без зависимости от discord — семантика матча живёт в
``automod_mirror``.
"""

from __future__ import annotations

import re
import unicodedata
from functools import lru_cache

# Визуальные двойники в русскую кириллицу. Только уверенные начертания (после
# casefold): слабые пары (п/n, г/r, и/u) не берём — они дают ложные совпадения.
# Расширять по реальным попыткам из #чек-лист.
_CONFUSABLES: dict[str, str] = {
    # латиница
    "a": "а", "b": "в", "c": "с", "e": "е", "h": "н", "i": "и", "k": "к",
    "m": "м", "o": "о", "p": "р", "t": "т", "x": "х", "y": "у",
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

# Серия из 3+ одиночных букв, разделённых разделителями: «с п а м», «х.у.й»,
# «н_а_х». Границы (?<![^\W_]) / (?![^\W_]) не дают захватить крайнюю букву
# соседнего слова; порог в 3 буквы отсекает «я и ты», «и т. д.». Подчёркивание —
# разделитель, не буква.
_SPACED_RUN = re.compile(r"(?<![^\W_])[^\W_](?:[\W_]+[^\W_]){2,}(?![^\W_])", re.UNICODE)
_SEP = re.compile(r"[\W_]+", re.UNICODE)


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

    Пробелы и переносы сохраняются — склейку разнесённых букв делает
    ``deobfuscate_spacing`` поверх результата.
    """
    return _finish_normalize(baseline(text), collapse_min)


def deobfuscate_spacing(text: str, *, collapse_min: int = 3) -> str:
    """Склеить серии «одиночная буква + разделитель» (от 3 букв).

    ``с п а м`` в ``спам``, ``х.у.й`` в ``хуй``. Обычные слова и короткие связки
    (``я и``, ``и т. д.``) не трогает. Повторы схлопываются повторно (padding
    вида ``с с с п а м``).
    """
    joined = _SPACED_RUN.sub(lambda m: _SEP.sub("", m.group(0)), text)
    return _collapse_re(collapse_min).sub(r"\1", joined)


def variants(text: str, *, collapse_min: int = 3) -> tuple[str, str, str]:
    """``(baseline, normalize, deobfuscate_spacing)`` одной строки — единый вход."""
    base = baseline(text)
    norm = _finish_normalize(base, collapse_min)
    return base, norm, deobfuscate_spacing(norm, collapse_min=collapse_min)
