"""Раздел `google` файла `secrets\\livecraft.json`: файл проекта Google (CLAUDE.md §9, §14 решение 66).

Проект Google — файл клиента Google типа Desktop из Google Cloud Console. Человек выбирает его в окне на «Главной»:
файл лежит где угодно и называется как угодно, программа запоминает путь к нему (`project_file`) и не копирует его.
Путь внутри папки программы хранится от корня, вне её — полный: правило места то же, что у папок ролей
(`LivecraftPaths.project_file`), дальше путь знает только `LivecraftPaths`. Пустое значение — проект не выбран; это не
ошибка файла: о нём скажет готовность. Раздел строит себя сам из узла JSON (`from_node`) в пару к `to_data`.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.config.json_node import JsonNode, json_value
from app.config.setting_key import SettingKey


@dataclass(frozen=True)
class GoogleSettings:
    """Путь к файлу проекта Google как в файле; пусто — проект не выбран."""

    project_file: str

    @classmethod
    def from_node(cls, node: JsonNode) -> GoogleSettings:
        """Раздел `google` файла."""
        node.mapping(SettingKey.leaves(SettingKey.GOOGLE))
        return cls(project_file=node.field(SettingKey.GOOGLE_PROJECT_FILE.leaf).string())

    def to_data(self) -> dict[str, Any]:
        return {leaf: json_value(getattr(self, leaf)) for leaf in SettingKey.leaves(SettingKey.GOOGLE)}

    @property
    def project_path(self) -> Path | None:
        """Файл проекта для путей программы; не выбран — None."""
        return Path(self.project_file) if self.project_file else None
