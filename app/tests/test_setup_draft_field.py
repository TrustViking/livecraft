from __future__ import annotations

import math

import pytest

from app.config.channel import ChannelKey
from app.config.setting_key import SettingKey
from app.setup.fields.draft_field import DraftField, DraftKind
from app.setup.fields.settings_draft import SettingsDraft


def _field(kind: DraftKind) -> DraftField:
    return DraftField(SettingKey.KEEP_DAYS, kind)


def test_the_name_and_the_key_path_come_from_the_key() -> None:
    field: DraftField = DraftField(SettingKey.LLM_MODEL, DraftKind.TEXT)
    assert (field.name, field.key_path) == ("llm_model", "llm.model")
    assert DraftField(ChannelKey.GOOGLE_ACCOUNT, DraftKind.TEXT).name == "google_account"


@pytest.mark.parametrize(("kind", "text", "data"), [
    (DraftKind.TEXT, "  Europe/Kyiv ", "Europe/Kyiv"),
    (DraftKind.CHOICE, " flex ", "flex"),
    (DraftKind.INTEGER, " 14 ", 14),
    (DraftKind.INTEGER, "abc", "abc"),                 # не число — текстом, ошибку назовёт загрузчик
    (DraftKind.NUMBER, "0,5", 0.5),
    (DraftKind.NUMBER, " 2 ", 2.0),
    (DraftKind.NUMBER, "полсекунды", "полсекунды"),
    (DraftKind.HANDLE, " kanal_hu ", "@kanal_hu"),
    (DraftKind.HANDLE, "@kanal_hu", "@kanal_hu"),
    (DraftKind.HANDLE, "   ", ""),                     # пустой ник — пустым: загрузчик назовёт его пустым
])
def test_the_text_goes_to_the_file_by_the_kind(kind: DraftKind, text: str, data: object) -> None:
    assert _field(kind).data(text) == data


def test_nan_goes_to_the_file_as_a_number() -> None:
    """Правило конечности одно — у загрузчика: поле отдаёт nan числом, а не текстом."""
    value: object = _field(DraftKind.NUMBER).data("nan")
    assert isinstance(value, float) and math.isnan(value)


def test_a_flag_and_languages_go_to_the_file_as_bool_and_list() -> None:
    assert _field(DraftKind.FLAG).data(True) is True
    assert _field(DraftKind.LANGUAGE).data(("uk", "ru")) == ["uk", "ru"]


def test_languages_travel_through_the_window_variable_as_codes() -> None:
    field: DraftField = DraftField(ChannelKey.LANGUAGES, DraftKind.LANGUAGE)
    assert field.shown(("ru", "en")) == "ru en"
    assert field.draft_value("ru en") == ("ru", "en")
    assert field.draft_value("") == ()
    assert _field(DraftKind.TEXT).draft_value(" 7 ") == " 7 "        # прочие поля — как введено
    assert _field(DraftKind.FLAG).shown(False) is False


def test_a_choice_field_is_not_narrower_than_its_longest_label() -> None:
    """Смотр окна 29-09-2026: поле доступа к документу обрезало «все по ссылке — правк…»."""
    access: DraftField = next(field for field in SettingsDraft.FIELDS if field.key is SettingKey.DOCS_ACCESS)
    width: int | None = access.input_width
    assert width is not None and width > max(len(label) for label in access.labels)
    text: DraftField = DraftField(SettingKey.TIMEZONE, DraftKind.TEXT, width=20)
    assert text.input_width == 20 and DraftField(SettingKey.TIMEZONE, DraftKind.TEXT).input_width is None
