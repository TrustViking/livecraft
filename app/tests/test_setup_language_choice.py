from __future__ import annotations

import gettext

import pycountry
import pytest

from app.config.loader import SettingProblem
from app.setup.fields.language_choice import (
    TRANSLATION_DOMAIN,
    TRANSLATION_LOCALE,
    LanguageCatalog,
    LanguageOption,
    LanguageSelection,
)
from app.ui import messages_ru as msg

FORM_CODES: tuple[str, ...] = ("uk", "ru", "en", "hu")      # варианты вопроса о языке поставочной формы
ALPHA_2_COUNT: int = sum(1 for language in pycountry.languages if hasattr(language, "alpha_2"))


@pytest.fixture(scope="module")
def catalog() -> LanguageCatalog:
    return LanguageCatalog.load(FORM_CODES)


def _alphabet_key(name: str) -> str:
    return name.casefold().replace("ё", "е")


# --- порядок и пометки


def test_every_two_letter_language_is_in_the_list_once(catalog: LanguageCatalog) -> None:
    codes: list[str] = [option.code for option in catalog.options]
    assert len(codes) == len(set(codes)) == ALPHA_2_COUNT


def test_form_languages_come_first_in_form_order_and_marked(catalog: LanguageCatalog) -> None:
    head: tuple[LanguageOption, ...] = catalog.options[: len(FORM_CODES)]
    assert tuple(option.code for option in head) == FORM_CODES
    assert all(option.in_form for option in head)
    assert not any(option.in_form for option in catalog.options[len(FORM_CODES):])
    assert catalog.has_form


def test_the_rest_go_by_russian_alphabet_then_untranslated(catalog: LanguageCatalog) -> None:
    rest: tuple[LanguageOption, ...] = catalog.options[len(FORM_CODES):]
    translated: list[str] = [option.name for option in rest if option.is_translated]
    untranslated: list[str] = [option.name for option in rest if not option.is_translated]
    assert [option.is_translated for option in rest] == [True] * len(translated) + [False] * len(untranslated)
    assert translated == sorted(translated, key=_alphabet_key)
    assert untranslated == sorted(untranslated, key=str.casefold)
    assert translated[0] == "абхазский"


def test_names_are_russian_where_the_catalog_has_a_translation(catalog: LanguageCatalog) -> None:
    """Перевод в каталоге pycountry проверяется фактически: для uk и ru он есть, для nb — нет."""
    translation: gettext.NullTranslations = gettext.translation(
        TRANSLATION_DOMAIN, pycountry.LOCALES_DIR, languages=[TRANSLATION_LOCALE]
    )
    assert translation.gettext("Ukrainian") == "украинский"
    assert translation.gettext("Norwegian Bokmål") == "Norwegian Bokmål"
    assert catalog.name("uk") == "украинский"
    assert catalog.name("ru") == "русский"
    bokmal: LanguageOption | None = catalog.option("nb")
    assert bokmal is not None
    assert (bokmal.name, bokmal.is_translated) == ("Norwegian Bokmål", False)


def test_labels_carry_the_code_and_the_form_mark(catalog: LanguageCatalog) -> None:
    ukrainian: LanguageOption | None = catalog.option("uk")
    german: LanguageOption | None = catalog.option("de")
    assert ukrainian is not None and german is not None
    assert ukrainian.label == msg.SETUP_LANGUAGE_OPTION_IN_FORM.format(name="украинский", code="uk")
    assert ukrainian.label == "украинский (uk) — есть в форме"
    assert german.label == "немецкий (de)"


def test_a_form_code_unknown_to_pycountry_is_kept_by_its_code() -> None:
    catalog: LanguageCatalog = LanguageCatalog.load(("uk", "zz"))
    assert [option.code for option in catalog.options[:2]] == ["uk", "zz"]
    unknown: LanguageOption | None = catalog.option("zz")
    assert unknown is not None and unknown.in_form and unknown.name == "zz"


def test_without_form_codes_nothing_is_marked() -> None:
    catalog: LanguageCatalog = LanguageCatalog.load(())
    assert not catalog.has_form
    assert not any(option.in_form for option in catalog.options)
    assert len(catalog.options) == ALPHA_2_COUNT


# --- поиск, названия, языки не из формы


def test_search_finds_by_code_and_by_part_of_the_name_ignoring_case(catalog: LanguageCatalog) -> None:
    by_code: list[str] = [option.code for option in catalog.search("HU")]
    assert by_code[0] == "hu"                                # язык формы — первым
    assert set(by_code) == {"hu", "cu", "ii", "za"}          # «hu» есть и в Church Slavic, Sichuan Yi, Zhuang
    assert [option.code for option in catalog.search("немец")] == ["de"]
    assert [option.code for option in catalog.search("ВЕНГ")] == ["hu"]
    assert "uk" in [option.code for option in catalog.search("  украин ")]
    assert catalog.search("") == catalog.options
    assert catalog.search("нет-такого-языка") == ()


