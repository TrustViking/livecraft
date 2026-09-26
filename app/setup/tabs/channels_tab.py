"""Вкладка окна «Каналы YouTube» поверх модели `ChannelsPanel` (CLAUDE.md §8.2 п.2).

Таблица каналов — строки модели (`drafts`), под ней сетка полей черновика канала (`ChannelDraft.FIELDS`) и
кнопки. Выбор строки заполняет поля; «добавить» и «изменить выбранный» отдают черновик модели, и ответ модели
заменяет вкладку либо называет проблему красной строкой с подписью поля. Своих правил у вкладки нет:
годность канала решает загрузчик внутри модели. Набранное в полях, но не принятое моделью, —
несохранённое вкладки: окно спросит перед закрытием.

У канала один язык (§14 решение 21): он выбирается полем выбора с поиском (`LanguageBox`) из всех языков по
названию. Языки Google-формы — первыми и с пометкой; их вкладке даёт модель настроек при открытии и после
сохранения вкладки «Настройки запуска», а не прочитались настройки — список полный, но без пометок. В таблице
каналов язык показан названием. Ряд кнопок — по центру окна.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable, Iterable
from tkinter import ttk
from typing import Final

from app.config.json_node import SettingProblem
from app.setup.fields.channel_draft import ChannelDraft
from app.setup.fields.draft_field import DraftField, DraftKind
from app.setup.fields.language_choice import LanguageDirectory, LanguagePicker
from app.setup.panels.channels_panel import ChannelsPanel
from app.setup.panels.panel_edit import PanelEdit
from app.setup.tabs.language_box import LanguageBox
from app.setup.tabs.tab_event import TkEvent
from app.setup.tabs.tab_grid import DraftVariables, FormGrid
from app.setup.tabs.tab_layout import PAD, ProblemLine
from app.setup.tabs.tab_shell import TabAction, TabShell
from app.ui import messages_ru as msg

DRAFT_FIELDS: Final[tuple[str, ...]] = tuple(field.name for field in ChannelDraft.FIELDS)
TREE_HEIGHT_ROWS: Final[int] = 8
TREE_SHOW: Final[str] = "headings"
LANGUAGE_FIELD: Final[DraftField] = next(field for field in ChannelDraft.FIELDS if field.kind is DraftKind.LANGUAGE)


class ChannelsTab:
    """Вкладка «Каналы YouTube» в оболочке `shell`: таблица каналов, поля черновика (`variables`, `grid`),
    поле выбора языка (`language`), кнопки и строки проблем."""

    def __init__(
        self, notebook: ttk.Notebook, panel: ChannelsPanel, on_saved: Callable[[], None], form_languages: Iterable[str]
    ) -> None:
        self.shell: TabShell[ChannelsPanel] = TabShell(notebook, panel, on_saved)
        self.frame: ttk.Frame = self.shell.frame
        self.list_problem: ProblemLine = ProblemLine(self.frame, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.list_problem.label.pack(fill=tk.X, anchor=tk.W)
        self.tree: ttk.Treeview = self._build_tree()
        self.variables: DraftVariables[ChannelDraft] = DraftVariables(self.frame, ChannelDraft.blank())
        self.grid: FormGrid = FormGrid(self.frame, msg.SETUP_CHANNEL_FIELD_LABELS, {})
        self.inputs: dict[str, ttk.Widget] = self.grid.inputs
        self.language: LanguageBox = self._build_form(LanguagePicker.of(form_languages))
        self.buttons: dict[TabAction, ttk.Button] = self.shell.button_row(
            {
                TabAction.ADD: self.add,
                TabAction.UPDATE: self.update,
                TabAction.REMOVE: self.remove,
                TabAction.SAVE: self.save,
            }
        )
        self.edit_problem: ProblemLine = ProblemLine(self.frame, msg.SETUP_CHANNEL_FIELD_LABELS)
        self.edit_problem.label.pack(fill=tk.X, anchor=tk.W)
        self._show()

    @property
    def panel(self) -> ChannelsPanel:
        return self.shell.panel

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — в модели, в полях канала или в поле языка набрана строка поиска."""
        return self.shell.is_dirty(self.variables.has_typed or self.language.picker.is_search)

    @property
    def form_draft(self) -> ChannelDraft:
        """Черновик канала из полей окна — текстом, как введено; язык — кодом выбранного."""
        return self.variables.typed

    @property
    def selected_index(self) -> int | None:
        """Номер выбранного канала в модели; ничего не выбрано — None."""
        selection: tuple[str, ...] = self.tree.selection()
        return int(selection[0]) if selection else None

    def fill_from_selection(self) -> None:
        """Выбор строки таблицы заполняет поля черновиком этого канала; язык — первым из записанных."""
        index: int | None = self.selected_index
        if index is None:
            return
        draft: ChannelDraft = self.panel.drafts[index]
        self.variables.show(draft)
        self.language.choose(draft.languages)
        self.variables.accept()

    def refresh_form_languages(self, form_languages: Iterable[str]) -> None:
        """Настройки сохранены: пометки и предупреждение о языке — по новой форме, выбор тот же."""
        known: list[str] = [code for draft in self.panel.drafts for code in draft.languages]
        self.language.with_form(form_languages, known)

    def add(self) -> None:
        """«Добавить»: черновик — модели, в конец списка; текст языка не из списка — проблема поля."""
        if not self._refuses_language_text():
            self._apply(self.panel.add(self.form_draft))

    def update(self) -> None:
        """«Изменить выбранный»: черновик заменяет выбранный канал."""
        index: int | None = self.selected_index
        if index is None:
            self.edit_problem.show_text(msg.SETUP_CHANNELS_NOTHING_SELECTED)
        elif not self._refuses_language_text():
            self._apply(self.panel.update(index, self.form_draft))

    def remove(self) -> None:
        """«Удалить выбранный»: пустой список модель покажет своей проблемой над таблицей."""
        index: int | None = self.selected_index
        if index is None:
            self.edit_problem.show_text(msg.SETUP_CHANNELS_NOTHING_SELECTED)
            return
        self.shell.panel = self.panel.remove(index)
        self.edit_problem.show_text(None)
        self._show()

    def save(self) -> None:
        """«Сохранить»: модель пишет channels.json через загрузчик. Сбой диска — диалог."""
        try:
            edit: PanelEdit[ChannelsPanel] = self.panel.save()
        except OSError as error:
            self.shell.refuse_save(msg.SETUP_CHANNELS_SAVE_FAILED.format(error=error))
            return
        if self._apply(edit):
            self.shell.on_saved()

    def _apply(self, edit: PanelEdit[ChannelsPanel]) -> bool:
        """Ответ модели: принято — новая вкладка, набранное принято, True; нет — проблема с подписью поля, False."""
        self.edit_problem.show_problem(edit.problem)
        if not edit.is_applied:
            return False
        self.shell.panel = edit.panel
        self.variables.accept()
        self._show()
        return True

    def _refuses_language_text(self) -> bool:
        """Набранный текст — не язык из списка: проблема поля, черновик модели не отдаётся."""
        problem: SettingProblem | None = self.language.problem
        if problem is not None:
            self.edit_problem.show_problem(problem)
        return problem is not None

    def _show(self) -> None:
        """Перерисовать оговорки, проблему списка и таблицу по модели; языки таблицы — названиями."""
        self.shell.show_notices()
        self.list_problem.show_problem(self.panel.problem)
        self.tree.delete(*self.tree.get_children())
        drafts: tuple[ChannelDraft, ...] = self.panel.drafts
        self.language.including(code for draft in drafts for code in draft.languages)
        directory: LanguageDirectory = self.language.picker.directory
        for index, draft in enumerate(drafts):
            values: tuple[str, ...] = tuple(
                directory.names(draft.languages) if field is LANGUAGE_FIELD else getattr(draft, field.name)
                for field in ChannelDraft.FIELDS
            )
            self.tree.insert("", tk.END, iid=str(index), values=values)

    def _build_tree(self) -> ttk.Treeview:
        tree: ttk.Treeview = ttk.Treeview(
            self.frame, columns=DRAFT_FIELDS, show=TREE_SHOW, height=TREE_HEIGHT_ROWS, selectmode=tk.BROWSE
        )
        for name in DRAFT_FIELDS:
            tree.heading(name, text=msg.SETUP_CHANNEL_FIELD_LABELS[name])
        tree.bind(TkEvent.TREE_SELECT, lambda _event: self.fill_from_selection())
        tree.pack(fill=tk.BOTH, expand=True, pady=PAD)
        return tree

    def _build_form(self, picker: LanguagePicker) -> LanguageBox:
        """Строки полей черновика; в ячейку языка — поле выбора языка, которое пишет коды в черновик."""
        for field in ChannelDraft.FIELDS:
            self.grid.add(field, self.variables.variables[field.name])
        codes: tk.Variable = self.variables.variables[LANGUAGE_FIELD.name]
        return LanguageBox(self.grid.inputs[LANGUAGE_FIELD.name], LANGUAGE_FIELD, picker, codes)
