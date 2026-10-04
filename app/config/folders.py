"""Раздел `folders` файла `secrets\\livecraft.json`: папки пакетов, копий документов и превью (CLAUDE.md §14
решение 37, §6 инвариант 10).

Папки этих трёх ролей выбирает человек; в поставке — `bcast`, `docs` и `image` в корне программы. Путь относительный —
от корня программы, абсолютный — как есть: правило задаёт `DataFolders` (app\\paths.py), которому раздел отдаёт свои
папки (`data_folders`); дальше их знает только `LivecraftPaths`. Пустое значение — ошибка файла с путём ключа (разбор
`JsonNode.text`). Раздел строит себя сам из узла JSON (`from_node`) в пару к `to_data`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.json_node import JsonNode, json_value
from app.config.setting_key import SettingKey
from app.paths import DataFolders


@dataclass(frozen=True)
class FolderSettings:
    """Папки ролей как в файле: пакеты plan_*.bcast, копии документов объявлений .docx, превью."""

    packages: str
    docs: str
    images: str

    @classmethod
    def from_node(cls, node: JsonNode) -> FolderSettings:
        """Раздел `folders` файла: каждая папка — непустая строка."""
        node.mapping(SettingKey.leaves(SettingKey.FOLDERS))
        return cls(
            packages=node.field(SettingKey.FOLDERS_PACKAGES.leaf).text(),
            docs=node.field(SettingKey.FOLDERS_DOCS.leaf).text(),
            images=node.field(SettingKey.FOLDERS_IMAGES.leaf).text(),
        )

    def to_data(self) -> dict[str, Any]:
        return {leaf: json_value(getattr(self, leaf)) for leaf in SettingKey.leaves(SettingKey.FOLDERS)}

    @property
    def data_folders(self) -> DataFolders:
        """Папки ролей для путей программы."""
        return DataFolders(packages=Path(self.packages), docs=Path(self.docs), images=Path(self.images))
