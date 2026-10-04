"""Строка открытой ссылки livecraft.json без окна (CLAUDE.md §8.2 п.2, §14 решение 15).

Ссылка на форму ключей не секрет: она лежит в livecraft.json открытым текстом и показывается как есть (папка Google
Диска — поле сейфа, §14 решение 39). Строка знает своё поле (`SettingKey`), задана ли ссылка и что показать;
своих правил проверки у неё нет: ввод ставится в данные файла на место поля и разбирается тем же разбором, что читает
файл (`SettingsFile.parse`), — ошибка разбора и есть проблема поля. Пишет строка только своё поле — поверх файла, как
он сейчас на диске (`SettingsFile.latest`): сохранение других вкладок не откатывается.

Модель неизменяемая: `replace`, `clear` и `save` отдают новую. Поле — всегда в разделе файла (`form.url`), не в корне.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass

from app.config.files import SettingsFile
from app.config.json_node import ConfigError, SettingProblem
from app.config.setting_key import SettingKey
from app.config.settings import LivecraftSettings
from app.paths import LivecraftPaths
from app.setup.panels.panel_edit import PanelEdit
from app.ui.messages import msg


@dataclass(frozen=True)
class SettingLink:
    """Открытая ссылка livecraft.json: поле, ссылка, какой она будет записана, и какой прочитана с диска."""

    key: SettingKey
    url: str
    loaded_url: str
    file: SettingsFile

    @classmethod
    def from_paths(cls, paths: LivecraftPaths, key: SettingKey) -> SettingLink:
        """Ссылка поля `key` в livecraft.json этой установки."""
        return cls.from_file(SettingsFile.of(paths), key)

    @classmethod
    def from_file(cls, file: SettingsFile, key: SettingKey) -> SettingLink:
        """Ссылка, как она сейчас на диске; файл не читается — как в поставочном виде (пусто — не задана)."""
        url: str = str(file.latest.to_data()[key.section][key.leaf])
        return cls(key=key, url=url, loaded_url=url, file=file)

    @property
    def label(self) -> str:
        return msg.SETUP_LINK_LABELS[self.key.value]

    @property
    def hint(self) -> str:
        return msg.SETUP_LINK_HINTS[self.key.value]

    @property
    def is_set(self) -> bool:
        """Ссылка задана; пусто — не задана (§5: это не ошибка файла, а неготовая часть режима)."""
        return bool(self.url)

    @property
    def status(self) -> str:
        """Задана — сама ссылка: она не секрет; нет — «не задано»."""
        return msg.SETUP_LINK_STATUS_SET.format(url=self.url) if self.is_set else msg.SETUP_STATUS_NOT_SET

    @property
    def is_dirty(self) -> bool:
        """Есть несохранённое: ссылка отличается от прочитанной с диска."""
        return self.url != self.loaded_url

    def replace(self, raw: str) -> PanelEdit[SettingLink]:
        """Вписать ссылку: пусто — просьба ввести (задана — назвать кнопку «Удалить»); негодна — проблема разбора с
        путём поля; годна — новая модель."""
        text: str = raw.strip()
        if not text:
            empty: str = msg.SETUP_INPUT_EMPTY_RESET.format(button=msg.SETUP_KEYS_BUTTON_DELETE_OWN)
            problem: str = empty if self.is_set else msg.SETUP_INPUT_EMPTY
            return PanelEdit(panel=self, problem=SettingProblem(key=self.key.value, text=problem))
        try:
            self.file.parse(self._data(self.file.latest, text))
        except ConfigError as error:
            return PanelEdit(panel=self, problem=SettingProblem(key=error.key_path, text=error.problem))
        return PanelEdit(panel=dataclasses.replace(self, url=text))

    def clear(self) -> SettingLink:
        """Убрать ссылку: поле станет пустым — «не задано»."""
        return dataclasses.replace(self, url="")

    def save(self) -> PanelEdit[SettingLink]:
        """Своё поле — поверх файла, как он сейчас на диске, через разбор файла; вернуть строку, прочитанную заново.

        OSError — наружу: сказать о нём человеку — дело окна.
        """
        self.file.save(self.file.parse(self._data(self.file.latest, self.url)))
        return PanelEdit(panel=SettingLink.from_file(self.file, self.key))

    def _data(self, settings: LivecraftSettings, url: str) -> dict[str, object]:
        """Данные livecraft.json: данные `settings`, где на месте поля стоит `url`."""
        root: dict[str, object] = settings.to_data()
        section: dict[str, object] = {**settings.to_data()[self.key.section], self.key.leaf: url}
        return {**root, self.key.section: section}
