from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path
from typing import Any

import pytest

from app.config.docs import DocAccess, DocsSettings
from app.config.files import SettingsFile
from app.config.folders import FolderSettings
from app.config.setting_key import SettingKey
from app.config.settings import LivecraftSettings, ReasoningEffort, ServiceTier
from app.config.telegram import ChatTarget, TelegramSettings
from app.paths import FileName, LivecraftPaths
from app.run.mode import RunPart
from app.setup.fields.settings_draft import SettingsDraft
from app.setup.panels.panel_edit import PanelEdit
from app.setup.panels.link_panel import SettingLink
from app.setup.panels.settings_panel import SettingsPanel
from app.tests.conftest import SHIPPED_SETTINGS_FILE
from app.tests.fixtures.drafts import draft_with
from app.tests.fixtures.settings import lines_without, set_folders, set_lines
from app.ui import messages_ru as msg

BROKEN_JSON: bytes = b'{"min_lead_minutes": 60,'
FORM_URL: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-own-form/viewform"


def _shipped() -> LivecraftSettings:
    return SettingsFile(SHIPPED_SETTINGS_FILE).load()


def _applied(panel: SettingsPanel, **changes: Any) -> SettingsPanel:
    edit: PanelEdit[SettingsPanel] = panel.apply(draft_with(panel.draft, **changes))
    assert edit.is_applied, edit.problem
    return edit.panel


def _rejected(panel: SettingsPanel, **changes: Any) -> PanelEdit[SettingsPanel]:
    edit: PanelEdit[SettingsPanel] = panel.apply(draft_with(panel.draft, **changes))
    assert not edit.is_applied
    assert edit.panel is panel
    return edit


# --- чтение


def test_the_draft_shows_the_shipped_values(ready_paths: LivecraftPaths) -> None:
    panel: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    assert panel.draft == SettingsDraft(
        min_lead_minutes="60",
        keep_days="30",
        auto_start=True,
        set_thumbnail=True,
        category_id="22",
        youtube_pause_seconds="0.5",
        image_dir_template="{date}/{language}",
        drive_preview_path_template="preview/{date}/{language}",
        timezone="Europe/Kyiv",
        llm_model="gpt-5.6-sol",
        llm_fallback_model="gpt-5.4",
        llm_reasoning_effort="medium",
        llm_service_tier="flex",
        llm_timeout_sec="900",
        llm_max_output_tokens="8000",
        docs_access="writer",
        docs_contacts="",
    )
    assert panel.settings == _shipped()
    assert panel.loaded == panel.settings
    assert not panel.is_dirty
    assert panel.notices == ()


def test_the_unchanged_draft_applies_to_the_same_settings(ready_paths: LivecraftPaths) -> None:
    panel: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    edit: PanelEdit[SettingsPanel] = panel.apply(panel.draft)
    assert edit.is_applied
    assert edit.panel.settings == panel.settings
    assert not edit.panel.is_dirty


def test_the_choices_come_from_the_loader_enums() -> None:
    choices: dict[str, tuple[str, ...]] = {field.name: field.choices for field in SettingsDraft.FIELDS if field.choices}
    assert choices == {
        "llm_reasoning_effort": tuple(item.value for item in ReasoningEffort),
        "llm_service_tier": tuple(item.value for item in ServiceTier),
        "docs_access": tuple(item.value for item in DocAccess),
    }


# --- правки


def test_a_changed_keep_days_applies_and_makes_the_panel_dirty(ready_paths: LivecraftPaths) -> None:
    panel: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    changed: SettingsPanel = _applied(panel, keep_days=" 14 ")
    assert changed.settings.keep_days == 14
    assert changed.is_dirty
    assert panel.settings.keep_days == 30
    assert not panel.is_dirty


def test_text_in_an_integer_field_is_named_by_the_loader(ready_paths: LivecraftPaths) -> None:
    edit: PanelEdit[SettingsPanel] = _rejected(SettingsPanel.from_paths(ready_paths), min_lead_minutes="abc")
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == ("min_lead_minutes", msg.CONFIG_PROBLEM_INT_MIN.format(minimum=0))


