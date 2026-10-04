"""Раздел `drive` файла `secrets\\livecraft.json`: подпапки превью на Google Диске (CLAUDE.md §5, §14 решения 27, 39).

Саму папку материалов задаёт человек ссылкой, и её id лежит в сейфе (`SecretField.DRIVE_FOLDER`, решение 39): в
livecraft.json её нет. Внутри папки программа сама создаёт подпапки превью по шаблону `preview_path_template` (правило
шаблона — `FolderTemplate`, то же, что у папки превью в image\\). Раздел строит себя сам из узла JSON (`from_node`) в
пару к `to_data` и сам говорит, что с ним не так (`problem`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.config.folder_template import FolderTemplate
from app.config.json_node import JsonNode, SettingProblem, json_value
from app.config.setting_key import SettingKey


@dataclass(frozen=True)
class DriveSettings:
    """Шаблон подпапки превью внутри папки материалов на Google Диске."""

    preview_path_template: str

    @classmethod
    def from_node(cls, node: JsonNode) -> DriveSettings:
        """Раздел `drive` файла."""
        node.mapping(SettingKey.leaves(SettingKey.DRIVE))
        return cls(preview_path_template=node.field(SettingKey.DRIVE_PREVIEW_PATH_TEMPLATE.leaf).text())

    def to_data(self) -> dict[str, Any]:
        return {leaf: json_value(getattr(self, leaf)) for leaf in SettingKey.leaves(SettingKey.DRIVE)}

    @property
    def preview_folder(self) -> FolderTemplate:
        """Шаблон подпапки превью внутри папки материалов."""
        return FolderTemplate(self.preview_path_template)

    @property
    def problem(self) -> SettingProblem | None:
        """Что не так с разделом по смыслу: шаблон подпапки негоден; путь — от корня."""
        return self.preview_folder.problem(SettingKey.DRIVE_PREVIEW_PATH_TEMPLATE)
