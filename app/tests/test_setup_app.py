"""Окно настройщика по-настоящему: Tk создаётся и прячется (withdraw), кнопки нажимаются через invoke.

Окно без рабочего стола не создаётся — такой прогон падает с TclError, а не пропускается: настройщик
на машине оператора обязан открываться.
"""
from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Iterator
from tkinter import messagebox, ttk

import pytest

from app.config.loader import load_channels, load_settings
from app.paths import LivecraftPaths
from app.secretsafe.value import SecretField, SecretValue
from app.setup.app import SetupWindow
from app.setup.panels.keys_panel import KeysPanel
from app.setup.readiness import Readiness
from app.setup.tabs.channels_tab import ChannelsTab
from app.setup.tabs.keys_tab import SECRET_ECHO, KeyRowView, KeysTab
from app.setup.tabs.settings_tab import SettingsTab
from app.tests.conftest import REPO_CHANNELS_EXAMPLE, REPO_SETTINGS_FILE
from app.ui import messages_ru as msg

OWN_OPENAI_KEY: str = "sk-proj-own-Zy9xWvUtSrQpOnMlKjIhGfEdCbA9876543210"
BAD_OPENAI_KEY: str = "not-a-key"


def _open(paths: LivecraftPaths, capsys: pytest.CaptureFixture[str]) -> Iterator[SetupWindow]:
    """Окно создаётся при приостановленном перехвате вывода pytest.

    На Windows pytest перехватывает вывод подменой дескрипторов 0–2, а вместе с ними — стандартных описателей
    процесса. Tcl при создании интерпретатора берёт эти описатели в свои стандартные каналы; pytest потом
    закрывает подменные файлы, Windows отдаёт их номера другим файлам, и следующее окно время от времени не
    читает init.tcl («couldn't read file … No error»). На время создания окна перехват выключен, и Tcl
    видит настоящие описатели консоли — как при боевом запуске. Всё остальное в тестах идёт с перехватом.
    """
    with capsys.disabled():
        window: SetupWindow = SetupWindow(paths)
    window.root.withdraw()
    try:
        yield window
    finally:
        if not window.is_closed:
            window.root.destroy()


@pytest.fixture
def window(ready_paths: LivecraftPaths, capsys: pytest.CaptureFixture[str]) -> Iterator[SetupWindow]:
    """Окно на готовом корне: поставочный сейф на все поля, настройки поставки, каналы примера."""
    yield from _open(ready_paths, capsys)


@pytest.fixture
def bare_window(livecraft_paths: LivecraftPaths, capsys: pytest.CaptureFixture[str]) -> Iterator[SetupWindow]:
    """Окно на чистой установке: ни сейфа, ни конфигов."""
    yield from _open(livecraft_paths, capsys)


def _widgets(root: tk.Misc) -> Iterator[tk.Misc]:
    for child in root.winfo_children():
        yield child
        yield from _widgets(child)


def _visible_texts(window: SetupWindow) -> list[str]:
    """Всё, что окно показывает человеку: подписи, кнопки, поля ввода, строки таблиц, вкладки и заголовок."""
    texts: list[str] = [window.root.title()]
    texts.extend(str(window.notebook.tab(index, "text")) for index in range(window.notebook.index(tk.END)))
    for widget in _widgets(window.root):
        if isinstance(widget, (ttk.Label, ttk.Button, ttk.Checkbutton, tk.Label, tk.Button)):
            texts.append(str(widget.cget("text")))
        if isinstance(widget, (ttk.Entry, tk.Entry)):     # ttk.Combobox — тоже Entry
            texts.append(widget.get())
        if isinstance(widget, ttk.Treeview):
            for item in widget.get_children():
                texts.extend(str(value) for value in widget.item(item, "values"))
    return texts


def _secret_values(panel: KeysPanel) -> set[str]:
    """Эталон теста: значения сейфа раскрывает тест, а не окно."""
    values: set[str] = set()
    for vault in (panel.supplied, panel.own, panel.vault):
        values.update(secret.reveal() for secret in vault.secrets())
    return values


def _row(tab: KeysTab, field: SecretField) -> KeyRowView:
    return tab.rows[field]


