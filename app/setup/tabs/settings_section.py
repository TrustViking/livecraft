"""Раздел дополнительных настроек на вкладке окна (CLAUDE.md §8.2, §14 решение 37).

Поля livecraft.json разложены по вкладкам линий: параметры модели — на «Нейросети», шаблоны папок превью — на
«Превью», доступ и контакты документа — на «Google-документе», настройки эфира — на «Эфирах YouTube», пояс и срок
хранения — на «Дополнительно». Раздел — сетка своих полей черновика (`SettingsDraft.FIELDS`: текст — поле ввода,
«да / нет» — ползунок, варианты — выбор из списка), строка проблемы и кнопка «Сохранить» по центру. «Сохранить» кладёт
набранное в разделе поверх черновика модели окна (`SettingsBook`) и отдаёт его модели: принято — модель пишет файл, и
окно перерисовывается; отказ — красная строка с подписью поля. Каждая строка сетки — поле со своими линиями
(`FieldUse`): не нужно ни одной работающей — бледное. Своих правил у раздела нет.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.config.setting_key import SettingKey
from app.setup.fields.draft_field import DraftField
from app.setup.fields.field_use import FieldUse
from app.setup.fields.settings_draft import SettingsDraft
from app.setup.panels.panel_edit import PanelEdit
from app.setup.panels.settings_panel import SettingsPanel
from app.setup.tabs.field_shade import FieldNote
from app.setup.tabs.settings_write import SettingsWrite
from app.setup.tabs.setup_context import SettingsBook, SetupContext
from app.setup.tabs.tab_grid import DraftVariables, FormGrid
from app.setup.tabs.tab_layout import PAD, ProblemLine
from app.ui.messages import msg


class SettingsSection:
    """Раздел настроек в `parent`: модель окна `book`, переменные и сетка своих полей, строка проблемы и «Сохранить»."""

    def __init__(self, parent: ttk.Frame, context: SetupContext, keys: tuple[SettingKey, ...]) -> None:
        self.book: SettingsBook = context.settings
        fields: tuple[DraftField, ...] = tuple(
            next(field for field in SettingsDraft.FIELDS if field.key is key) for key in keys
        )
        self.variables: DraftVariables[SettingsDraft] = DraftVariables(parent, self.book.panel.draft, fields)
        self.grid: FormGrid = FormGrid(parent, msg.SETUP_SETTINGS_FIELD_LABELS, msg.SETUP_SETTINGS_FIELD_HINTS)
        for field in fields:
            self.grid.add(field, self.variables.variables[field.name])
            note: FieldNote = FieldNote(self.grid.frame, self.grid.note_row(field.name))
            context.shades.row(FieldUse.of(field.key), self.grid.row_widgets(field.name), note)
        self.problem: ProblemLine = ProblemLine(parent, msg.SETUP_SETTINGS_FIELD_LABELS)
        self.problem.label.pack(fill=tk.X, anchor=tk.W)
        buttons: ttk.Frame = ttk.Frame(parent)
        buttons.pack(side=tk.TOP, anchor=tk.CENTER, pady=PAD)
        self.save_button: ttk.Button = ttk.Button(buttons, text=msg.SETUP_BUTTON_SAVE, command=self.save)
        self.save_button.pack(side=tk.LEFT, padx=PAD)
        self.book.drafts.append(self.variables)

    @property
    def inputs(self) -> dict[str, tk.Widget]:
        return self.grid.inputs

    @property
    def form_draft(self) -> SettingsDraft:
        """Черновик модели окна, в котором поля раздела — как в окне сейчас."""
        return self.variables.typed_over(self.book.panel.draft)

    def save(self) -> None:
        """«Сохранить»: черновик — модели; принято — модель пишет файл, поля раздела — по записанному. Сбой диска —
        диалог по общему правилу окна (`SettingsWrite`), модель остаётся с принятым и несохранённым."""
        edit: PanelEdit[SettingsPanel] = self.book.panel.apply(self.form_draft)
        self.problem.show_problem(edit.problem)
        if not edit.is_applied:
            return
        self.book.panel = edit.panel
        saved: SettingsPanel | None = SettingsWrite(self.grid.frame).run(lambda: edit.panel.save().panel)
        if saved is None:
            return
        self.book.panel = saved
        self.variables.show(self.book.panel.draft)
        self.variables.accept()
        self.book.on_saved()
