from __future__ import annotations

import dataclasses
import json
import math
from typing import Any

import pytest

from app.config.loader import (
    LivecraftSettings,
    ReasoningEffort,
    ServiceTier,
    load_settings,
    render_settings_file,
)
from app.paths import LivecraftPaths
from app.setup.fields.settings_draft import SettingsDraft
from app.setup.panels.settings_panel import SettingsPanel, SettingsPanelEdit
from app.tests.conftest import SHIPPED_SETTINGS_FILE
from app.ui import messages_ru as msg

BROKEN_JSON: bytes = b'{"min_lead_minutes": 60,'
FORM_URL: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-own-form/viewform"


def _shipped() -> LivecraftSettings:
    return load_settings(SHIPPED_SETTINGS_FILE)


def _applied(panel: SettingsPanel, **changes: Any) -> SettingsPanel:
    edit: SettingsPanelEdit = panel.apply(dataclasses.replace(panel.draft, **changes))
    assert edit.is_applied, edit.problem
    return edit.panel


def _rejected(panel: SettingsPanel, **changes: Any) -> SettingsPanelEdit:
    edit: SettingsPanelEdit = panel.apply(dataclasses.replace(panel.draft, **changes))
    assert not edit.is_applied
    assert edit.panel is panel
    return edit


# --- чтение


def test_the_draft_shows_the_shipped_values(ready_paths: LivecraftPaths) -> None:
    panel: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    assert panel.draft == SettingsDraft(
        form_url="",
        min_lead_minutes="60",
        keep_days="30",
        auto_start=True,
        set_thumbnail=True,
        category_id="22",
        youtube_pause_seconds="0.5",
        image_dir_template="{date}/{language}",
        timezone="Europe/Kyiv",
        llm_model="gpt-5.6-sol",
        llm_fallback_model="gpt-5.4",
        llm_reasoning_effort="medium",
        llm_service_tier="flex",
        llm_timeout_sec="900",
        llm_max_output_tokens="8000",
    )
    assert panel.settings == _shipped()
    assert panel.loaded == panel.settings
    assert not panel.is_dirty
    assert panel.notices == ()


def test_the_unchanged_draft_applies_to_the_same_settings(ready_paths: LivecraftPaths) -> None:
    panel: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    edit: SettingsPanelEdit = panel.apply(panel.draft)
    assert edit.is_applied
    assert edit.panel.settings == panel.settings
    assert not edit.panel.is_dirty


def test_the_choice_options_come_from_the_loader_enums(ready_paths: LivecraftPaths) -> None:
    panel: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    assert panel.reasoning_effort_options == tuple(item.value for item in ReasoningEffort)
    assert panel.service_tier_options == tuple(item.value for item in ServiceTier)


# --- правки


def test_a_changed_keep_days_applies_and_makes_the_panel_dirty(ready_paths: LivecraftPaths) -> None:
    panel: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    changed: SettingsPanel = _applied(panel, keep_days=" 14 ")
    assert changed.settings.keep_days == 14
    assert changed.is_dirty
    assert panel.settings.keep_days == 30
    assert not panel.is_dirty


def test_text_in_an_integer_field_is_named_by_the_loader(ready_paths: LivecraftPaths) -> None:
    edit: SettingsPanelEdit = _rejected(SettingsPanel.from_paths(ready_paths), min_lead_minutes="abc")
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == ("min_lead_minutes", msg.CONFIG_PROBLEM_INT_MIN.format(minimum=0))


def test_a_value_below_the_minimum_is_named_by_the_loader(ready_paths: LivecraftPaths) -> None:
    edit: SettingsPanelEdit = _rejected(SettingsPanel.from_paths(ready_paths), llm_timeout_sec="0")
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == ("llm.timeout_sec", msg.CONFIG_PROBLEM_INT_MIN.format(minimum=1))


def test_a_decimal_comma_in_the_pause_is_accepted(ready_paths: LivecraftPaths) -> None:
    changed: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), youtube_pause_seconds="0,5")
    assert changed.settings.youtube_pause_seconds == 0.5


def test_a_whole_pause_becomes_a_number(ready_paths: LivecraftPaths) -> None:
    changed: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), youtube_pause_seconds="2")
    assert changed.settings.youtube_pause_seconds == 2.0


