"""automod_mirror: матч по семантике Discord AutoMod + правило дельты (обход).

Нейтральные слова-заглушки ("спам", "казино", "анал"/"анализ") вместо банвордов.
"""

from __future__ import annotations

from connor.core import deobfuscate
from connor.core.automod_mirror import AutoModKeywords


def _kw(words=(), allow=(), regex=(), ignore=()) -> AutoModKeywords:
    return AutoModKeywords.build(
        list(words), list(allow), list(regex), collapse_min=3, ignore=list(ignore)
    )


def _bypass(mk: AutoModKeywords, text: str):
    base, norm = deobfuscate.variants(text, collapse_min=3)
    return mk.find_bypass(raw=base, norm=norm)


# --- дельта: сырой матч не считается обходом -------------------------------------


def test_plain_word_visible_in_raw_is_not_bypass() -> None:
    assert _bypass(_kw(["спам"]), "это просто спам тут") is None


def test_clean_message_is_not_bypass() -> None:
    assert _bypass(_kw(["спам"]), "совершенно обычный текст") is None


def test_empty_ruleset_never_matches() -> None:
    assert _bypass(AutoModKeywords.empty(), "сп@м") is None
    assert _bypass(_kw([]), "с п а м") is None


# --- подмена символов ----------------------------------------------------------


def test_leet_substitution_flagged() -> None:
    hit = _bypass(_kw(["спам"]), "налетай сп@м дёшево")
    assert hit is not None
    assert hit.keyword == "спам"
    assert hit.form == "подмена символов"


def test_homoglyph_substitution_flagged() -> None:
    hit = _bypass(_kw(["спам"]), "тут спaм")  # латинская a
    assert hit is not None and hit.form == "подмена символов"


def test_translit_s_substitution_flagged() -> None:
    hit = _bypass(_kw(["спам"]), "налетай Sпам")  # транслит S -> с
    assert hit is not None and hit.form == "подмена символов"


def test_mixed_translit_letter_flagged() -> None:
    hit = _bypass(_kw(["казино"]), "тут каzино открыто")  # латинская z
    assert hit is not None and hit.form == "подмена символов"


# --- разделители между буквами -----------------------------------------------


def test_every_letter_spaced_flagged() -> None:
    hit = _bypass(_kw(["спам"]), "смотри с п а м здесь")
    assert hit is not None
    assert hit.keyword == "спам"
    assert hit.form == "разделители между буквами"


def test_single_space_split_flagged() -> None:
    # один пробел, куски по 2+ буквы — раньше не ловилось
    for text in ("сп ам", "с пам", "спа м"):
        hit = _bypass(_kw(["спам"]), f"тут {text} вот")
        assert hit is not None, text
        assert hit.keyword == "спам"
        assert hit.form == "разделители между буквами"


def test_dotted_letters_flagged() -> None:
    hit = _bypass(_kw(["спам"]), "с.п.а.м")
    assert hit is not None and hit.form == "разделители между буквами"


# --- защита от ложных срабатываний --------------------------------------------


def test_longer_word_containing_keyword_not_flagged() -> None:
    # "спам" — не целое слово в "спамер"/"спамил"; допуск разделителей это не меняет
    assert _bypass(_kw(["спам"]), "спамер уже спамил в чате") is None


def test_gap_does_not_cross_letters() -> None:
    # между буквами банворда допускаются только разделители, не другие буквы
    assert _bypass(_kw(["спам"]), "спХам спаХм") is None


def test_short_keyword_has_no_gap_tolerance() -> None:
    # слово короче 3 букв — только точный матч, иначе "х й" ловит слишком часто
    assert _bypass(_kw(["хй"]), "буквы х й тут") is None
    assert _bypass(_kw(["хй"]), "буквы xй тут") is not None  # латинская x, подмена ловится


# --- латинские ключевые слова (обе стороны фолдятся одинаково) -----------------