def test_search_keeps_the_catalog_order(catalog: LanguageCatalog) -> None:
    found: tuple[LanguageOption, ...] = catalog.search("ский")
    positions: list[int] = [catalog.options.index(option) for option in found]
    assert positions == sorted(positions)
    assert found[0].code == "uk"


def test_names_for_the_table(catalog: LanguageCatalog) -> None:
    assert catalog.names(["ru", "en"]) == "русский, английский"
    assert catalog.names(["xx"]) == "xx"
    assert catalog.names([]) == ""


def test_foreign_lists_codes_outside_the_form(catalog: LanguageCatalog) -> None:
    assert catalog.foreign(["uk", "de", "hu", "xx"]) == ("de", "xx")
    assert catalog.foreign(["uk", "ru"]) == ()
    assert LanguageCatalog.load(()).foreign(["de"]) == ()


def test_including_adds_unknown_codes_once_at_the_end(catalog: LanguageCatalog) -> None:
    wider: LanguageCatalog = catalog.including(["uk", "xx", "xx"])
    assert len(wider.options) == len(catalog.options) + 1
    assert wider.options[-1].code == "xx"
    assert catalog.including(["uk"]) is catalog


# --- подпись в поле выбора и обратно (один язык на канал)


@pytest.mark.parametrize("code", ["uk", "hu", "de"])
def test_label_and_code_go_both_ways(catalog: LanguageCatalog, code: str) -> None:
    label: str = catalog.label_of(code)
    assert catalog.code_of(label) == code


def test_a_form_language_label_carries_the_mark(catalog: LanguageCatalog) -> None:
    assert catalog.label_of("uk") == msg.SETUP_LANGUAGE_OPTION_IN_FORM.format(name="украинский", code="uk")
    assert catalog.label_of("de") == msg.SETUP_LANGUAGE_OPTION.format(name="немецкий", code="de")


def test_a_language_without_a_russian_name_goes_both_ways(catalog: LanguageCatalog) -> None:
    option: LanguageOption = next(item for item in catalog.options if not item.is_translated)
    assert catalog.code_of(catalog.label_of(option.code)) == option.code


def test_an_unknown_code_gets_a_label_with_the_code(catalog: LanguageCatalog) -> None:
    assert catalog.label_of("xx") == msg.SETUP_LANGUAGE_OPTION.format(name="xx", code="xx")
    assert catalog.code_of(catalog.label_of("xx")) is None                  # в каталоге его нет
    wider: LanguageCatalog = catalog.including(["xx"])
    assert wider.code_of(wider.label_of("xx")) == "xx"


@pytest.mark.parametrize("text", ["укр", "uk", "украинский", "украинский (uk)", " " + "украинский (uk) — есть в форме"])
def test_code_of_anything_but_an_exact_label_is_none(catalog: LanguageCatalog, text: str) -> None:
    assert catalog.code_of(text) is None


def test_labels_keep_the_given_order(catalog: LanguageCatalog) -> None:
    found: tuple[LanguageOption, ...] = catalog.search("укр")
    assert catalog.labels(found) == tuple(option.label for option in found)
    assert catalog.labels(catalog.options)[: len(FORM_CODES)] == tuple(catalog.label_of(code) for code in FORM_CODES)


def test_text_problem_only_for_text_that_is_not_a_label(catalog: LanguageCatalog) -> None:
    assert catalog.text_problem(catalog.label_of("uk")) is None
    assert catalog.text_problem("") is None and catalog.text_problem("   ") is None
    problem: SettingProblem | None = catalog.text_problem("укр")
    assert problem is not None
    assert (problem.key, problem.text) == ("languages", msg.SETUP_LANGUAGE_PICK_FROM_LIST)


# --- выбор


def test_selection_from_draft_text_keeps_the_first_code() -> None:
    selection: LanguageSelection = LanguageSelection.from_text("ru, en  ru")
    assert selection.codes == ("ru", "en")
    assert selection.first == "ru"
    assert selection.extra_codes == ("en",)
    assert selection.text == "ru"                    # в черновик уходит один код
    empty: LanguageSelection = LanguageSelection.from_text("")
    assert empty.codes == () and empty.first is None and empty.extra_codes == () and empty.text == ""


def test_single_is_exactly_one_language() -> None:
    selection: LanguageSelection = LanguageSelection.single("hu")
    assert selection.codes == ("hu",)
    assert selection.extra_codes == ()
    assert selection.text == "hu"
