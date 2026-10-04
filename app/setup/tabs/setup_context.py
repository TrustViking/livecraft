"""Общее у всех вкладок окна настройщика (CLAUDE.md §8.2, §14 решение 37).

`SetupContext` — то, что окно даёт каждой вкладке: блокнот, пути установки, сейф окна (читается один раз и заново —
после записи окна), ползунки линий (одна переменная на линию на всё окно), бледность полей, настройки окна и что сделать
после любой записи. `SettingsBook` — одна модель
дополнительных настроек (`SettingsPanel`) на все разделы вкладок: поля livecraft.json разложены по вкладкам линий, а
пишется файл одной моделью, поверх того, что на диске. Разделы кладут сюда свои переменные: несохранённое окна —
набранное в любом разделе или то, что модель ещё не записала. Файл записал не раздел окна (загруженный токен доступа) —
модель и поля разделов перечитываются с диска (`reload`).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from tkinter import ttk

from app.paths import LivecraftPaths
from app.setup.fields.settings_draft import SettingsDraft
from app.setup.panels.settings_panel import SettingsPanel
from app.setup.setup_vault import SetupVault
from app.setup.tabs.field_shade import FieldShades
from app.setup.tabs.line_switches import LineSwitches
from app.setup.tabs.tab_grid import DraftVariables


@dataclass
class SettingsBook:
    """Модель дополнительных настроек окна, переменные разделов вкладок и что сделать после записи."""

    panel: SettingsPanel
    on_saved: Callable[[], None]
    drafts: list[DraftVariables[SettingsDraft]] = field(default_factory=list)

    @property
    def is_dirty(self) -> bool:
        """Модель не записала своё (файл не прочитан) или в каком-то разделе набрано непринятое."""
        return self.panel.is_dirty or any(draft.has_typed for draft in self.drafts)

    def reload(self) -> None:
        """Модель и поля всех разделов — как livecraft.json сейчас на диске: его записал загруженный токен доступа
        (контакты документа объявлений). Без этого раздел показывал бы прежнее значение, а запись любого раздела
        вернула бы его в файл."""
        self.panel = SettingsPanel.from_file(self.panel.file)
        for draft in self.drafts:
            draft.show(self.panel.draft)
            draft.accept()


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
