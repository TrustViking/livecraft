"""Окно настройщика по-настоящему: Tk создаётся и прячется (withdraw), кнопки нажимаются через invoke.

Окно без рабочего стола не создаётся — такой прогон падает с TclError, а не пропускается: настройщик
на машине оператора обязан открываться.
"""
from __future__ import annotations

import json
import logging
import tkinter as tk
from collections.abc import Iterator
from pathlib import Path
from tkinter import font, messagebox, ttk
from typing import Any

import pytest

from app.config.files import SettingsFile, ShippedSettings
from app.config.json_node import SettingProblem
from app.config.settings import LivecraftSettings, ServiceTier
from app.config.telegram import ChatTarget, TelegramSettings
from app.core.text_format import NEWLINE
from app.paths import FileName, LivecraftPaths
from app.publish.telegram_bot import TelegramBot
from app.secretsafe.field import SecretField
from app.secretsafe.store import VaultLayerState, VaultStore
from app.secretsafe.value import SecretValue
from app.run.mode import LINE_ORDER, LineStage, RunPart
from app.setup.app import DpiAwareness, SetupWindow
from app.setup.page import SetupPage
from app.setup.fields.language_choice import LanguageDirectory
from app.setup.panels.keys_panel import KeysPanel
from app.setup.readiness import Readiness
from app.setup.tabs.channels_tab import ChannelsTab
from app.setup.tabs.key_rows import SECRET_ECHO, KeyRowView
from app.setup.tabs.broadcast_choices import KeysChoiceRow
from app.setup.tabs.chat_block import ChatRowView
from app.setup.tabs.home_tab import CHOICE_PARTS, InputChoiceRow
from app.setup.tabs.line_switches import LineHeader
from app.setup.tabs.link_row import LinkRowView
from app.setup.tabs.merge_tab import MergeTab
from app.setup.tabs.plan_tab import PlanTab
from app.setup.tabs.publish_tab import PublishTab
from app.setup.tabs.settings_section import SettingsSection
from app.setup.tabs.tab_event import BREAK, KEYCODE_A, KEYCODE_C, KEYCODE_V, KEYCODE_X, EditShortcut, EditShortcuts, TkEvent
from app.setup.tabs.tab_layout import PAD
from app.setup.tabs.tab_shell import TabAction
from app.setup.tabs.tab_theme import (
    DIM_FOREGROUND, SEGMENT_STYLE, SELECTED, STATUS_SET_FOREGROUND, STATUS_UNSET_FOREGROUND, SWITCH_DIM_SHARE, SWITCH_OFF,
    SWITCH_ON, TAB_STYLE, THEME, WINDOW_BACKGROUND, RgbColor,
)
from app.setup.tabs.toggle_switch import ToggleSwitch
from app.tests.conftest import FORM_URL, REPO_CHANNELS_EXAMPLE, SHIPPED_SETTINGS_FILE, TOKEN_VALUES
from app.tests.fixtures.config import channels_of
from app.tests.fixtures.setup_window import CAPTURE_OPTION, FD_CAPTURE, FD_CAPTURE_PROBLEM, SetupWindowDriver
from app.tests.fixtures.settings import set_drive_folder, set_form_url
from app.tests.fixtures.telegram import BOT_TOKEN, FakeTelegram, connect_private_chat
from app.tests.fixtures.vault import VaultReads
from app.ui import messages_ru as msg

OWN_OPENAI_KEY: str = "sk-proj-own-Zy9xWvUtSrQpOnMlKjIhGfEdCbA9876543210"
BAD_OPENAI_KEY: str = "not-a-key"
OTHER_OPENAI_KEY: str = "sk-proj-other-Ab1cDe2fGh3iJk4lMn5oPq6rSt7uVw8xYz9012345"
OLD_FILE_LANGUAGES: tuple[str, ...] = ("ru", "en")   # channels.json до решения 21: у канала два языка
OWN_SHEET_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table"


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    """Окно на готовом корне: значения из токена на таблицу и ключ OpenAI, настройки поставки, каналы примера."""
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


@pytest.fixture
def two_languages_driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    """Окно на своём channels.json старого вида: у второго канала два языка (совместимость, §14 решение 21)."""
    data: dict[str, Any] = json.loads(ready_paths.file(FileName.CHANNELS).read_text(encoding="utf-8"))
    data["channels"][1]["languages"] = list(OLD_FILE_LANGUAGES)
    ready_paths.file(FileName.CHANNELS).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


