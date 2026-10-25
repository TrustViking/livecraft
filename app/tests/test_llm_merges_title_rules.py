"""Правила названия эфира и первой фразы описания (CLAUDE.md §14 решение 82)."""
from __future__ import annotations

import pytest

from app.llm.merges.description import MergedDescription
from app.llm.merges.title_rules import TitleFinding, TitleFindings, TitleRules, TitleViolation, TitleWord

RULES: TitleRules = TitleRules.load()
WRONG_QUOTE: str = "«Бог — це пліснява»: як ярлик перетворюється на інституційний тиск"
WRONG_NUMBERS: str = "9 роликов с 25 августа по 9 сентября: кто защищает Якуба Яхла?"
RIGHT_TITLES: tuple[str, ...] = (
    "Соціальна маска Олександра Дворкіна: аналіз антикультової мережі",
    "Расследование о защитниках Якуба Яхла и кампании против АЛЛАТРА",
    "Свідчення з Танзанії і позиція чеських медіа у справі Якуба Яхла",
)


@pytest.mark.parametrize(
    ("title", "violation"),
    [
        ("Тема 2026 року", TitleViolation.DIGIT),
        ("Частина друга", TitleViolation.NUMBER_WORD),
        ("Part II", TitleViolation.ROMAN_NUMERAL),
        ("Nine videos", TitleViolation.NUMBER_WORD),
        ("Why is it still free?", TitleViolation.QUESTION_OR_EXCLAMATION),
        ("Stop now!", TitleViolation.QUESTION_OR_EXCLAMATION),
        ("«Цитата»: тема", TitleViolation.QUOTE),
        ("Тема | Бренд", TitleViolation.SEPARATOR),
        ("ВСЁ ЗАГЛАВНЫМИ", TitleViolation.ALL_CAPS),
        ("Бог", TitleViolation.FORBIDDEN_WORD),
        ("Богу", TitleViolation.FORBIDDEN_WORD),
        ("война", TitleViolation.FORBIDDEN_WORD),
    ],
)
def test_every_violation_is_caught(title: str, violation: TitleViolation) -> None:
    assert violation in RULES.title_violations(title).violations


def test_the_wrong_titles_of_the_prompt_break_the_rules() -> None:
    quote: TitleFindings = RULES.title_violations(WRONG_QUOTE)
    assert quote.violations == (TitleViolation.FORBIDDEN_WORD, TitleViolation.QUOTE)
    assert quote.label == "forbidden_word(Бог),quote(«,»)"
    numbers: TitleFindings = RULES.title_violations(WRONG_NUMBERS)
    assert numbers.violations == (TitleViolation.DIGIT, TitleViolation.QUESTION_OR_EXCLAMATION)
    assert numbers.label == "digit(9,25),question_or_exclamation(?)"


@pytest.mark.parametrize(
    "title", ["богослов", "богатство", "зв'язки", "Washington DC", "ОБСЄ і АЛЛАТРА", "Екран LCD", *RIGHT_TITLES]
)
def test_neutral_titles_pass(title: str) -> None:
    assert not RULES.title_violations(title).is_found


def test_words_are_compared_whole_without_case_yo_and_apostrophe_kind() -> None:
    assert TitleWord("Пʼять").key == TitleWord("п’ять").key == "п'ять"
    assert TitleWord("Трёх").key == "трех"
    assert RULES.title_violations("Пʼять кроків").violations == (TitleViolation.NUMBER_WORD,)
    assert RULES.title_violations("Трёх свидетелей").violations == (TitleViolation.NUMBER_WORD,)


def test_one_letter_words_do_not_make_a_title_all_caps() -> None:
    assert not RULES.title_violations("A B").is_found
    assert RULES.title_violations("FBI").violations == (TitleViolation.ALL_CAPS,)


def test_a_finding_without_words_is_its_code() -> None:
    assert TitleFinding(TitleViolation.ALL_CAPS).label == "all_caps"
    assert TitleFindings().label == "" and not TitleFindings().is_found


def test_blasphemy_in_the_first_sentence_breaks_the_opening() -> None:
    opening: TitleFindings = RULES.opening_violations(MergedDescription("Бог у цій історії ні до чого. Далі факти.\n\nДва."))
    assert opening.violations == (TitleViolation.FORBIDDEN_WORD,)
    assert opening.label == "forbidden_word(Бог)"


def test_negative_words_in_the_first_sentence_are_allowed() -> None:
    assert not RULES.opening_violations(MergedDescription("Насильство в школі розслідують журналісти.\n\nДва.")).is_found


def test_blasphemy_after_the_first_sentence_is_allowed() -> None:
    description: MergedDescription = MergedDescription("Журналісти розслідують справу. Бог тут ні до чого.\n\nДва.")
    assert not RULES.opening_violations(description).is_found
