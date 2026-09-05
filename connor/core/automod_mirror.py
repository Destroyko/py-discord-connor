"""Зеркало ключевых слов Discord AutoMod + детект их обхода.

Список банвордов бот читает из правил AutoMod типа «keyword» (только включённых)
по API — здесь не дублируется. ``AutoModKeywords`` матчит текст по семантике
Discord (целое слово / wildcard ``*`` / regex, минус allow-list) и применяет
правило: **обфусцированный текст матчит, а сырой — нет** ⇒ это обход.

Ключевые слова держатся в двух формах:

- ``strict`` (NFKC + casefold) сравнивается с ``baseline`` сообщения — эталон
  «как у Discord». Совпадение здесь означает, что слово видно и так;
- ``loose`` (полная нормализация) сравнивается с ``normalize`` сообщения. Обе
  стороны фолдятся одинаково, поэтому латинские ключевые слова не ломаются о
  кириллические двойники и наоборот. В ``loose`` между каждой парой букв слова
  допускается до ``_GAP`` символов-разделителей — так ловятся ``го йда``,
  ``гой да``, ``г.о.й.д.а`` (граница слова сохраняется: ``гойда`` внутри
  длинного слова не матчится). Допуск не применяется к словам короче
  ``_MIN_GAP_LEN`` — на них он даёт слишком много ложных совпадений.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from connor.core import deobfuscate

log = logging.getLogger(__name__)

_FORM_CHARS = "подмена символов"
_FORM_SPACING = "разделители между буквами"

#: допустимо символов-разделителей между двумя буквами банворда в ``loose``
_GAP = r"[\W_]{0,2}"
#: слова короче — только точный матч (допуск разделителей для них слишком шумный)
_MIN_GAP_LEN = 3
_SEP_RE = re.compile(r"[\W_]")


@dataclass(frozen=True, slots=True)
class BypassHit:
    """Совпадение по обходу: какое слово правила и за счёт какой обфускации."""

    keyword: str
    form: str


def _spaced(word: str, gap: str) -> str:
    """Экранированное слово с допуском ``gap`` между каждой парой букв."""
    return gap.join(re.escape(ch) for ch in word)


def _wild_pattern(kw: str, gap: str) -> re.Pattern[str]:
    """``кв*`` → префикс слова, ``*кв`` → суффикс, ``*кв*`` → подстрока, ``к*в`` → к…в."""
    g = gap if len(kw.replace("*", "")) >= _MIN_GAP_LEN else ""
    segs = [_spaced(s, g) for s in kw.split("*") if s]
    core = r"\w*".join(segs) if segs else r"\w+"
    left = "" if kw.startswith("*") else r"(?<!\w)"
    right = "" if kw.endswith("*") else r"(?!\w)"
    return re.compile(left + core + right)


def _split_keywords(
    words: Iterable[str], prep: Callable[[str], str]
) -> tuple[frozenset[str], tuple[str, ...]]:
    plain: set[str] = set()
    wild: list[str] = []
    for raw in words:
        kw = "*".join(prep(part) for part in raw.strip().split("*"))
        if not kw.strip("*"):
            continue
        if "*" in kw:
            wild.append(kw)
        else:
            plain.add(kw)
    return frozenset(plain), tuple(dict.fromkeys(wild))


def _country_flag(code: str) -> str:
    """ISO-код страны из 2 латинских букв → эмодзи-флаг (пара regional indicator)."""
    return "".join(chr(0x1F1E6 + ord(c) - ord("a")) for c in code)


def _ignore_keys(ignore: Iterable[str], *, collapse_min: int) -> set[str]:
    """Нормализованные формы игнор-записей. Запись из 2 латинских букв трактуется
    ещё и как ISO-код страны — добавляется её эмодзи-флаг (в правилах AutoMod
    флаг лежит именно эмодзи, не буквами)."""
    keys: set[str] = set()
    for raw in ignore:
        token = raw.strip()
        if not token:
            continue
        key = deobfuscate.normalize(token.replace("*", ""), collapse_min=collapse_min)
        if key:
            keys.add(key)
        low = token.casefold()
        if len(low) == 2 and low.isascii() and low.isalpha():
            keys.add(_country_flag(low))
    return keys


def _compile_regexes(patterns: Iterable[str]) -> tuple[re.Pattern[str], ...]:
    out: list[re.Pattern[str]] = []
    for pat in patterns:
        try:
            out.append(re.compile(pat, re.IGNORECASE))
        except re.error as exc:
            log.warning("AutoMod regex пропущен (несовместим с Python re): %r — %s", pat, exc)
    return tuple(out)


class _Matcher:
    """Матч по семантике Discord: целое слово, wildcard, regex.

    ``gap`` (непустой только у ``loose``) — regex-вставка, допускаемая между
    каждой парой букв слова: разделители внутри банворда.
    """

    __slots__ = ("_plain_re", "_regexes", "_wild")

    def __init__(
        self,
        plain: frozenset[str],
        wild: tuple[str, ...],
        regexes: tuple[re.Pattern[str], ...],
        *,
        gap: str = "",
    ) -> None:
        self._plain_re: re.Pattern[str] | None = None
        if plain:
            alts = "|".join(
                _spaced(k, gap if len(k) >= _MIN_GAP_LEN else "")
                for k in sorted(plain, key=len, reverse=True)
            )
            self._plain_re = re.compile(rf"(?<!\w)(?:{alts})(?!\w)")
        self._wild: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
            (kw, _wild_pattern(kw, gap)) for kw in wild
        )
        self._regexes = regexes

    def match(self, text: str) -> tuple[str, str] | None:
        """``(ключевое слово, совпавший фрагмент)`` первого совпадения или ``None``."""
        if not text:
            return None
        if self._plain_re is not None:
            m = self._plain_re.search(text)
            if m is not None:
                got = m.group(0)
                return _SEP_RE.sub("", got), got  # ключ без вставленных разделителей
        for kw, pat in self._wild:
            m = pat.search(text)
            if m is not None:
                return kw, m.group(0)
        for rx in self._regexes:
            m = rx.search(text)
            if m is not None:
                return m.group(0), m.group(0)
        return None


class AutoModKeywords:
    __slots__ = ("_allow", "_loose", "_strict", "keyword_count", "regex_count")

    def __init__(
        self,
        *,
        strict: _Matcher,
        loose: _Matcher,
        allow: tuple[str, ...],
        keyword_count: int,
        regex_count: int,
    ) -> None:
        self._strict = strict
        self._loose = loose
        self._allow = allow
        self.keyword_count = keyword_count
        self.regex_count = regex_count

    @classmethod
    def empty(cls) -> AutoModKeywords:
        blank = _Matcher(frozenset(), (), ())
        return cls(strict=blank, loose=blank, allow=(), keyword_count=0, regex_count=0)

    @classmethod
    def build(
        cls,
        keyword_filter: Iterable[str],
        allow_list: Iterable[str],
        regex_patterns: Iterable[str],
        *,
        collapse_min: int,
        ignore: Iterable[str] = (),
    ) -> AutoModKeywords:
        # записи AutoMod, которые оператор пометил как «не нарушение» (эмодзи-флаги
        # и т.п.): убираем из обоих наборов до сборки матчеров
        ignore_norm = _ignore_keys(ignore, collapse_min=collapse_min)
        if ignore_norm:

            def _ignored(entry: str) -> bool:
                key = deobfuscate.normalize(entry.replace("*", ""), collapse_min=collapse_min)
                return key in ignore_norm

            keyword_filter = [w for w in keyword_filter if not _ignored(w)]
            regex_patterns = [p for p in regex_patterns if not _ignored(p)]

        words = list(keyword_filter)
        regexes = _compile_regexes(regex_patterns)

        strict_plain, strict_wild = _split_keywords(words, deobfuscate.baseline)
        loose_plain, loose_wild = _split_keywords(
            words, lambda s: deobfuscate.normalize(s, collapse_min=collapse_min)
        )
        allow = tuple(
            a
            for a in (deobfuscate.normalize(x, collapse_min=collapse_min) for x in allow_list)
            if a
        )
        return cls(
            strict=_Matcher(strict_plain, strict_wild, regexes),
            loose=_Matcher(loose_plain, loose_wild, regexes, gap=_GAP),
            allow=allow,
            keyword_count=len(strict_plain) + len(strict_wild),
            regex_count=len(regexes),
        )

    def _allowed(self, text: str, keyword: str) -> bool:
        core = keyword.replace("*", "")
        return any(a and a in text and core in a for a in self._allow)

    def find_bypass(self, *, raw: str, norm: str) -> BypassHit | None:
        if self._strict.match(raw) is not None:
            return None
        hit = self._loose.match(norm)
        if hit is None:
            return None
        keyword, got = hit
        if self._allowed(norm, keyword):
            return None
        form = _FORM_SPACING if _SEP_RE.search(got) else _FORM_CHARS
        return BypassHit(keyword=keyword, form=form)
