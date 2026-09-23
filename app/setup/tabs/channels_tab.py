"""Вкладка окна «Каналы YouTube» поверх модели `ChannelsPanel` (CLAUDE.md §8.2 п.2).

Таблица каналов — строки модели (`drafts`), под ней форма из пяти полей черновика канала и кнопки.
Выбор строки заполняет форму; «добавить» и «изменить выбранный» отдают черновик модели, и ответ модели
заменяет вкладку либо называет проблему красной строкой с подписью поля. Своих правил у вкладки нет:
годность канала решает загрузчик внутри модели. Входа в канал и «проверить все» здесь нет (задача 2.4).
"""
from __future__ import annotations

import dataclasses
import tkinter as tk
from collections.abc import Callable
from tkinter import messagebox, ttk
from typing import Final

from app.paths import LivecraftPaths
from app.setup.fields.channel_draft import ChannelDraft
from app.setup.panels.channels_panel import ChannelsPanel, ChannelsPanelEdit
from app.setup.tabs import NOTICE_JOINER, PAD, TEXT_WRAP_PIXELS, ProblemLine
from app.ui import messages_ru as msg

DRAFT_FIELDS: Final[tuple[str, ...]] = tuple(field.name for field in dataclasses.fields(ChannelDraft))
CHOICE_FIELD: Final[str] = "privacy"       # только выбор из перечня модели
TREE_HEIGHT_ROWS: Final[int] = 8
ENTRY_WIDTH_CHARS: Final[int] = 40
TREE_SHOW: Final[str] = "headings"
READONLY: Final[str] = "readonly"


class ChannelsTab:
    """Вкладка «Каналы YouTube». `panel` — текущая модель; после каждого действия её заменяет ответ модели."""

    def __init__(self, notebook: ttk.Notebook, paths: LivecraftPaths, on_saved: Callable[[], None]) -> None:
        self.paths: LivecraftPaths = paths
        self.panel: ChannelsPanel = ChannelsPanel.from_paths(paths)
        self.frame: ttk.Frame = ttk.Frame(notebook, padding=PAD)
        self.notice: ttk.Label = ttk.Label(self.frame, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        self.notice.pack(fill=tk.X, anchor=tk.W)
        self.list_problem: ProblemLine = ProblemLine(self.frame, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.list_problem.label.pack(fill=tk.X, anchor=tk.W)
        self.tree: ttk.Treeview = self._build_tree()
        self.form: dict[str, tk.StringVar] = {name: tk.StringVar(master=self.frame) for name in DRAFT_FIELDS}
        self.inputs: dict[str, ttk.Entry] = self._build_form()
        self.buttons: dict[str, ttk.Button] = self._build_buttons()
        self.edit_problem: ProblemLine = ProblemLine(self.frame, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.edit_problem.label.pack(fill=tk.X, anchor=tk.W)
        self._on_saved: Callable[[], None] = on_saved
        self.form[CHOICE_FIELD].set(self.panel.privacy_options[0])
        self._show()

    @property
    def is_dirty(self) -> bool:
        """Есть несохранённое — по модели."""
        return self.panel.is_dirty

    @property
    def form_draft(self) -> ChannelDraft:
        """Черновик канала из полей формы — текстом, как введено."""
        return ChannelDraft(**{name: variable.get() for name, variable in self.form.items()})

    @property
    def selected_index(self) -> int | None:
        """Номер выбранного канала в модели; ничего не выбрано — None."""
        selection: tuple[str, ...] = self.tree.selection()
        return int(selection[0]) if selection else None

    def fill_from_selection(self) -> None:
        """Выбор строки таблицы заполняет форму черновиком этого канала."""
        index: int | None = self.selected_index
        if index is None:
            return
        draft: ChannelDraft = self.panel.drafts[index]
        for name, variable in self.form.items():
            variable.set(getattr(draft, name))

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

    def _show(self) -> None:
        """Перерисовать оговорки, проблему списка и таблицу по модели."""
        self.notice.configure(text=NOTICE_JOINER.join(self.panel.notices))
        self.list_problem.show_problem(self.panel.problem)
        self.tree.delete(*self.tree.get_children())
        for index, draft in enumerate(self.panel.drafts):
            self.tree.insert("", tk.END, iid=str(index), values=tuple(getattr(draft, name) for name in DRAFT_FIELDS))

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
        """Пять полей черновика; видимость — только выбор из перечня модели."""
        form_frame: ttk.Frame = ttk.Frame(self.frame)
        form_frame.pack(fill=tk.X, anchor=tk.W)
        inputs: dict[str, ttk.Entry] = {}
        for row, name in enumerate(DRAFT_FIELDS):
            ttk.Label(form_frame, text=msg.SETUP_CHANNEL_FIELD_LABELS[name]).grid(
                row=row, column=0, sticky=tk.W, padx=PAD, pady=(PAD, 0)
            )
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

    def _build_buttons(self) -> dict[str, ttk.Button]:
        """Кнопки вкладки; ключ — английский идентификатор действия."""
        buttons_frame: ttk.Frame = ttk.Frame(self.frame)
        buttons_frame.pack(fill=tk.X, pady=PAD)
        commands: tuple[tuple[str, str, Callable[[], None]], ...] = (
            ("add", msg.SETUP_CHANNELS_BUTTON_ADD, self.add),
            ("update", msg.SETUP_CHANNELS_BUTTON_UPDATE, self.update),
            ("remove", msg.SETUP_CHANNELS_BUTTON_REMOVE, self.remove),
            ("save", msg.SETUP_BUTTON_SAVE, self.save),
        )
        buttons: dict[str, ttk.Button] = {}
        for key, text, command in commands:
            button: ttk.Button = ttk.Button(buttons_frame, text=text, command=command)
            button.pack(side=tk.LEFT, padx=(0, PAD))
            buttons[key] = button
        return buttons
