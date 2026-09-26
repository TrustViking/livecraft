"""Вкладка «Настройки запуска» без окна (CLAUDE.md §8.2 п.3, §5).

Вкладка держит настройки, какими они будут записаны (всегда годные), и то, какими они прочитаны с диска.
Своих правил проверки у неё нет: черновик переводится в данные livecraft.json и разбирается тем же
разбором, что читает файл (`SettingsFile.parse`); ошибка разбора и есть проблема поля. Контракт формы на
вкладке не правится и переносится при записи как есть. Пишет только файл настроек (`SettingsFile.save`).

Нет или не читается livecraft.json — вкладка открывается на поставочном шаблоне программы (`ShippedSettings`),
говорит об этом и пишет файл только по «сохранить»: разбор по-прежнему умолчаний не подставляет (§16, решения
к задаче 2.2).

Вкладка неизменяемая: `apply` и `save` отдают новую. Окно Tk (задача 2.3) только рисует её ответы.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from app.config.files import SettingsFile, ShippedSettings
from app.config.json_node import ConfigError, SettingProblem
from app.config.settings import LivecraftSettings, ReasoningEffort, ServiceTier
from app.paths import LivecraftPaths
from app.setup.fields.settings_draft import SettingsDraft
from app.ui import messages_ru as msg


@dataclass(frozen=True)
class SettingsPanelEdit:
    """Итог правки: вкладка после неё и проблема. Негодно — `panel` та же, что была, `problem` называет почему."""

    panel: SettingsPanel
    problem: SettingProblem | None

    @property
    def is_applied(self) -> bool:
        """Правка принята: вкладка содержит новые настройки."""
        return self.problem is None


@dataclass(frozen=True)
class SettingsPanel:
    """Вкладка «Настройки запуска».

    `settings` — настройки, какими будут записаны; всегда прошли загрузчик. `loaded` — как прочитано с диска
    (None — не прочитано), `load_problem` — почему. `file` — файл настроек: его разбор проверяет правки.
    """

    settings: LivecraftSettings
    loaded: LivecraftSettings | None
    load_problem: SettingProblem | None
    file: SettingsFile

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> SettingsPanel:
        """Прочитать livecraft.json. Не прочитался — вкладка на шаблоне программы и с причиной от разбора."""
        file: SettingsFile = SettingsFile.of(paths)
        try:
            settings: LivecraftSettings = file.load()
        except ConfigError as error:
            return cls(
                settings=ShippedSettings().settings,
                loaded=None,
                load_problem=SettingProblem(key=error.key_path, text=error.problem),
                file=file,
            )
        return cls(settings=settings, loaded=settings, load_problem=None, file=file)

    @property
    def draft(self) -> SettingsDraft:
        """Поля вкладки текстом — что окно показывает и отдаёт обратно в `apply`."""
        return SettingsDraft.of(self.settings)

    @property
    def reasoning_effort_options(self) -> tuple[str, ...]:
        """Варианты уровня reasoning — из самого перечня загрузчика."""
        return tuple(effort.value for effort in ReasoningEffort)

    @property
    def service_tier_options(self) -> tuple[str, ...]:
        """Варианты тарифа — из самого перечня загрузчика."""
        return tuple(tier.value for tier in ServiceTier)

    @property
    def is_dirty(self) -> bool:
        """Есть несохранённое: настройки отличаются от прочитанных; файл не прочитан — записывать есть что."""
        return self.loaded is None or self.settings != self.loaded

    @property
    def notices(self) -> tuple[str, ...]:
        """Строки вкладки для человека: файл не прочитан — почему и на чём открыта вкладка."""
        if self.load_problem is None:
            return ()
        return (msg.SETUP_SETTINGS_NOTICE_UNREADABLE.format(key=self.load_problem.key, problem=self.load_problem.text),)

    def apply(self, draft: SettingsDraft) -> SettingsPanelEdit:
        """Принять поля вкладки: разбор загрузчиком; негодно — та же вкладка и проблема с путём поля."""
        try:
            settings: LivecraftSettings = self.file.parse(draft.to_data(self.settings.form))
        except ConfigError as error:
            return SettingsPanelEdit(panel=self, problem=SettingProblem(key=error.key_path, text=error.problem))
        return SettingsPanelEdit(panel=dataclasses.replace(self, settings=settings), problem=None)

    def save(self, paths: LivecraftPaths) -> SettingsPanel:
        """Записать настройки через загрузчик и вернуть вкладку, прочитанную заново.

        OSError — наружу: сказать о нём человеку — дело окна (задача 2.3).
        """
        SettingsFile.of(paths).save(self.settings)
        return SettingsPanel.from_paths(paths)