@pytest.mark.parametrize("text", ["nan", "inf", "-inf", "Infinity"])
def test_a_pause_that_is_not_a_finite_number_is_a_problem(ready_paths: LivecraftPaths, text: str) -> None:
    """nan и бесконечность черновик отдаёт числом: точный текст о конечности называет загрузчик."""
    edit: SettingsPanelEdit = _rejected(SettingsPanel.from_paths(ready_paths), youtube_pause_seconds=text)
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == ("youtube_pause_seconds", msg.CONFIG_PROBLEM_NUMBER_FINITE)


@pytest.mark.parametrize("text", ["abc", "полсекунды", ""])
def test_a_pause_that_is_not_a_number_is_a_problem(ready_paths: LivecraftPaths, text: str) -> None:
    edit: SettingsPanelEdit = _rejected(SettingsPanel.from_paths(ready_paths), youtube_pause_seconds=text)
    assert edit.problem is not None
    assert edit.problem.key == "youtube_pause_seconds"
    assert edit.problem.text == msg.CONFIG_PROBLEM_NUMBER_MIN.format(minimum=0.0)


def test_the_draft_leaves_the_finiteness_rule_to_the_loader(ready_paths: LivecraftPaths) -> None:
    """Правило конечности одно — у загрузчика: черновик отдаёт nan числом, а не текстом."""
    draft: SettingsDraft = dataclasses.replace(SettingsPanel.from_paths(ready_paths).draft, youtube_pause_seconds="nan")
    value: Any = draft.to_data(_shipped().form)["youtube_pause_seconds"]
    assert isinstance(value, float) and math.isnan(value)


def test_an_unknown_timezone_is_a_problem(ready_paths: LivecraftPaths) -> None:
    edit: SettingsPanelEdit = _rejected(SettingsPanel.from_paths(ready_paths), timezone="Europe/Nowhere")
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == ("timezone", msg.CONFIG_PROBLEM_TIMEZONE_UNKNOWN)


def test_spaces_around_the_timezone_are_trimmed(ready_paths: LivecraftPaths) -> None:
    changed: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), timezone=" Europe/Warsaw ")
    assert changed.settings.timezone == "Europe/Warsaw"


def test_an_unknown_reasoning_effort_is_a_problem(ready_paths: LivecraftPaths) -> None:
    edit: SettingsPanelEdit = _rejected(SettingsPanel.from_paths(ready_paths), llm_reasoning_effort="extreme")
    assert edit.problem is not None
    assert edit.problem.key == "llm.reasoning_effort"
    assert edit.problem.text == msg.CONFIG_PROBLEM_CHOICE.format(allowed="none, low, medium, high, xhigh, max")


def test_the_flags_are_applied(ready_paths: LivecraftPaths) -> None:
    changed: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), auto_start=False, set_thumbnail=False)
    assert (changed.settings.auto_start, changed.settings.set_thumbnail) == (False, False)


# --- ссылка на форму ключей (открытая настройка, §14 решение 15)


def test_a_form_url_is_applied_with_spaces_trimmed(ready_paths: LivecraftPaths) -> None:
    changed: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), form_url=f"  {FORM_URL} ")
    assert changed.settings.form.url == FORM_URL
    assert changed.settings.form.is_configured
    assert changed.is_dirty


@pytest.mark.parametrize(
    "text",
    [
        "http://forms.gle/AbCdEf123456",
        "https://example.com/forms/x",
        "не ссылка",
        "https://docs.google.com]/forms/x",   # urlsplit бросает ValueError — проблема поля, а не падение
        "https://[bad",
    ],
)
def test_a_bad_form_url_is_a_problem_of_the_field(ready_paths: LivecraftPaths, text: str) -> None:
    edit: SettingsPanelEdit = _rejected(SettingsPanel.from_paths(ready_paths), form_url=text)
    assert edit.problem is not None
    assert edit.problem.key == "form.url"
    assert edit.problem.text == msg.CONFIG_PROBLEM_FORM_URL


def test_an_emptied_form_url_means_not_configured(ready_paths: LivecraftPaths) -> None:
    panel: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), form_url=FORM_URL)
    cleared: SettingsPanel = _applied(panel, form_url="   ")
    assert cleared.settings.form.url == ""
    assert not cleared.settings.form.is_configured


