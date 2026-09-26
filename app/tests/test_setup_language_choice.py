from __future__ import annotations

import gettext

import pycountry
import pytest

from app.config.loader import SettingProblem
from app.setup.fields.language_choice import (
    TRANSLATION_DOMAIN,
    TRANSLATION_LOCALE,
    LanguageDirectory,
    LanguageOption,
    LanguagePicker,
)
from app.ui import messages_ru as msg

FORM_CODES: tuple[str, ...] = ("uk", "ru", "en", "hu")      # варианты вопроса о языке поставочной формы
ALPHA_2_COUNT: int = sum(1 for language in pycountry.languages if hasattr(language, "alpha_2"))


@pytest.fixture(scope="module")
def directory() -> LanguageDirectory:
    return LanguageDirectory.load(FORM_CODES)


def _alphabet_key(name: str) -> str:
    return name.casefold().replace("ё", "е")


# --- порядок и пометки


def test_every_two_letter_language_is_in_the_list_once(directory: LanguageDirectory) -> None:
    codes: list[str] = [option.code for option in directory.options]
    assert len(codes) == len(set(codes)) == ALPHA_2_COUNT


def test_form_languages_come_first_in_form_order_and_marked(directory: LanguageDirectory) -> None:
    head: tuple[LanguageOption, ...] = directory.options[: len(FORM_CODES)]
    assert tuple(option.code for option in head) == FORM_CODES
    assert all(option.in_form for option in head)
    assert not any(option.in_form for option in directory.options[len(FORM_CODES):])
    assert directory.has_form


def test_the_rest_go_by_russian_alphabet_then_untranslated(directory: LanguageDirectory) -> None:
    rest: tuple[LanguageOption, ...] = directory.options[len(FORM_CODES):]
    translated: list[str] = [option.name for option in rest if option.is_translated]
    untranslated: list[str] = [option.name for option in rest if not option.is_translated]
    assert [option.is_translated for option in rest] == [True] * len(translated) + [False] * len(untranslated)
    assert translated == sorted(translated, key=_alphabet_key)
    assert untranslated == sorted(untranslated, key=str.casefold)
    assert translated[0] == "абхазский"


def test_names_are_russian_where_the_catalog_has_a_translation(directory: LanguageDirectory) -> None:
    """Перевод в каталоге pycountry проверяется фактически: для uk и ru он есть, для nb — нет."""
    translation: gettext.NullTranslations = gettext.translation(
        TRANSLATION_DOMAIN, pycountry.LOCALES_DIR, languages=[TRANSLATION_LOCALE]
    )
    assert translation.gettext("Ukrainian") == "украинский"
    assert translation.gettext("Norwegian Bokmål") == "Norwegian Bokmål"
    assert directory.name("uk") == "украинский"
    assert directory.name("ru") == "русский"
    bokmal: LanguageOption | None = directory.option("nb")
    assert bokmal is not None
    assert (bokmal.name, bokmal.is_translated) == ("Norwegian Bokmål", False)


def test_labels_carry_the_code_and_the_form_mark(directory: LanguageDirectory) -> None:
    ukrainian: LanguageOption | None = directory.option("uk")
    german: LanguageOption | None = directory.option("de")
    assert ukrainian is not None and german is not None
    assert ukrainian.label == msg.SETUP_LANGUAGE_OPTION_IN_FORM.format(name="украинский", code="uk")
    assert ukrainian.label == "украинский (uk) — есть в форме"
    assert german.label == "немецкий (de)"


def test_a_form_code_unknown_to_pycountry_is_kept_by_its_code_and_marked() -> None:
    directory: LanguageDirectory = LanguageDirectory.load(("uk", "zz"))
    assert [option.code for option in directory.options[:2]] == ["uk", "zz"]
    unknown: LanguageOption | None = directory.option("zz")
    assert unknown is not None and unknown.in_form and unknown.name == "zz" and not unknown.is_standard
    assert unknown.label == msg.SETUP_LANGUAGE_OPTION_NOT_ISO_IN_FORM.format(code="zz")
    assert unknown.label == "zz (не код ISO 639-1) — есть в форме"
    assert directory.code_of(unknown.label) == "zz"