def test_a_value_below_the_minimum_is_named_by_the_loader(ready_paths: LivecraftPaths) -> None:
    edit: PanelEdit[SettingsPanel] = _rejected(SettingsPanel.from_paths(ready_paths), llm_timeout_sec="0")
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
    edit: PanelEdit[SettingsPanel] = _rejected(SettingsPanel.from_paths(ready_paths), youtube_pause_seconds=text)
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == ("youtube_pause_seconds", msg.CONFIG_PROBLEM_NUMBER_FINITE)


@pytest.mark.parametrize("text", ["abc", "полсекунды", ""])
def test_a_pause_that_is_not_a_number_is_a_problem(ready_paths: LivecraftPaths, text: str) -> None:
    edit: PanelEdit[SettingsPanel] = _rejected(SettingsPanel.from_paths(ready_paths), youtube_pause_seconds=text)
    assert edit.problem is not None
    assert edit.problem.key == "youtube_pause_seconds"
    assert edit.problem.text == msg.CONFIG_PROBLEM_NUMBER_MIN.format(minimum=0.0)


def test_the_draft_leaves_the_finiteness_rule_to_the_loader(ready_paths: LivecraftPaths) -> None:
    """Правило конечности одно — у загрузчика: черновик отдаёт nan числом, а не текстом."""
    draft: SettingsDraft = draft_with(SettingsPanel.from_paths(ready_paths).draft, youtube_pause_seconds="nan")
    value: object = draft.to_data(_shipped())["youtube_pause_seconds"]
    assert isinstance(value, float) and math.isnan(value)


def test_an_unknown_timezone_is_a_problem(ready_paths: LivecraftPaths) -> None:
    edit: PanelEdit[SettingsPanel] = _rejected(SettingsPanel.from_paths(ready_paths), timezone="Europe/Nowhere")
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == ("timezone", msg.CONFIG_PROBLEM_TIMEZONE_UNKNOWN)


def test_spaces_around_the_timezone_are_trimmed(ready_paths: LivecraftPaths) -> None:
    changed: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), timezone=" Europe/Warsaw ")
    assert changed.settings.timezone == "Europe/Warsaw"


def test_an_unknown_reasoning_effort_is_a_problem(ready_paths: LivecraftPaths) -> None:
    edit: PanelEdit[SettingsPanel] = _rejected(SettingsPanel.from_paths(ready_paths), llm_reasoning_effort="extreme")
    assert edit.problem is not None
    assert edit.problem.key == "llm.reasoning_effort"
    assert edit.problem.text == msg.CONFIG_PROBLEM_CHOICE.format(allowed="none, low, medium, high, xhigh, max")


def test_the_flags_are_applied(ready_paths: LivecraftPaths) -> None:
    changed: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), auto_start=False, set_thumbnail=False)
    assert (changed.settings.auto_start, changed.settings.set_thumbnail) == (False, False)


# --- запись


def test_save_changes_only_the_edited_field(ready_paths: LivecraftPaths) -> None:
    before: dict[str, Any] = json.loads(ready_paths.file(FileName.CONFIG).read_text(encoding="utf-8"))
    saved: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), keep_days="14").save().panel
    after: dict[str, Any] = json.loads(ready_paths.file(FileName.CONFIG).read_text(encoding="utf-8"))
    assert after["form"] == before["form"]
    assert list(after["form"]["values"]["language"]) == list(before["form"]["values"]["language"])
    assert {key for key in before if before[key] != after[key]} == {"keep_days"}
    assert after["keep_days"] == 14
    assert saved.loaded == saved.settings
    assert not saved.is_dirty


def test_save_without_changes_writes_the_shipped_file_again(ready_paths: LivecraftPaths) -> None:
    assert SettingsPanel.from_paths(ready_paths).save().is_applied
    assert ready_paths.file(FileName.CONFIG).read_bytes() == SHIPPED_SETTINGS_FILE.read_bytes()


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
    assert not livecraft_paths.file(FileName.CONFIG).exists()
    saved: SettingsPanel = panel.save().panel
    assert SettingsFile(livecraft_paths.file(FileName.CONFIG)).load() == panel.settings
    assert saved.notices == ()