def test_save_writes_the_form_url_and_keeps_the_form_contract(ready_paths: LivecraftPaths) -> None:
    before: dict[str, Any] = json.loads(ready_paths.config_file.read_text(encoding="utf-8"))
    saved: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), form_url=FORM_URL).save(ready_paths)
    after: dict[str, Any] = json.loads(ready_paths.config_file.read_text(encoding="utf-8"))
    assert after["form"]["url"] == FORM_URL
    assert list(after["form"])[0] == "url"
    assert {key: value for key, value in after["form"].items() if key != "url"} == {
        key: value for key, value in before["form"].items() if key != "url"
    }
    assert {key for key in before if before[key] != after[key]} == {"form"}
    assert load_settings(ready_paths.config_file).form.url == FORM_URL
    assert saved.draft.form_url == FORM_URL and not saved.is_dirty


# --- запись


def test_save_changes_only_the_edited_field(ready_paths: LivecraftPaths) -> None:
    before: dict[str, Any] = json.loads(ready_paths.config_file.read_text(encoding="utf-8"))
    saved: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), keep_days="14").save(ready_paths)
    after: dict[str, Any] = json.loads(ready_paths.config_file.read_text(encoding="utf-8"))
    assert after["form"] == before["form"]
    assert list(after["form"]["values"]["language"]) == list(before["form"]["values"]["language"])
    assert {key for key in before if before[key] != after[key]} == {"keep_days"}
    assert after["keep_days"] == 14
    assert saved.loaded == saved.settings
    assert not saved.is_dirty


def test_save_without_changes_writes_the_shipped_file_again(ready_paths: LivecraftPaths) -> None:
    SettingsPanel.from_paths(ready_paths).save(ready_paths)
    assert ready_paths.config_file.read_bytes() == SHIPPED_SETTINGS_FILE.read_bytes()


def test_without_a_settings_file_the_panel_opens_on_the_template(livecraft_paths: LivecraftPaths) -> None:
    panel: SettingsPanel = SettingsPanel.from_paths(livecraft_paths)
    assert panel.settings == _shipped()
    assert panel.loaded is None
    assert panel.load_problem is not None
    assert (panel.load_problem.key, panel.load_problem.text) == (msg.CONFIG_ROOT_KEY, msg.CONFIG_PROBLEM_FILE_MISSING)
    assert panel.notices == (
        msg.SETUP_SETTINGS_NOTICE_UNREADABLE.format(key=msg.CONFIG_ROOT_KEY, problem=msg.CONFIG_PROBLEM_FILE_MISSING),
    )
    assert panel.is_dirty
    assert not livecraft_paths.config_file.exists()
    saved: SettingsPanel = panel.save(livecraft_paths)
    assert load_settings(livecraft_paths.config_file) == panel.settings
    assert saved.notices == ()


def test_a_broken_settings_file_is_named_and_replaced_only_on_save(livecraft_paths: LivecraftPaths) -> None:
    livecraft_paths.config_file.write_bytes(BROKEN_JSON)
    panel: SettingsPanel = SettingsPanel.from_paths(livecraft_paths)
    assert panel.settings == _shipped()
    assert panel.loaded is None
    assert panel.load_problem is not None
    assert len(panel.notices) == 1
    assert livecraft_paths.config_file.read_bytes() == BROKEN_JSON
    panel.save(livecraft_paths)
    assert livecraft_paths.config_file.read_text(encoding="utf-8") == render_settings_file(panel.settings)
    assert load_settings(livecraft_paths.config_file) == panel.settings


def test_a_settings_file_missing_a_field_opens_on_the_template(livecraft_paths: LivecraftPaths) -> None:
    data: dict[str, Any] = json.loads(SHIPPED_SETTINGS_FILE.read_text(encoding="utf-8"))
    del data["timezone"]
    livecraft_paths.config_file.write_text(json.dumps(data), encoding="utf-8")
    panel: SettingsPanel = SettingsPanel.from_paths(livecraft_paths)
    assert panel.loaded is None
    assert panel.load_problem is not None
    assert (panel.load_problem.key, panel.load_problem.text) == ("timezone", msg.CONFIG_PROBLEM_MISSING_KEY)
