"""Вкладка окна «Каналы YouTube» поверх модели `ChannelsPanel` (CLAUDE.md §8.2 п.2).

Таблица каналов — строки модели (`drafts`), под ней форма из пяти полей черновика канала и кнопки.
Выбор строки заполняет форму; «добавить» и «изменить выбранный» отдают черновик модели, и ответ модели
заменяет вкладку либо называет проблему красной строкой с подписью поля. Своих правил у вкладки нет:
годность канала решает загрузчик внутри модели. Входа в канал и «проверить все» здесь нет (задача 2.4).

Языки канала выбираются из списка всех языков по названию (`LanguageCatalog`): строка поиска и список с
множественным выбором; поиск выбор не сбрасывает (`LanguageSelection`). Языки Google-формы — первыми и с
пометкой; они берутся из прочитанных настроек, а не прочитались настройки — список полный, но без пометок.
Язык не из формы вкладка называет сразу строкой-предупреждением: сохранению это не мешает, но эфиры на нём
допущены не будут (§6 инвариант 2). В таблице каналов языки показаны названиями; черновик получает коды, как
и прежде. Ряд кнопок — по центру окна.
"""
from __future__ import annotations

import dataclasses
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Final

from app.config.loader import ConfigError, load_settings
from app.paths import LivecraftPaths
from app.setup.fields.channel_draft import ChannelDraft
from app.setup.fields.language_choice import LanguageCatalog, LanguageOption, LanguageSelection
from app.setup.panels.channels_panel import ChannelsPanel, ChannelsPanelEdit
from app.setup.tabs import NOTICE_JOINER, PAD, TEXT_WRAP_PIXELS, ProblemLine
from app.ui import messages_ru as msg

DRAFT_FIELDS: Final[tuple[str, ...]] = tuple(field.name for field in dataclasses.fields(ChannelDraft))
CHOICE_FIELD: Final[str] = "privacy"       # только выбор из перечня модели
LANGUAGES_FIELD: Final[str] = "languages"  # выбор из списка языков, не ввод текстом
FORM_LANGUAGE_VALUES_KEY: Final[str] = "language"   # варианты вопроса о языке в form.values livecraft.json
TREE_HEIGHT_ROWS: Final[int] = 8
ENTRY_WIDTH_CHARS: Final[int] = 40
LANGUAGE_LIST_HEIGHT_ROWS: Final[int] = 8
LANGUAGE_LIST_WIDTH_CHARS: Final[int] = 48
TREE_SHOW: Final[str] = "headings"
READONLY: Final[str] = "readonly"
LISTBOX_SELECT_EVENT: Final[str] = "<<ListboxSelect>>"
VARIABLE_WRITE: Final[str] = "write"