def test_a_broken_settings_file_is_named_and_replaced_only_on_save(livecraft_paths: LivecraftPaths) -> None:
    livecraft_paths.file(FileName.CONFIG).write_bytes(BROKEN_JSON)
    panel: SettingsPanel = SettingsPanel.from_paths(livecraft_paths)
    assert panel.settings == _shipped()
    assert panel.loaded is None
    assert panel.load_problem is not None
    assert len(panel.notices) == 1
    assert livecraft_paths.file(FileName.CONFIG).read_bytes() == BROKEN_JSON
    panel.save()
    config: Path = livecraft_paths.file(FileName.CONFIG)
    assert config.read_text(encoding="utf-8") == SettingsFile(config).render(panel.settings)
    assert SettingsFile(config).load() == panel.settings


def test_a_settings_file_missing_a_field_opens_on_the_template(livecraft_paths: LivecraftPaths) -> None:
    data: dict[str, Any] = json.loads(SHIPPED_SETTINGS_FILE.read_text(encoding="utf-8"))
    del data["timezone"]
    livecraft_paths.file(FileName.CONFIG).write_text(json.dumps(data), encoding="utf-8")
    panel: SettingsPanel = SettingsPanel.from_paths(livecraft_paths)
    assert panel.loaded is None
    assert panel.load_problem is not None
    assert (panel.load_problem.key, panel.load_problem.text) == ("timezone", msg.CONFIG_PROBLEM_MISSING_KEY)


# --- черновик: поля и данные файла


def test_the_draft_fields_are_the_draft_attributes() -> None:
    """Имя поля черновика — имя члена SettingKey строчными; порядок полей — порядок вкладки."""
    assert [field.name for field in SettingsDraft.FIELDS] == [field.name for field in dataclasses.fields(SettingsDraft)]
    for field in SettingsDraft.FIELDS:
        assert SettingKey(field.key_path).name.lower() == field.name
        assert field.key_path in msg.SETUP_SETTINGS_FIELD_LABELS


def test_the_draft_data_puts_every_field_at_its_key_and_keeps_the_rest(ready_paths: LivecraftPaths) -> None:
    """Данные черновика — данные настроек, где каждое поле вкладки стоит на месте своего ключа."""
    settings: LivecraftSettings = _shipped()
    draft: SettingsDraft = draft_with(SettingsDraft.of(settings), keep_days="7", llm_model=" gpt-x ")
    data: dict[str, object] = draft.to_data(settings)
    expected: dict[str, Any] = settings.to_data()
    expected["keep_days"] = 7
    expected["llm"]["model"] = "gpt-x"
    assert data == expected
    assert list(data) == list(expected)


# --- вкладка пишет только свои поля поверх свежего файла (§13 задача 4.1)


def test_saving_does_not_roll_back_the_telegram_section_saved_by_the_telegram_tab(ready_paths: LivecraftPaths) -> None:
    """Вкладка открыта до того, как «Telegram» подключил чат: её сохранение берёт раздел telegram с диска."""
    panel: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    file: SettingsFile = SettingsFile.of(ready_paths)
    on_disk: LivecraftSettings = file.load()
    file.save(on_disk.with_telegram(TelegramSettings(ChatTarget.PRIVATE, "", "111000111", "")))
    saved: SettingsPanel = _applied(panel, keep_days="12").save().panel
    assert saved.settings.keep_days == 12
    assert saved.settings.telegram == TelegramSettings(ChatTarget.PRIVATE, "", "111000111", "")
    assert file.load() == saved.settings and not saved.is_dirty