def test_without_form_codes_nothing_is_marked() -> None:
    directory: LanguageDirectory = LanguageDirectory.load(())
    assert not directory.has_form
    assert not any(option.in_form for option in directory.options)
    assert len(directory.options) == ALPHA_2_COUNT


# --- поиск, названия, языки не из формы


def test_search_finds_by_code_and_by_part_of_the_name_ignoring_case(directory: LanguageDirectory) -> None:
    by_code: list[str] = [option.code for option in directory.search("HU")]
    assert by_code[0] == "hu"                                # язык формы — первым
    assert set(by_code) == {"hu", "cu", "ii", "za"}          # «hu» есть и в Church Slavic, Sichuan Yi, Zhuang
    assert [option.code for option in directory.search("немец")] == ["de"]
    assert [option.code for option in directory.search("ВЕНГ")] == ["hu"]
    assert "uk" in [option.code for option in directory.search("  украин ")]
    assert directory.search("") == directory.options
    assert directory.search("нет-такого-языка") == ()


def test_search_keeps_the_catalog_order(directory: LanguageDirectory) -> None:
    found: tuple[LanguageOption, ...] = directory.search("ский")
    positions: list[int] = [directory.options.index(option) for option in found]
    assert positions == sorted(positions)
    assert found[0].code == "uk"


def test_names_for_the_table(directory: LanguageDirectory) -> None:
    assert directory.names(["ru", "en"]) == "русский, английский"
    assert directory.names(["xx"]) == "xx"
    assert directory.names([]) == ""


def test_foreign_lists_codes_outside_the_form(directory: LanguageDirectory) -> None:
    assert directory.foreign(["uk", "de", "hu", "xx"]) == ("de", "xx")
    assert directory.foreign(["uk", "ru"]) == ()
    assert LanguageDirectory.load(()).foreign(["de"]) == ()


def test_including_adds_unknown_codes_once_at_the_end(directory: LanguageDirectory) -> None:
    wider: LanguageDirectory = directory.including(["uk", "xx", "xx"])
    assert len(wider.options) == len(directory.options) + 1
    assert wider.options[-1].code == "xx"
    assert directory.including(["uk"]) is directory


# --- подпись в поле выбора и обратно (один язык на канал)


@pytest.mark.parametrize("code", ["uk", "hu", "de"])
def test_label_and_code_go_both_ways(directory: LanguageDirectory, code: str) -> None:
    label: str = directory.label_of(code)
    assert directory.code_of(label) == code


def test_a_form_language_label_carries_the_mark(directory: LanguageDirectory) -> None:
    assert directory.label_of("uk") == msg.SETUP_LANGUAGE_OPTION_IN_FORM.format(name="украинский", code="uk")
    assert directory.label_of("de") == msg.SETUP_LANGUAGE_OPTION.format(name="немецкий", code="de")


def test_a_language_without_a_russian_name_goes_both_ways(directory: LanguageDirectory) -> None:
    option: LanguageOption = next(item for item in directory.options if not item.is_translated)
    assert directory.code_of(directory.label_of(option.code)) == option.code


def test_an_unknown_code_gets_a_label_marked_outside_iso(directory: LanguageDirectory) -> None:
    """Код вне ISO 639-1 (язык старого channels.json) помечен: загрузчик его не примет."""
    assert directory.label_of("xx") == msg.SETUP_LANGUAGE_OPTION_NOT_ISO.format(code="xx")
    assert directory.label_of("xx") == "xx (не код ISO 639-1)"
    assert directory.code_of(directory.label_of("xx")) is None                  # в каталоге его нет
    wider: LanguageDirectory = directory.including(["xx"])
    assert wider.code_of(wider.label_of("xx")) == "xx"


@pytest.mark.parametrize("text", ["укр", "uk", "украинский", "украинский (uk)", " " + "украинский (uk) — есть в форме"])
def test_code_of_anything_but_an_exact_label_is_none(directory: LanguageDirectory, text: str) -> None:
    assert directory.code_of(text) is None


def test_labels_keep_the_given_order(directory: LanguageDirectory) -> None:
    found: tuple[LanguageOption, ...] = directory.search("укр")
    assert directory.labels(found) == tuple(option.label for option in found)
    assert directory.labels(directory.options)[: len(FORM_CODES)] == tuple(directory.label_of(code) for code in FORM_CODES)