def test_latin_keyword_in_plain_text_is_not_bypass() -> None:
    assert _bypass(_kw(["onlyfans"]), "смотри onlyfans тут") is None


def test_latin_keyword_with_cyrillic_homoglyphs_flagged() -> None:
    hit = _bypass(_kw(["onlyfans"]), "смотри оnlуfаns тут")  # кириллические о, у, а
    assert hit is not None
    assert hit.form == "подмена символов"


# --- wildcard ----------------------------------------------------------------


def test_wildcard_prefix_visible_in_raw_not_bypass() -> None:
    assert _bypass(_kw(["спам*"]), "эти спамеры надоели") is None


def test_wildcard_prefix_obfuscated_flagged() -> None:
    hit = _bypass(_kw(["спам*"]), "эти сп@меры надоели")
    assert hit is not None and hit.keyword == "спам*"


# --- allow-list -------------------------------------------------------------


def test_allow_list_exempts_obfuscated_substring() -> None:
    mk = _kw(["*анал*"], allow=["анализ"])
    assert _bypass(mk, "мой @нализ по рынку") is None


def test_allow_list_does_not_exempt_bare_keyword() -> None:
    mk = _kw(["*анал*"], allow=["анализ"])
    hit = _bypass(mk, "@нал")
    assert hit is not None and hit.keyword == "*анал*"


def test_allow_list_exempts_regex_match_too() -> None:
    mk = _kw(regex=[r"ан[а@]л"], allow=["анализ"])
    assert _bypass(mk, "мой @нализ по рынку") is None


# --- regex ----------------------------------------------------------------


def test_regex_pattern_matches_after_normalization() -> None:
    mk = _kw(regex=[r"сп[а@]м"])
    assert _bypass(mk, "спам") is None  # виден в сыром
    hit = _bypass(mk, "сп​ам")  # zero-width ломает сырой матч
    assert hit is not None


def test_invalid_regex_is_skipped_not_raised() -> None:
    mk = _kw(regex=[r"(unclosed", r"валид"])
    assert mk.regex_count == 1


# --- игнор-список оператора ----------------------------------------------------


def test_ignored_keyword_is_dropped() -> None:
    mk = _kw(["спам", "🇷🇺"], ignore=["🇷🇺"])
    assert mk.keyword_count == 1  # осталось только "спам"
    assert _bypass(mk, "флаг 🇷🇺 в тексте") is None
    assert _bypass(mk, "сп@м") is not None  # другой ключ по-прежнему ловится


def test_ignore_matches_by_normalized_form() -> None:
    # оператор записал игнор латиницей, ключ правила кириллицей — всё равно совпадёт
    mk = _kw(["спам"], ignore=["cпaм"])
    assert mk.keyword_count == 0


def test_ignored_regex_is_dropped() -> None:
    mk = _kw(regex=[r"лох[аи]"], ignore=[r"лох[аи]"])
    assert mk.regex_count == 0


_RU_FLAG = "\U0001f1f7\U0001f1fa"
_UA_FLAG = "\U0001f1fa\U0001f1e6"


def test_ignore_country_code_expands_to_flag_emoji() -> None:
    # в правиле AutoMod флаг лежит эмодзи, а в конфиге оператор пишет "ru"/"ua"
    mk = _kw([_RU_FLAG, _UA_FLAG, "спам"], ignore=["ru", "ua"])
    assert mk.keyword_count == 1  # оба флага выкинуты, осталось "спам"
    assert _bypass(mk, f"слава {_RU_FLAG} вперёд") is None
    assert _bypass(mk, "сп@м") is not None


def test_ignore_accepts_flag_emoji_directly() -> None:
    mk = _kw([_RU_FLAG, "спам"], ignore=[_RU_FLAG])
    assert mk.keyword_count == 1


# --- метаданные ----------------------------------------------------------------


def test_keyword_and_regex_counts() -> None:
    mk = _kw(["спам", "казино*", "лох"], regex=[r"\d{4}"])
    assert mk.keyword_count == 3
    assert mk.regex_count == 1