def test_saving_does_not_roll_back_the_form_url_saved_by_the_google_tab(ready_paths: LivecraftPaths) -> None:
    """Ссылку на форму задаёт вкладка «Ключи в форму»: сохранение настроек берёт раздел form с диска."""
    panel: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    SettingLink.from_paths(ready_paths, SettingKey.FORM_URL).replace(FORM_URL).panel.save()
    saved: SettingsPanel = _applied(panel, keep_days="12").save().panel
    assert (saved.settings.keep_days, saved.settings.form.url) == (12, FORM_URL)
    assert SettingsFile.of(ready_paths).load() == saved.settings and not saved.is_dirty


def test_saving_writes_the_preview_template_on_the_drive(ready_paths: LivecraftPaths) -> None:
    """Шаблон подпапки превью на Диске — раздел настроек (§14 решение 27); саму папку хранит сейф (решение 39)."""
    panel: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    saved: SettingsPanel = _applied(panel, drive_preview_path_template="covers/{language}/{date}").save().panel
    assert saved.settings.drive.preview_path_template == "covers/{language}/{date}"
    assert SettingsFile.of(ready_paths).load() == saved.settings and not saved.is_dirty


def test_a_preview_template_on_the_drive_follows_the_folder_template_rule(ready_paths: LivecraftPaths) -> None:
    edit: PanelEdit[SettingsPanel] = _rejected(SettingsPanel.from_paths(ready_paths), drive_preview_path_template="x")
    assert edit.problem is not None and edit.problem.key == "drive.preview_path_template"
    assert edit.problem.text == msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_PLACEHOLDERS.format(absent="date, language")


def test_the_preview_template_on_the_drive_is_a_field_of_the_tab() -> None:
    assert SettingKey.DRIVE_PREVIEW_PATH_TEMPLATE in [field.key for field in SettingsDraft.FIELDS]


def test_the_form_url_is_not_a_field_of_the_tab() -> None:
    assert SettingKey.FORM_URL not in [field.key for field in SettingsDraft.FIELDS]
    assert "form.url" not in msg.SETUP_SETTINGS_FIELD_LABELS


# --- документ объявлений (раздел docs, §13 задача 4.4)


def test_the_doc_access_is_chosen_by_words_and_saved_as_its_value(ready_paths: LivecraftPaths) -> None:
    """Окно показывает доступ словами, в черновик и файл уходит вариант; контакты — текстом без краёв."""
    [field] = [field for field in SettingsDraft.FIELDS if field.key is SettingKey.DOCS_ACCESS]
    assert field.options == tuple(msg.SETUP_DOC_ACCESS_LABELS[access.value] for access in DocAccess)
    assert field.draft_value(msg.SETUP_DOC_ACCESS_LABELS["reader"]) == "reader"
    panel: SettingsPanel = _applied(SettingsPanel.from_paths(ready_paths), docs_access="private", docs_contacts=" @help ")
    panel.save()
    assert SettingsFile.of(ready_paths).load().docs == DocsSettings(access=DocAccess.PRIVATE, contacts="@help")


def test_an_unknown_doc_access_is_rejected_with_its_key(ready_paths: LivecraftPaths) -> None:
    edit: PanelEdit[SettingsPanel] = _rejected(SettingsPanel.from_paths(ready_paths), docs_access="everyone")
    assert edit.problem is not None and edit.problem.key == "docs.access"


def test_saving_does_not_roll_back_the_lines_and_the_folders(ready_paths: LivecraftPaths) -> None:
    """Линии работы и папки ролей на вкладке не правятся (§14 решение 37): её сохранение берёт их с диска."""
    panel: SettingsPanel = SettingsPanel.from_paths(ready_paths)
    set_lines(ready_paths, lines_without(RunPart.ANNOUNCE))
    set_folders(ready_paths, FolderSettings(packages="shared/packages", docs="docs", images="image"))
    saved: SettingsPanel = _applied(panel, keep_days="12").save().panel
    assert saved.settings.keep_days == 12
    assert not saved.settings.lines.is_on(RunPart.ANNOUNCE)
    assert saved.settings.folders.packages == "shared/packages"
    assert SettingsFile.of(ready_paths).load() == saved.settings and not saved.is_dirty
