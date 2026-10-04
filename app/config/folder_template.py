"""Шаблон папки превью: папка внутри image\\ и подпапка внутри папки материалов на Google Диске (CLAUDE.md §5,
§14 решение 27).

Одно правило на оба шаблона (`image_dir_template` и `drive.preview_path_template`): путь относительный, в нём есть
{date} и {language} и нет чужих подстановок. Шаблон сам проверяет себя (`problem`) и сам даёт части пути для даты и
языка эфира (`parts`): локальная копия превью ставит их под image\\, копия на Диске — подпапками папки материалов.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath
from typing import Final

from app.config.json_node import SettingProblem
from app.config.setting_key import SettingKey
from app.ui.messages import msg

# Подстановки шаблона: папка {date}\{language} (§5).
FOLDER_TEMPLATE_PLACEHOLDERS: Final[tuple[str, ...]] = ("date", "language")
FOLDER_TEMPLATE_PLACEHOLDER: Final[str] = "{{{name}}}"
FOLDER_TEMPLATE_PROBE: Final[str] = "probe"
# Части пути разделяет любая косая черта: человек пишет и preview/{date}, и preview\{date}.
FOLDER_SEPARATOR_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\\/]+")


@dataclass(frozen=True)
class FolderTemplate:
    """Шаблон папки превью, как он записан в livecraft.json."""

    text: str

    def problem(self, key: SettingKey) -> SettingProblem | None:
        """Что не так с шаблоном поля `key`: нет {date} или {language}, путь абсолютный, чужая подстановка."""
        absent: tuple[str, ...] = tuple(
            name for name in FOLDER_TEMPLATE_PLACEHOLDERS
            if FOLDER_TEMPLATE_PLACEHOLDER.format(name=name) not in self.text
        )
        if absent:
            text: str = msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_PLACEHOLDERS.format(absent=msg.LIST_JOINER.join(absent))
            return SettingProblem(key=key.value, text=text)
        if PureWindowsPath(self.text).is_absolute() or PurePosixPath(self.text).is_absolute():
            return SettingProblem(key=key.value, text=msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_ABSOLUTE)
        try:
            self.text.format(**{name: FOLDER_TEMPLATE_PROBE for name in FOLDER_TEMPLATE_PLACEHOLDERS})
        except (KeyError, IndexError, ValueError):
            return SettingProblem(key=key.value, text=msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_FORMAT)
        return None

    def parts(self, date: str, language: str) -> tuple[str, ...]:
        """Части пути папки эфира этой даты и языка, без пустых: «preview/{date}/{language}» →
        («preview», «28-09-2026», «uk»). Шаблон годен: его проверил разбор настроек."""
        rendered: str = self.text.format(date=date, language=language)
        return tuple(part.strip() for part in FOLDER_SEPARATOR_PATTERN.split(rendered) if part.strip())
