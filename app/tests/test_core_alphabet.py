from __future__ import annotations

import re

import pytest

from app.core.alphabet import (
    CYRILLIC_LETTER_PATTERN,
    LANGUAGE_HOMOGLYPHS,
    LATIN_LETTER_PATTERN,
    LETTERS,
    LOWER_LETTERS,
    RUSSIAN_LETTER_PATTERN,
    SAFE_HOMOGLYPHS,
    UKRAINIAN_LETTER_PATTERN,
    UPPER_LETTERS,
    YO_FOLD,
    CoreLanguage,
)


@pytest.mark.parametrize("letter", ["а", "Я", "ё", "Ё", "і", "Ї", "є", "Ґ"])
def test_cyrillic_class_holds_russian_and_ukrainian_letters(letter: str) -> None:
    assert CYRILLIC_LETTER_PATTERN.fullmatch(letter)
    assert not LATIN_LETTER_PATTERN.fullmatch(letter)
    assert re.fullmatch(f"[{LETTERS}]", letter)


@pytest.mark.parametrize("char", ["1", "_", "-", " ", "ʼ", "é"])
def test_digits_signs_and_other_scripts_are_not_letters_of_the_classes(char: str) -> None:
    assert not re.fullmatch(f"[{LETTERS}]", char)


def test_upper_and_lower_classes_split_by_case() -> None:
    assert re.fullmatch(f"[{UPPER_LETTERS}]+", "ABCЁІЇЄҐЯ")
    assert re.fullmatch(f"[{LOWER_LETTERS}]+", "abcёіїєґя")
    assert not re.fullmatch(f"[{UPPER_LETTERS}]", "ґ")
    assert not re.fullmatch(f"[{LOWER_LETTERS}]", "Ґ")


def test_letters_of_one_language_only() -> None:
    assert UKRAINIAN_LETTER_PATTERN.search("привіт") and not UKRAINIAN_LETTER_PATTERN.search("привет")
    assert RUSSIAN_LETTER_PATTERN.search("объём") and not RUSSIAN_LETTER_PATTERN.search("обсяг")


def test_yo_folds_to_ye_in_both_cases() -> None:
    assert "Ёлка ёж".translate(YO_FOLD) == "Елка еж"
    assert "їжак".translate(YO_FOLD) == "їжак"


def test_core_languages() -> None:
    assert [member.value for member in CoreLanguage] == ["uk", "en", "ru"]
    assert CoreLanguage.covers("uk") and CoreLanguage.covers("en") and CoreLanguage.covers("ru")
    assert not CoreLanguage.covers("pl") and not CoreLanguage.covers("")


def test_homoglyphs_are_latin_letters_with_a_cyrillic_twin() -> None:
    assert all(LATIN_LETTER_PATTERN.fullmatch(latin) for latin in SAFE_HOMOGLYPHS)
    assert all(CYRILLIC_LETTER_PATTERN.fullmatch(cyrillic) for cyrillic in SAFE_HOMOGLYPHS.values())
    assert LANGUAGE_HOMOGLYPHS["uk"]["i"] == "і" and LANGUAGE_HOMOGLYPHS["ru"]["i"] == "и"
    assert set(LANGUAGE_HOMOGLYPHS) == {"uk", "ru"}
