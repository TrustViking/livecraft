"""Раздел дополнительных настроек на вкладке окна (CLAUDE.md §8.2, §14 решения 37, 63).

Поля livecraft.json разложены по вкладкам линий: параметры модели — на «Нейросети», шаблоны папок превью — на
«Превью», доступ и контакты документа — на «Google-документе», настройки эфира — на «Эфирах YouTube», пояс и срок
хранения — на «Дополнительно», срок напоминания о cookies — на «Cookies YouTube». Раздел — сетка своих полей черновика
(`SETTINGS_FIELDS`: текст — поле ввода, «да / нет» — ползунок, варианты — выбор из списка, малое целое — поле со
стрелками); под каждым полем — строка итога его записи. Кнопки «Сохранить» у раздела нет: каждое поле сохраняется само
(§8.2, «Сохранение — у поля») — ползунок сразу после переключения, выбор — после выбора варианта, стрелка — после
щелчка (§14 решение 75), текст — по Enter и когда фокус уходит из поля. Пишет поле модель окна
(`SettingsBook.commit`): записано — «✓ сохранено» зелёным и перерисовка окна; отказ — причина красным с подписью поля.
Каждая строка сетки — поле со своими линиями (`FieldUse`): не нужно ни одной работающей — бледное. Своих правил у
раздела нет.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from app.config.setting_key import SettingKey
from app.setup.fields.draft_field import DraftField, DraftKind
from app.setup.fields.field_use import FieldUse
from app.setup.fields.settings_draft import SETTINGS_FIELDS, SettingsDraft
from app.setup.tabs.field_shade import FieldNote
from app.setup.tabs.setup_context import SettingRow, SettingsBook, SetupContext
from app.setup.tabs.tab_event import TkEvent
from app.setup.tabs.tab_grid import DraftVariables, FormGrid
from app.setup.tabs.tab_layout import ProblemLine
from app.setup.tabs.toggle_switch import ToggleSwitch
from app.ui.messages import msg


class SettingsSection:
    """Раздел настроек в `parent`: модель окна `book`, сетка своих полей и по полю окна (`rows`, по имени поля
    черновика) — переменная и строка итога записи."""

    def __init__(self, parent: ttk.Frame, context: SetupContext, keys: tuple[SettingKey, ...]) -> None:
        self.book: SettingsBook = context.settings
        fields: tuple[DraftField, ...] = tuple(
            next(field for field in SETTINGS_FIELDS if field.key is key) for key in keys
        )
        self.grid: FormGrid = FormGrid(parent, msg.SETUP_SETTINGS_FIELD_LABELS, msg.SETUP_SETTINGS_FIELD_HINTS)
        variables: DraftVariables[SettingsDraft] = DraftVariables(self.grid.frame, self.book.panel.draft, fields)
        self.rows: dict[str, SettingRow] = {}
        for field in fields:
            row: SettingRow = SettingRow(
                field, variables.variables[field.name], ProblemLine(self.grid.frame, msg.SETUP_SETTINGS_FIELD_LABELS)
            )
            self._place(row)
            note: FieldNote = FieldNote(self.grid.frame, self.grid.note_row(field.name))
            context.shades.row(FieldUse.of(field.key), self.grid.row_widgets(field.name), note)

    @property
    def inputs(self) -> dict[str, tk.Widget]:
        return self.grid.inputs

    def _place(self, row: SettingRow) -> None:
        """Строка поля в сетке и строка итога под ним; поле сохраняется само — по своему виду (§8.2)."""
        widget: tk.Widget = self.grid.add(row.field, row.variable)
        self.grid.place_result(row.field.name, row.line.label)
        self.rows[row.field.name] = row
        self.book.rows.append(row)
        if isinstance(widget, ToggleSwitch):
            widget.command = lambda: self.book.commit(row)
        elif row.field.kind is DraftKind.CHOICE:
            widget.bind(TkEvent.COMBOBOX_SELECTED, lambda _event: self.book.commit(row))
        else:
            for event in (TkEvent.RETURN, TkEvent.FOCUS_OUT):
                widget.bind(event, lambda _event: self.book.commit(row), add=True)
            if row.field.spin is not None:
                widget.configure(command=lambda: self.book.commit(row))
