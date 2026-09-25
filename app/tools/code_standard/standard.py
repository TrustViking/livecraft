"""Стандарт кода как данные: пороги и списки из `standard.json` (REFACTORING_STANDARD.md §5, §6).

В коде замка порогов нет: каждое число и каждый список правила берутся отсюда.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.tools.code_standard.json_file import JsonObject
from app.tools.code_standard.source import SourceKey


class StandardKey(str, Enum):
    """Ключи `standard.json`."""

    MAX_DEFINITION_LINES = "max_definition_lines"
    MAX_PARAMETERS = "max_parameters"
    MAX_MODULE_LINES = "max_module_lines"
    MAX_CLASS_MEMBERS = "max_class_members"
    MODULE_SIZE_EXEMPT = "module_size_exempt"
    WRAPPER_BUILTINS = "wrapper_builtins"


@dataclass(frozen=True)
class Standard:
    """Пороги правил формы (E3, E4, E18) и списки, которые меняют их прочтение (E12, E18).

    Пути модулей-исключений приводятся к ключу с обратной косой чертой, как ключи реестра.
    """

    max_definition_lines: int
    max_parameters: int
    max_module_lines: int
    max_class_members: int
    module_size_exempt: frozenset[str]
    wrapper_builtins: frozenset[str]

    @classmethod
    def load(cls, path: Path) -> Standard:
        """Стандарт из файла; нет ключа или не тот тип — `StandardFileError`."""
        data: JsonObject = JsonObject.read(path)
        return cls(
            max_definition_lines=data.integer(StandardKey.MAX_DEFINITION_LINES.value),
            max_parameters=data.integer(StandardKey.MAX_PARAMETERS.value),
            max_module_lines=data.integer(StandardKey.MAX_MODULE_LINES.value),
            max_class_members=data.integer(StandardKey.MAX_CLASS_MEMBERS.value),
            module_size_exempt=frozenset(
                SourceKey.of(exempt).text for exempt in data.texts(StandardKey.MODULE_SIZE_EXEMPT.value)
            ),
            wrapper_builtins=frozenset(data.texts(StandardKey.WRAPPER_BUILTINS.value)),
        )
