"""Окно настройщика по-настоящему: Tk создаётся и прячется (withdraw), кнопки нажимаются через invoke.

Окно без рабочего стола не создаётся — такой прогон падает с TclError, а не пропускается: настройщик
на машине оператора обязан открываться.
"""
from __future__ import annotations

import json
import logging
import tkinter as tk
from collections.abc import Iterator
from tkinter import font, messagebox, ttk
from typing import Any

import pytest

from app.config.files import SettingsFile
from app.config.json_node import SettingProblem
from app.config.settings import ServiceTier
from app.paths import LivecraftPaths
from app.secretsafe.field import SecretField
from app.secretsafe.store import LocalVaultState, VaultStore
from app.secretsafe.value import SecretValue
from app.setup.app import SetupWindow
from app.setup.fields.language_choice import LanguageDirectory
from app.setup.panels.keys_panel import KeysPanel
from app.setup.readiness import Readiness
from app.setup.tabs.channels_tab import ChannelsTab
from app.setup.tabs.keys_tab import SECRET_ECHO, KeyRowView, KeysTab
from app.setup.tabs.settings_tab import SettingsTab
from app.setup.tabs.tab_event import BREAK, KEYCODE_A, KEYCODE_C, KEYCODE_V, KEYCODE_X, EditShortcut, EditShortcuts, TkEvent
from app.setup.tabs.tab_layout import PAD
from app.setup.tabs.tab_shell import TabAction
from app.setup.tabs.tab_theme import SELECTED, TAB_STYLE, THEME
from app.tests.conftest import REPO_CHANNELS_EXAMPLE, SHIPPED_SETTINGS_FILE, SUPPLIED_VALUES
from app.tests.fixtures.config import channels_of
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.ui import messages_ru as msg

OWN_OPENAI_KEY: str = "sk-proj-own-Zy9xWvUtSrQpOnMlKjIhGfEdCbA9876543210"
BAD_OPENAI_KEY: str = "not-a-key"
OLD_FILE_LANGUAGES: tuple[str, ...] = ("ru", "en")   # channels.json до решения 21: у канала два языка
OWN_RANGE: str = "A:G"


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    """Окно на готовом корне: поставочный сейф на все поля, настройки поставки, каналы примера."""
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


@pytest.fixture
def two_languages_driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    """Окно на своём channels.json старого вида: у второго канала два языка (совместимость, §14 решение 21)."""
    data: dict[str, Any] = json.loads(ready_paths.channels_file.read_text(encoding="utf-8"))
    data["channels"][1]["languages"] = list(OLD_FILE_LANGUAGES)
    ready_paths.channels_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


