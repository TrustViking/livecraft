"""Окно настройщика в тестах: открыть, найти виджеты, набрать и выбрать так, как это делает человек.

Окно создаётся и прячется (withdraw); кнопки нажимаются через invoke. Окно без рабочего стола не создаётся —
такой прогон падает с TclError, а не пропускается: настройщик на машине оператора обязан открываться.
"""
from __future__ import annotations

import dataclasses
import time
import tkinter as tk
from collections.abc import Iterator
from datetime import datetime, timezone
from tkinter import ttk

import pytest

from app.config.files import SettingsFile
from app.config.settings import FormQuestion, FormSettings, LivecraftSettings
from app.core.clock import Clock
from app.llm.backend import LlmBackend
from app.paths import LivecraftPaths
from app.secretsafe.field import SecretField
from app.secretsafe.network_time import NetworkTime
from app.setup.app import SetupWindow
from app.setup.page import SetupPage
from app.setup.panels.channels_check import ChannelsCheck
from app.setup.panels.folder_check import FolderCheck
from app.setup.panels.form_check import FormCheck
from app.setup.panels.llm_key_check import LlmKeyCheck
from app.setup.panels.logs_panel import LogsPanel
from app.setup.panels.table_check import TableCheck
from app.setup.panels.token_panel import TokenPanel
from app.run.mode import RunPart
from app.setup.tabs.channels_tab import ChannelsTab
from app.setup.tabs.check_line import CheckLine
from app.setup.tabs.folder_block import FolderBlock
from app.setup.tabs.key_rows import KeyRowView
from app.setup.tabs.language_box import LanguageBox
from app.setup.tabs.logs_tab import LogsTab
from app.setup.tabs.chat_block import LISTBOX_SELECT
from app.setup.tabs.publish_tab import PublishTab
from app.setup.tabs.settings_section import SettingsSection
from app.setup.tabs.setup_tabs import SetupTabs
from app.setup.tabs.tab_event import TkEvent
from app.setup.tabs.table_block import TableBlock
from app.setup.tabs.tab_shell import TabAction
from app.setup.tabs.toggle_switch import ToggleSwitch
from app.setup.tabs.tokens_tab import TokensTab
from app.tests.fixtures.broadcasts import BroadcastBench, form_page
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.drive import FakeDriveService, drive_client
from app.tests.fixtures.form import FakeForms
from app.tests.fixtures.merges import QueueBackend
from app.tests.fixtures.sheets import FakeSheetsReader
from app.tests.fixtures.telegram import FakeTelegram
from app.tests.fixtures.token import FakePicker, network_at

CAPTURE_OPTION: str = "capture"
FD_CAPTURE: str = "fd"
FD_CAPTURE_PROBLEM: str = "окно Tk под --capture=fd ломает стандартные каналы Tcl: нужен перехват из pytest.ini"
OFF_SCREEN: str = "+-10000+-10000"
TABLE_CHECK_TIMEOUT_SEC: float = 10.0
LOGS_MOMENT: datetime = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)   # 15:00 по Киеву


