"""Вкладка окна «Настройки запуска» поверх модели `SettingsPanel` (CLAUDE.md §8.2 п.3).

Сетка полей черновика настроек (`SettingsDraft.FIELDS`): текст — поле ввода (ссылка на форму — тоже обычное
открытое поле: она не секрет, §14 решение 15), флажок — ttk.Checkbutton, уровень рассуждений и тариф — выбор из
вариантов модели. «Сохранить» отдаёт черновик модели (`apply`) и, если модель его приняла, просит её записать
livecraft.json; отказ — красная строка с подписью поля. Своих правил нет. Кнопка — в ряду по центру окна, как
на вкладке каналов.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from app.setup.fields.settings_draft import SettingsDraft
from app.setup.panels.panel_edit import PanelEdit
from app.setup.panels.settings_panel import SettingsPanel
from app.setup.tabs.tab_grid import DraftVariables, FormGrid
from app.setup.tabs.tab_layout import ProblemLine
from app.setup.tabs.tab_shell import TabAction, TabShell
from app.ui import messages_ru as msg


class SettingsTab:
    """Вкладка «Настройки запуска» в оболочке `shell`: поля черновика (`variables`, `grid`), строка проблемы и
    кнопка «Сохранить»; `inputs` и `hints` — виджеты полей и серых подсказок по имени поля черновика."""

    def __init__(self, notebook: ttk.Notebook, panel: SettingsPanel, on_saved: Callable[[], None]) -> None:
        self.shell: TabShell[SettingsPanel] = TabShell(notebook, panel, on_saved)
        self.frame: ttk.Frame = self.shell.frame
        self.variables: DraftVariables[SettingsDraft] = DraftVariables(self.frame, panel.draft)
        self.grid: FormGrid = FormGrid(self.frame, msg.SETUP_SETTINGS_FIELD_LABELS, msg.SETUP_SETTINGS_FIELD_HINTS)
        for field in SettingsDraft.FIELDS:
            self.grid.add(field, self.variables.variables[field.name])
        self.inputs: dict[str, ttk.Widget] = self.grid.inputs
        self.hints: dict[str, ttk.Label] = self.grid.hints
        self.problem: ProblemLine = ProblemLine(self.frame, msg.SETUP_SETTINGS_FIELD_LABELS)
        self.problem.label.pack(fill=tk.X, anchor=tk.W)
        self.buttons: dict[TabAction, ttk.Button] = self.shell.button_row({TabAction.SAVE: self.save})
        self._show()

    @property
    def panel(self) -> SettingsPanel:
        return self.shell.panel

    @property
    def form_draft(self) -> SettingsDraft:
        """Черновик из полей окна: текст — как введён, флажки — bool."""
        return self.variables.typed

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — в модели или в полях окна, ещё не принятых моделью."""
        return self.shell.is_dirty(self.variables.has_typed)

    def save(self) -> None:
        """«Сохранить»: черновик — модели; принято — модель пишет файл. Сбой диска — диалог."""
        edit: PanelEdit[SettingsPanel] = self.panel.apply(self.form_draft)
        self.problem.show_problem(edit.problem)
        if not edit.is_applied:
            return
        self.shell.panel = edit.panel
        try:
            self.shell.panel = self.panel.save().panel
        except OSError as error:
            self.shell.refuse_save(msg.SETUP_SETTINGS_SAVE_FAILED.format(error=error))
            return
        self._show()
        self.shell.on_saved()

    def _show(self) -> None:
        """Перерисовать оговорки и поля по модели: то, что показала модель, — принятое."""
        self.shell.show_notices()
        self.variables.show(self.panel.draft)
        self.variables.accept()