class ChannelsTab:
    """Вкладка «Каналы YouTube». `panel` — текущая модель; после каждого действия её заменяет ответ модели.

    `catalog` — языки списка, `selection` — выбранные языки формы канала, `visible_languages` — языки,
    которые сейчас видны в списке после поиска (по ним номера строк списка переводятся в коды).
    """

    def __init__(self, notebook: ttk.Notebook, paths: LivecraftPaths, on_saved: Callable[[], None]) -> None:
        self.paths: LivecraftPaths = paths
        self.panel: ChannelsPanel = ChannelsPanel.from_paths(paths)
        self.catalog: LanguageCatalog = LanguageCatalog.load(self._form_language_codes(paths))
        self.selection: LanguageSelection = LanguageSelection(codes=())
        self.visible_languages: tuple[LanguageOption, ...] = ()
        self.frame: ttk.Frame = ttk.Frame(notebook, padding=PAD)
        self.notice: ttk.Label = ttk.Label(self.frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.notice.pack(fill=tk.X, anchor=tk.W)
        self.list_problem: ProblemLine = ProblemLine(self.frame, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.list_problem.label.pack(fill=tk.X, anchor=tk.W)
        self.tree: ttk.Treeview = self._build_tree()
        self.form: dict[str, tk.StringVar] = {name: tk.StringVar(master=self.frame) for name in DRAFT_FIELDS}
        self.language_search: tk.StringVar = tk.StringVar(master=self.frame)
        self.inputs: dict[str, ttk.Entry] = self._build_form()
        self.buttons: dict[str, ttk.Button] = self._build_buttons()
        self.edit_problem: ProblemLine = ProblemLine(self.frame, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.edit_problem.label.pack(fill=tk.X, anchor=tk.W)
        self._on_saved: Callable[[], None] = on_saved
        self.form[CHOICE_FIELD].set(self.panel.privacy_options[0])
        self.language_search.trace_add(VARIABLE_WRITE, lambda *_args: self.filter_languages())
        self._choose_languages(self.selection)
        self._show()

    @property
    def is_dirty(self) -> bool:
        """Есть несохранённое — по модели."""
        return self.panel.is_dirty

    @property
    def form_draft(self) -> ChannelDraft:
        """Черновик канала из полей формы — текстом, как введено; языки — кодами выбранного."""
        return ChannelDraft(**{name: variable.get() for name, variable in self.form.items()})

    @property
    def selected_index(self) -> int | None:
        """Номер выбранного канала в модели; ничего не выбрано — None."""
        selection: tuple[str, ...] = self.tree.selection()
        return int(selection[0]) if selection else None

    def fill_from_selection(self) -> None:
        """Выбор строки таблицы заполняет форму черновиком этого канала, языки — отметками в списке."""
        index: int | None = self.selected_index
        if index is None:
            return
        draft: ChannelDraft = self.panel.drafts[index]
        for name, variable in self.form.items():
            variable.set(getattr(draft, name))
        self._choose_languages(LanguageSelection.from_text(draft.languages))

    def filter_languages(self) -> None:
        """Строка поиска изменилась: в списке — подходящие языки, выбранные среди них отмечены."""
        self.visible_languages = self.catalog.search(self.language_search.get())
        self.language_list.delete(0, tk.END)
        self.language_list.insert(tk.END, *(option.label for option in self.visible_languages))
        chosen: set[str] = set(self.selection.codes)
        for position, option in enumerate(self.visible_languages):
            if option.code in chosen:
                self.language_list.selection_set(position)

    def pick_languages(self) -> None:
        """Щелчок в списке: видимые языки — как отмечено, скрытые поиском — как были."""
        visible: tuple[str, ...] = tuple(option.code for option in self.visible_languages)
        chosen: tuple[str, ...] = tuple(visible[position] for position in self.language_list.curselection())
        self.selection = self.selection.with_visible(visible, chosen)
        self._show_languages()

    def add(self) -> None:
        """«Добавить»: черновик формы — модели, в конец списка."""
        self._apply(self.panel.add(self.form_draft))

    def update(self) -> None:
        """«Изменить выбранный»: черновик формы заменяет выбранный канал."""
        index: int | None = self.selected_index
        if index is None:
            self.edit_problem.show_text(msg.SETUP_CHANNELS_NOTHING_SELECTED)
            return
        self._apply(self.panel.update(index, self.form_draft))

    def remove(self) -> None:
        """«Удалить выбранный»: пустой список модель покажет своей проблемой над таблицей."""
        index: int | None = self.selected_index
        if index is None:
            self.edit_problem.show_text(msg.SETUP_CHANNELS_NOTHING_SELECTED)
            return
        self.panel = self.panel.remove(index)
        self.edit_problem.show_text(None)
        self._show()

    def save(self) -> None:
        """«Сохранить»: модель пишет channels.json через загрузчик. Сбой диска — диалог."""
        try:
            edit: ChannelsPanelEdit = self.panel.save(self.paths)
        except OSError as error:
            messagebox.showerror(
                msg.SETUP_SAVE_FAILED_TITLE, msg.SETUP_CHANNELS_SAVE_FAILED.format(error=error), parent=self.frame
            )
            return
        if not edit.is_applied:
            self.edit_problem.show_problem(edit.problem)
            return
        self.panel = edit.panel
        self.edit_problem.show_text(None)
        self._show()
        self._on_saved()

    def _apply(self, edit: ChannelsPanelEdit) -> None:
        """Ответ модели на правку: принято — новая вкладка; нет — проблема с подписью поля."""
        if not edit.is_applied:
            self.edit_problem.show_problem(edit.problem)
            return
        self.panel = edit.panel
        self.edit_problem.show_text(None)
        self._show()

    def _choose_languages(self, selection: LanguageSelection) -> None:
        """Выбор целиком (из строки таблицы): незнакомые каталогу коды добавляются в него, чтобы не потеряться."""
        self.catalog = self.catalog.including(selection.codes)
        self.selection = selection
        self.filter_languages()
        self._show_languages()

    def _show_languages(self) -> None:
        """Выбор — в черновик кодами, подпись «выбрано» — названиями, язык не из формы — предупреждением."""
        self.form[LANGUAGES_FIELD].set(self.selection.text)
        codes: tuple[str, ...] = self.selection.codes
        self.language_selected.configure(
            text=msg.SETUP_LANGUAGE_SELECTED.format(names=self.catalog.names(codes))
            if codes
            else msg.SETUP_LANGUAGE_SELECTED_NONE
        )
        foreign: tuple[str, ...] = self.catalog.foreign(codes)
        self.language_warning.show_text(
            msg.SETUP_LANGUAGE_NOT_IN_FORM.format(names=self.catalog.names(foreign)) if foreign else None
        )

    def _show(self) -> None:
        """Перерисовать оговорки, проблему списка и таблицу по модели."""
        self.notice.configure(text=NOTICE_JOINER.join(self.panel.notices))
        self.list_problem.show_problem(self.panel.problem)
        self.tree.delete(*self.tree.get_children())
        for index, draft in enumerate(self.panel.drafts):
            self.catalog = self.catalog.including(draft.language_codes)
            self.tree.insert("", tk.END, iid=str(index), values=self._tree_values(draft))

    def _tree_values(self, draft: ChannelDraft) -> tuple[str, ...]:
        """Строка таблицы: поля черновика как есть, языки — названиями."""
        return tuple(
            self.catalog.names(draft.language_codes) if name == LANGUAGES_FIELD else getattr(draft, name)
            for name in DRAFT_FIELDS
        )

    @staticmethod
    def _form_language_codes(paths: LivecraftPaths) -> tuple[str, ...]:
        """Коды вариантов вопроса о языке из livecraft.json; настройки не прочитались — языков формы нет."""
        try:
            values: dict[str, dict[str, str]] = load_settings(paths.config_file).form.values
        except ConfigError:
            return ()
        return tuple(values.get(FORM_LANGUAGE_VALUES_KEY, {}))

    def _build_tree(self) -> ttk.Treeview:
        tree: ttk.Treeview = ttk.Treeview(
            self.frame, columns=DRAFT_FIELDS, show=TREE_SHOW, height=TREE_HEIGHT_ROWS, selectmode=tk.BROWSE
        )
        for name in DRAFT_FIELDS:
            tree.heading(name, text=msg.SETUP_CHANNEL_FIELD_LABELS[name])
        tree.bind("<<TreeviewSelect>>", lambda _event: self.fill_from_selection())
        tree.pack(fill=tk.BOTH, expand=True, pady=PAD)
        return tree

    def _build_form(self) -> dict[str, ttk.Entry]:
        """Поля черновика: видимость — выбор из перечня модели, языки — выбор из списка, прочее — ввод текстом."""
        form_frame: ttk.Frame = ttk.Frame(self.frame)
        form_frame.pack(fill=tk.X, anchor=tk.W)
        inputs: dict[str, ttk.Entry] = {}
        for row, name in enumerate(DRAFT_FIELDS):
            ttk.Label(form_frame, text=msg.SETUP_CHANNEL_FIELD_LABELS[name]).grid(
                row=row, column=0, sticky=tk.NW, padx=PAD, pady=(PAD, 0)
            )
            if name == LANGUAGES_FIELD:
                self._build_language_picker(form_frame).grid(row=row, column=1, sticky=tk.W, padx=PAD, pady=(PAD, 0))
                continue
            widget: ttk.Entry = (
                ttk.Combobox(
                    form_frame, textvariable=self.form[name], values=self.panel.privacy_options, state=READONLY
                )
                if name == CHOICE_FIELD
                else ttk.Entry(form_frame, textvariable=self.form[name], width=ENTRY_WIDTH_CHARS)
            )
            widget.grid(row=row, column=1, sticky=tk.W, padx=PAD, pady=(PAD, 0))
            inputs[name] = widget
        return inputs

    def _build_language_picker(self, parent: ttk.Frame) -> ttk.Frame:
        """Строка поиска, список языков со скроллом, подсказка, подпись «выбрано» и строка-предупреждение."""
        picker: ttk.Frame = ttk.Frame(parent)
        search_row: ttk.Frame = ttk.Frame(picker)
        search_row.pack(fill=tk.X, anchor=tk.W)
        ttk.Label(search_row, text=msg.SETUP_LANGUAGE_SEARCH_LABEL).pack(side=tk.LEFT)
        self.language_search_entry: ttk.Entry = ttk.Entry(
            search_row, textvariable=self.language_search, width=ENTRY_WIDTH_CHARS
        )
        self.language_search_entry.pack(side=tk.LEFT, padx=(PAD, 0))
        list_row: ttk.Frame = ttk.Frame(picker)
        list_row.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        # exportselection=False: выбор списка не пропадает, когда фокус уходит в строку поиска или другое поле.
        self.language_list: tk.Listbox = tk.Listbox(
            list_row,
            selectmode=tk.MULTIPLE,
            exportselection=False,
            height=LANGUAGE_LIST_HEIGHT_ROWS,
            width=LANGUAGE_LIST_WIDTH_CHARS,
        )
        scrollbar: ttk.Scrollbar = ttk.Scrollbar(list_row, orient=tk.VERTICAL, command=self.language_list.yview)
        self.language_list.configure(yscrollcommand=scrollbar.set)
        self.language_list.pack(side=tk.LEFT)
        scrollbar.pack(side=tk.LEFT, fill=tk.Y)
        self.language_list.bind(LISTBOX_SELECT_EVENT, lambda _event: self.pick_languages())
        ttk.Label(picker, text=msg.SETUP_LANGUAGE_LIST_HINT, wraplength=TEXT_WRAP_PIXELS).pack(anchor=tk.W)
        self.language_selected: ttk.Label = ttk.Label(picker, wraplength=TEXT_WRAP_PIXELS)
        self.language_selected.pack(anchor=tk.W)
        self.language_warning: ProblemLine = ProblemLine(picker, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.language_warning.label.pack(anchor=tk.W)
        return picker

    def _build_buttons(self) -> dict[str, ttk.Button]:
        """Кнопки вкладки в ряду по центру окна, своего размера; ключ — английский идентификатор действия."""
        self.buttons_frame: ttk.Frame = ttk.Frame(self.frame)
        self.buttons_frame.pack(side=tk.TOP, anchor=tk.CENTER, pady=PAD)
        commands: tuple[tuple[str, str, Callable[[], None]], ...] = (
            ("add", msg.SETUP_CHANNELS_BUTTON_ADD, self.add),
            ("update", msg.SETUP_CHANNELS_BUTTON_UPDATE, self.update),
            ("remove", msg.SETUP_CHANNELS_BUTTON_REMOVE, self.remove),
            ("save", msg.SETUP_BUTTON_SAVE, self.save),
        )
        buttons: dict[str, ttk.Button] = {}
        for key, text, command in commands:
            button: ttk.Button = ttk.Button(self.buttons_frame, text=text, command=command)
            button.pack(side=tk.LEFT, padx=PAD)
            buttons[key] = button
        return buttons