@pytest.fixture
def bare_driver(livecraft_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    """Окно на чистой установке: ни сейфа, ни конфигов."""
    yield from SetupWindowDriver.opened(livecraft_paths, pytestconfig)


def _secret_values(panel: KeysPanel) -> set[str]:
    """Эталон теста: значения сейфа раскрывает тест, а не окно."""
    values: set[str] = set()
    for vault in (panel.supplied, panel.own, panel.vault):
        values.update(secret.reveal() for secret in vault.secrets())
    return values


def _row(driver: SetupWindowDriver, field: SecretField) -> KeyRowView:
    return driver.window.keys_tab.rows[field]


# --- «Ключи и ссылки»


def test_the_keys_tab_has_three_rows_with_hidden_input(driver: SetupWindowDriver) -> None:
    """Ссылки на форму на вкладке ключей нет: она открытая настройка (§14 решение 15)."""
    tab: KeysTab = driver.window.keys_tab
    assert len(tab.panel.rows) == 3
    assert tuple(tab.rows) == SecretField.current()
    for view in tab.rows.values():
        assert view.entry.cget("show") == SECRET_ECHO
    entries: list[tk.Misc] = [entry for entry in driver.widgets(tab.frame) if isinstance(entry, ttk.Entry)]
    assert all(entry.cget("show") == SECRET_ECHO for entry in entries)


def test_the_window_shows_no_vault_value(driver: SetupWindowDriver) -> None:
    """Обход всех виджетов окна: ни одного значения сейфа — только маски (§7.4)."""
    panel: KeysPanel = driver.window.keys_tab.panel
    values: set[str] = _secret_values(panel)
    assert len(values) == len(SecretField.current())
    texts: list[str] = driver.visible_texts()
    for row in panel.rows:
        assert row.display in texts                  # маска на месте…
    for value in values:
        assert not any(value in text for text in texts)   # …а значения нет нигде


def test_the_window_shows_no_value_after_an_own_key_is_accepted(driver: SetupWindowDriver) -> None:
    driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert not any(OWN_OPENAI_KEY in text for text in driver.visible_texts())


def test_a_good_own_key_becomes_own_and_clears_the_input(driver: SetupWindowDriver) -> None:
    tab: KeysTab = driver.window.keys_tab
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert view.origin.cget("text") == msg.VAULT_ORIGIN_OWN
    assert view.entry.get() == ""
    assert not tab.is_dirty                    # «Сохранить значение» записало сейф сразу
    assert not driver.window.is_dirty


def test_a_bad_own_key_shows_the_problem_and_keeps_the_input(driver: SetupWindowDriver) -> None:
    """Отказ модели: причина под полем, введённое остаётся — и оно несохранённое вкладки, а модель не менялась."""
    tab: KeysTab = driver.window.keys_tab
    problem: SettingProblem | None = tab.panel.replace(SecretField.OPENAI_API_KEY, BAD_OPENAI_KEY).problem
    assert problem is not None
    expected: str = problem.text
    view: KeyRowView = _row(driver, SecretField.OPENAI_API_KEY)
    driver.type(view.entry, BAD_OPENAI_KEY)
    view.accept_button.invoke()
    assert view.problem.text == expected
    assert view.entry.get() == BAD_OPENAI_KEY
    assert view.origin.cget("text") == msg.VAULT_ORIGIN_SUPPLIED
    assert not tab.panel.is_dirty
    assert tab.is_dirty


def _own_on_disk(paths: LivecraftPaths, field: SecretField) -> str | None:
    """Своё значение поля так, как его прочитает следующий запуск; значение раскрывает тест, а не окно."""
    secret: SecretValue | None = VaultStore.open(paths).load().own.get(field)
    return None if secret is None else secret.reveal()


def test_accepting_a_value_writes_the_own_vault_at_once(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    tab: KeysTab = driver.window.keys_tab
    assert not ready_paths.vault_local_file.exists()
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert ready_paths.vault_local_file.is_file()
    assert _own_on_disk(ready_paths, SecretField.OPENAI_API_KEY) == OWN_OPENAI_KEY
    assert not tab.is_dirty
    assert view.reset_button.winfo_manager() == "grid"        # своё значение можно сбросить к поставке


def test_a_second_value_changes_the_file_again(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    before: bytes = ready_paths.vault_local_file.read_bytes()
    driver.accept_key(SecretField.SHEETS_RANGE, OWN_RANGE)
    assert ready_paths.vault_local_file.read_bytes() != before
    assert _own_on_disk(ready_paths, SecretField.SHEETS_RANGE) == OWN_RANGE
    assert _own_on_disk(ready_paths, SecretField.OPENAI_API_KEY) == OWN_OPENAI_KEY


def test_the_keys_tab_has_no_common_save_button(driver: SetupWindowDriver) -> None:
    tab: KeysTab = driver.window.keys_tab
    assert not hasattr(tab, "buttons")
    buttons: list[str] = [str(widget.cget("text")) for widget in driver.widgets(tab.frame) if isinstance(widget, ttk.Button)]
    assert msg.SETUP_BUTTON_SAVE not in buttons
    assert buttons.count(msg.SETUP_KEYS_BUTTON_ACCEPT) == len(SecretField.current())


def test_deleting_the_own_value_is_written_at_once(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    view.reset_button.invoke()
    assert _own_on_disk(ready_paths, SecretField.OPENAI_API_KEY) is None
    assert view.origin.cget("text") == msg.VAULT_ORIGIN_SUPPLIED
    assert not driver.window.keys_tab.is_dirty


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
    assert view.origin.cget("text") == msg.VAULT_ORIGIN_SUPPLIED
    assert not driver.window.keys_tab.panel.is_dirty
    assert driver.window.keys_tab.is_dirty
    assert not ready_paths.vault_local_file.exists()


# --- «Каналы YouTube»


def test_a_channel_added_through_the_form_appears_in_the_table(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.window.channels_tab
    assert len(tab.tree.get_children()) == 2
    driver.fill_channel(
        account_name="Канал HU", handle="kanal_hu", google_account="owner@gmail.com", languages="hu",
        privacy="public",
    )
    driver.press_button(tab, TabAction.ADD)
    assert tab.edit_problem.text == ""
    children: tuple[str, ...] = tab.tree.get_children()
    assert len(children) == 3
    assert tab.tree.item(children[-1], "values")[1] == "@kanal_hu"
    assert tab.is_dirty
    assert not tab.variables.has_typed                  # набранное модель приняла


def test_a_channel_without_languages_shows_the_problem_with_the_field_label(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.window.channels_tab
    driver.fill_channel(account_name="Канал HU", handle="@kanal_hu", google_account="owner@gmail.com")
    assert tab.language.picker.codes == ()
    driver.press_button(tab, TabAction.ADD)
    assert tab.edit_problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_CHANNEL_FIELD_LABELS["languages"], text=msg.CONFIG_PROBLEM_LANGUAGES
    )
    assert len(tab.tree.get_children()) == 2


def test_selecting_a_row_fills_the_form(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.window.channels_tab
    tab.tree.selection_set("0")
    tab.fill_from_selection()
    assert tab.form_draft == tab.panel.drafts[0]
    assert not tab.is_dirty                              # показанное из модели — не набранное


def test_update_without_a_selection_says_so(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.window.channels_tab
    driver.press_button(tab, TabAction.UPDATE)
    assert tab.edit_problem.text == msg.SETUP_CHANNELS_NOTHING_SELECTED


def test_saving_the_channels_writes_channels_json(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    tab: ChannelsTab = driver.window.channels_tab
    driver.fill_channel(account_name="Канал HU", handle="@kanal_hu", google_account="owner@gmail.com", languages="hu")
    driver.press_button(tab, TabAction.ADD)
    driver.press_button(tab, TabAction.SAVE)
    assert channels_of(ready_paths.channels_file) == tab.panel.channels
    assert len(tab.panel.channels) == 3
    assert ready_paths.channels_previous_file.read_bytes() == REPO_CHANNELS_EXAMPLE.read_bytes()
    assert not tab.is_dirty


def test_removing_every_channel_shows_the_list_problem(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.window.channels_tab
    for _ in range(2):
        tab.tree.selection_set("0")
        driver.press_button(tab, TabAction.REMOVE)
    assert tab.tree.get_children() == ()
    assert tab.list_problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_CHANNEL_FIELD_LABELS["channels"], text=msg.CONFIG_PROBLEM_CHANNELS_EMPTY
    )


# --- «Настройки запуска»


def _settings_entry(driver: SetupWindowDriver, name: str) -> ttk.Entry:
    entry: ttk.Widget = driver.window.settings_tab.inputs[name]
    assert isinstance(entry, ttk.Entry)
    return entry


def test_a_changed_keep_days_is_saved(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    tab: SettingsTab = driver.window.settings_tab
    driver.type(_settings_entry(driver, "keep_days"), "14")
    assert tab.is_dirty
    driver.press_button(tab, TabAction.SAVE)
    assert SettingsFile(ready_paths.config_file).load().keep_days == 14
    assert tab.problem.text == ""
    assert not tab.is_dirty


def test_text_in_an_integer_field_shows_the_problem_and_keeps_the_file(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    tab: SettingsTab = driver.window.settings_tab
    driver.type(_settings_entry(driver, "min_lead_minutes"), "abc")
    driver.press_button(tab, TabAction.SAVE)
    assert tab.problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_SETTINGS_FIELD_LABELS["min_lead_minutes"], text=msg.CONFIG_PROBLEM_INT_MIN.format(minimum=0)
    )
    assert ready_paths.config_file.read_bytes() == SHIPPED_SETTINGS_FILE.read_bytes()
    assert tab.is_dirty


def test_the_form_url_is_an_open_field_that_saves(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    """Ссылка на форму — не секрет (§14 решение 15): обычное поле без маски, запись — в form.url."""
    tab: SettingsTab = driver.window.settings_tab
    entry: ttk.Entry = _settings_entry(driver, "form_url")
    assert entry.cget("show") == ""
    assert tab.hints["form_url"].cget("text") == msg.SETUP_SETTINGS_FIELD_HINTS["form.url"]
    driver.type(entry, "https://forms.gle/AbCdEf123456")
    driver.press_button(tab, TabAction.SAVE)
    assert tab.problem.text == ""
    assert SettingsFile(ready_paths.config_file).load().form.url == "https://forms.gle/AbCdEf123456"


def test_a_bad_form_url_shows_the_problem_and_keeps_the_file(driver: SetupWindowDriver, ready_paths: LivecraftPaths) -> None:
    tab: SettingsTab = driver.window.settings_tab
    driver.type(_settings_entry(driver, "form_url"), "http://forms.gle/AbCdEf123456")
    driver.press_button(tab, TabAction.SAVE)
    assert tab.problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_SETTINGS_FIELD_LABELS["form.url"], text=msg.CONFIG_PROBLEM_FORM_URL
    )
    assert ready_paths.config_file.read_bytes() == SHIPPED_SETTINGS_FILE.read_bytes()


def test_the_settings_widgets_follow_the_value_types(driver: SetupWindowDriver) -> None:
    inputs: dict[str, ttk.Widget] = driver.window.settings_tab.inputs
    assert isinstance(inputs["auto_start"], ttk.Checkbutton)
    assert isinstance(inputs["llm_reasoning_effort"], ttk.Combobox)
    assert str(inputs["llm_reasoning_effort"].cget("state")) == "readonly"
    assert tuple(inputs["llm_service_tier"].cget("values")) == tuple(tier.value for tier in ServiceTier)
    assert str(inputs["form_url"].cget("width")) == "64"


# --- строка готовности и закрытие


def test_the_readiness_line_on_a_ready_root_says_ready(driver: SetupWindowDriver) -> None:
    assert driver.window.readiness_line.cget("text") == msg.SETUP_READY


def test_the_readiness_line_on_a_clean_root_lists_the_problems(
    bare_driver: SetupWindowDriver, livecraft_paths: LivecraftPaths
) -> None:
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.problems
    assert bare_driver.window.readiness_line.cget("text") == readiness.window_line


def test_saving_refreshes_the_readiness_line(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> None:
    """Каналов нет — не готово; канал добавлен и сохранён — строка готовности обновилась сама."""
    ready_paths.channels_file.unlink()
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        window: SetupWindow = driver.window
        assert window.readiness_line.cget("text") != msg.SETUP_READY
        tab: ChannelsTab = window.channels_tab
        driver.fill_channel(account_name="Канал", handle="@kanal_hu", google_account="owner@gmail.com", languages="hu")
        driver.press_button(tab, TabAction.ADD)
        driver.press_button(tab, TabAction.SAVE)
        assert window.readiness_line.cget("text") == msg.SETUP_READY


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
    handle: ttk.Widget = driver.window.channels_tab.inputs["handle"]
    driver.type(handle, "@kanal_new")
    assert not driver.window.channels_tab.panel.is_dirty
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
    ready_paths.vault_local_file.write_bytes(b"\xff\xfe\x00vault\x80\x81")
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        tab: KeysTab = driver.window.keys_tab
        assert tab.panel.local_state is LocalVaultState.BROKEN
        assert msg.SETUP_KEYS_NOTICE_LOCAL_BROKEN in tab.notice.cget("text")
        assert tab.rows_frame.winfo_manager() != ""         # строки с кнопками записи есть
        assert set(tab.rows) == set(SecretField.current())
        assert not tab.is_dirty


def test_a_broken_supplied_vault_file_is_named_on_the_keys_tab(
    ready_paths: LivecraftPaths, pytestconfig: pytest.Config
) -> None:
    """Файл программы повреждён: вкладка называет файл и действие и не даёт править; окно открывается."""
    ready_paths.vault_file.write_bytes(b"\xff\xfe\x00vault\x80\x81")
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        tab: KeysTab = driver.window.keys_tab
        assert tab.panel.load_problem is not None
        assert tab.panel.rows == ()
        text: str = tab.notice.cget("text")
        assert ready_paths.vault_file.name in text and msg.VAULT_FILE_ADVICE_SUPPLIED in text
        assert tab.rows_frame.winfo_manager() == ""         # строк с кнопками записи нет
        assert not tab.is_dirty


# --- «показать своё» (§14 решение 11)


def _revealed_key(driver: SetupWindowDriver) -> KeyRowView:
    """Своё значение ключа OpenAI принято и показано по кнопке."""
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    view.reveal_button.invoke()
    assert view.is_revealed
    assert view.display.cget("text") == OWN_OPENAI_KEY
    return view


def _own_mask() -> str:
    return SecretValue(field=SecretField.OPENAI_API_KEY, value=OWN_OPENAI_KEY).masked


def _assert_masked(view: KeyRowView, mask: str) -> None:
    assert not view.is_revealed
    assert view.display.cget("text") == mask
    assert view.reveal_button.cget("text") == msg.SETUP_KEYS_BUTTON_REVEAL


def test_supplied_fields_have_no_reveal_button(driver: SetupWindowDriver) -> None:
    driver.window.root.update_idletasks()
    for view in driver.window.keys_tab.rows.values():
        assert view.reveal_button.grid_info() == {}
        assert not view.reveal_button.winfo_ismapped()


def test_the_reveal_button_of_a_supplied_field_reveals_nothing(driver: SetupWindowDriver) -> None:
    """Даже вызванная в обход окна, кнопка поставочного поля ничего не показывает."""
    view: KeyRowView = _row(driver, SecretField.OPENAI_API_KEY)
    mask: str = view.display.cget("text")
    view.reveal_button.invoke()
    _assert_masked(view, mask)


def test_an_own_field_gets_the_button_and_toggles_value_and_mask(driver: SetupWindowDriver) -> None:
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert view.reveal_button.grid_info() != {}
    _assert_masked(view, _own_mask())
    view.reveal_button.invoke()
    assert view.display.cget("text") == OWN_OPENAI_KEY
    assert view.reveal_button.cget("text") == msg.SETUP_KEYS_BUTTON_HIDE
    view.reveal_button.invoke()
    _assert_masked(view, _own_mask())
    for other in SecretField.current():
        if other is not SecretField.OPENAI_API_KEY:
            assert _row(driver, other).reveal_button.grid_info() == {}


def test_accepting_another_field_hides_the_value(driver: SetupWindowDriver) -> None:
    view: KeyRowView = _revealed_key(driver)
    driver.accept_key(SecretField.SHEETS_RANGE, OWN_RANGE)
    _assert_masked(view, _own_mask())


def test_a_refused_input_in_another_field_hides_the_value(driver: SetupWindowDriver) -> None:
    view: KeyRowView = _revealed_key(driver)
    other: KeyRowView = _row(driver, SecretField.SHEETS_RANGE)
    driver.type(other.entry, "не диапазон")
    other.accept_button.invoke()
    assert other.problem.text != ""
    _assert_masked(view, _own_mask())


def test_reset_hides_the_value(driver: SetupWindowDriver) -> None:
    view: KeyRowView = _revealed_key(driver)
    supplied: SecretValue | None = driver.window.keys_tab.panel.supplied.get(SecretField.OPENAI_API_KEY)
    assert supplied is not None
    supplied_mask: str = supplied.masked
    view.reset_button.invoke()
    _assert_masked(view, supplied_mask)
    assert view.reveal_button.grid_info() == {}


def test_the_written_own_value_keeps_its_reveal_button(driver: SetupWindowDriver) -> None:
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    _assert_masked(view, _own_mask())
    assert view.reveal_button.grid_info() != {}      # после записи поле по-прежнему своё


def test_leaving_the_keys_tab_hides_the_value(driver: SetupWindowDriver) -> None:
    view: KeyRowView = _revealed_key(driver)
    window: SetupWindow = driver.window
    window.notebook.select(window.channels_tab.frame)
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
        elif isinstance(widget, (ttk.Label, ttk.Button, ttk.Checkbutton)) and OWN_OPENAI_KEY in str(
            widget.cget("text")
        ):
            holders.append(widget)
    assert holders == [view.display]
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


def test_the_tab_titles_come_from_the_models(driver: SetupWindowDriver) -> None:
    window: SetupWindow = driver.window
    titles: list[str] = [str(window.notebook.tab(index, "text")) for index in range(window.notebook.index(tk.END))]
    assert titles == [msg.SETUP_TAB_KEYS, msg.SETUP_TAB_CHANNELS, msg.SETUP_TAB_SETTINGS]


@pytest.mark.parametrize("name", ["category_id", "image_dir_template"])
def test_the_settings_hint_is_shown_next_to_the_field(driver: SetupWindowDriver, name: str) -> None:
    tab: SettingsTab = driver.window.settings_tab
    hint: ttk.Label = tab.hints[name]
    assert hint.cget("text") == msg.SETUP_SETTINGS_FIELD_HINTS[name]
    assert hint.grid_info()["column"] == 2
    assert hint.grid_info()["row"] == tab.inputs[name].grid_info()["row"]


def test_every_settings_hint_belongs_to_a_known_field() -> None:
    assert set(msg.SETUP_SETTINGS_FIELD_HINTS) <= set(msg.SETUP_SETTINGS_FIELD_LABELS)


def test_the_folder_hint_keeps_its_braces_literal(driver: SetupWindowDriver) -> None:
    text: str = str(driver.window.settings_tab.hints["image_dir_template"].cget("text"))
    assert "{date}" in text and "{language}" in text


def test_the_keys_notice_names_no_storage_details(driver: SetupWindowDriver) -> None:
    notice: str = str(driver.window.keys_tab.notice.cget("text"))
    assert msg.SETUP_KEYS_NOTICE_PROTECTION in notice
    assert "не от специалиста" in notice              # оговорка §14 решения 6 — обязательна
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
        for value in SUPPLIED_VALUES.values():
            assert value not in field.human_label


# --- правка полей в любой раскладке
#
# На Windows keysym события Tk вычисляет по коду клавиши и раскладке уже при разборе привязок, а ключ
# `-keysym` у `event generate` служит только для поиска кода и отвергает буквы, которых нет в текущей
# раскладке. Поэтому настоящие нажатия в тестах — по коду клавиши (в латинской раскладке их берёт штатная
# привязка Tk, в чужой — EditShortcuts: вставка в обоих случаях одна), а ветки «латинская буква» и «чужая
# раскладка» проверяются ещё и через тот же обработчик событием, где keysym задан явно.

CLIPBOARD_TEXT: str = "@Pasted.Handle"
CHANNEL_TEXT: str = "Osvald.X"


class _KeyEvent(tk.Event):  # type: ignore[type-arg]
    """Событие клавиши, собранное тестом: виджет, код клавиши и keysym любой раскладки."""

    def __init__(self, widget: tk.Misc, keycode: int, keysym: str) -> None:
        self.widget = widget
        self.keycode = keycode
        self.keysym = keysym


def _channel_entry(driver: SetupWindowDriver) -> ttk.Entry:
    entry: ttk.Widget = driver.window.channels_tab.inputs["handle"]
    assert isinstance(entry, ttk.Entry)
    return entry


def _key_entry(driver: SetupWindowDriver) -> ttk.Entry:
    return _row(driver, SecretField.OPENAI_API_KEY).entry


def test_ctrl_v_pastes_into_a_channel_field_exactly_once(driver: SetupWindowDriver) -> None:
    entry: ttk.Entry = _channel_entry(driver)
    driver.type(entry, "")
    driver.put_in_clipboard(CLIPBOARD_TEXT)
    driver.focus(driver.window.channels_tab.frame, entry)
    driver.press(entry, KEYCODE_V)
    assert entry.get() == CLIPBOARD_TEXT


def test_ctrl_a_selects_the_whole_field(driver: SetupWindowDriver) -> None:
    entry: ttk.Entry = _channel_entry(driver)
    driver.type(entry, CHANNEL_TEXT)
    entry.selection_clear()
    driver.focus(driver.window.channels_tab.frame, entry)
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
    button: ttk.Button = driver.window.settings_tab.buttons[TabAction.SAVE]
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
    driver.focus(driver.window.keys_tab.frame, entry)
    driver.press(entry, KEYCODE_V)
    assert entry.get() == OWN_OPENAI_KEY
    driver.press(entry, KEYCODE_A)
    assert entry.selection_present()


def test_ctrl_c_in_a_key_field_leaves_the_clipboard_alone(driver: SetupWindowDriver) -> None:
    entry: ttk.Entry = _key_entry(driver)
    driver.type(entry, OWN_OPENAI_KEY)
    driver.put_in_clipboard(CLIPBOARD_TEXT)
    driver.focus(driver.window.keys_tab.frame, entry)
    entry.selection_range(0, tk.END)
    driver.press(entry, KEYCODE_C)
    entry.event_generate(TkEvent.COPY)
    driver.window.root.update()
    assert driver.window.root.clipboard_get() == CLIPBOARD_TEXT


def test_ctrl_x_in_a_key_field_cuts_nothing(driver: SetupWindowDriver) -> None:
    entry: ttk.Entry = _key_entry(driver)
    driver.type(entry, OWN_OPENAI_KEY)
    driver.put_in_clipboard(CLIPBOARD_TEXT)
    driver.focus(driver.window.keys_tab.frame, entry)
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
    driver.focus(driver.window.channels_tab.frame, entry)
    entry.selection_range(0, tk.END)
    driver.press(entry, KEYCODE_X)
    assert entry.get() == ""
    assert driver.window.root.clipboard_get() == CHANNEL_TEXT


# --- подпись кнопки сброса своего значения


def test_the_reset_button_over_the_supply_returns_the_program_value(driver: SetupWindowDriver) -> None:
    view: KeyRowView = driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert view.reset_button.cget("text") == msg.SETUP_KEYS_BUTTON_RESET_TO_SUPPLIED


def test_the_reset_button_without_supply_deletes_the_own_value(bare_driver: SetupWindowDriver) -> None:
    view: KeyRowView = bare_driver.accept_key(SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert view.reset_button.grid_info() != {}
    assert view.reset_button.cget("text") == msg.SETUP_KEYS_BUTTON_DELETE_OWN


def test_the_keys_notice_says_own_values_stay_on_this_computer(driver: SetupWindowDriver) -> None:
    text: str = str(driver.window.keys_tab.notice.cget("text"))
    assert "Свои значения и их сброс касаются только этого компьютера." in text


# --- ряды кнопок по центру


@pytest.mark.parametrize("tab_name", ["channels_tab", "settings_tab"])
def test_the_button_row_is_centred_without_stretching(driver: SetupWindowDriver, tab_name: str) -> None:
    frame: ttk.Frame = getattr(driver.window, tab_name).shell.buttons_frame
    info: dict[str, object] = frame.pack_info()
    assert (info["anchor"], info["fill"], info["side"]) == ("center", "none", "top")
    assert info["pady"] == PAD
    for button in frame.winfo_children():
        assert button.pack_info()["fill"] == "none"


def test_the_save_buttons_live_in_the_centred_rows(driver: SetupWindowDriver) -> None:
    window: SetupWindow = driver.window
    assert window.settings_tab.buttons[TabAction.SAVE].master is window.settings_tab.shell.buttons_frame
    assert window.channels_tab.buttons[TabAction.SAVE].master is window.channels_tab.shell.buttons_frame


# --- язык канала: одно выпадающее поле с поиском


def test_the_language_field_is_a_combobox_next_to_privacy_of_the_same_width(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.window.channels_tab
    box: ttk.Combobox = tab.language.box
    privacy: ttk.Widget = tab.inputs["privacy"]
    assert isinstance(box, ttk.Combobox) and isinstance(privacy, ttk.Combobox)
    assert box.master is tab.inputs["languages"]
    assert str(box.cget("width")) == str(privacy.cget("width"))
    assert box.master.grid_info()["column"] == privacy.grid_info()["column"]
    assert str(box.cget("state")) != "readonly"           # в поле можно печатать — это поиск
    assert not any(isinstance(widget, tk.Listbox) for widget in driver.widgets(tab.frame))


def test_picking_a_language_gives_the_draft_one_code(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.window.channels_tab
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
    tab: ChannelsTab = driver.window.channels_tab
    tab.tree.selection_set("0")
    tab.fill_from_selection()
    driver.window.root.update()
    assert not driver.is_language_list_open


def test_typing_does_not_change_the_draft_and_unknown_text_is_a_field_problem(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.window.channels_tab
    driver.pick_language("hu")
    driver.fill_channel(account_name="Канал HU", handle="@kanal_hu", google_account="owner@gmail.com")
    tab.language.box.set("венгерский язык")
    assert tab.form_draft.languages == ("hu",)               # набранный текст в черновик не уходит
    driver.press_button(tab, TabAction.ADD)
    assert tab.edit_problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_CHANNEL_FIELD_LABELS["languages"], text=msg.SETUP_LANGUAGE_PICK_FROM_LIST
    )
    assert len(tab.tree.get_children()) == 2


def test_escape_brings_back_the_chosen_language(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.window.channels_tab
    driver.pick_language("hu")
    tab.language.box.set("нем")
    tab.language.restore()
    assert tab.language.text.get() == tab.language.picker.directory.label_of("hu")
    assert tab.language.problem is None


def test_escape_is_bound_to_the_language_field(driver: SetupWindowDriver) -> None:
    assert driver.language.box.bind(TkEvent.ESCAPE)


def test_selecting_a_row_shows_the_channel_language(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.window.channels_tab
    tab.tree.selection_set("0")
    tab.fill_from_selection()
    assert tab.language.text.get() == tab.language.picker.directory.label_of("uk")
    assert tab.form_draft.languages == ("uk",)
    assert tab.language.note.text == ""


def test_a_channel_with_two_languages_keeps_the_first_on_save(
    two_languages_driver: SetupWindowDriver, ready_paths: LivecraftPaths
) -> None:
    """Канал старого файла записан с двумя языками: показан первый, строка о лишних; после сохранения — один код."""
    tab: ChannelsTab = two_languages_driver.window.channels_tab
    tab.tree.selection_set("1")
    tab.fill_from_selection()
    assert tab.language.text.get() == tab.language.picker.directory.label_of("ru")
    assert tab.language.note.text == msg.SETUP_LANGUAGE_SEVERAL.format(name="русский")
    assert not tab.is_dirty                                  # строка только показана, правки ещё нет
    two_languages_driver.press_button(tab, TabAction.UPDATE)
    two_languages_driver.press_button(tab, TabAction.SAVE)
    assert tab.edit_problem.text == ""
    assert channels_of(ready_paths.channels_file)[1].languages == ("ru",)


def test_picking_another_language_clears_the_several_languages_line(two_languages_driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = two_languages_driver.window.channels_tab
    tab.tree.selection_set("1")
    tab.fill_from_selection()
    two_languages_driver.pick_language("en")
    assert tab.language.note.text == ""
    assert tab.form_draft.languages == ("en",)


def test_the_form_languages_come_first_and_marked(driver: SetupWindowDriver) -> None:
    directory: LanguageDirectory = driver.language.picker.directory
    form_codes: tuple[str, ...] = tuple(SettingsFile(driver.window.paths.config_file).load().form.values["language"])
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
    tab: ChannelsTab = driver.window.channels_tab
    driver.fill_channel(account_name="Канал DE", handle="@kanal_de", google_account="owner@gmail.com", languages="de")
    driver.press_button(tab, TabAction.ADD)
    driver.press_button(tab, TabAction.SAVE)
    assert tab.edit_problem.text == ""
    assert channels_of(ready_paths.channels_file)[-1].languages == ("de",)


def test_the_table_shows_language_names(driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = driver.window.channels_tab
    column: int = list(tab.tree.cget("columns")).index("languages")
    assert tab.tree.item("0", "values")[column] == "украинский"
    assert tab.tree.item("1", "values")[column] == "русский"


def test_the_table_shows_every_language_of_an_old_file(two_languages_driver: SetupWindowDriver) -> None:
    tab: ChannelsTab = two_languages_driver.window.channels_tab
    column: int = list(tab.tree.cget("columns")).index("languages")
    assert tab.tree.item("1", "values")[column] == "русский, английский"


def test_saving_new_form_languages_updates_the_marks_without_reopening(driver: SetupWindowDriver) -> None:
    """Форма сменилась на вкладке настроек — пометки и предупреждение на вкладке каналов сразу новые."""
    tab: ChannelsTab = driver.window.channels_tab
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
    ready_paths.config_file.write_text("{", encoding="utf-8")
    for driver in SetupWindowDriver.opened(ready_paths, pytestconfig):
        assert not driver.language.picker.directory.has_form
        assert len(driver.box_values()) == len(LanguageDirectory.load(()).options)
        driver.pick_language("de")
        assert driver.language.warning.text == ""