def test_text_problem_only_for_text_that_is_not_a_label(directory: LanguageDirectory) -> None:
    assert directory.text_problem(directory.label_of("uk")) is None
    assert directory.text_problem("") is None and directory.text_problem("   ") is None
    problem: SettingProblem | None = directory.text_problem("укр")
    assert problem is not None
    assert (problem.key, problem.text) == ("languages", msg.SETUP_LANGUAGE_PICK_FROM_LIST)


# --- поле выбора языка канала


@pytest.fixture
def picker() -> LanguagePicker:
    return LanguagePicker.of(FORM_CODES)


def test_an_empty_picker_has_no_language_and_lists_everything(picker: LanguagePicker) -> None:
    assert (picker.codes, picker.text, picker.first, picker.chosen_label) == ((), "", None, "")
    assert picker.draft_codes == ()
    assert not picker.is_search
    assert picker.choices == picker.directory.labels(picker.directory.options)
    assert picker.problem is None and picker.note is None and picker.warning is None


def test_the_codes_of_an_old_channel_keep_the_first_for_the_draft(picker: LanguagePicker) -> None:
    chosen: LanguagePicker = picker.chose(("ru", "en", "ru"))
    assert chosen.codes == ("ru", "en")
    assert chosen.first == "ru"
    assert chosen.draft_codes == ("ru",)                 # в черновик уходит один код
    assert chosen.text == chosen.directory.label_of("ru")
    assert chosen.note == msg.SETUP_LANGUAGE_SEVERAL.format(name="русский")


def test_a_label_typed_into_the_field_chooses_exactly_one_language(picker: LanguagePicker) -> None:
    typed: LanguagePicker = picker.typed(picker.directory.label_of("hu"))
    assert typed.codes == ("hu",)
    assert typed.is_label and not typed.is_search
    assert typed.note is None


def test_the_label_of_the_same_language_keeps_the_extra_codes(picker: LanguagePicker) -> None:
    """Подпись того же языка выбор не меняет: строка о лишних языках остаётся до сохранения."""
    chosen: LanguagePicker = picker.chose(("ru", "en"))
    assert chosen.typed(chosen.text).codes == ("ru", "en")


def test_search_text_narrows_the_choices_and_keeps_the_choice(picker: LanguagePicker) -> None:
    searched: LanguagePicker = picker.chose(("hu",)).typed("укр")
    assert searched.is_search and not searched.is_label
    assert searched.codes == ("hu",)                     # набранный текст выбор не меняет
    assert searched.choices == (searched.directory.label_of("uk"),)
    assert searched.problem is not None
    assert (searched.problem.key, searched.problem.text) == ("languages", msg.SETUP_LANGUAGE_PICK_FROM_LIST)


def test_an_emptied_field_has_no_language(picker: LanguagePicker) -> None:
    assert picker.chose(("hu",)).typed("  ").codes == ()


def test_restored_brings_back_the_label_of_the_choice(picker: LanguagePicker) -> None:
    restored: LanguagePicker = picker.chose(("hu",)).typed("нем").restored()
    assert restored.text == restored.directory.label_of("hu")
    assert restored.problem is None


def test_a_language_outside_the_form_is_warned(picker: LanguagePicker) -> None:
    assert picker.chose(("uk",)).warning is None
    assert picker.chose(("de",)).warning == msg.SETUP_LANGUAGE_NOT_IN_FORM.format(names="немецкий")
    assert LanguagePicker.of(()).chose(("de",)).warning is None


def test_new_form_codes_remark_the_choice(picker: LanguagePicker) -> None:
    chosen: LanguagePicker = picker.chose(("de",))
    refreshed: LanguagePicker = chosen.with_form(("de", "uk"), ("xx",))
    assert refreshed.codes == ("de",)
    assert refreshed.text == msg.SETUP_LANGUAGE_OPTION_IN_FORM.format(name="немецкий", code="de")
    assert refreshed.warning is None
    assert refreshed.directory.option("xx") is not None


def test_including_keeps_the_choice_and_widens_the_directory(picker: LanguagePicker) -> None:
    wider: LanguagePicker = picker.chose(("hu",)).including(("xx",))
    assert wider.codes == ("hu",)
    assert wider.directory.label_of("xx") in wider.choices