def _type(entry: ttk.Entry, text: str) -> None:
    entry.delete(0, tk.END)
    entry.insert(0, text)


def _fill_channel(tab: ChannelsTab, **values: str) -> None:
    for name, value in values.items():
        widget: ttk.Entry = tab.inputs[name]
        if isinstance(widget, ttk.Combobox):
            widget.set(value)
        else:
            _type(widget, value)


# --- «Ключи и ссылки»


def test_the_keys_tab_has_four_rows_with_hidden_input(window: SetupWindow) -> None:
    tab: KeysTab = window.keys_tab
    assert tab.panel is not None
    assert len(tab.panel.rows) == 4
    assert tuple(tab.rows) == tuple(SecretField)
    for view in tab.rows.values():
        assert view.entry.cget("show") == SECRET_ECHO
    assert all(entry.cget("show") == SECRET_ECHO for entry in _widgets(tab.frame) if isinstance(entry, ttk.Entry))


def test_the_window_shows_no_vault_value(window: SetupWindow) -> None:
    """Обход всех виджетов окна: ни одного значения сейфа — только маски (§7.4)."""
    panel: KeysPanel | None = window.keys_tab.panel
    assert panel is not None
    values: set[str] = _secret_values(panel)
    assert len(values) == len(SecretField)
    texts: list[str] = _visible_texts(window)
    for row in panel.rows:
        assert row.display in texts                  # маска на месте…
    for value in values:
        assert not any(value in text for text in texts)   # …а значения нет нигде


def test_the_window_shows_no_value_after_an_own_key_is_accepted(window: SetupWindow) -> None:
    view: KeyRowView = _row(window.keys_tab, SecretField.OPENAI_API_KEY)
    _type(view.entry, OWN_OPENAI_KEY)
    view.accept_button.invoke()
    texts: list[str] = _visible_texts(window)
    assert not any(OWN_OPENAI_KEY in text for text in texts)


def test_a_good_own_key_becomes_own_and_clears_the_input(window: SetupWindow) -> None:
    tab: KeysTab = window.keys_tab
    view: KeyRowView = _row(tab, SecretField.OPENAI_API_KEY)
    _type(view.entry, OWN_OPENAI_KEY)
    view.accept_button.invoke()
    assert view.origin.cget("text") == msg.VAULT_ORIGIN_OWN
    assert view.entry.get() == ""
    assert view.problem.text == ""
    assert tab.is_dirty
    assert window.is_dirty


def test_a_bad_own_key_shows_the_problem_and_keeps_the_input(window: SetupWindow) -> None:
    tab: KeysTab = window.keys_tab
    assert tab.panel is not None
    expected: str | None = tab.panel.replace(SecretField.OPENAI_API_KEY, BAD_OPENAI_KEY).problem
    view: KeyRowView = _row(tab, SecretField.OPENAI_API_KEY)
    _type(view.entry, BAD_OPENAI_KEY)
    view.accept_button.invoke()
    assert expected is not None
    assert view.problem.text == expected
    assert view.entry.get() == BAD_OPENAI_KEY
    assert view.origin.cget("text") == msg.VAULT_ORIGIN_SUPPLIED
    assert not tab.is_dirty


def test_saving_the_keys_writes_the_own_vault(window: SetupWindow, ready_paths: LivecraftPaths) -> None:
    tab: KeysTab = window.keys_tab
    view: KeyRowView = _row(tab, SecretField.OPENAI_API_KEY)
    _type(view.entry, OWN_OPENAI_KEY)
    view.accept_button.invoke()
    tab.save_button.invoke()
    assert ready_paths.vault_local_file.is_file()
    assert not tab.is_dirty
    assert view.reset_button.winfo_manager() == "grid"        # своё значение можно сбросить к поставке


# --- «Каналы YouTube»


def test_a_channel_added_through_the_form_appears_in_the_table(window: SetupWindow) -> None:
    tab: ChannelsTab = window.channels_tab
    assert len(tab.tree.get_children()) == 2
    _fill_channel(
        tab, account_name="Канал HU", handle="kanal_hu", google_account="owner@gmail.com", languages="hu",
        privacy="public",
    )
    tab.buttons["add"].invoke()
    assert tab.edit_problem.text == ""
    children: tuple[str, ...] = tab.tree.get_children()
    assert len(children) == 3
    assert tab.tree.item(children[-1], "values")[1] == "@kanal_hu"
    assert tab.is_dirty


