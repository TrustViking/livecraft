"""Значение JSON с его путём: одно правило чтения поля конфига и одна ошибка (CLAUDE.md §5, §14 решение 4).

Конфиги livecraft — JSON, все поля обязательные, умолчаний в коде нет. Каждый объект настроек строит себя сам
из `JsonNode` (`from_node`): узел знает своё значение, путь ключа (`KeyPath`: `channels[1].languages`,
`form.fields.date`) и файл, поэтому любая проблема поля — `ConfigError` с точным путём, а правило чтения
значения одного вида (строка, целое, выбор из перечня) — одно на все файлы.

Неизвестное и повторённое поле — тоже ошибка с его именем: `json` молча взял бы последнее из повторов.
"""
from __future__ import annotations

import json
import math
from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Final, TypeVar

from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogEvent
from app.ui import messages_ru as msg

KEY_SEPARATOR: Final[str] = "."          # части пути ключа: form.fields.date
ITEM_TEMPLATE: Final[str] = "[{index}]"  # элемент списка в пути: channels[1]

ChoiceT = TypeVar("ChoiceT", bound=Enum)


class ConfigProblem(str, Enum):
    """Что именно не так: нет файла, нет поля или негодное значение («не настроено» против «сломано»)."""

    FILE_MISSING = "file_missing"
    FIELD_MISSING = "field_missing"
    INVALID = "invalid"


class ConfigEvent(str, Enum):
    """События конфигов в логе."""

    ERROR = "config_error"


@dataclass(frozen=True)
class SettingProblem:
    """Что не так со значением настройки: путь ключа относительно объекта и русский текст причины."""

    key: str
    text: str


@dataclass(frozen=True)
class KeyPath:
    """Путь ключа в файле конфига: имена полей и номера элементов списков; пустой путь — корень файла."""

    parts: tuple[str | int, ...] = ()

    def child(self, key: str) -> KeyPath:
        """Путь к полю этого объекта; `key` может быть и путём через точку (`values.platform`)."""
        return KeyPath(parts=(*self.parts, key))

    def item(self, index: int) -> KeyPath:
        return KeyPath(parts=(*self.parts, index))

    @property
    def within_item(self) -> KeyPath:
        """Путь внутри первого элемента списка: у `channels[1].handle` — `handle`; без элемента — сам путь."""
        for position, part in enumerate(self.parts):
            if isinstance(part, int) and self.parts[position + 1:]:
                return KeyPath(parts=self.parts[position + 1:])
        return self

    @property
    def text(self) -> str:
        """`channels[1].languages`; корень файла — своим названием для человека."""
        if not self.parts:
            return msg.CONFIG_ROOT_KEY
        text: str = ""
        for part in self.parts:
            if isinstance(part, int):
                text += ITEM_TEMPLATE.format(index=part)
            else:
                text += f"{KEY_SEPARATOR}{part}" if text else part
        return text


class ConfigError(Exception):
    """Ошибка конфигурации: файл, путь ключа и причина. Текст — для оператора (контракт ошибок, §11)."""

    def __init__(
        self, config_path: Path, key: KeyPath, problem: str, reason: ConfigProblem = ConfigProblem.INVALID
    ) -> None:
        self.config_path: Path = config_path
        self.key: KeyPath = key
        self.problem: str = problem
        self.reason: ConfigProblem = reason
        super().__init__(self.human)

    @property
    def key_path(self) -> str:
        return self.key.text

    @property
    def is_file_missing(self) -> bool:
        """Файла нет: программа ещё не настроена, а не сломана."""
        return self.reason is ConfigProblem.FILE_MISSING

    @property
    def human(self) -> str:
        return msg.CONFIG_ERROR.format(path=self.config_path, key=self.key_path, problem=self.problem)

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(ConfigEvent.ERROR, path=self.config_path, key=self.key_path).extended(
            kind=self.reason, problem=self.problem
        )

    @property
    def log_line(self) -> str:
        return self.event.text

    def __str__(self) -> str:
        return self.human


class UniqueKeys(dict[str, Any]):
    """Объект JSON, который помнит повторённые поля: `json` молча взял бы последнее значение."""

    def __init__(self, pairs: Iterable[tuple[str, Any]]) -> None:
        super().__init__()
        self.duplicates: list[str] = []
        for key, value in pairs:
            if key in self:
                self.duplicates.append(key)
            self[key] = value


def json_value(value: object) -> Any:
    """Значение поля объекта → значение JSON: член перечисления — его значение, кортеж — список, словарь — копия."""
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, tuple):
        return [json_value(item) for item in value]
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    return value


