"""Общее у всех вкладок окна настройщика (CLAUDE.md §8.2, §14 решение 37).

`SetupContext` — то, что окно даёт каждой вкладке: блокнот, пути установки, сейф окна (читается один раз и заново —
после записи окна), ползунки линий (одна переменная на линию на всё окно), бледность полей, настройки окна и что сделать
после любой записи. `SettingsBook` — одна модель дополнительных настроек (`SettingsPanel`) на все разделы вкладок: поля
livecraft.json разложены по вкладкам линий, а пишется файл одной моделью, поверх того, что на диске. Каждое поле
сохраняется само (§8.2, «Сохранение — у поля»): разделы кладут сюда свои поля окна (`SettingRow`), и книга пишет одно
поле, когда в нём не то, что сохранено (`commit`); итог — строкой у поля. Несохранённое окна — поле, запись которого
отказала (негодное значение, сбой диска). Перед закрытием окна книга сохраняет набранное во всех полях
(`commit_typed`): закрытие — тоже уход из поля. Файл записал не раздел окна (загруженный токен доступа) — модель и
поля перечитываются с диска (`reload`).
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass, field
from tkinter import ttk

from app.paths import LivecraftPaths
from app.setup.fields.draft_field import DraftField, DraftValue
from app.setup.fields.settings_draft import SettingsDraft
from app.setup.panels.panel_edit import PanelEdit
from app.setup.panels.settings_panel import SettingsPanel
from app.setup.setup_vault import SetupVault
from app.setup.tabs.field_shade import FieldShades
from app.setup.tabs.line_switches import LineSwitches
from app.setup.tabs.settings_write import SettingsWrite
from app.setup.tabs.tab_layout import ProblemLine


@dataclass(frozen=True)
class SettingRow:
    """Поле настройки в окне: поле черновика, переменная Tk с его значением и строка итога его записи."""

    field: DraftField
    variable: tk.Variable
    line: ProblemLine

    @property
    def value(self) -> DraftValue:
        """Значение поля окна в черновике: подпись варианта — сам вариант."""
        return self.field.draft_value(self.variable.get())

    def is_saved_in(self, draft: SettingsDraft) -> bool:
        """В поле то же, что в сохранённом черновике `draft`, — по значению для файла: пробелы по краям текста и
        запись числа («014») не в счёт."""
        return self.field.data(self.value) == self.field.data(getattr(draft, self.field.name))

    def show(self, draft: SettingsDraft) -> None:
        """Поле окна — по черновику `draft`."""
        self.variable.set(self.field.shown(getattr(draft, self.field.name)))


@dataclass
class SettingsBook:
    """Модель дополнительных настроек окна, поля разделов вкладок (`rows`) и что сделать после записи."""

    panel: SettingsPanel
    on_saved: Callable[[], None]
    rows: list[SettingRow] = field(default_factory=list)

    @property
    def is_dirty(self) -> bool:
        """Хотя бы в одном поле — не то, что сохранено: его запись отказала."""
        saved: SettingsDraft = self.panel.draft
        return any(not row.is_saved_in(saved) for row in self.rows)

    def commit(self, row: SettingRow) -> None:
        """Поле `row` — в файл, если в нём не то, что сохранено: модель кладёт значение поверх сохранённых настроек и
        пишет файл; записано — поле по записанному, «✓ сохранено» и перерисовка окна; негодно — проблема у поля, файл
        не тронут, набранное остаётся. Сбой диска — диалог по общему правилу окна (`SettingsWrite`). То же, что
        сохранено, — файл не пишется; строка, которая что-то говорила, — «✓ сохранено»."""
        saved: SettingsDraft = self.panel.draft
        if row.is_saved_in(saved):
            row.show(saved)
            if row.line.text:
                row.line.show_saved()
            return
        value: DraftValue = row.value
        edit: PanelEdit[SettingsPanel] | None = SettingsWrite(row.line.label).run(
            lambda: self.panel.save_value(row.field, value)
        )
        if edit is None:
            return
        if not edit.is_applied:
            row.line.show_problem(edit.problem)
            return
        self.panel = edit.panel
        row.show(self.panel.draft)
        row.line.show_saved()
        self.on_saved()

    def commit_typed(self) -> None:
        """Набранное во всех полях — в файл, поле за полем (`commit`): закрытие окна — тоже уход из поля."""
        for row in self.rows:
            self.commit(row)

    def reload(self) -> None:
        """Модель и поля — как livecraft.json сейчас на диске: его записал загруженный токен доступа (контакты
        документа объявлений). Без этого поле показывало бы прежнее значение, а набранное в нём вернуло бы его в
        файл."""
        self.panel = SettingsPanel.from_file(self.panel.file)
        for row in self.rows:
            row.show(self.panel.draft)
            row.line.show_text(None)


@dataclass(frozen=True)
class SetupContext:
    """Что окно даёт вкладкам: блокнот, пути, сейф окна, ползунки линий, бледность полей, настройки и что сделать после
    записи."""

    notebook: ttk.Notebook
    paths: LivecraftPaths
    vault: SetupVault
    switches: LineSwitches
    shades: FieldShades
    settings: SettingsBook
    on_saved: Callable[[], None]