def test_uppercase_languages_show_the_problem_with_the_field_label(window: SetupWindow) -> None:
    tab: ChannelsTab = window.channels_tab
    _fill_channel(tab, account_name="Канал HU", handle="@kanal_hu", google_account="owner@gmail.com", languages="UK")
    tab.buttons["add"].invoke()
    assert tab.edit_problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_CHANNEL_FIELD_LABELS["languages"], text=msg.CONFIG_PROBLEM_LANGUAGES
    )
    assert len(tab.tree.get_children()) == 2


def test_selecting_a_row_fills_the_form(window: SetupWindow) -> None:
    tab: ChannelsTab = window.channels_tab
    tab.tree.selection_set("1")
    tab.fill_from_selection()
    assert tab.form_draft == tab.panel.drafts[1]


def test_update_without_a_selection_says_so(window: SetupWindow) -> None:
    tab: ChannelsTab = window.channels_tab
    tab.buttons["update"].invoke()
    assert tab.edit_problem.text == msg.SETUP_CHANNELS_NOTHING_SELECTED


def test_saving_the_channels_writes_channels_json(window: SetupWindow, ready_paths: LivecraftPaths) -> None:
    tab: ChannelsTab = window.channels_tab
    _fill_channel(tab, account_name="Канал HU", handle="@kanal_hu", google_account="owner@gmail.com", languages="hu")
    tab.buttons["add"].invoke()
    tab.buttons["save"].invoke()
    assert load_channels(ready_paths.channels_file) == tab.panel.channels
    assert len(tab.panel.channels) == 3
    assert ready_paths.channels_previous_file.read_bytes() == REPO_CHANNELS_EXAMPLE.read_bytes()
    assert not tab.is_dirty


def test_removing_every_channel_shows_the_list_problem(window: SetupWindow) -> None:
    tab: ChannelsTab = window.channels_tab
    for _ in range(2):
        tab.tree.selection_set("0")
        tab.buttons["remove"].invoke()
    assert tab.tree.get_children() == ()
    assert tab.list_problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_CHANNEL_FIELD_LABELS["channels"], text=msg.CONFIG_PROBLEM_CHANNELS_EMPTY
    )


# --- «Настройки запуска»


def test_a_changed_keep_days_is_saved(window: SetupWindow, ready_paths: LivecraftPaths) -> None:
    tab: SettingsTab = window.settings_tab
    entry: ttk.Widget = tab.inputs["keep_days"]
    assert isinstance(entry, ttk.Entry)
    _type(entry, "14")
    assert tab.is_dirty
    tab.save_button.invoke()
    assert load_settings(ready_paths.config_file).keep_days == 14
    assert tab.problem.text == ""
    assert not tab.is_dirty


def test_text_in_an_integer_field_shows_the_problem_and_keeps_the_file(
    window: SetupWindow, ready_paths: LivecraftPaths
) -> None:
    tab: SettingsTab = window.settings_tab
    entry: ttk.Widget = tab.inputs["min_lead_minutes"]
    assert isinstance(entry, ttk.Entry)
    _type(entry, "abc")
    tab.save_button.invoke()
    assert tab.problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_SETTINGS_FIELD_LABELS["min_lead_minutes"], text=msg.CONFIG_PROBLEM_INT_MIN.format(minimum=0)
    )
    assert ready_paths.config_file.read_bytes() == REPO_SETTINGS_FILE.read_bytes()
    assert tab.is_dirty


def test_the_settings_widgets_follow_the_value_types(window: SetupWindow) -> None:
    inputs: dict[str, ttk.Widget] = window.settings_tab.inputs
    assert isinstance(inputs["auto_start"], ttk.Checkbutton)
    assert isinstance(inputs["llm_reasoning_effort"], ttk.Combobox)
    assert str(inputs["llm_reasoning_effort"].cget("state")) == "readonly"
    assert tuple(inputs["llm_service_tier"].cget("values")) == window.settings_tab.panel.service_tier_options