@dataclass(frozen=True)
class JsonNode:
    """Значение JSON, его путь в файле и сам файл. Каждое чтение значения проверяет вид и отдаёт его или
    бросает `ConfigError` с путём этого узла."""

    value: Any
    source: Path
    path: KeyPath = KeyPath()

    @classmethod
    def read(cls, source: Path) -> JsonNode:
        """Корень файла конфига. Нет файла — FILE_MISSING; не открылся или не JSON — INVALID."""
        if not source.is_file():
            raise ConfigError(source, KeyPath(), msg.CONFIG_PROBLEM_FILE_MISSING, ConfigProblem.FILE_MISSING)
        try:
            return cls.parse(source.read_text(encoding=TEXT_ENCODING), source)
        except (OSError, UnicodeDecodeError) as error:
            raise ConfigError(source, KeyPath(), msg.CONFIG_PROBLEM_JSON.format(error=error)) from error

    @classmethod
    def parse(cls, text: str, source: Path) -> JsonNode:
        """Корень из текста JSON; `source` — только для ошибок."""
        try:
            return cls(value=json.loads(text, object_pairs_hook=UniqueKeys), source=source)
        except json.JSONDecodeError as error:
            raise ConfigError(source, KeyPath(), msg.CONFIG_PROBLEM_JSON.format(error=error)) from error

    def error(self, problem: str, reason: ConfigProblem = ConfigProblem.INVALID) -> ConfigError:
        return ConfigError(self.source, self.path, problem, reason)

    def check(self, problem: SettingProblem | None) -> None:
        """Объект сам сказал, что с ним не так; узлу остаётся приписать путь и файл."""
        if problem is not None:
            raise ConfigError(self.source, self.path.child(problem.key), problem.text)

    def mapping(self, keys: Iterable[str]) -> JsonNode:
        """Объект ровно с этими полями: неизвестное, повторённое, потом отсутствующее поле — ошибка с его именем."""
        allowed: tuple[str, ...] = tuple(keys)
        if not isinstance(self.value, dict):
            raise self.error(msg.CONFIG_PROBLEM_NOT_MAPPING)
        for key in self.value:
            if key not in allowed:
                raise self.field(key).error(msg.CONFIG_PROBLEM_UNKNOWN_KEY)
        if isinstance(self.value, UniqueKeys) and self.value.duplicates:
            raise self.field(self.value.duplicates[0]).error(msg.CONFIG_PROBLEM_DUPLICATE_KEY)
        for key in allowed:
            if key not in self.value:
                raise self.field(key).error(msg.CONFIG_PROBLEM_MISSING_KEY, ConfigProblem.FIELD_MISSING)
        return self

    def field(self, key: str) -> JsonNode:
        """Поле этого объекта; его значение — то, что лежит в файле (нет поля — None, его ловит `mapping`)."""
        return JsonNode(value=self.value.get(key), source=self.source, path=self.path.child(key))

    def items(self, problem: str) -> tuple[JsonNode, ...]:
        """Непустой список; иначе ошибка с текстом `problem` вызывающего — у каждого списка свой."""
        if not isinstance(self.value, list) or not self.value:
            raise self.error(problem)
        return tuple(
            JsonNode(value=item, source=self.source, path=self.path.item(index))
            for index, item in enumerate(self.value)
        )

    def text(self) -> str:
        """Непустая строка."""
        if not isinstance(self.value, str) or not self.value.strip():
            raise self.error(msg.CONFIG_PROBLEM_NON_EMPTY_STRING)
        return self.value

    def string(self) -> str:
        """Строка, которая может быть пустой: пустое значение открытой настройки — «не настроено» (§5)."""
        if not isinstance(self.value, str):
            raise self.error(msg.CONFIG_PROBLEM_STRING)
        return self.value

    def nullable_text(self) -> str | None:
        """Название вопроса формы: непустая строка либо null — вопроса в форме нет (§6 инвариант 2)."""
        if self.value is None:
            return None
        if not isinstance(self.value, str) or not self.value.strip():
            raise self.error(msg.CONFIG_PROBLEM_TEXT_OR_NULL)
        return self.value

    def text_mapping(self) -> dict[str, str]:
        """Тексты вариантов вопроса: объект «код → непустой текст», хотя бы один вариант, без повторов кода."""
        value: Any = self.value
        valid: bool = isinstance(value, dict) and bool(value) and all(
            isinstance(code, str) and code.strip() and isinstance(text, str) and text.strip()
            for code, text in value.items()
        )
        if not valid:
            raise self.error(msg.CONFIG_PROBLEM_TEXT_MAPPING)
        if isinstance(value, UniqueKeys) and value.duplicates:
            raise self.field(value.duplicates[0]).error(msg.CONFIG_PROBLEM_DUPLICATE_KEY)
        return dict(value)

    def integer(self, minimum: int) -> int:
        """Целое не меньше `minimum`; bool целым не считается."""
        if isinstance(self.value, bool) or not isinstance(self.value, int) or self.value < minimum:
            raise self.error(msg.CONFIG_PROBLEM_INT_MIN.format(minimum=minimum))
        return self.value

    def number(self, minimum: float) -> float:
        """Число, можно дробное: int и float — да; bool, строка, NaN, бесконечность и меньше минимума — ошибка.

        json.loads принимает NaN, Infinity и -Infinity, а nan < minimum ложно: без проверки конечности
        такое значение прошло бы минимум.
        """
        if isinstance(self.value, bool) or not isinstance(self.value, (int, float)):
            raise self.error(msg.CONFIG_PROBLEM_NUMBER_MIN.format(minimum=minimum))
        if not math.isfinite(self.value):
            raise self.error(msg.CONFIG_PROBLEM_NUMBER_FINITE)
        if self.value < minimum:
            raise self.error(msg.CONFIG_PROBLEM_NUMBER_MIN.format(minimum=minimum))
        return float(self.value)

    def boolean(self) -> bool:
        if not isinstance(self.value, bool):
            raise self.error(msg.CONFIG_PROBLEM_BOOL)
        return self.value

    def choice(self, enum_type: type[ChoiceT]) -> ChoiceT:
        """Значение из перечня: допустимые значения задаёт сам enum, узел лишь сверяет."""
        try:
            return enum_type(self.value)
        except ValueError:
            raise self.error(msg.CONFIG_PROBLEM_CHOICE.format(allowed=allowed_values(enum_type))) from None


def allowed_values(enum_type: type[Enum]) -> str:
    """Допустимые значения поля — и для ошибки, и для подсказки к шаблону channels.json."""
    return msg.LIST_JOINER.join(str(member.value) for member in enum_type)
