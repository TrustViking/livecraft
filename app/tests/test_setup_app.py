"""Окно настройщика по-настоящему: Tk создаётся и прячется (withdraw), кнопки нажимаются через invoke.

Окно без рабочего стола не создаётся — такой прогон падает с TclError, а не пропускается: настройщик
на машине оператора обязан открываться.
"""
from __future__ import annotations

import logging
import tkinter as tk
from collections.abc import Iterator
from tkinter import font, messagebox, ttk

import pytest

from app.config.loader import load_channels, load_settings
from app.paths import LivecraftPaths
from app.secretsafe.value import SecretField, SecretValue
from app.setup.app import SELECTED, TAB_STYLE, THEME, SetupWindow
from app.setup.panels.keys_panel import KeysPanel
from app.setup.readiness import Readiness
from app.setup.tabs import (
    BREAK,
    COPY_EVENT,
    CUT_EVENT,
    KEYCODE_A,
    KEYCODE_C,
    KEYCODE_V,
    KEYCODE_X,
    PASTE_EVENT,
    EditShortcut,
    EditShortcuts,
)
from app.setup.tabs.channels_tab import ChannelsTab
from app.setup.tabs.keys_tab import SECRET_ECHO, KeyRowView, KeysTab
from app.setup.tabs.settings_tab import SettingsTab
from app.tests.conftest import REPO_CHANNELS_EXAMPLE, SHIPPED_SETTINGS_FILE, SUPPLIED_VALUES
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


def test_the_keys_tab_has_three_rows_with_hidden_input(window: SetupWindow) -> None:
    """Ссылки на форму на вкладке ключей нет: она открытая настройка (§14 решение 15)."""
    tab: KeysTab = window.keys_tab
    assert tab.panel is not None
    assert len(tab.panel.rows) == 3
    assert tuple(tab.rows) == SecretField.current()
    for view in tab.rows.values():
        assert view.entry.cget("show") == SECRET_ECHO
    assert all(entry.cget("show") == SECRET_ECHO for entry in _widgets(tab.frame) if isinstance(entry, ttk.Entry))


def test_the_window_shows_no_vault_value(window: SetupWindow) -> None:
    """Обход всех виджетов окна: ни одного значения сейфа — только маски (§7.4)."""
    panel: KeysPanel | None = window.keys_tab.panel
    assert panel is not None
    values: set[str] = _secret_values(panel)
    assert len(values) == len(SecretField.current())
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
    assert ready_paths.config_file.read_bytes() == SHIPPED_SETTINGS_FILE.read_bytes()
    assert tab.is_dirty


def test_the_form_url_is_an_open_field_that_saves(window: SetupWindow, ready_paths: LivecraftPaths) -> None:
    """Ссылка на форму — не секрет (§14 решение 15): обычное поле без маски, запись — в form.url."""
    tab: SettingsTab = window.settings_tab
    entry: ttk.Widget = tab.inputs["form_url"]
    assert isinstance(entry, ttk.Entry)
    assert entry.cget("show") == ""
    assert tab.hints["form_url"].cget("text") == msg.SETUP_SETTINGS_FIELD_HINTS["form.url"]
    _type(entry, "https://forms.gle/AbCdEf123456")
    tab.save_button.invoke()
    assert tab.problem.text == ""
    assert load_settings(ready_paths.config_file).form.url == "https://forms.gle/AbCdEf123456"


def test_a_bad_form_url_shows_the_problem_and_keeps_the_file(window: SetupWindow, ready_paths: LivecraftPaths) -> None:
    tab: SettingsTab = window.settings_tab
    entry: ttk.Widget = tab.inputs["form_url"]
    assert isinstance(entry, ttk.Entry)
    _type(entry, "http://forms.gle/AbCdEf123456")
    tab.save_button.invoke()
    assert tab.problem.text == msg.SETUP_PROBLEM_LINE.format(
        label=msg.SETUP_SETTINGS_FIELD_LABELS["form.url"], text=msg.CONFIG_PROBLEM_FORM_URL
    )
    assert ready_paths.config_file.read_bytes() == SHIPPED_SETTINGS_FILE.read_bytes()


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
    for other in SecretField.current():
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


# --- понятность окна (задача 2.3b, смотр окна 23-09-2026)

STORAGE_WORDS: tuple[str, ...] = ("vault", "DPAPI", "secrets", "внутри программы")


def _state_value(window: SetupWindow, option: str, state: str) -> object | None:
    """Значение опции вкладки для состояния из map стиля; нет такого состояния — None."""
    for *states, value in window.style.map(TAB_STYLE, option):
        if state in states:
            return value
    return None


def test_the_tabs_have_inner_padding(window: SetupWindow) -> None:
    padding: object = window.style.lookup(TAB_STYLE, "padding")
    assert padding not in ("", None, ())
    assert _state_value(window, "padding", SELECTED) not in ("", None, ())


