"""deobfuscate: снятие обфускации символов и склейка разнесённых букв.

Нейтральные слова-заглушки ("казино", "спам") вместо реальных банвордов.
"""

from __future__ import annotations

from connor.core.deobfuscate import (
    baseline,
    deobfuscate_spacing,
    normalize,
    variants,
)

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
    assert normalize("к а з и н о") == "к а з и н о"
    once = normalize("Kаз​ИИИно")
    assert normalize(once) == once


# --- deobfuscate_spacing: склейка разнесённых букв -------------------------------


def test_spacing_joins_single_letter_runs() -> None:
    assert deobfuscate_spacing("к а з и н о") == "казино"
    assert deobfuscate_spacing("к.а.з.и.н.о") == "казино"
    assert deobfuscate_spacing("к-а-з-и-н-о.") == "казино."
    assert deobfuscate_spacing("н_а_х") == "нах"


def test_spacing_leaves_normal_words_alone() -> None:
    assert deobfuscate_spacing("это обычное слово") == "это обычное слово"
    assert deobfuscate_spacing("казино") == "казино"
    assert deobfuscate_spacing("я") == "я"


def test_spacing_ignores_short_letter_runs() -> None:
    # порог 3 буквы: связки из 1-2 одиночных букв не склеиваются
    assert deobfuscate_spacing("я и ты") == "я и ты"
    assert deobfuscate_spacing("а б") == "а б"
    # 3+ одиночных букв склеиваются (известный компромисс по ложным срабатываниям)
    assert deobfuscate_spacing("и т д") == "итд"


def test_spacing_collapses_padding_repeats() -> None:
    assert deobfuscate_spacing("к к к а з и н о") == "казино"


# --- variants: единый вход ------------------------------------------------------


def test_baseline_does_not_fold_lookalikes() -> None:
    assert baseline("Kазино") == "kазино"  # латинская K сохранена, регистр снят


def test_variants_triplet_is_consistent() -> None:
    base, norm, deobf = variants("K А З И Н О")
    assert base == "k а з и н о"
    assert norm == "к а з и н о"
    assert deobf == "казино"


def test_variants_empty() -> None:
    assert variants("") == ("", "", "")
    assert normalize("") == ""
    assert deobfuscate_spacing("") == ""