# --- строка готовности и закрытие


def test_the_readiness_line_on_a_ready_root_says_ready(window: SetupWindow) -> None:
    assert window.readiness_line.cget("text") == msg.SETUP_READY


def test_the_readiness_line_on_a_clean_root_lists_the_problems(
    bare_window: SetupWindow, livecraft_paths: LivecraftPaths
) -> None:
    problems: tuple[str, ...] = Readiness.check(livecraft_paths).problems
    assert problems
    assert bare_window.readiness_line.cget("text") == "\n".join(problems)


def test_saving_refreshes_the_readiness_line(ready_paths: LivecraftPaths, capsys: pytest.CaptureFixture[str]) -> None:
    """Каналов нет — не готово; канал добавлен и сохранён — строка готовности обновилась сама."""
    ready_paths.channels_file.unlink()
    for window in _open(ready_paths, capsys):
        assert window.readiness_line.cget("text") != msg.SETUP_READY
        tab: ChannelsTab = window.channels_tab
        _fill_channel(tab, account_name="Канал", handle="@kanal_hu", google_account="owner@gmail.com", languages="hu")
        tab.buttons["add"].invoke()
        tab.buttons["save"].invoke()
        assert window.readiness_line.cget("text") == msg.SETUP_READY


def _answer(monkeypatch: pytest.MonkeyPatch, answer: bool) -> list[str]:
    asked: list[str] = []

    def _askyesno(title: str, message: str, **_options: object) -> bool:
        asked.append(message)
        return answer

    monkeypatch.setattr(messagebox, "askyesno", _askyesno)
    return asked


def _make_dirty(window: SetupWindow) -> None:
    entry: ttk.Widget = window.settings_tab.inputs["keep_days"]
    assert isinstance(entry, ttk.Entry)
    _type(entry, "7")
    assert window.is_dirty