def test_the_selected_tab_is_bold_and_on_another_background(window: SetupWindow) -> None:
    assert window.style.theme_use() == THEME          # тема Windows по умолчанию фон вкладки не берёт
    selected_font: object = _state_value(window, "font", SELECTED)
    assert selected_font is not None
    assert font.Font(root=window.root, font=selected_font).actual("weight") == font.BOLD
    normal_font: str = str(window.style.lookup(TAB_STYLE, "font"))
    assert font.Font(root=window.root, font=normal_font).actual("weight") == font.NORMAL
    selected_background: object = _state_value(window, "background", SELECTED)
    other_background: object = _state_value(window, "background", "!" + SELECTED)
    assert selected_background is not None and other_background is not None
    assert selected_background != other_background


def test_there_is_a_gap_between_the_tabs(window: SetupWindow) -> None:
    """Между соседними вкладками — полоса, которая не принадлежит ни одной вкладке."""
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


@pytest.mark.parametrize("name", ["category_id", "image_dir_template"])
def test_the_settings_hint_is_shown_next_to_the_field(window: SetupWindow, name: str) -> None:
    hint: ttk.Label = window.settings_tab.hints[name]
    assert hint.cget("text") == msg.SETUP_SETTINGS_FIELD_HINTS[name]
    assert hint.grid_info()["column"] == 2
    assert hint.grid_info()["row"] == window.settings_tab.inputs[name].grid_info()["row"]


def test_every_settings_hint_belongs_to_a_known_field() -> None:
    assert set(msg.SETUP_SETTINGS_FIELD_HINTS) <= set(msg.SETUP_SETTINGS_FIELD_LABELS)


def test_the_folder_hint_keeps_its_braces_literal(window: SetupWindow) -> None:
    text: str = str(window.settings_tab.hints["image_dir_template"].cget("text"))
    assert "{date}" in text and "{language}" in text


def test_the_keys_notice_names_no_storage_details(window: SetupWindow) -> None:
    notice: str = str(window.keys_tab.notice.cget("text"))
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



# --- правка полей в любой раскладке (задача 2.3d)
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


def _focus(window: SetupWindow, tab: ttk.Frame, entry: ttk.Entry) -> None:
    """Окно за краем экрана, вкладка выбрана, фокус в поле: нажатие Tk доставляет только в поле с фокусом."""
    window.root.geometry("+-10000+-10000")
    window.root.deiconify()
    window.notebook.select(tab)
    window.root.update()
    entry.focus_force()
    window.root.update()
    assert window.root.focus_get() is entry


def _press(window: SetupWindow, entry: ttk.Entry, keycode: int) -> None:
    entry.event_generate("<Control-KeyPress>", keycode=keycode)
    window.root.update()


def _put_in_clipboard(window: SetupWindow, text: str) -> None:
    window.root.clipboard_clear()
    window.root.clipboard_append(text)
    window.root.update()


def _channel_entry(window: SetupWindow) -> ttk.Entry:
    return window.channels_tab.inputs["handle"]


def _key_entry(window: SetupWindow) -> ttk.Entry:
    return _row(window.keys_tab, SecretField.OPENAI_API_KEY).entry


def test_ctrl_v_pastes_into_a_channel_field_exactly_once(window: SetupWindow) -> None:
    entry: ttk.Entry = _channel_entry(window)
    _type(entry, "")
    _put_in_clipboard(window, CLIPBOARD_TEXT)
    _focus(window, window.channels_tab.frame, entry)
    _press(window, entry, KEYCODE_V)
    assert entry.get() == CLIPBOARD_TEXT


def test_ctrl_a_selects_the_whole_field(window: SetupWindow) -> None:
    entry: ttk.Entry = _channel_entry(window)
    _type(entry, CHANNEL_TEXT)
    entry.selection_clear()
    _focus(window, window.channels_tab.frame, entry)
    _press(window, entry, KEYCODE_A)
    assert entry.selection_present()
    assert (entry.index(tk.SEL_FIRST), entry.index(tk.SEL_LAST)) == (0, len(CHANNEL_TEXT))


def test_a_cyrillic_keysym_pastes_through_the_shortcut_once(window: SetupWindow) -> None:
    entry: ttk.Entry = _channel_entry(window)
    _type(entry, "")
    _put_in_clipboard(window, CLIPBOARD_TEXT)
    answer: str | None = window.edit_shortcuts.handle(_KeyEvent(entry, KEYCODE_V, "Cyrillic_em"))
    window.root.update()
    assert answer == BREAK
    assert entry.get() == CLIPBOARD_TEXT


@pytest.mark.parametrize("keysym", ["v", "V"])
def test_a_latin_keysym_is_left_to_the_standard_binding(window: SetupWindow, keysym: str) -> None:
    """Латинскую букву Tk уже связал с <<Paste>>: обработчик не вмешивается, иначе вставка была бы двойной."""
    entry: ttk.Entry = _channel_entry(window)
    _type(entry, "")
    _put_in_clipboard(window, CLIPBOARD_TEXT)
    assert window.edit_shortcuts.handle(_KeyEvent(entry, KEYCODE_V, keysym)) is None
    window.root.update()
    assert entry.get() == ""


