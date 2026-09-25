"""Файлы замка в JSON: стандарт, реестр долгов, исключения (REFACTORING_STANDARD.md §6).

Разбор проверяет форму значений сам: сломанный файл — `StandardFileError` с причиной-перечислением,
текст для человека — в `messages_ru`. Запись — UTF-8 без экранирования кириллицы, переводы строк LF.
"""
from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.ui import messages_ru as msg

JSON_INDENT: Final[int] = 2
LINE_END: Final[str] = "\n"
LOG_EVENT: Final[str] = "code_standard_file_error"
LOG_TEMPLATE: Final[str] = "{event} reason={reason} file={file} key={key}"


class JsonProblem(str, Enum):
    """Почему файл замка не читается."""

    UNREADABLE = "unreadable"
    NOT_JSON = "not_json"
    NOT_OBJECT = "not_object"
    MISSING = "missing"
    NOT_INTEGER = "not_integer"
    NOT_TEXT = "not_text"
    NOT_TEXT_LIST = "not_text_list"
    NOT_INTEGER_LIST = "not_integer_list"
    NOT_OBJECT_LIST = "not_object_list"
    UNKNOWN_LEVEL = "unknown_level"
    UNKNOWN_KEY = "unknown_key"
    GIT_FAILED = "git_failed"


class StandardFileError(Exception):
    """Файл замка не прочитан: причина, файл и ключ, на котором разбор остановился."""

    def __init__(self, problem: JsonProblem, origin: str, key: str = "") -> None:
        super().__init__(problem.value)
        self.problem: JsonProblem = problem
        self.origin: str = origin
        self.key: str = key

    @property
    def human(self) -> str:
        """Причина по-русски: файл и ключ."""
        return msg.CODE_STANDARD_FILE_PROBLEMS[self.problem.value].format(file=self.origin, key=self.key)

    @property
    def log_line(self) -> str:
        """Строка для разработчика: `key=value`."""
        return LOG_TEMPLATE.format(event=LOG_EVENT, reason=self.problem.value, file=self.origin, key=self.key)

    def __str__(self) -> str:
        return self.human


@dataclass(frozen=True)
class JsonObject:
    """Объект JSON файла замка вместе с именем, под которым о нём говорят в причинах."""

    origin: str
    values: Mapping[str, object]

    @classmethod
    def read(cls, path: Path) -> JsonObject:
        """Файл целиком; не читается или не JSON-объект — `StandardFileError`."""
        try:
            text: str = path.read_bytes().decode()
        except (OSError, UnicodeDecodeError) as error:
            raise StandardFileError(JsonProblem.UNREADABLE, path.name) from error
        return cls.parse(text, path.name)

    @classmethod
    def parse(cls, text: str, origin: str) -> JsonObject:
        """Текст JSON; корень — объект, иначе `StandardFileError`."""
        try:
            data: object = json.loads(text)
        except ValueError as error:
            raise StandardFileError(JsonProblem.NOT_JSON, origin) from error
        return cls(origin, cls._object(data, origin, ""))

    @classmethod
    def _object(cls, data: object, origin: str, key: str) -> Mapping[str, object]:
        if not isinstance(data, dict):
            raise StandardFileError(JsonProblem.NOT_OBJECT, origin, key)
        return data

    @property
    def keys(self) -> tuple[str, ...]:
        """Ключи в порядке файла."""
        return tuple(self.values)

    def child(self, key: str) -> JsonObject:
        """Вложенный объект по ключу."""
        return JsonObject(self.origin, self._object(self._value(key), self.origin, key))

    def children(self, allowed: frozenset[str]) -> Mapping[str, JsonObject]:
        """Все вложенные объекты по ключам; ключ не из `allowed` — `StandardFileError`."""
        for key in self.keys:
            if key not in allowed:
                raise StandardFileError(JsonProblem.UNKNOWN_KEY, self.origin, key)
        return {key: self.child(key) for key in self.keys}

    def integer(self, key: str) -> int:
        """Целое число по ключу; `true` и `false` числом не считаются."""
        value: object = self._value(key)
        if isinstance(value, bool) or not isinstance(value, int):
            raise StandardFileError(JsonProblem.NOT_INTEGER, self.origin, key)
        return value

    def text(self, key: str) -> str:
        """Строка по ключу."""
        value: object = self._value(key)
        if not isinstance(value, str):
            raise StandardFileError(JsonProblem.NOT_TEXT, self.origin, key)
        return value

    def texts(self, key: str) -> tuple[str, ...]:
        """Список строк по ключу."""
        return tuple(self._list(key, str, JsonProblem.NOT_TEXT_LIST))

    def integers(self, key: str) -> tuple[int, ...]:
        """Список целых чисел по ключу; `true` и `false` числами не считаются."""
        return tuple(self._list(key, int, JsonProblem.NOT_INTEGER_LIST))

    def objects(self, key: str) -> tuple[JsonObject, ...]:
        """Список объектов JSON по ключу."""
        return tuple(JsonObject(self.origin, item) for item in self._list(key, dict, JsonProblem.NOT_OBJECT_LIST))

    def _list(self, key: str, kind: type, problem: JsonProblem) -> list:
        """Список по ключу, все элементы которого ровно этого типа (у чисел `bool` не проходит)."""
        value: object = self._value(key)
        if not isinstance(value, list) or not all(type(item) is kind for item in value):
            raise StandardFileError(problem, self.origin, key)
        return value

    def _value(self, key: str) -> object:
        if key not in self.values:
            raise StandardFileError(JsonProblem.MISSING, self.origin, key)
        return self.values[key]


@dataclass(frozen=True)
class JsonDocument:
    """Данные, которые замок пишет в свой файл: реестр долгов."""

    data: Mapping[str, object]

    @property
    def text(self) -> str:
        """JSON с отступом, кириллица как есть, перевод строки в конце."""
        return json.dumps(self.data, ensure_ascii=False, indent=JSON_INDENT) + LINE_END

    def save(self, path: Path) -> None:
        """Запись байтами UTF-8: перевод строки LF при любой ОС."""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(self.text.encode())