def test_closing_a_dirty_window_asks_and_no_keeps_it_open(
    window: SetupWindow, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[str] = _answer(monkeypatch, False)
    _make_dirty(window)
    window.request_close()
    assert asked == [msg.SETUP_CLOSE_DIRTY_TEXT]
    assert not window.is_closed
    assert window.root.winfo_exists()


def test_closing_a_dirty_window_asks_and_yes_closes_it(window: SetupWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = _answer(monkeypatch, True)
    _make_dirty(window)
    window.request_close()
    assert asked == [msg.SETUP_CLOSE_DIRTY_TEXT]
    assert window.is_closed


def test_closing_a_clean_window_does_not_ask(window: SetupWindow, monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = _answer(monkeypatch, True)
    window.request_close()
    assert asked == []
    assert window.is_closed


def test_the_close_button_of_the_window_goes_through_the_question(window: SetupWindow) -> None:
    assert str(window.root.protocol("WM_DELETE_WINDOW")).endswith("request_close")


def test_a_broken_vault_file_is_named_on_the_keys_tab(
    ready_paths: LivecraftPaths, capsys: pytest.CaptureFixture[str]
) -> None:
    """Файл сейфа чужого формата: вкладка называет причину и не даёт править; окно открывается."""
    ready_paths.vault_local_file.write_bytes(b"\xff\xfe\x00vault\x80\x81")
    for window in _open(ready_paths, capsys):
        tab: KeysTab = window.keys_tab
        assert tab.panel is None
        assert ready_paths.vault_local_file.name in tab.notice.cget("text")
        assert tab.save_button.instate(["disabled"])
        assert not tab.is_dirty


# --- «показать своё» (задача 2.3a, §14 решение 11)

OWN_RANGE: str = "A:G"


def _accept(window: SetupWindow, field: SecretField, value: str) -> KeyRowView:
    view: KeyRowView = _row(window.keys_tab, field)
    _type(view.entry, value)
    view.accept_button.invoke()
    assert view.problem.text == ""
    return view


def _revealed_key(window: SetupWindow) -> KeyRowView:
    """Своё значение ключа OpenAI принято и показано по кнопке."""
    view: KeyRowView = _accept(window, SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
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


def test_supplied_fields_have_no_reveal_button(window: SetupWindow) -> None:
    window.root.update_idletasks()
    for view in window.keys_tab.rows.values():
        assert view.reveal_button.grid_info() == {}
        assert not view.reveal_button.winfo_ismapped()


def test_the_reveal_button_of_a_supplied_field_reveals_nothing(window: SetupWindow) -> None:
    """Даже вызванная в обход окна, кнопка поставочного поля ничего не показывает."""
    view: KeyRowView = _row(window.keys_tab, SecretField.OPENAI_API_KEY)
    mask: str = view.display.cget("text")
    view.reveal_button.invoke()
    _assert_masked(view, mask)


def test_an_own_field_gets_the_button_and_toggles_value_and_mask(window: SetupWindow) -> None:
    view: KeyRowView = _accept(window, SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert view.reveal_button.grid_info() != {}
    _assert_masked(view, _own_mask())
    view.reveal_button.invoke()
    assert view.display.cget("text") == OWN_OPENAI_KEY
    assert view.reveal_button.cget("text") == msg.SETUP_KEYS_BUTTON_HIDE
    view.reveal_button.invoke()
    _assert_masked(view, _own_mask())
    for other in SecretField:
        if other is not SecretField.OPENAI_API_KEY:
            assert _row(window.keys_tab, other).reveal_button.grid_info() == {}


def test_accepting_another_field_hides_the_value(window: SetupWindow) -> None:
    view: KeyRowView = _revealed_key(window)
    _accept(window, SecretField.SHEETS_RANGE, OWN_RANGE)
    _assert_masked(view, _own_mask())


def test_a_refused_input_in_another_field_hides_the_value(window: SetupWindow) -> None:
    view: KeyRowView = _revealed_key(window)
    other: KeyRowView = _row(window.keys_tab, SecretField.SHEETS_RANGE)
    _type(other.entry, "не диапазон")
    other.accept_button.invoke()
    assert other.problem.text != ""
    _assert_masked(view, _own_mask())


def test_reset_hides_the_value(window: SetupWindow) -> None:
    view: KeyRowView = _revealed_key(window)
    panel: KeysPanel | None = window.keys_tab.panel
    assert panel is not None
    supplied: SecretValue | None = panel.supplied.get(SecretField.OPENAI_API_KEY)
    assert supplied is not None
    supplied_mask: str = supplied.masked
    view.reset_button.invoke()
    _assert_masked(view, supplied_mask)
    assert view.reveal_button.grid_info() == {}


def test_save_hides_the_value(window: SetupWindow) -> None:
    view: KeyRowView = _revealed_key(window)
    window.keys_tab.save_button.invoke()
    _assert_masked(view, _own_mask())
    assert view.reveal_button.grid_info() != {}      # после записи поле по-прежнему своё


def test_leaving_the_keys_tab_hides_the_value(window: SetupWindow) -> None:
    view: KeyRowView = _revealed_key(window)
    window.notebook.select(window.channels_tab.frame)
    window.notebook.event_generate("<<NotebookTabChanged>>")
    window.root.update()
    _assert_masked(view, _own_mask())


def test_the_revealed_value_goes_only_to_its_own_label(
    window: SetupWindow, caplog: pytest.LogCaptureFixture
) -> None:
    """Показанное значение — только в подписи своей строки: не в полях ввода, не в строке готовности, не в логе."""
    with caplog.at_level(logging.DEBUG):
        view: KeyRowView = _revealed_key(window)
        window.keys_tab.save_button.invoke()
        view.reveal_button.invoke()
    holders: list[tk.Misc] = []
    for widget in _widgets(window.root):
        if isinstance(widget, (ttk.Entry, tk.Entry)):     # ttk.Combobox — тоже Entry
            assert OWN_OPENAI_KEY not in widget.get()
        elif isinstance(widget, (ttk.Label, ttk.Button, ttk.Checkbutton)) and OWN_OPENAI_KEY in str(
            widget.cget("text")
        ):
            holders.append(widget)
    assert holders == [view.display]
    assert OWN_OPENAI_KEY not in window.readiness_line.cget("text")
    assert OWN_OPENAI_KEY not in window.root.title()
    assert not any(OWN_OPENAI_KEY in record.getMessage() for record in caplog.records)
