"""Вкладка окна «Каналы YouTube» поверх модели `ChannelsPanel` (CLAUDE.md §8.2 п.2).

Таблица каналов — строки модели (`drafts`), под ней форма из пяти полей черновика канала и кнопки.
Выбор строки заполняет форму; «добавить» и «изменить выбранный» отдают черновик модели, и ответ модели
заменяет вкладку либо называет проблему красной строкой с подписью поля. Своих правил у вкладки нет:
годность канала решает загрузчик внутри модели. Входа в канал и «проверить все» здесь нет (задача 2.4).

У канала один язык (решение Артура 24-09-2026): он выбирается выпадающим полем того же вида и ширины, что
«видимость», из всех языков по названию (`LanguageCatalog`). В поле можно печатать — значения сужаются до
подходящих языков; Esc возвращает прежний выбор. Черновик получает ровно один код; текст, который не строка
списка, — проблема поля (`LanguageCatalog.text_problem`), и такой черновик модели не отдаётся. Канал из
старого файла с несколькими языками показан первым и строкой «при сохранении останется …». Языки
Google-формы — первыми и с пометкой; они берутся из прочитанных настроек и перечитываются после сохранения
вкладки «Настройки запуска», а не прочитались настройки — список полный, но без пометок. Язык не из формы
вкладка называет сразу строкой-предупреждением: сохранению это не мешает, но эфиры на нём допущены не будут
(§6 инвариант 2). В таблице каналов язык показан названием. Ряд кнопок — по центру окна.
"""
from __future__ import annotations

import dataclasses
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Final

from app.config.loader import ConfigError, SettingProblem, load_settings
from app.paths import LivecraftPaths
from app.setup.fields.channel_draft import ChannelDraft
from app.setup.fields.language_choice import LanguageCatalog, LanguageSelection
from app.setup.panels.channels_panel import ChannelsPanel, ChannelsPanelEdit
from app.setup.tabs import NOTICE_JOINER, PAD, TEXT_WRAP_PIXELS, ProblemLine
from app.ui import messages_ru as msg

DRAFT_FIELDS: Final[tuple[str, ...]] = tuple(field.name for field in dataclasses.fields(ChannelDraft))
CHOICE_FIELD: Final[str] = "privacy"       # только выбор из перечня модели
LANGUAGES_FIELD: Final[str] = "languages"  # выбор языка из списка; печать только сужает список
FORM_LANGUAGE_VALUES_KEY: Final[str] = "language"   # варианты вопроса о языке в form.values livecraft.json
TREE_HEIGHT_ROWS: Final[int] = 8
ENTRY_WIDTH_CHARS: Final[int] = 40
CHOICE_WIDTH_CHARS: Final[int] = ENTRY_WIDTH_CHARS   # «видимость» и «язык» — одного вида и одной ширины
TREE_SHOW: Final[str] = "headings"
READONLY: Final[str] = "readonly"
ESCAPE_EVENT: Final[str] = "<Escape>"
VARIABLE_WRITE: Final[str] = "write"