@pytest.fixture
def bare_driver(livecraft_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    """Окно на чистой установке: ни сейфа, ни конфигов."""
    yield from SetupWindowDriver.opened(livecraft_paths, pytestconfig)


def _secret_values(panel: KeysPanel) -> set[str]:
    """Эталон теста: значения сейфа раскрывает тест, а не окно."""
    values: set[str] = set()
    for vault in (panel.token, panel.own, panel.vault):
        values.update(secret.reveal() for secret in vault.secrets())
    return values


def _row(driver: SetupWindowDriver, field: SecretField) -> KeyRowView:
    return driver.key_view(field)


def _status(view: KeyRowView) -> str:
    return str(view.status.cget("text"))


def _own_status(field: SecretField, value: str) -> str:
    """Статус своего значения: короткая маска, без названия поля (значение маскирует тест, а не окно)."""
    return msg.SETUP_KEY_STATUS_OWN.format(mask=SecretValue(field=field, value=value).short_mask)


def _supplied_status(field: SecretField) -> str:
    return msg.SETUP_KEY_STATUS_TOKEN.format(mask=SecretValue(field=field, value=TOKEN_VALUES[field]).short_mask)


# --- поля сейфа: «Таблица плана», «Нейросеть»; открытые ссылки: «Форма», «Превью», «Google-документ»

KEY_FIELDS: tuple[SecretField, ...] = (SecretField.OPENAI_API_KEY, SecretField.SHEETS_ID)


def _hidden_and_open_entries(driver: SetupWindowDriver, frame: ttk.Frame) -> list[tk.Misc]:
    """Поля ввода вкладки, которые показывают набранное (не скрытые точками)."""
    entries: list[tk.Misc] = [entry for entry in driver.widgets(frame) if isinstance(entry, ttk.Entry)]
    return [entry for entry in entries if not isinstance(entry, ttk.Combobox) and entry.cget("show") != SECRET_ECHO]


def test_the_key_rows_are_hidden_and_the_links_are_open(driver: SetupWindowDriver) -> None:
    """Таблица — на «Таблице плана», ключ OpenAI — на «Нейросети», токен бота — на «Telegram», папка Google Диска — на
    «Превью» и «Google-документе»: скрытый ввод; ссылка на форму — открытая строка (§14 решения 15, 37, 39)."""
    assert tuple(driver.tabs.plan.rows) == (SecretField.SHEETS_ID,)
    assert tuple(driver.tabs.merge.rows) == (SecretField.OPENAI_API_KEY,)
    assert tuple(driver.telegram.rows) == (SecretField.TELEGRAM_BOT_TOKEN,)
    for field in (*KEY_FIELDS, SecretField.TELEGRAM_BOT_TOKEN):
        assert _row(driver, field).entry.cget("show") == SECRET_ECHO
    form: LinkRowView = driver.tabs.form.form_link
    assert form.entry.cget("show") == "" and str(form.entry.cget("width")) == "64"
    assert _hidden_and_open_entries(driver, driver.tabs.form.frame) == [form.entry]
    assert _hidden_and_open_entries(driver, driver.tabs.plan.frame) == []
    for tab in (driver.tabs.previews, driver.tabs.doc):
        assert tab.folder.row.entry.cget("show") == SECRET_ECHO
        assert tab.folder.row.entry not in _hidden_and_open_entries(driver, tab.frame)


def test_every_row_has_its_label_hint_and_coloured_status(driver: SetupWindowDriver) -> None:
    """Подпись, серая подсказка «где взять», статус: пришло с программой — зелёный, не задано — красный."""
    texts: list[str] = driver.visible_texts()
    for field in KEY_FIELDS:
        view: KeyRowView = _row(driver, field)
        assert msg.SETUP_KEY_FIELD_LABELS[field.value] in texts and msg.SETUP_KEY_FIELD_HINTS[field.value] in texts
        assert _status(view) == _supplied_status(field)
        assert str(view.status.cget("foreground")) == STATUS_SET_FOREGROUND
    link: LinkRowView = driver.tabs.form.form_link
    assert str(link.block.status.cget("text")) == msg.SETUP_STATUS_NOT_SET
    assert str(link.block.status.cget("foreground")) == STATUS_UNSET_FOREGROUND
    assert msg.SETUP_LINK_LABELS["form.url"] in texts and msg.SETUP_LINK_HINTS["form.url"] in texts


def test_the_window_shows_no_vault_value(driver: SetupWindowDriver) -> None:
    """Обход всех виджетов окна: ни одного значения сейфа — только маски (§7.4)."""
    panels: tuple[KeysPanel, ...] = (driver.tabs.plan.keys.panel, driver.tabs.merge.keys.panel)
    values: set[str] = _secret_values(panels[0]) | _secret_values(panels[1])
    assert len(values) == len(TOKEN_VALUES)      # в поставке — обязательные поля и старый диапазон, токена бота нет
    texts: list[str] = driver.visible_texts()
    for row in (*panels[0].rows, *panels[1].rows):
        assert row.status in texts                   # маска на месте…
    for value in values:
        assert not any(value in text for text in texts)   # …а значения нет нигде


def test_the_window_shows_no_value_after_an_own_key_is_accepted(driver: SetupWindowDriver) -> None:
    driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert not any(OWN_OPENAI_KEY in text for text in driver.visible_texts())


def test_a_good_own_key_becomes_own_and_clears_the_input(driver: SetupWindowDriver) -> None:
    tab: MergeTab = driver.tabs.merge
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert _status(view) == _own_status(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert view.entry.get() == ""
    assert not tab.is_dirty                    # «Сохранить значение» записало сейф сразу
    assert not driver.window.is_dirty


def test_a_bad_own_key_shows_the_problem_and_keeps_the_input(driver: SetupWindowDriver) -> None:
    """Отказ модели: причина под полем, введённое остаётся — и оно несохранённое вкладки, а модель не менялась."""
    tab: MergeTab = driver.tabs.merge
    problem: SettingProblem | None = tab.keys.panel.replace(SecretField.OPENAI_API_KEY, BAD_OPENAI_KEY).problem
    assert problem is not None
    expected: str = problem.text
    view: KeyRowView = _row(driver, SecretField.OPENAI_API_KEY)
    driver.type(view.entry, BAD_OPENAI_KEY)
    view.accept_button.invoke()
    assert view.problem.text == expected
    assert view.entry.get() == BAD_OPENAI_KEY
    assert _status(view) == _supplied_status(SecretField.OPENAI_API_KEY)
    assert not tab.keys.panel.is_dirty
    assert tab.is_dirty


def _own_on_disk(paths: LivecraftPaths, field: SecretField) -> str | None:
    """Своё значение поля так, как его прочитает следующий запуск; значение раскрывает тест, а не окно."""
    secret: SecretValue | None = VaultStore.open(paths).load().own.get(field)
    return None if secret is None else secret.reveal()


def test_accepting_a_value_writes_the_own_vault_at_once(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    tab: MergeTab = driver.tabs.merge
    assert not ready_paths.file(FileName.VAULT_LOCAL).exists()
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert ready_paths.file(FileName.VAULT_LOCAL).is_file()
    assert _own_on_disk(ready_paths, SecretField.OPENAI_API_KEY) == OWN_OPENAI_KEY
    assert not tab.is_dirty
    assert view.reset_button.winfo_manager() == "pack"        # своё значение можно сбросить к поставке


def test_a_second_value_changes_the_file_again(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    before: bytes = ready_paths.file(FileName.VAULT_LOCAL).read_bytes()
    driver.accept_key(SecretField.SHEETS_ID, OWN_SHEET_ID)
    assert ready_paths.file(FileName.VAULT_LOCAL).read_bytes() != before
    assert _own_on_disk(ready_paths, SecretField.SHEETS_ID) == OWN_SHEET_ID
    assert _own_on_disk(ready_paths, SecretField.OPENAI_API_KEY) == OWN_OPENAI_KEY


def test_the_plan_tab_has_no_common_save_button(driver: SetupWindowDriver) -> None:
    """У строки сейфа — своя «Сохранить», общей кнопки на вкладке нет."""
    tab: PlanTab = driver.tabs.plan
    assert not hasattr(tab, "buttons")
    buttons: list[str] = [str(widget.cget("text")) for widget in driver.widgets(tab.frame) if isinstance(widget, ttk.Button)]
    assert buttons.count(msg.SETUP_BUTTON_SAVE) == len(tab.rows)


def test_deleting_the_own_value_is_written_at_once(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    view.reset_button.invoke()
    assert _own_on_disk(ready_paths, SecretField.OPENAI_API_KEY) is None
    assert _status(view) == _supplied_status(SecretField.OPENAI_API_KEY)
    assert not driver.tabs.merge.is_dirty


def test_a_failed_write_keeps_the_input_and_leaves_the_model_unchanged(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Запись не удалась: диалог, модель на прочитанном с диска, введённое — в поле для повтора (несохранённое)."""
    shown: list[str] = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **_options: shown.append(message))

    def _refuse(self: VaultStore, own: object) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(VaultStore, "save_local", _refuse)
    view: KeyRowView = _row(driver, SecretField.OPENAI_API_KEY)
    driver.type(view.entry, OWN_OPENAI_KEY)
    view.accept_button.invoke()
    assert shown == [msg.SETUP_KEYS_SAVE_FAILED_OS]
    assert view.entry.get() == OWN_OPENAI_KEY
    assert _status(view) == _supplied_status(SecretField.OPENAI_API_KEY)
    assert not driver.tabs.merge.keys.panel.is_dirty
    assert driver.tabs.merge.is_dirty
    assert not ready_paths.file(FileName.VAULT_LOCAL).exists()


# --- «Эфиры YouTube»: каналы


def test_a_channel_added_through_the_form_appears_in_the_table(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    assert len(tab.tree.get_children()) == 2
    driver.fill_channel(
        handle="kanal_hu", google_account="owner@gmail.com", languages="hu", privacy="для всех",
    )
    driver.press_button(tab, TabAction.ADD)
    assert tab.edit_problem.text == ""
    children: tuple[str, ...] = tab.tree.get_children()
    assert len(children) == 3
    assert tab.tree.item(children[-1], "values")[0] == "@kanal_hu"
    assert tab.is_dirty
    assert not tab.variables.has_typed                  # набранное модель приняла


def test_a_channel_without_languages_shows_the_problem_with_the_field_label(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    driver.fill_channel(handle="@kanal_hu", google_account="owner@gmail.com")
    assert tab.language.picker.codes == ()
    driver.press_button(tab, TabAction.ADD)
    assert tab.edit_problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_CHANNEL_FIELD_LABELS["languages"], text=msg.CONFIG_PROBLEM_LANGUAGES
    )
    assert len(tab.tree.get_children()) == 2


def test_selecting_a_row_fills_the_form(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    tab.tree.selection_set("0")
    tab.fill_from_selection()
    assert tab.form_draft == tab.panel.drafts[0]
    assert not tab.is_dirty                              # показанное из модели — не набранное


def test_update_without_a_selection_says_so(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    driver.press_button(tab, TabAction.UPDATE)
    assert tab.edit_problem.text == msg.SETUP_CHANNELS_NOTHING_SELECTED


def test_saving_the_channels_writes_channels_json(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    tab: ChannelsTab = driver.channels
    driver.fill_channel(handle="@kanal_hu", google_account="owner@gmail.com", languages="hu")
    driver.press_button(tab, TabAction.ADD)
    driver.press_button(tab, TabAction.SAVE)
    assert channels_of(ready_paths.file(FileName.CHANNELS)) == tab.panel.channels
    assert len(tab.panel.channels) == 3
    assert ready_paths.file(FileName.CHANNELS_PREVIOUS).read_bytes() == REPO_CHANNELS_EXAMPLE.read_bytes()
    assert not tab.is_dirty


def test_removing_every_channel_shows_the_list_problem(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    for _ in range(2):
        tab.tree.selection_set("0")
        driver.press_button(tab, TabAction.REMOVE)
    assert tab.tree.get_children() == ()
    assert tab.list_problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_CHANNEL_FIELD_LABELS["channels"], text=msg.CONFIG_PROBLEM_CHANNELS_EMPTY
    )


# --- настройки livecraft.json на вкладках линий и «Дополнительно»


def _settings_entry(driver: SetupWindowDriver, name: str) -> ttk.Entry:
    entry: tk.Widget = driver.settings_input(name)
    assert isinstance(entry, ttk.Entry)
    return entry


def test_a_changed_keep_days_is_saved(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    section: SettingsSection = driver.tabs.advanced.section
    driver.type(_settings_entry(driver, "keep_days"), "14")
    assert driver.window.is_dirty
    section.save_button.invoke()
    assert SettingsFile(ready_paths.file(FileName.CONFIG)).load().keep_days == 14
    assert section.problem.text == ""
    assert not driver.window.is_dirty


def test_text_in_an_integer_field_shows_the_problem_and_keeps_the_file(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    """Запас до старта — на «Эфирах YouTube»: негодное число — строка проблемы раздела, файл прежний."""
    section: SettingsSection = driver.section_of("min_lead_minutes")
    assert section is driver.channels.settings
    driver.type(_settings_entry(driver, "min_lead_minutes"), "abc")
    section.save_button.invoke()
    assert section.problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_SETTINGS_FIELD_LABELS["min_lead_minutes"], text=msg.CONFIG_PROBLEM_INT_MIN.format(minimum=0)
    )
    assert ready_paths.file(FileName.CONFIG).read_bytes() == SHIPPED_SETTINGS_FILE.read_bytes()
    assert driver.window.is_dirty


def test_saving_a_section_keeps_what_another_section_typed(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    """Раздел пишет только свои поля: набранное в другом разделе не записывается и остаётся несохранённым."""
    driver.type(_settings_entry(driver, "category_id"), "24")
    driver.type(_settings_entry(driver, "keep_days"), "9")
    driver.tabs.advanced.section.save_button.invoke()
    saved: LivecraftSettings = SettingsFile.of(ready_paths).load()
    assert (saved.keep_days, saved.category_id) == (9, ShippedSettings().settings.category_id)
    assert _settings_entry(driver, "category_id").get() == "24" and driver.window.is_dirty
    driver.channels.settings.save_button.invoke()
    saved = SettingsFile.of(ready_paths).load()
    assert (saved.keep_days, saved.category_id) == (9, "24") and not driver.window.is_dirty


@pytest.mark.parametrize(
    ("name", "section"),
    [
        ("llm_model", "merge"), ("image_dir_template", "previews"), ("drive_preview_path_template", "previews"),
        ("docs_access", "doc"), ("category_id", "broadcasts"), ("auto_start", "broadcasts"), ("timezone", "advanced"),
    ],
)
def test_every_setting_is_on_the_tab_of_its_line(driver: SetupWindowDriver, name: str, section: str) -> None:
    tab_frame: ttk.Frame = getattr(driver.tabs, section).frame
    assert driver.settings_input(name) in list(driver.widgets(tab_frame))


def test_the_form_link_saves_at_once_and_is_shown_as_it_is(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    """Ссылка на форму — не секрет (§14 решение 15): обычное поле; «Сохранить» пишет form.url сразу."""
    link: LinkRowView = driver.tabs.form.form_link
    assert link.clear_button.winfo_manager() == ""                     # нечего удалять
    driver.type(link.entry, " https://forms.gle/AbCdEf123456 ")
    assert driver.window.is_dirty
    link.save_button.invoke()
    assert link.block.problem.text == "" and link.entry.get() == "" and not driver.window.is_dirty
    assert SettingsFile(ready_paths.file(FileName.CONFIG)).load().form.url == "https://forms.gle/AbCdEf123456"
    assert str(link.block.status.cget("text")) == msg.SETUP_LINK_STATUS_SET.format(url="https://forms.gle/AbCdEf123456")
    assert str(link.block.status.cget("foreground")) == STATUS_SET_FOREGROUND
    link.clear_button.invoke()
    assert not SettingsFile(ready_paths.file(FileName.CONFIG)).load().form.is_configured
    assert str(link.block.status.cget("text")) == msg.SETUP_STATUS_NOT_SET


def test_a_bad_form_link_shows_the_problem_and_keeps_the_file(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    link: LinkRowView = driver.tabs.form.form_link
    driver.type(link.entry, "http://forms.gle/AbCdEf123456")
    link.save_button.invoke()
    assert link.block.problem.text == msg.CONFIG_PROBLEM_FORM_URL
    assert ready_paths.file(FileName.CONFIG).read_bytes() == SHIPPED_SETTINGS_FILE.read_bytes()
    assert link.entry.get() == "http://forms.gle/AbCdEf123456" and driver.window.is_dirty


def test_the_advanced_tab_has_only_the_time_zone_and_the_keep_days(driver: SetupWindowDriver) -> None:
    assert tuple(driver.tabs.advanced.section.inputs) == ("timezone", "keep_days")
    texts: list[str] = driver.visible_texts()
    assert msg.SETUP_ADVANCED_INTRO in texts


def test_the_settings_widgets_follow_the_value_types(driver: SetupWindowDriver) -> None:
    """«Да / нет» — ползунок, варианты — выбор из списка; флажков в окне нет."""
    assert isinstance(driver.settings_input("auto_start"), ToggleSwitch)
    assert isinstance(driver.settings_input("set_thumbnail"), ToggleSwitch)
    effort: tk.Widget = driver.settings_input("llm_reasoning_effort")
    assert isinstance(effort, ttk.Combobox) and str(effort.cget("state")) == "readonly"
    service_tier: tk.Widget = driver.settings_input("llm_service_tier")
    assert tuple(service_tier.cget("values")) == tuple(tier.value for tier in ServiceTier)
    assert not any(isinstance(widget, ttk.Checkbutton) for widget in driver.widgets())


def test_a_switch_of_a_setting_saves_as_a_flag(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    switch: tk.Widget = driver.settings_input("auto_start")
    assert isinstance(switch, ToggleSwitch)
    before: bool = SettingsFile.of(ready_paths).load().auto_start
    switch.flip()
    assert driver.window.is_dirty
    driver.channels.settings.save_button.invoke()
    assert SettingsFile.of(ready_paths).load().auto_start is not before


# --- строка готовности и закрытие


def _configure_every_line(paths: LivecraftPaths) -> None:
    """Форма, папка Диска, бот и чат — всё, чего на готовом корне не хватает работающим линиям."""
    connect_private_chat(paths)
    set_form_url(paths, FORM_URL)
    set_drive_folder(paths)


def test_the_readiness_line_says_ready_when_every_working_line_is(
    ready_paths: LivecraftPaths, pytestconfig: pytest.Config
) -> None:
    _configure_every_line(ready_paths)
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        assert driver.window.readiness_line.cget("text") == msg.SETUP_READY


def test_the_readiness_line_names_what_the_working_lines_lack(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    """Те же строки нужд, что у запуска (§13 задача 7.1): на готовом корне нет формы, папки Диска и бота."""
    readiness: Readiness = Readiness.check(ready_paths)
    assert driver.window.readiness_line.cget("text") == readiness.window_line == NEWLINE.join(readiness.for_run().lines)


def test_the_readiness_line_on_a_clean_root_lists_the_problems(
    bare_driver: SetupWindowDriver, livecraft_paths: LivecraftPaths
) -> None:
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert not readiness.is_ready
    assert bare_driver.window.readiness_line.cget("text") == readiness.window_line


def test_saving_refreshes_the_readiness_line(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> None:
    """Каналов нет — не готово; канал добавлен и сохранён — строка готовности обновилась сама."""
    _configure_every_line(ready_paths)
    ready_paths.file(FileName.CHANNELS).unlink()
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        window: SetupWindow = driver.window
        assert window.readiness_line.cget("text") != msg.SETUP_READY
        tab: ChannelsTab = driver.channels
        driver.fill_channel(handle="@kanal_hu", google_account="owner@gmail.com", languages="hu")
        driver.press_button(tab, TabAction.ADD)
        driver.press_button(tab, TabAction.SAVE)
        assert window.readiness_line.cget("text") == msg.SETUP_READY


# --- сейф окна: один раз и заново — после своей записи (замирание окна до 4 с, лог 30-09-2026_200119)


def test_opening_and_refreshing_read_the_vault_once(
    ready_paths: LivecraftPaths, pytestconfig: pytest.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Прежде — 13 чтений при открытии и 5 на каждую проверку окна в главном потоке; строгое чтение прошло — мягкое
    берёт его итог."""
    reads: VaultReads = VaultReads.counted(monkeypatch)
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        for _ in range(3):
            driver.window.refresh()
        assert reads.both == (1, 0)


def test_after_an_own_value_is_saved_the_window_reads_the_vault_again(
    ready_paths: LivecraftPaths, pytestconfig: pytest.Config, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Запись окна сбрасывает прочитанное: следующая проверка окна читает сейф и видит новое своё значение."""
    reads: VaultReads = VaultReads.counted(monkeypatch)
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        assert SecretField.OPENAI_API_KEY.human_label not in driver.tokens.contents.cget("text")
        driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)      # запись и проверка окна после неё
        driver.window.refresh()
        assert reads.both == (2, 0)
        assert SecretField.OPENAI_API_KEY.human_label in driver.tokens.contents.cget("text")


def _answer(monkeypatch: pytest.MonkeyPatch, answer: bool) -> list[str]:
    asked: list[str] = []

    def _askyesno(title: str, message: str, **_options: object) -> bool:
        asked.append(message)
        return answer

    monkeypatch.setattr(messagebox, "askyesno", _askyesno)
    return asked


def _make_dirty(driver: SetupWindowDriver) -> None:
    driver.type(_settings_entry(driver, "keep_days"), "7")
    assert driver.window.is_dirty


def test_closing_a_dirty_window_asks_and_no_keeps_it_open(
    driver: SetupWindowDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = _answer(monkeypatch, False)
    _make_dirty(driver)
    driver.window.request_close()
    assert asked == [msg.SETUP_CLOSE_DIRTY_TEXT]
    assert not driver.window.is_closed
    assert driver.window.root.winfo_exists()


def test_closing_a_dirty_window_asks_and_yes_closes_it(driver: SetupWindowDriver, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = _answer(monkeypatch, True)
    _make_dirty(driver)
    driver.window.request_close()
    assert asked == [msg.SETUP_CLOSE_DIRTY_TEXT]
    assert driver.window.is_closed


def test_closing_a_clean_window_does_not_ask(driver: SetupWindowDriver, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = _answer(monkeypatch, True)
    driver.window.request_close()
    assert asked == []
    assert driver.window.is_closed


def test_closing_after_an_accepted_key_does_not_ask(driver: SetupWindowDriver, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = _answer(monkeypatch, True)
    driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    driver.window.request_close()
    assert asked == []
    assert driver.window.is_closed


def test_a_typed_but_not_added_channel_handle_asks_before_closing(
    driver: SetupWindowDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ник канала набран, но не добавлен: окно спрашивает; «нет» — окно открыто и набранное на месте."""
    asked: list[str] = _answer(monkeypatch, False)
    handle: ttk.Widget = driver.channels.inputs["handle"]
    driver.type(handle, "@kanal_new")
    assert not driver.channels.panel.is_dirty
    driver.window.request_close()
    assert asked == [msg.SETUP_CLOSE_DIRTY_TEXT]
    assert not driver.window.is_closed
    assert handle.get() == "@kanal_new"


def test_a_typed_but_not_saved_key_asks_before_closing(driver: SetupWindowDriver, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = _answer(monkeypatch, False)
    driver.type(_row(driver, SecretField.OPENAI_API_KEY).entry, OWN_OPENAI_KEY)
    driver.window.request_close()
    assert asked == [msg.SETUP_CLOSE_DIRTY_TEXT]
    assert not driver.window.is_closed


def test_a_typed_language_search_asks_before_closing(driver: SetupWindowDriver, monkeypatch: pytest.MonkeyPatch) -> None:
    """Строка поиска в поле языка — набранное, но не выбранное."""
    asked: list[str] = _answer(monkeypatch, False)
    driver.language.box.set("нем")
    driver.window.request_close()
    assert asked == [msg.SETUP_CLOSE_DIRTY_TEXT]


def test_the_close_button_of_the_window_goes_through_the_question(driver: SetupWindowDriver) -> None:
    assert str(driver.window.root.protocol("WM_DELETE_WINDOW")).endswith("request_close")


def test_a_broken_own_vault_file_opens_the_keys_tab_for_replacement(
    ready_paths: LivecraftPaths, pytestconfig: pytest.Config
) -> None:
    """Свой файл ключей повреждён: вкладка открыта со строками и говорит, что сохранение его заменит (D9)."""
    ready_paths.file(FileName.VAULT_LOCAL).write_bytes(b"\xff\xfe\x00vault\x80\x81")
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        tab: PlanTab = driver.tabs.plan
        assert tab.keys.panel.local_state is VaultLayerState.BROKEN
        assert msg.SETUP_KEYS_NOTICE_LOCAL_BROKEN in tab.shell.notice.cget("text")
        assert tab.keys.frame.winfo_manager() != ""         # строки с кнопками записи есть
        assert tuple(tab.rows) == (SecretField.SHEETS_ID,)
        assert not tab.is_dirty


def test_a_broken_token_vault_file_asks_to_load_the_token_again(
    ready_paths: LivecraftPaths, pytestconfig: pytest.Config
) -> None:
    """Файл значений из токена повреждён: окно открывается, вкладка просит загрузить токен заново, своё вписать можно."""
    ready_paths.file(FileName.VAULT_TOKEN).write_bytes(b"\xff\xfe\x00vault\x80\x81")
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        tab: PlanTab = driver.tabs.plan
        assert msg.SETUP_KEYS_NOTICE_TOKEN_UNREADABLE in tab.shell.notice.cget("text")
        assert tuple(tab.rows) == (SecretField.SHEETS_ID,)
        assert tab.keys.frame.winfo_manager() != ""         # строки с кнопками записи есть
        assert not tab.is_dirty


# --- «показать своё» (§14 решение 11)


def _revealed_key(driver: SetupWindowDriver) -> KeyRowView:
    """Своё значение ключа OpenAI принято и показано по кнопке."""
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    view.reveal_button.invoke()
    assert view.is_revealed
    assert _status(view) == REVEALED_STATUS
    return view


REVEALED_STATUS: str = msg.SETUP_KEY_STATUS_OWN.format(mask=OWN_OPENAI_KEY)


def _own_mask() -> str:
    return _own_status(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)


def _assert_masked(view: KeyRowView, status: str) -> None:
    assert not view.is_revealed
    assert _status(view) == status
    assert view.reveal_button.cget("text") == msg.SETUP_KEYS_BUTTON_REVEAL


def test_supplied_fields_have_no_reveal_button(driver: SetupWindowDriver) -> None:
    driver.window.root.update_idletasks()
    for view in (*driver.tabs.plan.rows.values(), *driver.tabs.merge.rows.values(), *driver.telegram.rows.values()):
        assert view.reveal_button.winfo_manager() == ""
        assert not view.reveal_button.winfo_ismapped()


def test_the_reveal_button_of_a_supplied_field_reveals_nothing(driver: SetupWindowDriver) -> None:
    """Даже вызванная в обход окна, кнопка поставочного поля ничего не показывает."""
    view: KeyRowView = _row(driver, SecretField.OPENAI_API_KEY)
    status: str = _status(view)
    view.reveal_button.invoke()
    _assert_masked(view, status)


def test_an_own_field_gets_the_button_and_toggles_value_and_mask(driver: SetupWindowDriver) -> None:
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert view.reveal_button.winfo_manager() == "pack"
    _assert_masked(view, _own_mask())
    view.reveal_button.invoke()
    assert _status(view) == REVEALED_STATUS
    assert view.reveal_button.cget("text") == msg.SETUP_KEYS_BUTTON_HIDE
    view.reveal_button.invoke()
    _assert_masked(view, _own_mask())
    for other in tuple(SecretField):
        if other is not SecretField.OPENAI_API_KEY:
            assert _row(driver, other).reveal_button.winfo_manager() == ""


def test_accepting_a_new_value_hides_the_shown_one(driver: SetupWindowDriver) -> None:
    view: KeyRowView = _revealed_key(driver)
    driver.accept_key(SecretField.OPENAI_API_KEY, OTHER_OPENAI_KEY)
    _assert_masked(view, _own_status(SecretField.OPENAI_API_KEY, OTHER_OPENAI_KEY))


def test_a_refused_input_hides_the_value(driver: SetupWindowDriver) -> None:
    view: KeyRowView = _revealed_key(driver)
    driver.type(view.entry, BAD_OPENAI_KEY)
    view.accept_button.invoke()
    assert view.problem.text != ""
    _assert_masked(view, _own_mask())


def test_reset_hides_the_value(driver: SetupWindowDriver) -> None:
    view: KeyRowView = _revealed_key(driver)
    supplied: SecretValue | None = driver.tabs.merge.keys.panel.token.get(SecretField.OPENAI_API_KEY)
    assert supplied is not None
    view.reset_button.invoke()
    _assert_masked(view, _supplied_status(SecretField.OPENAI_API_KEY))
    assert view.reveal_button.winfo_manager() == ""


def test_the_written_own_value_keeps_its_reveal_button(driver: SetupWindowDriver) -> None:
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    _assert_masked(view, _own_mask())
    assert view.reveal_button.winfo_manager() == "pack"      # после записи поле по-прежнему своё


def test_leaving_the_keys_tab_hides_the_value(driver: SetupWindowDriver) -> None:
    view: KeyRowView = _revealed_key(driver)
    window: SetupWindow = driver.window
    window.notebook.select(driver.channels.frame)
    window.notebook.event_generate(TkEvent.TAB_CHANGED)
    window.root.update()
    _assert_masked(view, _own_mask())


def test_the_revealed_value_goes_only_to_its_own_label(
    driver: SetupWindowDriver, caplog: pytest.LogCaptureFixture
) -> None:
    """Показанное значение — только в подписи своей строки: не в полях ввода, не в строке готовности, не в логе."""
    with caplog.at_level(logging.DEBUG):
        view: KeyRowView = _revealed_key(driver)
    holders: list[tk.Misc] = []
    for widget in driver.widgets():
        if isinstance(widget, (ttk.Entry, tk.Entry)):     # ttk.Combobox — тоже Entry
            assert OWN_OPENAI_KEY not in widget.get()
        elif isinstance(widget, (ttk.Label, ttk.Button, ttk.Radiobutton)) and OWN_OPENAI_KEY in str(
            widget.cget("text")
        ):
            holders.append(widget)
    assert holders == [view.status]
    assert OWN_OPENAI_KEY not in driver.window.readiness_line.cget("text")
    assert OWN_OPENAI_KEY not in driver.window.root.title()
    assert not any(OWN_OPENAI_KEY in record.getMessage() for record in caplog.records)


# --- понятность окна (смотр окна 23-09-2026)

STORAGE_WORDS: tuple[str, ...] = ("vault", "DPAPI", "secrets", "внутри программы")


def _state_value(window: SetupWindow, option: str, state: str) -> object | None:
    """Значение опции вкладки для состояния из map стиля; нет такого состояния — None."""
    for *states, value in window.theme.style.map(TAB_STYLE, option):
        if state in states:
            return value
    return None


def test_the_tabs_have_inner_padding(driver: SetupWindowDriver) -> None:
    padding: object = driver.window.theme.style.lookup(TAB_STYLE, "padding")
    assert padding not in ("", None, ())
    assert _state_value(driver.window, "padding", SELECTED) not in ("", None, ())


def test_the_selected_tab_is_bold_and_on_another_background(driver: SetupWindowDriver) -> None:
    window: SetupWindow = driver.window
    assert window.theme.style.theme_use() == THEME          # тема Windows по умолчанию фон вкладки не берёт
    selected_font: object = _state_value(window, "font", SELECTED)
    assert selected_font is not None
    assert font.Font(root=window.root, font=selected_font).actual("weight") == font.BOLD
    normal_font: str = str(window.theme.style.lookup(TAB_STYLE, "font"))
    assert font.Font(root=window.root, font=normal_font).actual("weight") == font.NORMAL
    selected_background: object = _state_value(window, "background", SELECTED)
    other_background: object = _state_value(window, "background", "!" + SELECTED)
    assert selected_background is not None and other_background is not None
    assert selected_background != other_background


def test_the_window_opens_with_the_program_icon(driver: SetupWindowDriver) -> None:
    """Иконка Livecraft ставится в конструкторе окна (§14 решение 53): файла нет или он не .ico — TclError, и окно
    настройки не открылось бы."""
    assert driver.window.root.winfo_exists()


def test_a_disabled_segment_button_is_dimmed_like_a_disabled_switch(driver: SetupWindowDriver) -> None:
    """Выбранная кнопка недоступного выбора («все» при выключенных ключах) — не ярко-зелёная, а смешанная с фоном
    окна наполовину, как недоступный ползунок."""
    style: ttk.Style = driver.window.theme.style
    states: dict[tuple[str, ...], str] = {
        tuple(spec): str(value) for *spec, value in style.map(SEGMENT_STYLE, "background")
    }
    window: RgbColor = RgbColor.of(WINDOW_BACKGROUND)
    assert states[("disabled", "selected")] == RgbColor.of(SWITCH_ON).mixed(window, SWITCH_DIM_SHARE).text
    assert states[("disabled", "!selected")] == RgbColor.of(SWITCH_OFF).mixed(window, SWITCH_DIM_SHARE).text
    assert states[("disabled", "selected")] != SWITCH_ON
    assert states[("selected",)] == SWITCH_ON


def test_there_is_a_gap_between_the_tabs(driver: SetupWindowDriver) -> None:
    """Между соседними вкладками — полоса, которая не принадлежит ни одной вкладке."""
    window: SetupWindow = driver.window
    window.root.deiconify()
    window.root.update()
    try:
        row: list[str] = [window.notebook.identify(x, 10) for x in range(window.notebook.winfo_width())]
    finally:
        window.root.withdraw()
    tabs: list[int] = [x for x, element in enumerate(row) if element == "tab"]
    assert tabs
    tab_parts: tuple[str, ...] = ("tab", "padding", "focus", "label")
    gaps: list[str] = [element for element in row[tabs[0]:tabs[-1]] if element not in tab_parts]
    assert gaps                                       # внутри ряда вкладок есть промежуток


def test_the_tabs_follow_the_stages_and_the_window_opens_on_home(driver: SetupWindowDriver) -> None:
    """«Главная», вкладки в порядке этапов (вход, обработка, вывод, эфиры), «Токены», «Логи» и «Дополнительно» (§14
    решения 20, 37, 48)."""
    window: SetupWindow = driver.window
    titles: list[str] = [str(window.notebook.tab(index, "text")) for index in range(window.notebook.index(tk.END))]
    assert titles == [
        "Главная", "Таблица плана", "Пакет", "Нейросеть", "Превью", "Google-документ", "Telegram", "Эфиры YouTube",
        "Форма", "Токены", "Логи", "Дополнительно",
    ]
    assert titles == [tab.page.title for tab in driver.tabs.all]
    assert [tab.page for tab in driver.tabs.all] == list(SetupPage)
    assert driver.selected_page is SetupPage.HOME


@pytest.mark.parametrize("name", ["category_id", "image_dir_template"])
def test_the_settings_hint_is_shown_next_to_the_field(driver: SetupWindowDriver, name: str) -> None:
    section: SettingsSection = driver.section_of(name)
    hint: ttk.Label = section.grid.hints[name]
    assert hint.cget("text") == msg.SETUP_SETTINGS_FIELD_HINTS[name]
    assert hint.grid_info()["column"] == 2
    assert hint.grid_info()["row"] == section.inputs[name].grid_info()["row"]


def test_every_settings_hint_belongs_to_a_known_field() -> None:
    assert set(msg.SETUP_SETTINGS_FIELD_HINTS) <= set(msg.SETUP_SETTINGS_FIELD_LABELS)


def test_the_folder_hint_keeps_its_braces_literal(driver: SetupWindowDriver) -> None:
    text: str = str(driver.section_of("image_dir_template").grid.hints["image_dir_template"].cget("text"))
    assert "{date}" in text and "{language}" in text


def test_the_keys_notice_names_no_storage_details(driver: SetupWindowDriver) -> None:
    notice: str = str(driver.tabs.plan.shell.notice.cget("text"))
    assert msg.SETUP_KEYS_NOTICE_PROTECTION in notice
    assert "специалист может их достать" in notice    # оговорка §14 решения 6 — обязательна
    for word in STORAGE_WORDS:
        assert word not in notice


def test_setup_texts_name_no_storage_details() -> None:
    """Ни одна строка настройщика не говорит, как и где хранятся значения."""
    texts: dict[str, str] = {
        name: value for name, value in vars(msg).items() if name.startswith("SETUP_") and isinstance(value, str)
    }
    assert texts
    for name, text in texts.items():
        assert "DPAPI" not in text, name
        assert "vault.local" not in text, name


def test_no_vault_field_name_contains_the_supplied_values() -> None:
    """Название поля стоит в масках и сводках: в нём не может быть поставочного значения (§7.4, §7.5)."""
    for field in SecretField:
        for value in TOKEN_VALUES.values():
            assert value not in field.human_label


# --- правка полей в любой раскладке
#
# На Windows keysym события Tk вычисляет по коду клавиши и раскладке уже при разборе привязок, а ключ
# `-keysym` у `event generate` служит только для поиска кода и отвергает буквы, которых нет в текущей
# раскладке. Поэтому настоящие нажатия в тестах — по коду клавиши (в латинской раскладке их берёт штатная
# привязка Tk, в чужой — EditShortcuts: вставка в обоих случаях одна), а ветки «латинская буква» и «чужая
# раскладка» проверяются ещё и через тот же обработчик событием, где keysym задан явно.

CLIPBOARD_TEXT: str = "@Pasted.Handle"
CHANNEL_TEXT: str = "Kanal.X"


class _KeyEvent(tk.Event):  # type: ignore[type-arg]
    """Событие клавиши, собранное тестом: виджет, код клавиши и keysym любой раскладки."""

    def __init__(self, widget: tk.Misc, keycode: int, keysym: str) -> None:
        self.widget = widget
        self.keycode = keycode
        self.keysym = keysym


def _channel_entry(driver: SetupWindowDriver) -> ttk.Entry:
    entry: ttk.Widget = driver.channels.inputs["handle"]
    assert isinstance(entry, ttk.Entry)
    return entry


def _key_entry(driver: SetupWindowDriver) -> ttk.Entry:
    return _row(driver, SecretField.OPENAI_API_KEY).entry


def test_ctrl_v_pastes_into_a_channel_field_exactly_once(driver: SetupWindowDriver) -> None:
    entry: ttk.Entry = _channel_entry(driver)
    driver.type(entry, "")
    driver.put_in_clipboard(CLIPBOARD_TEXT)
    driver.focus(driver.channels.frame, entry)
    driver.press(entry, KEYCODE_V)
    assert entry.get() == CLIPBOARD_TEXT


def test_ctrl_a_selects_the_whole_field(driver: SetupWindowDriver) -> None:
    entry: ttk.Entry = _channel_entry(driver)
    driver.type(entry, CHANNEL_TEXT)
    entry.selection_clear()
    driver.focus(driver.channels.frame, entry)
    driver.press(entry, KEYCODE_A)
    assert entry.selection_present()
    assert (entry.index(tk.SEL_FIRST), entry.index(tk.SEL_LAST)) == (0, len(CHANNEL_TEXT))


def test_a_cyrillic_keysym_pastes_through_the_shortcut_once(driver: SetupWindowDriver) -> None:
    entry: ttk.Entry = _channel_entry(driver)
    driver.type(entry, "")
    driver.put_in_clipboard(CLIPBOARD_TEXT)
    answer: str | None = driver.window.edit_shortcuts.handle(_KeyEvent(entry, KEYCODE_V, "Cyrillic_em"))
    driver.window.root.update()
    assert answer == BREAK
    assert entry.get() == CLIPBOARD_TEXT


@pytest.mark.parametrize("keysym", ["v", "V"])
def test_a_latin_keysym_is_left_to_the_standard_binding(driver: SetupWindowDriver, keysym: str) -> None:
    """Латинскую букву Tk уже связал с <<Paste>>: обработчик не вмешивается, иначе вставка была бы двойной."""
    entry: ttk.Entry = _channel_entry(driver)
    driver.type(entry, "")
    driver.put_in_clipboard(CLIPBOARD_TEXT)
    assert driver.window.edit_shortcuts.handle(_KeyEvent(entry, KEYCODE_V, keysym)) is None
    driver.window.root.update()
    assert entry.get() == ""


def test_every_shortcut_letter_is_bound_by_tk_to_its_event(driver: SetupWindowDriver) -> None:
    """Предпосылка правила «латинскую букву берёт Tk»: штатная связь есть у каждой из четырёх букв."""
    shortcuts: EditShortcuts = driver.window.edit_shortcuts
    assert {shortcut.keycode for shortcut in shortcuts.shortcuts} == {KEYCODE_V, KEYCODE_A, KEYCODE_X, KEYCODE_C}
    for shortcut in shortcuts.shortcuts:
        assert f"<Control-Key-{shortcut.letter}>" in driver.window.root.event_info(shortcut.virtual_event)


def test_the_shortcuts_leave_non_input_widgets_alone(driver: SetupWindowDriver) -> None:
    button: ttk.Button = driver.tabs.advanced.section.save_button
    assert driver.window.edit_shortcuts.handle(_KeyEvent(button, KEYCODE_V, "Cyrillic_em")) is None


def test_a_shortcut_matches_only_its_key_outside_the_latin_letter(driver: SetupWindowDriver) -> None:
    shortcut: EditShortcut = EditShortcut(KEYCODE_V, "v", TkEvent.PASTE)
    entry: ttk.Entry = _channel_entry(driver)
    assert shortcut.matches(_KeyEvent(entry, KEYCODE_V, "Cyrillic_em"))
    assert shortcut.matches(_KeyEvent(entry, KEYCODE_V, "??"))
    assert not shortcut.matches(_KeyEvent(entry, KEYCODE_V, "v"))
    assert not shortcut.matches(_KeyEvent(entry, KEYCODE_V, "V"))
    assert not shortcut.matches(_KeyEvent(entry, KEYCODE_C, "Cyrillic_es"))


def test_ctrl_v_and_ctrl_a_work_in_a_key_field(driver: SetupWindowDriver) -> None:
    entry: ttk.Entry = _key_entry(driver)
    driver.put_in_clipboard(OWN_OPENAI_KEY)
    driver.focus(driver.tabs.merge.frame, entry)
    driver.press(entry, KEYCODE_V)
    assert entry.get() == OWN_OPENAI_KEY
    driver.press(entry, KEYCODE_A)
    assert entry.selection_present()


def test_ctrl_c_in_a_key_field_leaves_the_clipboard_alone(driver: SetupWindowDriver) -> None:
    entry: ttk.Entry = _key_entry(driver)
    driver.type(entry, OWN_OPENAI_KEY)
    driver.put_in_clipboard(CLIPBOARD_TEXT)
    driver.focus(driver.tabs.merge.frame, entry)
    entry.selection_range(0, tk.END)
    driver.press(entry, KEYCODE_C)
    entry.event_generate(TkEvent.COPY)
    driver.window.root.update()
    assert driver.window.root.clipboard_get() == CLIPBOARD_TEXT


def test_ctrl_x_in_a_key_field_cuts_nothing(driver: SetupWindowDriver) -> None:
    entry: ttk.Entry = _key_entry(driver)
    driver.type(entry, OWN_OPENAI_KEY)
    driver.put_in_clipboard(CLIPBOARD_TEXT)
    driver.focus(driver.tabs.merge.frame, entry)
    entry.selection_range(0, tk.END)
    driver.press(entry, KEYCODE_X)
    entry.event_generate(TkEvent.CUT)
    driver.window.root.update()
    assert entry.get() == OWN_OPENAI_KEY
    assert driver.window.root.clipboard_get() == CLIPBOARD_TEXT


def test_ctrl_x_still_cuts_in_a_channel_field(driver: SetupWindowDriver) -> None:
    """Запрет — только у полей ключей: остальные поля вырезают как обычно."""
    entry: ttk.Entry = _channel_entry(driver)
    driver.type(entry, CHANNEL_TEXT)
    driver.focus(driver.channels.frame, entry)
    entry.selection_range(0, tk.END)
    driver.press(entry, KEYCODE_X)
    assert entry.get() == ""
    assert driver.window.root.clipboard_get() == CHANNEL_TEXT


# --- подпись кнопки сброса своего значения


def test_the_reset_button_over_the_supply_returns_the_program_value(driver: SetupWindowDriver) -> None:
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert view.reset_button.cget("text") == msg.SETUP_KEYS_BUTTON_RESET_TO_TOKEN


def test_the_reset_button_without_supply_deletes_the_own_value(bare_driver: SetupWindowDriver) -> None:
    view: KeyRowView = bare_driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert view.reset_button.winfo_manager() == "pack"
    assert view.reset_button.cget("text") == msg.SETUP_KEYS_BUTTON_DELETE_OWN


def test_the_keys_notice_says_own_values_stay_on_this_computer(driver: SetupWindowDriver) -> None:
    text: str = str(driver.tabs.plan.shell.notice.cget("text"))
    assert "Свои значения действуют только на этом компьютере" in text


def test_without_supplied_values_there_is_no_protection_notice(bare_driver: SetupWindowDriver) -> None:
    assert str(bare_driver.tabs.plan.shell.notice.cget("text")) == ""


# --- ряды кнопок по центру


def test_the_button_rows_are_centred_without_stretching(driver: SetupWindowDriver) -> None:
    """Ряд кнопок каналов и «Сохранить» каждого раздела настроек — по центру окна, кнопки своего размера."""
    buttons: tuple[ttk.Button, ...] = (
        driver.channels.buttons[TabAction.SAVE], *(section.save_button for section in driver.sections)
    )
    for button in buttons:
        frame: tk.Misc = button.master
        info: dict[str, object] = frame.pack_info()
        assert (info["anchor"], info["fill"], info["side"]) == ("center", "none", "top")
        assert info["pady"] == PAD
        for child in frame.winfo_children():
            assert child.pack_info()["fill"] == "none"


# --- язык канала: одно выпадающее поле с поиском


def test_the_language_field_is_a_combobox_next_to_privacy_of_the_same_width(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    box: ttk.Combobox = tab.language.box
    privacy: ttk.Widget = tab.inputs["privacy"]
    assert isinstance(box, ttk.Combobox) and isinstance(privacy, ttk.Combobox)
    assert box.master is tab.inputs["languages"]
    assert str(box.cget("width")) == str(privacy.cget("width"))
    assert box.master.grid_info()["column"] == privacy.grid_info()["column"]
    assert str(box.cget("state")) != "readonly"           # в поле можно печатать — это поиск
    assert not any(isinstance(widget, tk.Listbox) for widget in driver.widgets(tab.frame))


def test_picking_a_language_gives_the_draft_one_code(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    driver.pick_language("hu")
    assert tab.form_draft.languages == ("hu",)
    driver.pick_language("uk")
    assert tab.form_draft.languages == ("uk",)            # второй выбор заменяет первый, а не добавляется
    assert tab.language.text.get() == tab.language.picker.directory.label_of("uk")


def test_typing_narrows_the_values_to_matching_languages(driver: SetupWindowDriver) -> None:
    directory: LanguageDirectory = driver.language.picker.directory
    driver.language.box.set("укр")
    assert [directory.code_of(label) for label in driver.box_values()] == ["uk"]
    driver.language.box.set("")
    assert len(driver.box_values()) == len(directory.options)


def test_typing_opens_the_list_with_the_matching_languages(driver: SetupWindowDriver) -> None:
    """Человек печатает «укр»: список раскрыт сам, в нём украинский, и набранное целиком в поле."""
    assert not driver.is_language_list_open
    driver.type_language("укр")
    assert driver.is_language_list_open
    directory: LanguageDirectory = driver.language.picker.directory
    assert driver.language_list == (directory.label_of("uk"),)
    assert driver.language.text.get() == "укр"


def test_typing_without_matches_closes_the_list_and_gives_the_keyboard_back(driver: SetupWindowDriver) -> None:
    driver.type_language("укрщ")
    assert not driver.is_language_list_open
    assert driver.window.root.focus_get() is driver.language.box
    assert driver.language.text.get() == "укрщ"


def test_a_key_pressed_in_the_open_list_edits_the_field(driver: SetupWindowDriver) -> None:
    """Раскрытый список отдаёт полю буквы и Backspace; прочие клавиши (стрелки, Enter) остаются списку."""
    box: ttk.Combobox = driver.language.box
    box.set("нем")
    box.icursor(tk.END)
    assert driver.language.forward_key("е", "Cyrillic_ie") == BREAK
    assert box.get() == "неме"
    assert driver.language.forward_key("", "BackSpace") == BREAK
    assert box.get() == "нем"
    assert driver.language.forward_key("", "Down") is None
    assert box.get() == "нем"


def test_programmatic_choice_does_not_open_the_list(driver: SetupWindowDriver) -> None:
    """Выбор строки таблицы пишет в поле подпись языка, а не строку поиска: список не раскрывается."""
    tab: ChannelsTab = driver.channels
    tab.tree.selection_set("0")
    tab.fill_from_selection()
    driver.window.root.update()
    assert not driver.is_language_list_open


def test_typing_does_not_change_the_draft_and_unknown_text_is_a_field_problem(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    driver.pick_language("hu")
    driver.fill_channel(handle="@kanal_hu", google_account="owner@gmail.com")
    tab.language.box.set("венгерский язык")
    assert tab.form_draft.languages == ("hu",)               # набранный текст в черновик не уходит
    driver.press_button(tab, TabAction.ADD)
    assert tab.edit_problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_CHANNEL_FIELD_LABELS["languages"], text=msg.SETUP_LANGUAGE_PICK_FROM_LIST
    )
    assert len(tab.tree.get_children()) == 2


def test_escape_brings_back_the_chosen_language(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    driver.pick_language("hu")
    tab.language.box.set("нем")
    tab.language.restore()
    assert tab.language.text.get() == tab.language.picker.directory.label_of("hu")
    assert tab.language.problem is None


def test_escape_is_bound_to_the_language_field(driver: SetupWindowDriver) -> None:
    assert driver.language.box.bind(TkEvent.ESCAPE)


def test_selecting_a_row_shows_the_channel_language(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    tab.tree.selection_set("0")
    tab.fill_from_selection()
    assert tab.language.text.get() == tab.language.picker.directory.label_of("uk")
    assert tab.form_draft.languages == ("uk",)
    assert tab.language.note.text == ""


def test_empty_lines_under_the_language_leave_no_gap(two_languages_driver: SetupWindowDriver) -> None:
    """Пустая строка под полем языка не стоит в раскладке: до «Видимости» нет пустого промежутка (смотр 4.1b)."""
    tab: ChannelsTab = two_languages_driver.channels
    tab.tree.selection_set("0")
    tab.fill_from_selection()
    assert tab.language.note.label.winfo_manager() == "" and tab.language.warning.label.winfo_manager() == ""
    tab.tree.selection_set("1")
    tab.fill_from_selection()
    assert tab.language.note.label.winfo_manager() == "pack"


def test_a_channel_with_two_languages_keeps_the_first_on_save(
    two_languages_driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    """Канал старого файла записан с двумя языками: показан первый, строка о лишних; после сохранения — один код."""
    tab: ChannelsTab = two_languages_driver.channels
    tab.tree.selection_set("1")
    tab.fill_from_selection()
    assert tab.language.text.get() == tab.language.picker.directory.label_of("ru")
    assert tab.language.note.text == msg.SETUP_LANGUAGE_SEVERAL.format(name="русский")
    assert not tab.is_dirty                                  # строка только показана, правки ещё нет
    two_languages_driver.press_button(tab, TabAction.UPDATE)
    two_languages_driver.press_button(tab, TabAction.SAVE)
    assert tab.edit_problem.text == ""
    assert channels_of(ready_paths.file(FileName.CHANNELS))[1].languages == ("ru",)


def test_picking_another_language_clears_the_several_languages_line(two_languages_driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = two_languages_driver.channels
    tab.tree.selection_set("1")
    tab.fill_from_selection()
    two_languages_driver.pick_language("en")
    assert tab.language.note.text == ""
    assert tab.form_draft.languages == ("en",)


def test_the_form_languages_come_first_and_marked(driver: SetupWindowDriver) -> None:
    directory: LanguageDirectory = driver.language.picker.directory
    settings_file: SettingsFile = SettingsFile(driver.window.paths.file(FileName.CONFIG))
    form_codes: tuple[str, ...] = tuple(settings_file.load().form.values["language"])
    values: tuple[str, ...] = driver.box_values()
    assert [directory.code_of(label) for label in values[: len(form_codes)]] == list(form_codes)
    assert all(label.endswith("— есть в форме") for label in values[: len(form_codes)])
    assert not values[len(form_codes)].endswith("— есть в форме")
    assert len(values) == len(directory.options)


def test_a_language_not_in_the_form_is_named_at_once(driver: SetupWindowDriver) -> None:
    driver.pick_language("uk")
    assert driver.language.warning.text == ""
    driver.pick_language("de")
    assert driver.language.warning.text == msg.SETUP_LANGUAGE_NOT_IN_FORM.format(names="немецкий")


def test_a_language_not_in_the_form_does_not_stop_saving(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    tab: ChannelsTab = driver.channels
    driver.fill_channel(handle="@kanal_de", google_account="owner@gmail.com", languages="de")
    driver.press_button(tab, TabAction.ADD)
    driver.press_button(tab, TabAction.SAVE)
    assert tab.edit_problem.text == ""
    assert channels_of(ready_paths.file(FileName.CHANNELS))[-1].languages == ("de",)


def test_the_table_shows_language_names(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    column: int = list(tab.tree.cget("columns")).index("languages")
    assert tab.tree.item("0", "values")[column] == "украинский"
    assert tab.tree.item("1", "values")[column] == "русский"


def test_the_table_shows_every_language_of_an_old_file(two_languages_driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = two_languages_driver.channels
    column: int = list(tab.tree.cget("columns")).index("languages")
    assert tab.tree.item("1", "values")[column] == "русский, английский"


def test_saving_new_form_languages_updates_the_marks_without_reopening(driver: SetupWindowDriver) -> None:
    """Форма сменилась на вкладке настроек — пометки и предупреждение на вкладке каналов сразу новые."""
    tab: ChannelsTab = driver.channels
    driver.pick_language("de")
    assert tab.language.warning.text != ""
    driver.save_form_languages({"de": "Немецкий (German)", "uk": "Украинский ( Ukranian)"})
    directory: LanguageDirectory = tab.language.picker.directory
    assert directory.label_of("de") == msg.SETUP_LANGUAGE_OPTION_IN_FORM.format(name="немецкий", code="de")
    assert directory.label_of("ru") == msg.SETUP_LANGUAGE_OPTION.format(name="русский", code="ru")
    assert tab.language.text.get() == directory.label_of("de")
    assert tab.language.warning.text == ""
    assert tab.form_draft.languages == ("de",)
    assert [directory.code_of(label) for label in driver.box_values()[:2]] == ["de", "uk"]


def test_without_readable_settings_the_list_is_full_and_unmarked(
    ready_paths: LivecraftPaths, pytestconfig: pytest.Config
) -> None:
    ready_paths.file(FileName.CONFIG).write_text("{", encoding="utf-8")
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        assert not driver.language.picker.directory.has_form
        assert len(driver.box_values()) == len(LanguageDirectory.load(()).options)
        driver.pick_language("de")
        assert driver.language.warning.text == ""


# --- каналы на «Эфирах YouTube» (§8.2 п.4, §14 решение 25): названия канала в окне нет, видимость — словами


def test_the_channels_tab_has_no_account_name_and_explains_every_field(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.channels
    assert "account_name" not in tab.inputs
    headings: list[str] = [str(tab.tree.heading(column, "text")) for column in tab.tree.cget("columns")]
    assert headings == ["ник", "почта Google", "язык стримов", "видимость на YouTube"]
    for name in ("handle", "google_account", "languages", "privacy"):
        hint: ttk.Label = tab.grid.hints[name]
        assert hint.cget("text") == msg.SETUP_CHANNEL_FIELD_HINTS[name] and hint.grid_info()["column"] == 2
    assert tuple(tab.inputs["privacy"].cget("values")) == ("для всех", "по ссылке")
    assert tab.tree.item("1", "values")[3] == "по ссылке"
    assert msg.SETUP_CHANNELS_INTRO in driver.visible_texts()


def test_a_new_channel_is_named_by_its_handle(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    tab: ChannelsTab = driver.channels
    driver.fill_channel(handle="kanal_hu", google_account="owner@gmail.com", languages="hu", privacy="по ссылке")
    driver.press_button(tab, TabAction.ADD)
    driver.press_button(tab, TabAction.SAVE)
    saved = channels_of(ready_paths.file(FileName.CHANNELS))[-1]
    assert (saved.handle, saved.account_name, saved.privacy.value) == ("@kanal_hu", "kanal_hu", "unlisted")


def test_updating_a_channel_keeps_its_name(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    tab: ChannelsTab = driver.channels
    tab.tree.selection_set("1")
    tab.fill_from_selection()
    driver.fill_channel(google_account="other@gmail.com")
    driver.press_button(tab, TabAction.UPDATE)
    driver.press_button(tab, TabAction.SAVE)
    saved = channels_of(ready_paths.file(FileName.CHANNELS))[1]
    assert (saved.account_name, saved.google_account) == ("Канал RU", "other@gmail.com")


# --- «Главная» (§14 решение 37): линии работы, их ползунки и готовность, «Перейти»


def _line(driver: SetupWindowDriver, part: RunPart) -> LineHeader:
    return driver.tabs.home.lines[part]


def _state(driver: SetupWindowDriver, part: RunPart) -> str:
    return str(_line(driver, part).state.cget("text"))


def _flip(driver: SetupWindowDriver, part: RunPart) -> None:
    """Щелчок по ползунку линии: на «Главной», а у таблицы плана и передачи ключей — вверху их вкладок (на «Главной»
    у них выбор, а не ползунок)."""
    _headers(driver, part)[0].switch.flip()


def _input(driver: SetupWindowDriver) -> InputChoiceRow:
    return driver.tabs.home.input


def _keys(driver: SetupWindowDriver) -> KeysChoiceRow:
    return driver.tabs.home.keys


def _choose(row: InputChoiceRow | KeysChoiceRow, value: str) -> None:
    """Нажатие кнопки варианта так, как это делает человек."""
    row.row.choice.buttons[value].invoke()


def _is_disabled(row: InputChoiceRow | KeysChoiceRow) -> bool:
    return all(button.instate([tk.DISABLED]) for button in row.row.choice.buttons.values())


def _headers(driver: SetupWindowDriver, part: RunPart) -> list[LineHeader]:
    """Строки линии `part` во всём окне: на «Главной» и вверху её вкладки."""
    return [header for header in driver.window.context.switches.headers if header.part is part]


def test_the_home_tab_lists_the_lines_by_stages_and_goes_to_their_tabs(driver: SetupWindowDriver) -> None:
    """Этапы под чертами с подписями; вход — кнопками, ключи — «новые | все»; остальные линии — строкой с ползунком,
    названием, тем, что делает, готовностью и «Перейти» на вкладку линии (§14 решение 48)."""
    lines: dict[RunPart, LineHeader] = driver.tabs.home.lines
    assert list(lines) == [part for part in LINE_ORDER if part not in CHOICE_PARTS]
    for part, line in lines.items():
        assert isinstance(line.switch, ToggleSwitch) and line.switch.variable.get()
        assert str(line.title.cget("text")) == part.human_label
        assert str(line.does.cget("text")) == msg.SETUP_LINE_DOES[part.value]
        assert line.go_button is not None and str(line.go_button.cget("text")) == msg.SETUP_HOME_GO
        assert line.frame.master is not driver.tabs.home.body                 # строка — внутри рамки своего этапа
        driver.go(part)
        assert driver.selected_page is SetupPage.of_line(part)
    texts: list[str] = driver.visible_texts()
    assert all(stage.human_label in texts for stage in LineStage)
    assert list(msg.SETUP_HOME_INPUTS.values())[0] in texts and msg.SETUP_KEYS_CHOICES["all"] in texts
    assert any(msg.SETUP_HOME_INTRO in text and msg.SETUP_HOME_HOWTO in text for text in texts)
    separators: list[tk.Misc] = [widget for widget in driver.widgets(driver.tabs.home.body)
                                 if isinstance(widget, ttk.Separator)]
    assert len(separators) == len(LineStage)
    working: str = msg.LIST_JOINER.join(part.human_label for part in LINE_ORDER)
    assert str(driver.tabs.home.run_line.cget("text")) == msg.SETUP_HOME_RUNS.format(
        source=msg.SETUP_HOME_RUN_SOURCES["plan"], lines=working
    )


def test_saving_on_a_tab_refreshes_the_home_tab(driver: SetupWindowDriver) -> None:
    """Пакету не хватает ссылки на форму — ✗ красным; ссылка сохранена на «Ключах в форму» — ✓ готово зелёным."""
    form_gap: str = msg.READINESS_GAP_FORM              # без вкладки: её называет «Перейти» рядом
    line: LineHeader = _line(driver, RunPart.PACKAGE)
    assert _state(driver, RunPart.PACKAGE) == msg.SETUP_LINE_BLOCKED.format(gaps=form_gap)
    assert str(line.state.cget("foreground")) == STATUS_UNSET_FOREGROUND
    link: LinkRowView = driver.tabs.form.form_link
    driver.type(link.entry, "https://forms.gle/AbCdEf123456")
    link.save_button.invoke()
    assert _state(driver, RunPart.PACKAGE) == msg.SETUP_LINE_READY
    assert str(line.state.cget("foreground")) == STATUS_SET_FOREGROUND


def test_on_a_clean_install_every_line_lacks_something(bare_driver: SetupWindowDriver) -> None:
    lines: dict[RunPart, LineHeader] = bare_driver.tabs.home.lines
    assert all(str(line.state.cget("text")).startswith("✗") for line in lines.values())
    assert str(bare_driver.tabs.home.input.state.cget("text")).startswith("✗")


def test_a_switch_writes_only_the_lines_and_the_tab_switch_follows(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    """Ползунок нейросети на «Главной» выключен: в файле — только раздел lines; ползунок вверху «Нейросети» — то же
    значение; «Запуск сделает» — без нейросети; несохранённого нет."""
    before: dict[str, object] = SettingsFile.of(ready_paths).load().to_data()
    _flip(driver, RunPart.MERGE)
    after: dict[str, object] = SettingsFile.of(ready_paths).load().to_data()
    assert {key for key in before if before[key] != after[key]} == {"lines"}
    assert SettingsFile.of(ready_paths).load().lines.merge is False
    headers: list[LineHeader] = _headers(driver, RunPart.MERGE)
    assert len(headers) == 2 and all(header.switch.variable is headers[0].switch.variable for header in headers)
    assert not headers[1].switch.variable.get()
    assert _state(driver, RunPart.MERGE) == msg.SETUP_LINE_OFF
    assert RunPart.MERGE.human_label not in str(driver.tabs.home.run_line.cget("text"))
    assert not driver.window.is_dirty


def test_the_input_buttons_write_the_table_line_and_pale_the_stages(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    """Вход «Пакеты» — таблица плана выключена: нейросеть бледная (работает только от таблицы), вывод и эфиры — нет
    (от пакетов им опора не нужна); строка входа говорит, что он делает, «Перейти» ведёт на «Пакет»; значение нейросети
    хранится и вернётся с таблицей (§14 решения 48, 51)."""
    row: InputChoiceRow = _input(driver)
    assert driver.window.context.switches.source.get() == RunPart.PLAN.value
    assert str(row.row.text.cget("text")) == msg.SETUP_LINE_DOES["plan"]
    _choose(row, RunPart.PACKAGES_IN.value)
    assert SettingsFile.of(ready_paths).load().lines.plan is False
    assert str(row.row.text.cget("text")) == msg.SETUP_LINE_DOES["packages_in"]
    assert str(row.state.cget("text")) == msg.SETUP_LINE_READY
    row.go_button.invoke()
    assert driver.selected_page is SetupPage.PACKAGE
    merge: LineHeader = _line(driver, RunPart.MERGE)
    assert not merge.switch.is_enabled and _state(driver, RunPart.MERGE) == msg.SETUP_LINE_SUPPORT_REASONS["plan"]
    merge.switch.flip()                                          # недоступный ползунок не переключается
    assert merge.switch.variable.get() and SettingsFile.of(ready_paths).load().lines.merge
    assert all(_line(driver, part).switch.is_enabled for part in LineStage.OUTPUT.parts)
    assert _line(driver, RunPart.BROADCAST).switch.is_enabled
    assert msg.SETUP_HOME_RUN_SOURCES["packages_in"] in str(driver.tabs.home.run_line.cget("text"))
    assert not _headers(driver, RunPart.PLAN)[0].switch.variable.get()   # ползунок «Таблицы плана» — то же значение
    _choose(row, RunPart.PLAN.value)
    assert SettingsFile.of(ready_paths).load().lines.plan is True
    assert merge.switch.is_enabled and _state(driver, RunPart.MERGE) == msg.SETUP_LINE_READY
    row.go_button.invoke()
    assert driver.selected_page is SetupPage.PLAN


def test_from_the_table_without_the_ai_the_package_and_the_broadcasts_are_pale(driver: SetupWindowDriver) -> None:
    """Таблица без нейросети (§14 решение 50): пакет и эфиры бледные и говорят почему; ключи — недоступны."""
    _flip(driver, RunPart.MERGE)
    for part in (RunPart.PACKAGE, RunPart.BROADCAST):
        assert not _line(driver, part).switch.is_enabled
        assert _state(driver, part) == msg.SETUP_LINE_SUPPORT_REASONS["merge"]
    assert _is_disabled(_keys(driver)) and _keys(driver).text == msg.SETUP_KEYS_INACTIVE["no_merge"]


def test_no_working_line_says_the_run_does_nothing(driver: SetupWindowDriver) -> None:
    """Включена одна нейросеть, а таблица выключена: ей не с чем работать — запуск ничего не сделает."""
    for part in LINE_ORDER:
        if part is not RunPart.MERGE:
            _flip(driver, part)
    assert str(driver.tabs.home.run_line.cget("text")) == msg.SETUP_HOME_RUNS_NOTHING


def test_a_failed_line_write_says_so_and_keeps_the_file(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    shown: list[str] = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **_options: shown.append(message))

    def _refuse(self: SettingsFile, settings: LivecraftSettings) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(SettingsFile, "save", _refuse)
    _flip(driver, RunPart.MERGE)
    assert shown == [msg.SETUP_SETTINGS_SAVE_FAILED.format(error=PermissionError("locked"))]
    assert SettingsFile.of(ready_paths).load().lines.merge
    assert _line(driver, RunPart.MERGE).switch.variable.get()   # ползунок вернулся к записанному


# --- бледные поля (§14 решение 37): поле не нужно ни одной работающей линии — недоступно и серое


def test_a_field_of_a_switched_off_line_is_pale_and_names_its_lines(driver: SetupWindowDriver) -> None:
    entry: tk.Widget = driver.settings_input("llm_model")
    label: ttk.Label = driver.section_of("llm_model").grid.labels["llm_model"]
    _flip(driver, RunPart.MERGE)
    assert isinstance(entry, ttk.Entry) and entry.instate([tk.DISABLED])
    assert str(label.cget("foreground")) == DIM_FOREGROUND
    notes: list[str] = driver.visible_texts()
    assert msg.SETUP_FIELD_NEEDED_BY.format(lines=RunPart.MERGE.human_label) in notes
    _flip(driver, RunPart.MERGE)
    assert entry.instate(["!disabled"]) and str(label.cget("foreground")) != DIM_FOREGROUND
    assert msg.SETUP_FIELD_NEEDED_BY.format(lines=RunPart.MERGE.human_label) not in driver.visible_texts()


def test_the_form_link_stays_active_while_another_line_needs_it(driver: SetupWindowDriver) -> None:
    """Ссылка на форму нужна пакету, документу, Telegram и ключам: одна выключенная линия её не гасит."""
    entry: ttk.Entry = driver.tabs.form.form_link.entry
    _flip(driver, RunPart.KEYS)
    assert entry.instate(["!disabled"])
    for part in (RunPart.PACKAGE, RunPart.DOC, RunPart.ANNOUNCE):
        _flip(driver, part)
    assert entry.instate([tk.DISABLED])
    lines: str = msg.LIST_JOINER.join(part.human_label for part in (
        RunPart.DOC, RunPart.PACKAGE, RunPart.ANNOUNCE, RunPart.KEYS
    ))
    assert msg.SETUP_FIELD_NEEDED_BY.format(lines=lines) in driver.visible_texts()


def test_the_packages_folder_stays_active_without_the_table_while_any_line_works(driver: SetupWindowDriver) -> None:
    """Без таблицы все линии берут слоты из папки пакетов (§14 решение 51): папка нужна, пока работает хоть одна; с
    таблицей без пакета и эфиров она не нужна."""
    button: ttk.Button = driver.tabs.package.packages.choose_button
    _flip(driver, RunPart.PLAN)
    assert button.instate(["!disabled"])
    for part in LINE_ORDER:
        if part not in (RunPart.PLAN, RunPart.MERGE):
            _flip(driver, part)
    assert button.instate([tk.DISABLED])


def test_a_switch_of_a_pale_setting_is_pale_too(driver: SetupWindowDriver) -> None:
    switch: tk.Widget = driver.settings_input("auto_start")
    assert isinstance(switch, ToggleSwitch) and switch.is_enabled
    _flip(driver, RunPart.BROADCAST)
    assert not switch.is_enabled


# --- папки ролей, выбор ключей и вкладка «Форма», ссылка на папку Диска на двух вкладках


def test_a_folder_inside_the_root_is_written_relative_and_default_brings_the_role_back(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    row = driver.tabs.package.packages
    row.ask = lambda **_options: str(ready_paths.root / "sub" / "packs")
    row.choose_button.invoke()
    assert SettingsFile.of(ready_paths).load().folders.packages == "sub/packs"
    assert str(row.block.status.cget("text")) == msg.SETUP_FOLDER_STATUS.format(path=Path("sub") / "packs")
    row.default_button.invoke()
    assert SettingsFile.of(ready_paths).load().folders.packages == "bcast"


def test_a_cancelled_folder_choice_changes_nothing(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    before: bytes = ready_paths.file(FileName.CONFIG).read_bytes()
    row = driver.tabs.doc.copies
    row.ask = lambda **_options: ""
    row.choose_button.invoke()
    assert ready_paths.file(FileName.CONFIG).read_bytes() == before


def test_a_failed_folder_write_shows_the_dialog_and_keeps_the_row(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Запись настроек вкладки — одна (`TabShell.write_settings`): сбой диска — диалог, строка — по прежней записи."""
    shown: list[str] = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **_options: shown.append(message))

    def _refuse(self: SettingsFile, settings: LivecraftSettings) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr(SettingsFile, "save", _refuse)
    row = driver.tabs.package.packages
    status: str = str(row.block.status.cget("text"))
    row.ask = lambda **_options: str(ready_paths.root / "elsewhere")
    row.choose_button.invoke()
    assert shown == [msg.SETUP_SETTINGS_SAVE_FAILED.format(error=PermissionError("locked"))]
    assert SettingsFile.of(ready_paths).load().folders.packages == "bcast"
    assert str(row.block.status.cget("text")) == status


def test_the_keys_choice_writes_the_resend_keys_and_names_what_it_does(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    """«новые | все» на «Главной» (§14 решения 47, 49): выбор сразу в файле, строка под ним — что он делает, «Запуск
    сделает» — ключи всех эфиров заново."""
    set_form_url(ready_paths, FORM_URL)
    driver.window.refresh()
    keys: KeysChoiceRow = _keys(driver)
    assert not _is_disabled(keys) and keys.text == msg.SETUP_KEYS_HINTS["new"]
    assert driver.window.context.switches.keys.get() == "new"
    _choose(keys, "all")
    assert SettingsFile.of(ready_paths).load().broadcasts.resend_keys is True
    assert keys.text == msg.SETUP_KEYS_HINTS["all"]
    all_keys: str = msg.SETUP_HOME_RUNS_KEYS_ALL.format(line=RunPart.KEYS.human_label)
    assert str(driver.tabs.home.run_line.cget("text")).endswith(all_keys)
    _choose(keys, "new")
    assert SettingsFile.of(ready_paths).load().broadcasts.resend_keys is False
    assert all_keys not in str(driver.tabs.home.run_line.cget("text"))
    assert not driver.window.is_dirty


def test_the_keys_choice_is_pale_while_the_keys_line_is_off(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    """Передача ключей выключена ползунком вкладки «Форма» — выбор недоступен и называет, где её включить."""
    set_form_url(ready_paths, FORM_URL)
    header: LineHeader = _headers(driver, RunPart.KEYS)[0]
    assert str(header.title.cget("text")) == msg.SETUP_LINE_TITLES["keys"] == "Передавать ключи в форму"
    header.switch.flip()
    assert SettingsFile.of(ready_paths).load().lines.keys is False
    assert _is_disabled(_keys(driver)) and _keys(driver).text == msg.SETUP_KEYS_INACTIVE["off"]
    _choose(_keys(driver), "all")                                # недоступная кнопка не пишет
    assert SettingsFile.of(ready_paths).load().broadcasts.resend_keys is False


def test_the_keys_choice_is_pale_without_broadcasts(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    set_form_url(ready_paths, FORM_URL)
    _flip(driver, RunPart.BROADCAST)
    assert _is_disabled(_keys(driver)) and _keys(driver).text == msg.SETUP_KEYS_INACTIVE["no_broadcasts"]


def test_the_keys_choice_is_pale_from_the_table_without_a_form(driver: SetupWindowDriver) -> None:
    """Вход «Таблица», ссылки на форму нет — выбор недоступен; вход «Пакеты» — форма из пакетов, выбор доступен."""
    assert _is_disabled(_keys(driver)) and _keys(driver).text == msg.SETUP_KEYS_INACTIVE["no_form"]
    _choose(_input(driver), RunPart.PACKAGES_IN.value)
    assert not _is_disabled(_keys(driver)) and _keys(driver).text == msg.SETUP_KEYS_HINTS["new"]


def test_the_form_tab_has_the_keys_switch_and_the_form_link(driver: SetupWindowDriver) -> None:
    """Вкладка «Форма»: вверху — ползунок «Передавать ключи в форму» (линия ключей), ниже — ссылка на форму; выбора
    «новые | все» на ней нет — он на «Главной»."""
    tab_widgets: list[tk.Misc] = list(driver.widgets(driver.tabs.form.frame))
    header: LineHeader = _headers(driver, RunPart.KEYS)[0]
    assert header.frame in tab_widgets and driver.tabs.form.form_link.entry in tab_widgets
    assert not any(isinstance(widget, ttk.Radiobutton) for widget in tab_widgets)
    assert driver.tabs.form.page.title == "Форма"


def test_the_form_link_is_pale_with_the_packages_input(driver: SetupWindowDriver) -> None:
    """Вход «Пакеты»: форма у каждого эфира — из его пакета; поле ссылки бледное и говорит об этом (§14 решение 51)."""
    entry: ttk.Entry = driver.tabs.form.form_link.entry
    assert entry.instate(["!disabled"])
    _choose(_input(driver), RunPart.PACKAGES_IN.value)
    assert entry.instate([tk.DISABLED])
    assert msg.SETUP_FIELD_FROM_PACKAGES["form"] in driver.visible_texts()


def test_the_space_key_flips_a_focused_switch(driver: SetupWindowDriver) -> None:
    switch: ToggleSwitch = _headers(driver, RunPart.KEYS)[0].switch
    driver.focus(driver.tabs.form.frame, switch)  # type: ignore[arg-type]
    switch.event_generate(TkEvent.SPACE)
    driver.window.root.update()
    assert not switch.variable.get()


def test_the_drive_folder_saved_on_previews_shows_on_the_document_tab(driver: SetupWindowDriver) -> None:
    """Одно поле сейфа на двух вкладках (§14 решение 39): сохранено на «Превью» — та же маска на «Google-документе»."""
    previews: KeyRowView = driver.folder.row
    driver.type(previews.entry, "https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQrStUvWxYz")
    previews.accept_button.invoke()
    driver.wait_for_folder_check()
    status: str = _own_status(SecretField.DRIVE_FOLDER, "1AbCdEfGhIjKlMnOpQrStUvWxYz")
    assert str(driver.doc_folder.row.status.cget("text")) == str(previews.status.cget("text")) == status


# --- «Telegram» (§8.2 п.7, §14 решения 19, 20, 57, 58): три шага, чат с ботом и группа с ботом, «куда слать» и строка
# назначения; бот — подделка, к настоящему Telegram тесты не ходят

GROUP_ID: str = "-4000000001"
SUPERGROUP_ID: str = "-1001000000001"
PRIVATE_ID: str = "111000111"
BOT_READY: str = msg.SETUP_TELEGRAM_BOT_READY.format(name="Livecraft", username="livecraft_test_bot")


def _publish(driver: SetupWindowDriver) -> PublishTab:
    return driver.telegram


def _chat_row(driver: SetupWindowDriver, target: ChatTarget) -> ChatRowView:
    """Строка чата объявлений вида `target`: «Чат с ботом» или «Группа с ботом»."""
    return next(row for row in _publish(driver).chat.rows if row.search.targets == (target,))


def _target_button(driver: SetupWindowDriver, target: ChatTarget) -> ttk.Radiobutton:
    """Кнопка выбора «Куда слать объявления» для вида `target`."""
    return _publish(driver).targets.choice.buttons[target.value]


def _connected(target: str, title: str) -> str:
    into: str = msg.SETUP_TELEGRAM_TARGETS_INTO[target]
    return msg.SETUP_TELEGRAM_CONNECTED.format(destination=msg.SETUP_TELEGRAM_DESTINATION_BY_TITLE.format(into=into, title=title))


def _telegram_in_file(driver: SetupWindowDriver, paths: LivecraftPaths, telegram: TelegramSettings) -> None:
    """Раздел telegram на диске, вкладка перечитала его, окно перерисовано (бледность — последней)."""
    file: SettingsFile = SettingsFile.of(paths)
    file.save(file.load().with_telegram(telegram))
    _publish(driver).reload()
    driver.window.refresh()


def test_the_telegram_tab_shows_three_steps_two_chats_and_the_choice(driver: SetupWindowDriver) -> None:
    """Зачем объявления и три шага с номерами; на шаге 3 — чат с ботом и группа с ботом, у каждого своя кнопка, у
    группы — что сделать сначала, выбор «куда слать» и строка назначения; полей id чатов нет — только токен бота.
    Ничего не подключено — оба вида выбрать нельзя."""
    tab: PublishTab = _publish(driver)
    texts: list[str] = driver.visible_texts()
    for text in (
        msg.SETUP_TELEGRAM_INTRO, msg.SETUP_TELEGRAM_STEP_1_TITLE, msg.SETUP_TELEGRAM_STEP_1_TEXT,
        msg.SETUP_TELEGRAM_STEP_2_TITLE, msg.SETUP_TELEGRAM_STEP_2_TEXT, msg.SETUP_TELEGRAM_STEP_3_TITLE,
        msg.SETUP_TELEGRAM_STEP_3_TEXT, msg.SETUP_TELEGRAM_BUTTON_OPEN_BOT, "Чат с ботом", "Группа с ботом",
        "Подключить чат с ботом", "Подключить группу с ботом", "Куда слать объявления:", "в чат с ботом",
        "в группу с ботом", msg.SETUP_KEY_FIELD_LABELS["telegram_bot_token"], msg.SETUP_TELEGRAM_DESTINATION_NONE,
        msg.SETUP_TELEGRAM_TARGET_HINTS_UNNAMED["group"],
    ):
        assert text in texts
    entries: list[tk.Misc] = [widget for widget in driver.widgets(tab.frame) if isinstance(widget, (ttk.Entry, tk.Entry))]
    assert entries == [tab.rows[SecretField.TELEGRAM_BOT_TOKEN].entry]
    assert [row.line.cget("text") for row in tab.chat.rows] == ["не подключён", "не подключён"]
    assert tab.chat.chat_list.winfo_manager() == ""
    assert tab.target.get() == "private"
    assert all(_target_button(driver, target).instate([tk.DISABLED]) for target in ChatTarget)


def test_the_private_chat_by_the_file_is_connected_and_the_group_cannot_be_chosen(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    """Сценарий смотра 0.1.5: в файле личный чат, группы нет — «в группу» не нажимается и после бледности окна."""
    _telegram_in_file(driver, ready_paths, TelegramSettings(ChatTarget.PRIVATE, "", "222000222", ""))
    assert _chat_row(driver, ChatTarget.PRIVATE).line.cget("text") == "подключён: id 222000222"
    assert _chat_row(driver, ChatTarget.GROUP).line.cget("text") == "не подключён"
    assert _chat_row(driver, ChatTarget.PRIVATE).button.cget("text") == "Подключить другой чат с ботом"
    assert _publish(driver).destination.cget("text") == "Сейчас объявления уходят в чат с ботом (id 222000222)."
    assert _publish(driver).target.get() == "private"
    assert _target_button(driver, ChatTarget.PRIVATE).instate(["!disabled"])
    assert _target_button(driver, ChatTarget.GROUP).instate([tk.DISABLED])
    _target_button(driver, ChatTarget.GROUP).invoke()                 # недоступная кнопка не пишет
    assert SettingsFile.of(ready_paths).load().telegram.target is ChatTarget.PRIVATE


def test_without_a_token_every_step_asks_for_step_one(driver: SetupWindowDriver) -> None:
    tab: PublishTab = _publish(driver)
    opened: list[str] = driver.catch_opened()
    assert tab.telegram_bot() is None
    for button in (tab.open_button, *(row.button for row in tab.chat.rows)):
        button.invoke()
        assert tab.chat.status.cget("text") == msg.SETUP_TELEGRAM_STEP_1_FIRST
    assert opened == []


def test_the_bot_token_is_saved_on_step_one_names_the_bot_and_never_shows(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    """Токен бота — своё значение сейфа, как любое другое; после записи шаг 1 называет бота; в окне только маска."""
    driver.talk_to(FakeTelegram.answering("get_me"))
    view: KeyRowView = driver.accept_key(SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN)
    assert _status(view) == _own_status(SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN)
    assert _publish(driver).bot_key.line.cget("text") == BOT_READY
    assert not any(BOT_TOKEN in text for text in driver.visible_texts())
    bot: TelegramBot | None = _publish(driver).telegram_bot()
    assert bot is not None and bot.token.reveal() == BOT_TOKEN          # эталон теста раскрывает сам тест
    assert VaultStore.open(ready_paths).load().vault.get(SecretField.TELEGRAM_BOT_TOKEN) is not None


def test_open_bot_opens_its_address_in_the_browser(driver: SetupWindowDriver) -> None:
    opened: list[str] = driver.catch_opened()
    driver.talk_to(FakeTelegram.answering("get_me"))
    _publish(driver).open_button.invoke()
    assert opened == ["https://t.me/livecraft_test_bot"]
    assert _publish(driver).bot_key.line.cget("text") == BOT_READY


def test_one_private_chat_is_connected_at_once(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    tab: PublishTab = _publish(driver)
    driver.talk_to(FakeTelegram.answering("get_me", "webhook_none", "updates_private", "send_message_private"))
    _chat_row(driver, ChatTarget.PRIVATE).button.invoke()
    telegram: TelegramSettings = SettingsFile.of(ready_paths).load().telegram
    assert (telegram.target.value, telegram.private_chat_id) == ("private", PRIVATE_ID)
    assert tab.chat.status.cget("text") == _connected("private", "Test User @test_user")
    assert _chat_row(driver, ChatTarget.PRIVATE).line.cget("text") == "подключён: Test User @test_user"
    assert tab.chat.chat_list.winfo_manager() == "" and not driver.window.is_dirty
    assert _chat_row(driver, ChatTarget.PRIVATE).button.cget("text") == "Подключить другой чат с ботом"
    assert tab.destination.cget("text") == "Сейчас объявления уходят в чат с ботом «Test User @test_user»."
    assert _target_button(driver, ChatTarget.PRIVATE).instate(["!disabled"])
    assert _target_button(driver, ChatTarget.GROUP).instate([tk.DISABLED])


def test_a_connected_group_can_be_chosen_and_the_target_stays_until_it_is(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    """Чат с ботом подключён; кнопка группы подключает группу (чат с ботом в ответе бота она не берёт): назначение
    остаётся чатом с ботом (§14 решение 58), «в группу с ботом» нажимается; нажата — объявления уходят в группу, и
    строка назначения говорит это; обе строки чатов — с названиями этого окна или по файлу."""
    _telegram_in_file(driver, ready_paths, TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, ""))
    driver.talk_to(FakeTelegram.answering("get_me", "webhook_none", "updates", "send_message_group"))
    _chat_row(driver, ChatTarget.GROUP).button.invoke()
    assert len(driver.chat_lines) == 3 and not any("Test" in line for line in driver.chat_lines)
    assert _publish(driver).chat.status.cget("text") == "Бот видит несколько групп — нажмите в списке на нужную."
    driver.pick_chat(0)
    assert SettingsFile.of(ready_paths).load().telegram == TelegramSettings(ChatTarget.PRIVATE, GROUP_ID, PRIVATE_ID, "")
    assert _publish(driver).chat.status.cget("text") == _connected("group", "Livecraft group")
    assert _chat_row(driver, ChatTarget.GROUP).line.cget("text") == "подключён: Livecraft group"
    assert _chat_row(driver, ChatTarget.GROUP).hint.winfo_manager() == ""
    assert _publish(driver).target.get() == "private"
    assert all(_target_button(driver, target).instate(["!disabled"]) for target in ChatTarget)
    _target_button(driver, ChatTarget.GROUP).invoke()
    assert SettingsFile.of(ready_paths).load().telegram == TelegramSettings(ChatTarget.GROUP, GROUP_ID, PRIVATE_ID, "")
    assert _publish(driver).target.get() == "group"
    assert _publish(driver).destination.cget("text") == "Сейчас объявления уходят в группу с ботом «Livecraft group»."


def test_the_choice_is_pale_while_announcements_are_off(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    """Объявления выключены — выбор бледный, как весь шаг; включены — снова нажимается только подключённый вид."""
    _telegram_in_file(driver, ready_paths, TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, ""))
    _flip(driver, RunPart.ANNOUNCE)
    assert all(_target_button(driver, target).instate([tk.DISABLED]) for target in ChatTarget)
    _flip(driver, RunPart.ANNOUNCE)
    assert _target_button(driver, ChatTarget.PRIVATE).instate(["!disabled"])
    assert _target_button(driver, ChatTarget.GROUP).instate([tk.DISABLED])


def test_the_test_message_after_a_migration_writes_the_new_group_id(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    """Группа подключена, затем стала супергруппой: «Подключить другую (новую) группу с ботом» на ту же группу шлёт
    пробное сообщение, и новый id сразу в файле."""
    fake: FakeTelegram = FakeTelegram.answering(
        "get_me", "webhook_none", "updates_group", "send_message_group",
        "get_me", "webhook_none", "updates_group", "migrated", "send_message_supergroup",
    )
    driver.talk_to(fake)
    group: ChatRowView = _chat_row(driver, ChatTarget.GROUP)
    group.button.invoke()
    assert group.button.cget("text") == "Подключить другую (новую) группу с ботом"
    group.button.invoke()
    shown: str = str(_publish(driver).chat.status.cget("text"))
    assert msg.TELEGRAM_CHAT_MIGRATED.format(old_chat_id=GROUP_ID, new_chat_id=SUPERGROUP_ID) in shown
    assert _connected("group", "Livecraft super") in shown
    assert group.button.cget("text") == "Подключить другую (новую) группу с ботом"
    assert SettingsFile.of(ready_paths).load().telegram.group_chat_id == SUPERGROUP_ID
    assert fake.outcomes == []


def test_a_connected_chat_clears_the_telegram_gap_and_survives_the_advanced_tab(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    telegram_gap: str = msg.READINESS_GAP_TELEGRAM      # без вкладки: её называет «Перейти» рядом
    driver.talk_to(FakeTelegram.answering("get_me", "get_me", "webhook_none", "updates_group", "send_message_group"))
    driver.accept_key(SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN)
    assert telegram_gap in _state(driver, RunPart.ANNOUNCE)
    _chat_row(driver, ChatTarget.GROUP).button.invoke()
    assert telegram_gap not in _state(driver, RunPart.ANNOUNCE)
    section: SettingsSection = driver.tabs.advanced.section
    driver.type(_settings_entry(driver, "keep_days"), "13")
    section.save_button.invoke()
    saved: LivecraftSettings = SettingsFile.of(ready_paths).load()
    assert saved.keep_days == 13 and saved.telegram.group_chat_id == GROUP_ID


def test_the_group_hint_names_the_bot_once_it_is_known(driver: SetupWindowDriver) -> None:
    """Пока бот не назван — подсказка группы с «имя_бота»; бот сохранён и назван — с его @именем (§14 решение 58)."""
    group: ChatRowView = _chat_row(driver, ChatTarget.GROUP)
    assert group.hint.cget("text") == msg.SETUP_TELEGRAM_TARGET_HINTS_UNNAMED["group"]
    assert _chat_row(driver, ChatTarget.PRIVATE).hint.winfo_manager() == ""
    driver.talk_to(FakeTelegram.answering("get_me"))
    driver.accept_key(SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN)
    assert group.hint.cget("text") == msg.SETUP_TELEGRAM_TARGET_HINTS["group"].format(username="livecraft_test_bot")
    assert group.hint.winfo_manager() == "pack"


def test_an_action_on_the_telegram_tab_shows_at_once_on_home_and_on_the_logs_tab(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    """Группа поддержки подключена и на «Telegram»; подключение её там переносит её в супергруппу: «Главная» видит
    подключённый чат объявлений, «Логи» — новый id чата поддержки, без перезапуска окна."""
    file: SettingsFile = SettingsFile.of(ready_paths)
    file.save(file.load().with_telegram(TelegramSettings(ChatTarget.PRIVATE, "", "", GROUP_ID)))
    driver.tabs.logs.reload()
    driver.talk_to(FakeTelegram.answering(
        "get_me", "get_me", "webhook_none", "updates_group", "migrated", "send_message_supergroup"
    ))
    driver.accept_key(SecretField.TELEGRAM_BOT_TOKEN, BOT_TOKEN)
    assert msg.READINESS_GAP_TELEGRAM in _state(driver, RunPart.ANNOUNCE)
    _chat_row(driver, ChatTarget.GROUP).button.invoke()
    assert msg.READINESS_GAP_TELEGRAM not in _state(driver, RunPart.ANNOUNCE)
    by_id: str = msg.SETUP_TELEGRAM_CHAT_BY_ID.format(chat_id=SUPERGROUP_ID)
    assert driver.logs.chat.rows[0].line.cget("text") == msg.SETUP_TELEGRAM_CHAT_CONNECTED.format(chat=by_id)
    assert _publish(driver).destination.cget("text") == "Сейчас объявления уходят в группу с ботом «Livecraft super»."


# --- ошибка программы в действии окна (§13 задача 9.8): в лог и окном-сообщением, окно работает дальше


def test_a_failed_window_action_goes_to_the_log_and_a_message_and_the_window_lives_on(
    ready_paths: LivecraftPaths,
    pytestconfig: pytest.Config,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Окно так, как его открывает программа: исключение обработчика Tk — строка с трассировкой в лог запуска и одно
    окно-сообщение с путём лога поверх окна; окно не закрыто и отвечает."""
    monkeypatch.setattr(DpiAwareness, "apply", lambda self: None)    # осведомлённость о DPI — на весь процесс тестов
    shown: list[tuple[str, tk.Misc]] = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **options: shown.append((message, options["parent"])))
    log: Path = ready_paths.logs_dir / "03-10-2026_120000_livecraft.log"
    assert pytestconfig.getoption(CAPTURE_OPTION) != FD_CAPTURE, FD_CAPTURE_PROBLEM
    window: SetupWindow = SetupWindow.open(ready_paths, log)
    window.root.withdraw()

    def _broken_action() -> None:
        raise RuntimeError("handler exploded")

    try:
        with caplog.at_level(logging.ERROR):
            window.root.after(0, _broken_action)
            window.root.update()
        [record] = [record for record in caplog.records if "setup_action_failed" in record.getMessage()]
        assert record.getMessage() == f"setup_action_failed error=RuntimeError log={log}"
        assert record.exc_info is not None and str(record.exc_info[1]) == "handler exploded"
        assert shown == [(msg.SETUP_ACTION_FAILED.format(log=log), window.root)]
        assert not window.is_closed and window.root.winfo_exists()
        window.refresh()
    finally:
        window.close()
