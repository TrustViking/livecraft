"""Поля разделов настроек окна (CLAUDE.md §8.2, §14 решение 75): стрелки у малых чисел, модели OpenAI — выбор из
моделей не дороже поставочной, с ценой."""
from __future__ import annotations

from app.config.cookies import REMIND_DAYS_MINIMUM
from app.config.files import ShippedSettings
from app.config.setting_key import SettingKey
from app.config.settings import KEEP_DAYS_MINIMUM, MIN_LEAD_MINUTES_MINIMUM, LivecraftSettings
from app.setup.fields.draft_field import DraftField, DraftKind, SpinRange
from app.setup.fields.settings_draft import MODEL_CHOICES, MODEL_LABELS, SETTINGS_FIELDS, SettingsDraft
from app.tests.fixtures.drafts import draft_with

SHIPPED: LivecraftSettings = ShippedSettings().settings


def _field(key: SettingKey) -> DraftField:
    return next(field for field in SETTINGS_FIELDS if field.key is key)


def test_small_numbers_have_arrows_with_the_loader_minimum() -> None:
    assert _field(SettingKey.KEEP_DAYS).spin == SpinRange(KEEP_DAYS_MINIMUM, 365, 1)
    assert _field(SettingKey.COOKIES_REMIND_DAYS).spin == SpinRange(REMIND_DAYS_MINIMUM, 60, 1)
    assert _field(SettingKey.MIN_LEAD_MINUTES).spin == SpinRange(MIN_LEAD_MINUTES_MINIMUM, 1440, 5)
    assert {field.key for field in SETTINGS_FIELDS if field.spin is not None} == {
        SettingKey.KEEP_DAYS, SettingKey.COOKIES_REMIND_DAYS, SettingKey.MIN_LEAD_MINUTES
    }
    assert all(field.kind is DraftKind.INTEGER for field in SETTINGS_FIELDS if field.spin is not None)


def test_big_numbers_and_codes_stay_plain_fields() -> None:
    for key in (
        SettingKey.LLM_TIMEOUT_SEC, SettingKey.LLM_MAX_OUTPUT_TOKENS, SettingKey.YOUTUBE_PAUSE_SECONDS,
        SettingKey.CATEGORY_ID,
    ):
        assert _field(key).spin is None and _field(key).kind is not DraftKind.CHOICE, key


def test_both_models_are_chosen_from_the_priced_list() -> None:
    assert MODEL_CHOICES == ("gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.2", "gpt-5.4", "gpt-5.6-sol")
    assert MODEL_LABELS[0] == "gpt-5.6-luna — $0.20 / $1.20 за 1 млн токенов"
    assert MODEL_LABELS[-1] == "gpt-5.6-sol — $4.00 / $20.00 за 1 млн токенов"
    for key in (SettingKey.LLM_MODEL, SettingKey.LLM_FALLBACK_MODEL):
        field: DraftField = _field(key)
        assert (field.kind, field.choices, field.options) == (DraftKind.CHOICE, MODEL_CHOICES, MODEL_LABELS)
    assert SHIPPED.llm.model in MODEL_CHOICES and SHIPPED.llm.fallback_model in MODEL_CHOICES


def test_a_model_off_the_list_is_shown_and_kept_as_it_is() -> None:
    field: DraftField = _field(SettingKey.LLM_MODEL)
    assert field.shown("gpt-5.4") == MODEL_LABELS[MODEL_CHOICES.index("gpt-5.4")]
    assert field.shown("gpt-6-astra") == "gpt-6-astra"
    assert field.draft_value("gpt-6-astra") == "gpt-6-astra"
    draft: SettingsDraft = draft_with(SettingsDraft.of(SHIPPED), llm_model="gpt-6-astra")
    assert draft.to_data(SHIPPED)[SettingKey.LLM.value]["model"] == "gpt-6-astra"  # type: ignore[index]
