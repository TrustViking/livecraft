"""Папка роли в окне настройщика — без Tk (CLAUDE.md §14 решение 37, §6 инвариант 10).

Папки пакетов, копий документов и превью выбирает человек (раздел `folders` livecraft.json). В файл идёт путь,
как его понимает программа (`DataFolders`, app\\paths.py): папка внутри корня программы — относительным путём от корня,
вне корня — абсолютным; «По умолчанию» — имя папки роли в корне из поставочного шаблона (`bcast`, `docs`, `image`).
Выбор и возврат к умолчанию пишутся сразу — только своё поле раздела `folders` поверх файла, как он сейчас на диске
(`SettingsFile.latest`): сохранённое другими вкладками не откатывается. Модель неизменяемая: запись отдаёт модель,
прочитанную заново; OSError — наружу, сказать о нём человеку — дело окна.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from pathlib import Path

from app.config.files import SettingsFile, ShippedSettings
from app.config.folders import FolderSettings
from app.config.setting_key import SettingKey
from app.config.settings import LivecraftSettings
from app.paths import LivecraftPaths
from app.ui.messages import msg


@dataclass(frozen=True)
class FolderField:
    """Папка роли: ключ поля (`folders.packages`, `folders.docs`, `folders.images`), путь, как он в файле, корень
    программы и файл настроек."""

    key: SettingKey
    value: str
    root: Path
    file: SettingsFile

    @classmethod
    def from_paths(cls, paths: LivecraftPaths, key: SettingKey) -> FolderField:
        """Папка роли `key` в livecraft.json этой установки."""
        return cls.from_file(SettingsFile.of(paths), paths.root, key)

    @classmethod
    def from_file(cls, file: SettingsFile, root: Path, key: SettingKey) -> FolderField:
        """Папка, как она сейчас на диске; файл не читается — как в поставочном виде."""
        return cls(key=key, value=cls.value_in(file.latest.folders, key), root=root, file=file)

    @classmethod
    def value_in(cls, folders: FolderSettings, key: SettingKey) -> str:
        """Путь роли `key` в разделе `folders`."""
        return str(folders.to_data()[key.leaf])

    @property
    def label(self) -> str:
        return msg.SETUP_FOLDER_LABELS[self.key.value]

    @property
    def hint(self) -> str:
        return msg.SETUP_FOLDER_HINTS[self.key.value]

    @property
    def default(self) -> str:
        """Папка роли по умолчанию: имя роли в корне программы, как в поставочном шаблоне."""
        return self.value_in(ShippedSettings().settings.folders, self.key)

    @property
    def place(self) -> Path:
        """Где папка на диске: относительный путь — от корня программы, абсолютный — как есть."""
        return self.root / self.value

    @property
    def status(self) -> str:
        """Где папка — для человека: от корня программы, вне корня — целиком (правило `LivecraftPaths.shown`)."""
        return msg.SETUP_FOLDER_STATUS.format(path=LivecraftPaths(self.root).shown(self.place))

    def stored(self, picked: Path) -> str:
        """Путь для файла: папка внутри корня — относительно корня, вне корня — абсолютный."""
        if picked.is_relative_to(self.root):
            return picked.relative_to(self.root).as_posix()
        return str(picked)

    def choose(self, picked: Path) -> FolderField:
        """Выбрана папка `picked` — сразу в файл; модель, прочитанная заново."""
        return self._saved(self.stored(picked))

    def reset(self) -> FolderField:
        """«По умолчанию» — имя роли в корне программы, сразу в файл."""
        return self._saved(self.default)

    def _saved(self, value: str) -> FolderField:
        """Своё поле раздела `folders` — поверх файла, как он сейчас на диске."""
        latest: LivecraftSettings = self.file.latest
        folders: FolderSettings = dataclasses.replace(latest.folders, **{self.key.leaf: value})
        self.file.save(dataclasses.replace(latest, folders=folders))
        return FolderField.from_file(self.file, self.root, self.key)
