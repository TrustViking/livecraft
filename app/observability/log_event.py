"""Строка лога livecraft: область логгера, словарь значений и событие «имя key=value» (CLAUDE.md §11).

Логгеры livecraft живут под корнем `livecraft`; область — член `LogArea`, и только через неё модуль
получает свой логгер (`get_logger`). Строка лога — объект `LogEvent`: имя события — член перечисления
событий своей области, поля — `key=value` в порядке аргументов. Значение поля пишется по одному правилу:
bool — `yes` / `no`, None и пустое — `-`, член перечисления — его значение, последовательность — через `,`.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.text_format import SPACE
from app.version import APP_NAME

LOGGER_NAME_TEMPLATE: Final[str] = "{root}.{area}"
FIELD_TEMPLATE: Final[str] = "{name}={value}"
MESSAGE_TEMPLATE: Final[str] = "%s"      # готовая строка события — аргументом: фильтр секретов видит её целиком


class LogArea(str, Enum):
    """Область лога: хвост имени логгера `livecraft.<область>`."""

    AUTH = "auth"
    INTAKE = "intake"
    LLM = "llm"
    MAIN = "main"
    PACKAGES = "packages"
    RUNTIME = "runtime"
    SETUP = "setup"
    SHEETS = "sheets"
    SLOTS = "slots"
    SOURCES = "sources"
    SOURCES_PREVIEW = "sources.preview"
    SOURCES_YTDLP = "sources.ytdlp"
    TEXTS = "texts"
    LLM_PROBE = "tools.llm_probe"
    SHEETS_PROBE = "tools.sheets_probe"
    SOURCE_PROBE = "tools.source_probe"
    VAULT = "vault"


class LogValue(str, Enum):
    """Словарь значений строк лога: одно написание на смысл во всей программе."""

    YES = "yes"
    NO = "no"
    EMPTY = "-"              # значения нет или оно пустое
    UNKNOWN = "unknown"      # значение должно было прийти, но не пришло
    OK = "ok"
    LIST_SEPARATOR = ","     # элементы списка в одном поле


def get_logger(area: LogArea) -> logging.Logger:
    """Логгер области: `livecraft.<область>`."""
    return logging.getLogger(LOGGER_NAME_TEMPLATE.format(root=APP_NAME, area=area.value))


@dataclass(frozen=True)
class LogField:
    """Поле строки лога: имя и значение как есть; запись значения — одно правило `text`."""

    name: str
    value: object

    @property
    def text(self) -> str:
        return FIELD_TEMPLATE.format(name=self.name, value=self.rendered)

    @property
    def rendered(self) -> str:
        """bool — yes / no; None и пустое — «-»; член перечисления — значение; последовательность — через «,»."""
        value: object = self.value
        if isinstance(value, bool):
            return (LogValue.YES if value else LogValue.NO).value
        if isinstance(value, Enum):
            value = value.value
        if isinstance(value, Sequence) and not isinstance(value, str):
            value = LogValue.LIST_SEPARATOR.value.join(LogField(self.name, item).rendered for item in value)
        text: str = "" if value is None else str(value)
        return text or LogValue.EMPTY.value


@dataclass(frozen=True)
class LogEvent:
    """Строка лога: имя события и поля по порядку. Неизменяемая — `extended` строит новую."""

    name: str
    fields: tuple[LogField, ...] = ()

    @classmethod
    def of(cls, name: str, **fields: object) -> LogEvent:
        """Событие с полями в порядке аргументов; имя — член перечисления событий или строка."""
        event_name: str = name.value if isinstance(name, Enum) else name
        return cls(name=event_name, fields=tuple(LogField(key, value) for key, value in fields.items()))

    def extended(self, **fields: object) -> LogEvent:
        """То же событие с новыми полями в конце."""
        added: tuple[LogField, ...] = tuple(LogField(key, value) for key, value in fields.items())
        return LogEvent(name=self.name, fields=self.fields + added)

    @property
    def text(self) -> str:
        return SPACE.join((self.name, *(field.text for field in self.fields)))

    def emit(self, logger: logging.Logger, level: int = logging.INFO) -> None:
        logger.log(level, MESSAGE_TEMPLATE, self.text)
