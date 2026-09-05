"""deobfuscate: снятие обфускации символов (двойники, zero-width, лит, повторы).

Разделители между буквами разбирает матчер в automod_mirror, не этот модуль.
Нейтральные слова-заглушки ("казино", "спам") вместо реальных банвордов.
"""

from __future__ import annotations

from connor.core.deobfuscate import baseline, normalize, variants

# --- normalize: подмена символов --------------------------------------------------


def test_normalize_folds_latin_lookalikes() -> None:
    assert normalize("kазинo") == "казино"  # латинские k, o
    assert normalize("cпaм") == "спам"  # латинские c, a
    assert normalize("КАЗИНО") == "казино"  # регистр


def test_normalize_folds_leet_digits_and_symbols() -> None:
    assert normalize("ка3ино") == "казино"  # 3 -> з
    assert normalize("казин0") == "казино"  # 0 -> о
    assert normalize("к@зино") == "казино"  # @ -> а
    assert normalize("$пам") == "спам"  # $ -> с
    assert normalize("sпам") == "спам"  # транслит s -> с
    assert normalize("педаpаS") == "педарас"  # p -> р, S -> с


def test_normalize_folds_unambiguous_translit_letters() -> None:
    # d/f/g/l/v/z — однозначная транслит-замена латиница→кириллица, без конфликта
    assert normalize("гниdа") == "гнида"
    assert normalize("zараза") == "зараза"
    assert normalize("gном") == "гном"
    assert normalize("lама") == "лама"
    assert normalize("vаза") == "ваза"
    assert normalize("fары") == "фары"


def test_normalize_does_not_do_full_translit() -> None:
    # p визуально → р, r/u/n не сворачиваются: pidaras НЕ становится «пидарас»
    assert normalize("pidaras") == "ридаrас"


def test_normalize_strips_zero_width_and_diacritics() -> None:
    assert normalize("каз​ино") == "казино"  # ZERO WIDTH SPACE
    assert normalize("каз‍﻿ино") == "казино"  # ZWJ + BOM
    assert normalize("каз‮ино") == "казино"  # RTL override
    assert normalize("ка́зино") == "казино"  # комбинирующий U+0301
    assert normalize("спáм") == "спам"  # precomposed á как двойник a


def test_normalize_keeps_composed_cyrillic_letters() -> None:
    # NFKD раскладывает й/ё/ї/ў — не должны схлопнуться в и/е/и/у
    assert normalize("займ") == "займ"
    assert normalize("ёжик") == "ёжик"
    assert normalize("бельё") == "бельё"


def test_normalize_collapses_repeats() -> None:
    assert normalize("казиииино") == "казино"
    assert normalize("казиино") == "казиино"  # серия из 2 < collapse_min
    assert normalize("казиино", collapse_min=2) == "казино"


def test_normalize_keeps_spaces_and_is_idempotent() -> None:
    assert normalize("к а з и н о") == "к а з и н о"  # разделители трогает матчер, не norm
    once = normalize("Kаз​ИИИно")
    assert normalize(once) == once


# --- variants: единый вход ------------------------------------------------------


def test_baseline_does_not_fold_lookalikes() -> None:
    assert baseline("Kазино") == "kазино"  # латинская K сохранена, регистр снят


def test_variants_pair_is_consistent() -> None:
    base, norm = variants("K А З И Н О")
    assert base == "k а з и н о"
    assert norm == "к а з и н о"


def test_variants_empty() -> None:
    assert variants("") == ("", "")
    assert normalize("") == ""