class SetupWindowDriver:
    """Окно настройщика и действия человека в нём: набрать, выбрать, нажать, закрыть."""

    def __init__(self, window: SetupWindow) -> None:
        self.window: SetupWindow = window

    @classmethod
    def opened(cls, paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
        """Окно создаётся и прячется; после теста разрушается, если его не закрыл сам тест.

        Tcl берёт описатели ОС стандартных потоков своими стандартными каналами один раз на поток и держит их до
        конца процесса. Перехват pytest на уровне дескрипторов (--capture=fd) на каждой паузе и возобновлении
        делает dup2 на 0–2 и тем закрывает эти описатели; Windows отдаёт их номера следующим открытым файлам, и
        очередное окно не читает init.tcl. Поэтому pytest.ini в корне ставит перехват на уровне sys, а под
        --capture=fd окно не создаётся: тест падает с этой причиной, а не случайной TclError в другом тесте.
        """
        assert pytestconfig.getoption(CAPTURE_OPTION) != FD_CAPTURE, FD_CAPTURE_PROBLEM
        window: SetupWindow = SetupWindow(paths)
        window.root.withdraw()
        driver: SetupWindowDriver = cls(window)
        driver.read_table(FakeSheetsReader())          # к Google тесты не ходят: и проверка таблицы тоже
        driver.check_key_on(QueueBackend(probe_kind=None))      # к OpenAI тоже: ключ проверяет подделка
        driver.check_form_on(FakeForms.answering(form_page()), FakeSheetsReader())
        driver.check_channels_on(BroadcastBench(paths))         # к YouTube тоже: каналы — на подделке площадки
        driver.check_folder_on(FakeDriveService())              # к Google Диску тоже: папку проверяет подделка
        driver.tokens_on(network_at())                          # время для токена — от подделки, не от Google
        driver.logs_on()                                        # момент архива логов — от остановленных часов
        try:
            yield driver
        finally:
            if not window.is_closed:
                window.close()

    @property
    def tabs(self) -> SetupTabs:
        return self.window.tabs

    @property
    def channels(self) -> ChannelsTab:
        """Вкладка «Эфиры YouTube»: каналы и настройки эфира."""
        return self.window.tabs.broadcasts

    @property
    def telegram(self) -> PublishTab:
        return self.window.tabs.telegram

    @property
    def language(self) -> LanguageBox:
        return self.channels.language

    def widgets(self, root: tk.Misc | None = None) -> Iterator[tk.Misc]:
        """Все виджеты окна (или `root`) вглубь."""
        for child in (self.window.root if root is None else root).winfo_children():
            yield child
            yield from self.widgets(child)

    def visible_texts(self) -> list[str]:
        """Всё, что окно показывает человеку: подписи, кнопки, поля ввода, строки таблиц, вкладки и заголовок."""
        window: SetupWindow = self.window
        texts: list[str] = [window.root.title()]
        texts.extend(str(window.notebook.tab(index, "text")) for index in range(window.notebook.index(tk.END)))
        for widget in self.widgets():
            if isinstance(widget, (ttk.Label, ttk.Button, ttk.Radiobutton, tk.Label, tk.Button)):
                texts.append(str(widget.cget("text")))
            if isinstance(widget, (ttk.Entry, tk.Entry)):     # ttk.Combobox — тоже Entry
                texts.append(widget.get())
            if isinstance(widget, ttk.Treeview):
                for item in widget.get_children():
                    texts.extend(str(value) for value in widget.item(item, "values"))
        return texts

    def type(self, entry: ttk.Entry, text: str) -> None:
        """Поле ввода целиком заменено текстом."""
        entry.delete(0, tk.END)
        entry.insert(0, text)

    def box_values(self) -> tuple[str, ...]:
        """Значения выпадающего поля языка — как их покажет список поля."""
        box: ttk.Combobox = self.language.box
        return tuple(box.tk.splitlist(box.cget("values")))

    def pick_language(self, code: str) -> None:
        """Выбор языка так, как это делает человек: печать кода в поле сужает список, затем выбор строки списка."""
        box: ttk.Combobox = self.language.box
        box.set(code)
        [label] = [label for label in self.box_values() if self.language.picker.directory.code_of(label) == code]
        box.set(label)
        box.event_generate(TkEvent.COMBOBOX_SELECTED)

    def fill_channel(self, **values: str) -> None:
        """Поля канала; язык — кодом, он выбирается в выпадающем поле."""
        tab: ChannelsTab = self.channels
        for name, value in values.items():
            if name == "languages":
                self.pick_language(value)
                continue
            widget: ttk.Widget = tab.inputs[name]
            if isinstance(widget, ttk.Combobox):
                widget.set(value)
            else:
                self.type(widget, value)

    def press_button(self, tab: ChannelsTab, action: TabAction) -> None:
        tab.buttons[action].invoke()

    def key_view(self, field: SecretField) -> KeyRowView:
        """Строка поля сейфа — на той вкладке, где оно вводится («Таблица плана», «Нейросеть», «Telegram», «Логи»;
        папка Диска — на «Превью»)."""
        rows: dict[SecretField, KeyRowView] = {**self.tabs.plan.rows, **self.tabs.merge.rows, **self.telegram.rows}
        return {**rows, **self.logs.rows, **self.folder.keys.rows}[field]

    @property
    def sections(self) -> tuple[SettingsSection, ...]:
        """Разделы настроек всех вкладок."""
        return (
            self.tabs.merge.model, self.tabs.previews.local, self.tabs.previews.drive, self.tabs.doc.doc,
            self.channels.settings, self.tabs.advanced.section,
        )

    def section_of(self, name: str) -> SettingsSection:
        """Раздел настроек, в котором поле черновика `name`."""
        return next(section for section in self.sections if name in section.inputs)

    def settings_input(self, name: str) -> tk.Widget:
        """Поле настройки `name` — на вкладке своей линии."""
        return self.section_of(name).inputs[name]

    def switch(self, part: RunPart) -> ToggleSwitch:
        """Ползунок линии на «Главной»."""
        return self.tabs.home.lines[part].switch

    def accept_key(self, field: SecretField, value: str) -> KeyRowView:
        """Своё значение поля сейфа введено и принято кнопкой строки."""
        view: KeyRowView = self.key_view(field)
        self.type(view.entry, value)
        view.accept_button.invoke()
        assert view.problem.text == ""
        return view

    def focus(self, tab_frame: ttk.Frame, entry: ttk.Entry) -> None:
        """Окно за краем экрана, вкладка выбрана, фокус в поле: нажатие Tk доставляет только в поле с фокусом."""
        root: tk.Tk = self.window.root
        root.geometry(OFF_SCREEN)
        root.deiconify()
        self.window.notebook.select(tab_frame)
        root.update()
        entry.focus_force()
        root.update()
        assert root.focus_get() is entry

    def show(self, tab_frame: ttk.Frame, size: str) -> None:
        """Окно размера `size` («ширинаxвысота») за краем экрана, вкладка выбрана; раскладка и пересчёт страниц
        вкладок (отложенный до паузы окна) прошли."""
        root: tk.Tk = self.window.root
        root.geometry(size + OFF_SCREEN)
        root.deiconify()
        self.window.notebook.select(tab_frame)
        root.update()
        root.update()

    def press(self, entry: ttk.Entry, keycode: int) -> None:
        entry.event_generate(TkEvent.CONTROL_KEY_PRESS, keycode=keycode)
        self.window.root.update()

    def put_in_clipboard(self, text: str) -> None:
        root: tk.Tk = self.window.root
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update()

    def type_language(self, text: str) -> None:
        """Человек печатает в поле языка по букве: пока список закрыт, буква идёт в поле; раскрытый список
        забирает клавиатуру себе, и букву поле получает от списка."""
        box: ttk.Combobox = self.language.box
        self.focus(self.channels.frame, box)
        for char in text:
            if self.is_language_list_open:
                self.language.forward_key(char, char)
            else:
                box.insert(tk.INSERT, char)
            self.window.root.update()

    @property
    def is_language_list_open(self) -> bool:
        box: ttk.Combobox = self.language.box
        return bool(box.tk.getboolean(box.tk.call("winfo", "ismapped", self.language.listbox)))

    @property
    def language_list(self) -> tuple[str, ...]:
        """Строки раскрытого списка языков."""
        box: ttk.Combobox = self.language.box
        return tuple(box.tk.splitlist(box.tk.call(self.language.listbox, "get", 0, tk.END)))

    def save_form_languages(self, languages: dict[str, str]) -> None:
        """Варианты языка формы сменились в livecraft.json (контракт формы в окне не правится — он приходит с файлом),
        и человек жмёт «Сохранить» на вкладке «Дополнительно»: окно перечитывает файл без перезапуска."""
        section: SettingsSection = self.tabs.advanced.section
        file: SettingsFile = SettingsFile.of(self.window.paths)
        settings: LivecraftSettings = file.load()
        values: dict[str, dict[str, str]] = {**settings.form.values, FormQuestion.LANGUAGE.value: languages}
        form: FormSettings = dataclasses.replace(settings.form, values=values)
        file.save(dataclasses.replace(settings, form=form))
        section.save_button.invoke()
        assert section.problem.text == ""

    @property
    def table(self) -> TableBlock:
        return self.tabs.plan.table

    def read_table(self, reader: FakeSheetsReader, clock: Clock | None = None) -> None:
        """Проверка таблицы на вкладке «Таблица плана» читает подделку, а не Google; часы — свои, если заданы."""
        check: TableCheck = TableCheck(paths=self.window.paths, door=reader)
        self.table.check = check if clock is None else dataclasses.replace(check, clock=clock)

    def wait_for_table_check(self) -> None:
        """Окно крутит свои события, пока фоновая проверка таблицы не отдаст итог (как это делает цикл окна)."""
        self.wait_for(self.table.line)

    @property
    def folder(self) -> FolderBlock:
        return self.tabs.previews.folder

    @property
    def doc_folder(self) -> FolderBlock:
        """То же поле папки Диска на вкладке «Google-документ»."""
        return self.tabs.doc.folder

    def check_folder_on(self, service: FakeDriveService) -> None:
        """Проверка папки на вкладках «Превью» и «Google-документ» спрашивает подделку Диска, а не Google."""
        check: FolderCheck = FolderCheck(paths=self.window.paths, open_drive=lambda on_login: drive_client(service))
        self.folder.check = check
        self.doc_folder.check = check

    def wait_for_folder_check(self) -> None:
        """Окно крутит свои события, пока фоновая проверка папки не отдаст итог."""
        self.wait_for(self.folder.line)

    def wait_for(self, line: CheckLine) -> None:
        """Окно крутит свои события, пока фоновая проверка строки `line` не отдаст итог (как это делает цикл окна)."""
        deadline: float = time.monotonic() + TABLE_CHECK_TIMEOUT_SEC
        while line.is_running:
            assert time.monotonic() < deadline, "проверка не закончилась"
            self.window.root.update()
            time.sleep(0.01)

    def check_key_on(self, backend: LlmBackend) -> None:
        """Проверка ключа на «Нейросети» спрашивает подделку нейросети, а не OpenAI."""
        self.tabs.merge.check = LlmKeyCheck(paths=self.window.paths, open_backend=lambda vault, settings: backend)

    def check_form_on(self, forms: FakeForms, reader: FakeSheetsReader) -> None:
        """Проверка формы на «Ключах в форму» читает подделку формы и подделку таблицы, а не Google."""
        paths: LivecraftPaths = self.window.paths
        table: TableCheck = TableCheck(paths=paths, door=reader)
        self.tabs.form.check = FormCheck(table=table, open_forms=lambda clock: forms.book(paths.logs_dir))

    def check_channels_on(self, bench: BroadcastBench) -> None:
        """Вход и проверка каналов на «Эфирах YouTube» — на подделке площадки стенда, а не на YouTube."""
        self.channels.check = ChannelsCheck(
            paths=self.window.paths, open_services=lambda paths, settings, console: bench.services_on(console)
        )

    @property
    def tokens(self) -> TokensTab:
        return self.window.tabs.tokens

    def tokens_on(self, network: NetworkTime, picker: FakePicker | None = None) -> None:
        """Вкладка «Токены» спрашивает время у подделки сети и, если дан `picker`, выбирает файлы без диалогов."""
        self.tokens.panel = TokenPanel(paths=self.window.paths, network=network)
        if picker is not None:
            self.tokens.picker = picker  # type: ignore[assignment]

    @property
    def logs(self) -> LogsTab:
        return self.window.tabs.logs

    def logs_on(self) -> None:
        """Вкладка «Логи» берёт момент архива у остановленных часов."""
        self.logs.panel = LogsPanel(paths=self.window.paths, clock=StoppedClock.at(LOGS_MOMENT))

    def logs_talk_to(self, fake: FakeTelegram) -> None:
        """Вкладка «Логи» говорит с подделкой Telegram: и подключение чата поддержки, и отправка архива."""
        self.logs.bot_source = lambda: fake.bot

    def talk_to(self, fake: FakeTelegram) -> None:
        """Вкладка «Telegram» говорит с подделкой Telegram, а не с настоящим: к Bot API тесты не ходят."""
        self.telegram.bot_source = lambda: fake.bot

    def catch_opened(self) -> list[str]:
        """Адреса, которые вкладка «Telegram» открыла бы в браузере, — в список, а не в браузер."""
        opened: list[str] = []
        self.telegram.opener = opened.append
        return opened

    def go(self, part: RunPart) -> None:
        """«Перейти» у строки линии на «Главной»."""
        button: ttk.Button | None = self.tabs.home.lines[part].go_button
        assert button is not None
        button.invoke()

    @property
    def selected_page(self) -> SetupPage:
        """Какая вкладка открыта."""
        selected: str = str(self.window.notebook.select())
        return next(tab.page for tab in self.tabs.all if str(tab.frame) == selected)

    def pick_chat(self, index: int) -> None:
        """Выбор строки списка найденных чатов так, как это делает человек: вкладка видна (окно за краем экрана —
        список Tk шлёт событие выбора только показанным), выделение и событие выбора."""
        root: tk.Tk = self.window.root
        root.geometry(OFF_SCREEN)
        root.deiconify()
        self.window.notebook.select(self.telegram.frame)
        root.update()
        chat_list: tk.Listbox = self.telegram.chat.chat_list
        chat_list.selection_clear(0, tk.END)
        chat_list.selection_set(index)
        chat_list.event_generate(LISTBOX_SELECT)
        root.update()

    @property
    def chat_lines(self) -> tuple[str, ...]:
        chat_list: tk.Listbox = self.telegram.chat.chat_list
        return tuple(str(line) for line in chat_list.get(0, tk.END))
