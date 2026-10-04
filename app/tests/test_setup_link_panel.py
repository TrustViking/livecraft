"""Строка открытой ссылки на вкладках окна без окна: ссылка на форму ключей (CLAUDE.md §8.2 п.2, §14
решение 15). Проверка — разбором файла; запись — только своего поля поверх файла, как он на диске."""
from __future__ import annotations

import json
from typing import Any

import pytest

from app.config.files import SettingsFile
from app.config.setting_key import SettingKey
from app.config.settings import LivecraftSettings
from app.config.telegram import ChatTarget, TelegramSettings
from app.paths import FileName, LivecraftPaths
from app.setup.panels.link_panel import SettingLink
from app.setup.panels.panel_edit import PanelEdit
from app.tests.conftest import SHIPPED_SETTINGS_FILE
from app.ui import messages_ru as msg

FORM_URL: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-own-form/viewform"
SHORT_FORM_URL: str = "https://forms.gle/AbCdEf123456"


def _link(paths: LivecraftPaths) -> SettingLink:
    return SettingLink.from_paths(paths, SettingKey.FORM_URL)


def _saved(paths: LivecraftPaths, url: str) -> SettingLink:
    edit: PanelEdit[SettingLink] = _link(paths).replace(url)
    assert edit.is_applied, edit.problem
    return edit.panel.save().panel


def test_the_shipped_form_url_is_not_set(ready_paths: LivecraftPaths) -> None:
    link: SettingLink = _link(ready_paths)
    assert (link.url, link.is_set, link.is_dirty) == ("", False, False)
    assert link.status == msg.SETUP_STATUS_NOT_SET
    assert (link.label, link.hint) == (msg.SETUP_LINK_LABELS["form.url"], msg.SETUP_LINK_HINTS["form.url"])


def test_a_form_url_is_applied_with_spaces_trimmed_and_shown_as_it_is(ready_paths: LivecraftPaths) -> None:
    edit: PanelEdit[SettingLink] = _link(ready_paths).replace(f"  {FORM_URL} ")
    assert edit.is_applied
    assert edit.panel.url == FORM_URL and edit.panel.is_dirty
    assert edit.panel.status == msg.SETUP_LINK_STATUS_SET.format(url=FORM_URL)


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
    """Негодная ссылка — проблема разбора файла с путём поля; строка прежняя."""
    link: SettingLink = _link(ready_paths)
    edit: PanelEdit[SettingLink] = link.replace(text)
    assert not edit.is_applied and edit.panel is link
    assert edit.problem is not None
    assert (edit.problem.key, edit.problem.text) == ("form.url", msg.CONFIG_PROBLEM_FORM_URL)


def test_empty_input_asks_for_a_value_or_names_the_delete_button(ready_paths: LivecraftPaths) -> None:
    empty: PanelEdit[SettingLink] = _link(ready_paths).replace("   ")
    assert empty.problem is not None and empty.problem.text == msg.SETUP_INPUT_EMPTY
    saved: SettingLink = _saved(ready_paths, FORM_URL)
    over_set: PanelEdit[SettingLink] = saved.replace("")
    assert over_set.problem is not None
    assert over_set.problem.text == msg.SETUP_INPUT_EMPTY_RESET.format(button=msg.SETUP_KEYS_BUTTON_DELETE_OWN)


def test_save_writes_only_the_url_and_keeps_the_form_contract(ready_paths: LivecraftPaths) -> None:
    before: dict[str, Any] = json.loads(ready_paths.file(FileName.CONFIG).read_text(encoding="utf-8"))
    saved: SettingLink = _saved(ready_paths, FORM_URL)
    after: dict[str, Any] = json.loads(ready_paths.file(FileName.CONFIG).read_text(encoding="utf-8"))
    assert after["form"]["url"] == FORM_URL and list(after["form"])[0] == "url"
    assert {key: value for key, value in after["form"].items() if key != "url"} == {
        key: value for key, value in before["form"].items() if key != "url"
    }
    assert {key for key in before if before[key] != after[key]} == {"form"}
    assert (saved.url, saved.is_set, saved.is_dirty) == (FORM_URL, True, False)


def test_save_goes_over_the_file_as_it_is_on_disk(ready_paths: LivecraftPaths) -> None:
    """Строка открыта до того, как другие вкладки записали свои поля: её запись их не откатывает."""
    link: SettingLink = _link(ready_paths)
    file: SettingsFile = SettingsFile.of(ready_paths)
    on_disk: LivecraftSettings = file.load()
    telegram: TelegramSettings = TelegramSettings(ChatTarget.PRIVATE, "", "111000111", "")
    file.save(on_disk.with_telegram(telegram))
    link.replace(SHORT_FORM_URL).panel.save()
    saved: LivecraftSettings = file.load()
    assert (saved.form.url, saved.telegram) == (SHORT_FORM_URL, telegram)


def test_clear_makes_the_form_not_configured(ready_paths: LivecraftPaths) -> None:
    cleared: SettingLink = _saved(ready_paths, FORM_URL).clear()
    assert cleared.is_dirty and not cleared.is_set
    saved: SettingLink = cleared.save().panel
    assert not SettingsFile.of(ready_paths).load().form.is_configured
    assert saved.status == msg.SETUP_STATUS_NOT_SET
    assert ready_paths.file(FileName.CONFIG).read_bytes() == SHIPPED_SETTINGS_FILE.read_bytes()


def test_without_a_settings_file_the_link_is_not_set_and_the_first_save_writes_the_file(
    livecraft_paths: LivecraftPaths,
) -> None:
    assert not _link(livecraft_paths).is_set
    _saved(livecraft_paths, FORM_URL)
    assert SettingsFile.of(livecraft_paths).load().form.url == FORM_URL
