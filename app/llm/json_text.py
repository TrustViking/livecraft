"""JSON из ответа модели: объект ответа и то, как он найден (CLAUDE.md §2 строки про llm\\).

Модель отвечает JSON, но бывает, что обёрнутым в ```json … ``` или с пояснением вокруг. `JsonText` снимает обёртку и
находит объекты верхнего уровня `{…}` (скобки внутри строк JSON не считаются — `ObjectScan`). `ParsedJson` — итог
разбора: объект (или None) и как он найден. Два правила разбора:
- `ParsedJson.tolerant` — весь текст, иначе единственный объект `{…}` внутри текста; два объекта — не угадываем;
- `ParsedJson.first_object` — весь текст, затем объекты `{…}` по порядку: первый, что разобрался в объект.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final, cast

FENCE_OPEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*```(?:json)?\s*", flags=re.IGNORECASE)
FENCE_CLOSE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s*```\s*$")
FENCE_MARK: Final[str] = "```"
ESCAPE_CHAR: Final[str] = "\\"               # следующий знак экранирован
QUOTE_CHAR: Final[str] = '"'                 # граница строки JSON
OBJECT_OPEN: Final[str] = "{"
OBJECT_CLOSE: Final[str] = "}"
PARSE_DIRECT: Final[str] = "direct"          # разобран весь текст
PARSE_CANDIDATE: Final[str] = "candidate"    # разобран объект {…} внутри текста
PARSE_FAIL: Final[str] = "fail"


class JsonFound(str, Enum):
    """Как найден объект JSON: весь текст, объект `{…}` внутри текста или не найден."""

    DIRECT = PARSE_DIRECT
    CANDIDATE = PARSE_CANDIDATE
    FAIL = PARSE_FAIL


@dataclass
class ObjectScan:
    """Проход по тексту знак за знаком: внутри ли строки JSON, экранирован ли знак, глубина скобок, начало объекта."""

    text: str
    in_string: bool = False
    escaped: bool = False
    depth: int = 0
    start: int = 0
    found: list[str] = field(default_factory=list)

    def run(self) -> tuple[str, ...]:
        """Объекты верхнего уровня по порядку."""
        for index, char in enumerate(self.text):
            self._take(index, char)
        return tuple(self.found)

    def _take(self, index: int, char: str) -> None:
        if self.escaped:
            self.escaped = False
        elif char == ESCAPE_CHAR:
            self.escaped = True
        elif char == QUOTE_CHAR:
            self.in_string = not self.in_string
        elif self.in_string:
            return
        elif char == OBJECT_OPEN:
            self._open(index)
        elif char == OBJECT_CLOSE and self.depth > 0:
            self._close(index)

    def _open(self, index: int) -> None:
        if self.depth == 0:
            self.start = index
        self.depth += 1

    def _close(self, index: int) -> None:
        self.depth -= 1
        if self.depth == 0:
            self.found.append(self.text[self.start : index + 1])


@dataclass(frozen=True)
class JsonText:
    """Текст ответа без обёртки ```json … ``` и без краевых пробелов."""

    text: str

    @classmethod
    def of(cls, raw_text: str) -> JsonText:
        cleaned: str = str(raw_text or "").strip()
        if cleaned.startswith(FENCE_MARK):
            cleaned = FENCE_CLOSE_PATTERN.sub("", FENCE_OPEN_PATTERN.sub("", cleaned))
        return cls(cleaned.strip())

    @property
    def objects(self) -> tuple[str, ...]:
        """Объекты верхнего уровня `{…}` в тексте по порядку; скобки внутри строк JSON не считаются."""
        return ObjectScan(self.text).run()


@dataclass(frozen=True)
class JsonValue:
    """Разбор одной строки JSON: значение и разобралась ли строка вообще."""

    value: Any
    is_valid: bool

    @classmethod
    def load(cls, text: str) -> JsonValue:
        try:
            return cls(json.loads(text), True)
        except ValueError:
            return cls(None, False)


@dataclass(frozen=True)
class ParsedJson:
    """Объект JSON ответа (None — не найден) и как он найден."""

    data: dict[str, object] | None
    found: JsonFound

    @classmethod
    def of(cls, value: Any, found: JsonFound) -> ParsedJson:
        """Значение — объект: найден так, как сказано; иначе — не найден."""
        if isinstance(value, dict):
            return cls(cast(dict[str, object], value), found)
        return cls(None, JsonFound.FAIL)

    @classmethod
    def tolerant(cls, raw_text: str) -> ParsedJson:
        """Весь текст; не разобрался — единственный объект `{…}` внутри; весь текст не объект — не найден."""
        text: JsonText = JsonText.of(raw_text)
        whole: JsonValue = JsonValue.load(text.text)
        if not text.text or whole.is_valid:
            return cls.of(whole.value, JsonFound.DIRECT)
        objects: tuple[str, ...] = text.objects
        if len(objects) != 1:
            return cls(None, JsonFound.FAIL)
        return cls.of(JsonValue.load(objects[0]).value, JsonFound.CANDIDATE)

    @classmethod
    def first_object(cls, raw_text: str) -> ParsedJson:
        """Весь текст, затем объекты `{…}` по порядку: первый, что разобрался в объект."""
        text: JsonText = JsonText.of(raw_text)
        candidates: tuple[str, ...] = (text.text, *text.objects) if text.text else ()
        for index, candidate in enumerate(candidates):
            parsed: ParsedJson = cls.of(JsonValue.load(candidate).value, JsonFound.CANDIDATE if index else JsonFound.DIRECT)
            if parsed.data is not None:
                return parsed
        return cls(None, JsonFound.FAIL)
