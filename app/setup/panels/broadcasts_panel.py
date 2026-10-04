"""Раздел broadcasts без окна: какие ключи передать в форму — «новые | все» на «Главной» (CLAUDE.md §8.2, §14
решения 36, 47, 49).

«все» — передать ключи всех эфиров запуска ещё раз (`resend_keys`), «новые» — нет. Несохранённого у блока не бывает:
каждый выбор сразу пишется — в раздел, каким он сейчас на диске (`SettingsFile.save_broadcasts`), так что сохранённое
другими вкладками не откатывается, — и блок читается заново. Выбор делает строка «Ключи» «Главной» через модель линий
(`LinesPanel.choose_keys`).

Модель неизменяемая: каждое действие отдаёт новую (`PanelEdit`). OSError — наружу: сказать о нём человеку — дело окна.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.config.broadcasts import BroadcastSettings
from app.config.files import SettingsFile
from app.paths import LivecraftPaths
from app.setup.panels.panel_edit import PanelEdit


@dataclass(frozen=True)
class BroadcastsPanel:
    """Раздел broadcasts, каким он сейчас в файле настроек (файл не читается — поставочный вид), и файл."""

    broadcasts: BroadcastSettings
    file: SettingsFile

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> BroadcastsPanel:
        """Блок на livecraft.json этой установки."""
        return cls.from_file(SettingsFile.of(paths))

    @classmethod
    def from_file(cls, file: SettingsFile) -> BroadcastsPanel:
        return cls(broadcasts=file.latest.broadcasts, file=file)

    def switch_resend(self, resend_keys: bool) -> PanelEdit[BroadcastsPanel]:
        """«все» (`resend_keys`) или «новые» — в файл сразу, поверх свежего файла; блок, прочитанный заново."""
        self.file.save_broadcasts(self.file.latest.broadcasts.with_resend(resend_keys))
        return PanelEdit(panel=BroadcastsPanel.from_file(self.file))
