from __future__ import annotations

import pytest

from app.core.language_code import LanguageCode


@pytest.mark.parametrize("code", ["uk", "en", "ru", "de"])
def test_a_known_code_is_shaped_and_known(code: str) -> None:
    assert LanguageCode(code).is_shaped and LanguageCode(code).is_known


@pytest.mark.parametrize("text", ["UK", "ukr", "u", "", "u1", "уk", "uk "])
def test_anything_but_two_small_latin_letters_is_not_a_code(text: str) -> None:
    """Строчность — отдельно: поиск справочника регистр не различает и нашёл бы «UK»."""
    assert not LanguageCode(text).is_shaped and not LanguageCode(text).is_known


def test_a_shaped_code_the_registry_does_not_know_is_not_known() -> None:
    assert LanguageCode("qq").is_shaped and not LanguageCode("qq").is_known
