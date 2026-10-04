"""Дополнительные настройки окна без окна (CLAUDE.md §8.2 п.6, §5, §14 решение 37).

Одна модель на все разделы настроек: поля разложены по вкладкам линий («Нейросеть», «Превью», «Google-документ»,
«Эфиры YouTube») и «Дополнительно», а пишется файл одной моделью. Модель держит настройки, какими они будут записаны
(всегда годные), и то, какими они прочитаны с диска.
Своих правил проверки у неё нет: черновик переводится в данные livecraft.json и разбирается тем же
разбором, что читает файл (`SettingsFile.parse`); ошибка разбора и есть проблема поля. Разделы form, telegram,
broadcasts, lines и folders и ссылка на папку Диска на вкладке не правятся. Пишет только файл настроек
(`SettingsFile.save`): свои поля поверх свежепрочитанного файла, разделы form, telegram, broadcasts, lines и folders и
ссылка на папку — с диска, какими их сохранили строки ссылок, «Telegram», ползунки линий, папки ролей, переключатели
раздела broadcasts и запуск (раздел, дописанный из шаблона).

Нет или не читается livecraft.json — модель открывается на поставочном шаблоне программы (`ShippedSettings`),
говорит об этом («Дополнительно») и пишет файл только по «сохранить»: разбор по-прежнему умолчаний не подставляет. Языки формы
(`form_languages`) — только из прочитанного файла: на шаблоне вкладка не выдаёт чужую форму за настроенную.

API вкладки тот же, что у остальных моделей вкладок: `title`, `notices`, `is_dirty`, `save`. Вкладка неизменяемая:
`apply` и `save` отдают новую. Окно Tk только рисует её ответы.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from app.config.files import SettingsFile, ShippedSettings
from app.config.json_node import ConfigError, SettingProblem
from app.config.settings import FormQuestion, LivecraftSettings
from app.paths import LivecraftPaths
from app.setup.fields.settings_draft import SettingsDraft
from app.setup.page import SetupPage
from app.setup.panels.panel_edit import PanelEdit
from app.ui.messages import msg


@dataclass(frozen=True)
class SettingsPanel:
    """Вкладка «Дополнительно».

    `settings` — настройки, какими будут записаны; всегда прошли загрузчик. `loaded` — как прочитано с диска
    (None — не прочитано), `load_problem` — почему. `file` — файл настроек: его разбор проверяет правки.
    """

    settings: LivecraftSettings
    loaded: LivecraftSettings | None
    load_problem: SettingProblem | None
    file: SettingsFile

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> SettingsPanel:
        """Вкладка на livecraft.json этой установки."""
        return cls.from_file(SettingsFile.of(paths))

    @classmethod
    def from_file(cls, file: SettingsFile) -> SettingsPanel:
        """Прочитать файл настроек. Не прочитался — вкладка на шаблоне программы и с причиной от разбора."""
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
    def title(self) -> str:
        return SetupPage.ADVANCED.title

    @property
    def draft(self) -> SettingsDraft:
        """Поля вкладки текстом — что окно показывает и отдаёт обратно в `apply`."""
        return SettingsDraft.of(self.settings)

    @property
    def form_languages(self) -> tuple[str, ...]:
        """Коды вариантов вопроса о языке в форме прочитанного файла; файл не прочитан — языков формы нет."""
        if self.loaded is None:
            return ()
        return tuple(self.loaded.form.values.get(FormQuestion.LANGUAGE.value, {}))

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

    def apply(self, draft: SettingsDraft) -> PanelEdit[SettingsPanel]:
        """Принять поля вкладки: разбор загрузчиком; негодно — та же вкладка и проблема с путём поля."""
        try:
            settings: LivecraftSettings = self.file.parse(draft.to_data(self.settings))
        except ConfigError as error:
            return PanelEdit(panel=self, problem=SettingProblem(key=error.key_path, text=error.problem))
        return PanelEdit(panel=dataclasses.replace(self, settings=settings))

    def save(self) -> PanelEdit[SettingsPanel]:
        """Записать свои поля поверх файла, как он сейчас на диске, и вернуть вкладку, прочитанную заново.

        Разделы form, telegram, broadcasts, lines и folders — не поля этой вкладки: они берутся с диска, и сохранённое
        другими вкладками не откатывается. Настройки годны всегда. OSError — наружу: сказать о нём человеку — дело окна.
        """
        fresh: LivecraftSettings = self.file.latest
        kept: LivecraftSettings = dataclasses.replace(
            self.settings, form=fresh.form, telegram=fresh.telegram, broadcasts=fresh.broadcasts
        )
        self.file.save(dataclasses.replace(kept, lines=fresh.lines, folders=fresh.folders))
        return PanelEdit(panel=SettingsPanel.from_file(self.file))