class ChannelsTab:
    """Вкладка «Каналы YouTube». `panel` — текущая модель; после каждого действия её заменяет ответ модели.

    `catalog` — языки поля выбора, `selection` — языки канала в форме (выбирается один, лишние бывают только
    у канала из старого файла), `language_text` — текст поля выбора языка, как его видит человек.
    """

    def __init__(self, notebook: ttk.Notebook, paths: LivecraftPaths, on_saved: Callable[[], None]) -> None:
        self.paths: LivecraftPaths = paths
        self.panel: ChannelsPanel = ChannelsPanel.from_paths(paths)
        self.catalog: LanguageCatalog = LanguageCatalog.load(self._form_language_codes(paths))
        self.selection: LanguageSelection = LanguageSelection(codes=())
        self.frame: ttk.Frame = ttk.Frame(notebook, padding=PAD)
        self.notice: ttk.Label = ttk.Label(self.frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.notice.pack(fill=tk.X, anchor=tk.W)
        self.list_problem: ProblemLine = ProblemLine(self.frame, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.list_problem.label.pack(fill=tk.X, anchor=tk.W)
        self.tree: ttk.Treeview = self._build_tree()
        self.form: dict[str, tk.StringVar] = {name: tk.StringVar(master=self.frame) for name in DRAFT_FIELDS}
        self.language_text: tk.StringVar = tk.StringVar(master=self.frame)
        self.inputs: dict[str, ttk.Entry] = self._build_form()
        self.buttons: dict[str, ttk.Button] = self._build_buttons()
        self.edit_problem: ProblemLine = ProblemLine(self.frame, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.edit_problem.label.pack(fill=tk.X, anchor=tk.W)
        self._on_saved: Callable[[], None] = on_saved
        self.form[CHOICE_FIELD].set(self.panel.privacy_options[0])
        self.language_text.trace_add(VARIABLE_WRITE, lambda *_args: self.type_language())
        self._show()
        self._choose_languages(self.selection)

    @property
    def is_dirty(self) -> bool:
        """Есть несохранённое — по модели."""
        return self.panel.is_dirty

    @property
    def form_draft(self) -> ChannelDraft:
        """Черновик канала из полей формы — текстом, как введено; язык — кодом выбранного."""
        return ChannelDraft(**{name: variable.get() for name, variable in self.form.items()})

    @property
    def selected_index(self) -> int | None:
        """Номер выбранного канала в модели; ничего не выбрано — None."""
        selection: tuple[str, ...] = self.tree.selection()
        return int(selection[0]) if selection else None

    @property
    def language_box(self) -> ttk.Combobox:
        """Поле выбора языка — то же, что лежит в `inputs` под именем поля черновика."""
        return self._language_box

    @property
    def language_problem(self) -> SettingProblem | None:
        """Текст поля языка — не строка списка: черновик с ним модели не отдаётся."""
        return self.catalog.text_problem(self.language_text.get())

    def fill_from_selection(self) -> None:
        """Выбор строки таблицы заполняет форму черновиком этого канала; язык — первым из записанных."""
        index: int | None = self.selected_index
        if index is None:
            return
        draft: ChannelDraft = self.panel.drafts[index]
        for name, variable in self.form.items():
            variable.set(getattr(draft, name))
        self._choose_languages(LanguageSelection.from_text(draft.languages))

    def type_language(self) -> None:
        """Текст поля изменился: строка списка — это выбор языка; иначе значения поля сужаются до подходящих.

        Пустое поле — языка нет (что язык обязателен, скажет загрузчик). Прочий текст выбор не меняет.
        """
        text: str = self.language_text.get()
        code: str | None = self.catalog.code_of(text)
        if code is None and text.strip():
            self.language_box.configure(values=self.catalog.labels(self.catalog.search(text)))
            return
        self.language_box.configure(values=self.catalog.labels(self.catalog.options))
        if code != self.selection.first:
            self.selection = LanguageSelection(codes=()) if code is None else LanguageSelection.single(code)
        self._show_languages()

    def restore_language(self) -> None:
        """Esc: в поле — подпись прежнего выбора, набранный текст отбрасывается."""
        self.language_text.set(self._chosen_label)

    def refresh_form_languages(self) -> None:
        """Настройки сохранены: языки формы перечитываются, пометки и предупреждение — по новой форме."""
        codes: list[str] = [code for draft in self.panel.drafts for code in draft.language_codes]
        self.catalog = LanguageCatalog.load(self._form_language_codes(self.paths)).including(
            (*codes, *self.selection.codes)
        )
        self._choose_languages(self.selection)

    def add(self) -> None:
        """«Добавить»: черновик формы — модели, в конец списка; текст языка не из списка — проблема поля."""
        if self._refuses_language_text():
            return
        self._apply(self.panel.add(self.form_draft))

    def update(self) -> None:
        """«Изменить выбранный»: черновик формы заменяет выбранный канал."""
        index: int | None = self.selected_index
        if index is None:
            self.edit_problem.show_text(msg.SETUP_CHANNELS_NOTHING_SELECTED)
            return
        if self._refuses_language_text():
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

    def _refuses_language_text(self) -> bool:
        """Набранный текст — не язык из списка: проблема поля, черновик модели не отдаётся."""
        problem: SettingProblem | None = self.language_problem
        if problem is not None:
            self.edit_problem.show_problem(problem)
        return problem is not None

    @property
    def _chosen_label(self) -> str:
        """Подпись выбранного языка в поле; языка нет — пусто."""
        first: str | None = self.selection.first
        return "" if first is None else self.catalog.label_of(first)

    def _choose_languages(self, selection: LanguageSelection) -> None:
        """Языки канала целиком (строка таблицы, новая форма): незнакомые каталогу коды добавляются в него."""
        self.catalog = self.catalog.including(selection.codes)
        self.selection = selection
        self.language_text.set(self._chosen_label)
        self._show_languages()

    def _show_languages(self) -> None:
        """Язык — в черновик одним кодом; лишние языки старой записи и язык не из формы — строками под полем."""
        self.form[LANGUAGES_FIELD].set(self.selection.text)
        first: str | None = self.selection.first
        self.language_note.show_text(
            msg.SETUP_LANGUAGE_SEVERAL.format(name=self.catalog.name(first))
            if first is not None and self.selection.extra_codes
            else None
        )
        foreign: tuple[str, ...] = () if first is None else self.catalog.foreign((first,))
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
        """Поля черновика: видимость — выбор из перечня модели, язык — выбор из списка языков, прочее — ввод."""
        form_frame: ttk.Frame = ttk.Frame(self.frame)
        form_frame.pack(fill=tk.X, anchor=tk.W)
        inputs: dict[str, ttk.Entry] = {}
        for row, name in enumerate(DRAFT_FIELDS):
            ttk.Label(form_frame, text=msg.SETUP_CHANNEL_FIELD_LABELS[name]).grid(
                row=row, column=0, sticky=tk.NW, padx=PAD, pady=(PAD, 0)
            )
            if name == LANGUAGES_FIELD:
                cell: ttk.Frame = ttk.Frame(form_frame)
                cell.grid(row=row, column=1, sticky=tk.W, padx=PAD, pady=(PAD, 0))
                inputs[name] = self._build_language_box(cell)
                continue
            widget: ttk.Entry = (
                ttk.Combobox(
                    form_frame,
                    textvariable=self.form[name],
                    values=self.panel.privacy_options,
                    state=READONLY,
                    width=CHOICE_WIDTH_CHARS,
                )
                if name == CHOICE_FIELD
                else ttk.Entry(form_frame, textvariable=self.form[name], width=ENTRY_WIDTH_CHARS)
            )
            widget.grid(row=row, column=1, sticky=tk.W, padx=PAD, pady=(PAD, 0))
            inputs[name] = widget
        return inputs

    def _build_language_box(self, cell: ttk.Frame) -> ttk.Combobox:
        """Выпадающее поле языка с печатью для поиска; под ним — строки о лишних языках и о языке не из формы."""
        self._language_box: ttk.Combobox = ttk.Combobox(
            cell,
            textvariable=self.language_text,
            values=self.catalog.labels(self.catalog.options),
            width=CHOICE_WIDTH_CHARS,
        )
        self._language_box.pack(anchor=tk.W)
        self._language_box.bind(ESCAPE_EVENT, lambda _event: self.restore_language())
        self.language_note: ProblemLine = ProblemLine(cell, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.language_note.label.pack(anchor=tk.W)
        self.language_warning: ProblemLine = ProblemLine(cell, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.language_warning.label.pack(anchor=tk.W)
        return self._language_box

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