def test_every_shortcut_letter_is_bound_by_tk_to_its_event(window: SetupWindow) -> None:
    """Предпосылка правила «латинскую букву берёт Tk»: штатная связь есть у каждой из четырёх букв."""
    shortcuts: EditShortcuts = window.edit_shortcuts
    assert {shortcut.keycode for shortcut in shortcuts.shortcuts} == {KEYCODE_V, KEYCODE_A, KEYCODE_X, KEYCODE_C}
    for shortcut in shortcuts.shortcuts:
        assert f"<Control-Key-{shortcut.letter}>" in window.root.event_info(shortcut.virtual_event)


def test_the_shortcuts_leave_non_input_widgets_alone(window: SetupWindow) -> None:
    button: ttk.Button = window.keys_tab.save_button
    assert window.edit_shortcuts.handle(_KeyEvent(button, KEYCODE_V, "Cyrillic_em")) is None


def test_a_shortcut_matches_only_its_key_outside_the_latin_letter(window: SetupWindow) -> None:
    shortcut: EditShortcut = EditShortcut(KEYCODE_V, "v", PASTE_EVENT)
    entry: ttk.Entry = _channel_entry(window)
    assert shortcut.matches(_KeyEvent(entry, KEYCODE_V, "Cyrillic_em"))
    assert shortcut.matches(_KeyEvent(entry, KEYCODE_V, "??"))
    assert not shortcut.matches(_KeyEvent(entry, KEYCODE_V, "v"))
    assert not shortcut.matches(_KeyEvent(entry, KEYCODE_V, "V"))
    assert not shortcut.matches(_KeyEvent(entry, KEYCODE_C, "Cyrillic_es"))


def test_ctrl_v_and_ctrl_a_work_in_a_key_field(window: SetupWindow) -> None:
    entry: ttk.Entry = _key_entry(window)
    _put_in_clipboard(window, OWN_OPENAI_KEY)
    _focus(window, window.keys_tab.frame, entry)
    _press(window, entry, KEYCODE_V)
    assert entry.get() == OWN_OPENAI_KEY
    _press(window, entry, KEYCODE_A)
    assert entry.selection_present()


def test_ctrl_c_in_a_key_field_leaves_the_clipboard_alone(window: SetupWindow) -> None:
    entry: ttk.Entry = _key_entry(window)
    _type(entry, OWN_OPENAI_KEY)
    _put_in_clipboard(window, CLIPBOARD_TEXT)
    _focus(window, window.keys_tab.frame, entry)
    entry.selection_range(0, tk.END)
    _press(window, entry, KEYCODE_C)
    entry.event_generate(COPY_EVENT)
    window.root.update()
    assert window.root.clipboard_get() == CLIPBOARD_TEXT


def test_ctrl_x_in_a_key_field_cuts_nothing(window: SetupWindow) -> None:
    entry: ttk.Entry = _key_entry(window)
    _type(entry, OWN_OPENAI_KEY)
    _put_in_clipboard(window, CLIPBOARD_TEXT)
    _focus(window, window.keys_tab.frame, entry)
    entry.selection_range(0, tk.END)
    _press(window, entry, KEYCODE_X)
    entry.event_generate(CUT_EVENT)
    window.root.update()
    assert entry.get() == OWN_OPENAI_KEY
    assert window.root.clipboard_get() == CLIPBOARD_TEXT


def test_ctrl_x_still_cuts_in_a_channel_field(window: SetupWindow) -> None:
    """Запрет — только у полей ключей: остальные поля вырезают как обычно."""
    entry: ttk.Entry = _channel_entry(window)
    _type(entry, CHANNEL_TEXT)
    _focus(window, window.channels_tab.frame, entry)
    entry.selection_range(0, tk.END)
    _press(window, entry, KEYCODE_X)
    assert entry.get() == ""
    assert window.root.clipboard_get() == CHANNEL_TEXT


# --- подпись кнопки сброса своего значения


def test_the_reset_button_over_the_supply_returns_the_program_value(window: SetupWindow) -> None:
    view: KeyRowView = _accept(window, SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert view.reset_button.cget("text") == msg.SETUP_KEYS_BUTTON_RESET_TO_SUPPLIED


def test_the_reset_button_without_supply_deletes_the_own_value(bare_window: SetupWindow) -> None:
    view: KeyRowView = _accept(bare_window, SecretField.OPENAI_API_KEY, OWN_OPENAI_KEY)
    assert view.reset_button.grid_info() != {}
    assert view.reset_button.cget("text") == msg.SETUP_KEYS_BUTTON_DELETE_OWN


def test_the_keys_notice_says_own_values_stay_on_this_computer(window: SetupWindow) -> None:
    assert "Свои значения и их сброс касаются только этого компьютера." in str(window.keys_tab.notice.cget("text"))
