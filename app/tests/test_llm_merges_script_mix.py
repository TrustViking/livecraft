"""Смесь алфавитов: подозрительные слова в названии, тезисе и пунктах; починка латинских двойников кириллицы."""
from __future__ import annotations

import pytest

from app.llm.merges.description import MergedDescription
from app.llm.merges.script_mix import HomoglyphMap, HomoglyphRepair, ScriptMixProbe
from app.observability.log_event import LogEvent

PROBE: ScriptMixProbe = ScriptMixProbe.load()
EVENT: LogEvent = LogEvent.of("merge_script_mix_repaired")
MIXED_ZHAIVORONOK: str = "Жайворон" + "o" + "k"       # две последние буквы латинские
CYRILLIC_ZHAIVORONOK: str = "Жайворон" + "о" + "к"


def repaired(text: str, language: str) -> HomoglyphRepair:
    return HomoglyphRepair.of(MergedDescription(text), language)


@pytest.mark.parametrize(
    ("hook", "language", "expected"),
    [
        ("Цей текст містить мiксоване слово.", "uk", ("мiксоване",)),
        ("Ця новина про budget reform сьогодні.", "uk", ("budget", "reform")),
        ("OpenAI, YouTube, NASA, AI, Google, Kyiv — допустимі.", "uk", ()),
        ("Сайт news.bbc.co.uk, пошта team@site.org, #hashtag і https://x.org/latin", "ru", ()),
        ("The word пример appears here.", "en", ("пример",)),
        ("The letter я alone is fine.", "en", ()),
        ("Das Wort mиксed ist egal.", "de", ()),
        ("Слово cat коротке, tree — вже ні.", "ru", ("tree",)),
    ],
)
def test_script_mix_suspects(hook: str, language: str, expected: tuple[str, ...]) -> None:
    assert PROBE.suspects(("", hook), language) == expected


def test_script_mix_checks_the_texts_in_order_and_stops_at_five() -> None:
    texts: tuple[str, ...] = ("Заголовок FЕКРИС", "Текст alpha bravo", "🔹 charlie delta echo foxtrot")
    assert PROBE.suspects(texts, "ru") == (
        "FЕКРИС", "alpha", "bravo", "charlie", "delta",
    )


# --- починка латинских двойников кириллицы
def test_zhaivoronok_uk() -> None:
    repair = repaired(f"🔹 Тарас Іванов, Владислав {MIXED_ZHAIVORONOK} («Вікіпедія»)", "uk")
    assert repair.tokens_repaired == 1
    assert repair.tokens_before == (MIXED_ZHAIVORONOK,)
    assert repair.tokens_after == (CYRILLIC_ZHAIVORONOK,)
    assert MIXED_ZHAIVORONOK not in repair.description.text
    assert CYRILLIC_ZHAIVORONOK in repair.description.text
    assert repair.tokens_after[0][-1] == "к" and repair.tokens_after[0][-2] == "о"


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Hello twork world", "uk"),
        ("Звичайний український текст", "uk"),
        ("Кириллица" + "def", "uk"),
        ("Some english text with cyrillicа", "en"),
        ("", "uk"),
    ],
)
def test_texts_that_are_not_repaired(text: str, language: str) -> None:
    repair = repaired(text, language)
    assert repair.tokens_repaired == 0
    assert repair.description.text == text


def test_russian_i_and_c_repair() -> None:
    repair = repaired("текст" + "i" + "c", "ru")
    assert repair.tokens_repaired == 1
    assert repair.tokens_after == ("текст" + "и" + "с",)


def test_two_mixed_tokens_both_repaired() -> None:
    mixed: str = "К" + "o" + "зел"
    repair = repaired(f"{MIXED_ZHAIVORONOK} і {mixed}", "uk")
    assert repair.tokens_repaired == 2
    assert CYRILLIC_ZHAIVORONOK in repair.description.text and "Козел" in repair.description.text
    assert repair.extend(EVENT).text == (
        f"merge_script_mix_repaired tokens_repaired=2 before_tokens={MIXED_ZHAIVORONOK},{mixed} "
        f"after_tokens={CYRILLIC_ZHAIVORONOK},Козел"
    )


def test_latin_i_depends_on_the_language() -> None:
    assert HomoglyphMap.of("uk").repair_token("Кiев") == "Кіев"   # type: ignore[union-attr]
    assert HomoglyphMap.of("ru").repair_token("Кiев") == "Киев"   # type: ignore[union-attr]
    assert HomoglyphMap.of("en") is None


def test_token_with_equal_latin_and_cyrillic_is_left() -> None:
    assert HomoglyphMap.of("uk").repair_token("Кo") is None   # type: ignore[union-attr]


def test_no_repair_event() -> None:
    assert repaired("x", "uk").extend(EVENT).text == (
        "merge_script_mix_repaired tokens_repaired=0 before_tokens=- after_tokens=-"
    )
