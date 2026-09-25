"""Постоянные исключения эталона: `правило -> ключ -> обоснование` (REFACTORING_STANDARD.md §6).

Исключение — не долг: в реестр оно не идёт и сниматься не должно. Обоснование — русская строка, не пустая.
Исключение, которое правило больше не ловит, — устаревшее и должно уйти из файла.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from app.tools.code_standard.json_file import JsonObject
from app.tools.code_standard.measurement import Measurements
from app.tools.code_standard.rule import Rule
from app.ui import messages_ru as msg


@dataclass(frozen=True)
class Exemption:
    """Одно исключение: правило, ключ, обоснование."""

    rule: Rule
    key: str
    reason: str

    def problem(self, measurements: Measurements) -> str | None:
        """Почему исключение негодно: обоснование пустое или правило этот ключ больше не ловит."""
        if not self.reason.strip():
            return msg.CODE_STANDARD_EXEMPTION_NO_REASON.format(rule=self.rule.value, key=self.key)
        if self.key not in measurements.of(self.rule).values:
            return msg.CODE_STANDARD_EXEMPTION_NOT_CAUGHT.format(rule=self.rule.value, key=self.key)
        return None


@dataclass(frozen=True)
class Exceptions:
    """Все постоянные исключения."""

    items: tuple[Exemption, ...]

    @classmethod
    def load(cls, path: Path) -> Exceptions:
        """Файл исключений; нет файла — исключений нет."""
        return cls.from_json(JsonObject.read(path)) if path.is_file() else cls(())

    @classmethod
    def parse(cls, text: str, origin: str) -> Exceptions:
        return cls.from_json(JsonObject.parse(text, origin))

    @classmethod
    def from_json(cls, data: JsonObject) -> Exceptions:
        """Исключения по кодам правил; неизвестный код — `StandardFileError`."""
        sections: Mapping[str, JsonObject] = data.children(Rule.codes())
        return cls(tuple(
            Exemption(Rule(code), key, section.text(key)) for code, section in sections.items() for key in section.keys
        ))

    @property
    def keys(self) -> Mapping[Rule, frozenset[str]]:
        """Ключи исключений по правилам."""
        found: dict[Rule, set[str]] = {}
        for item in self.items:
            found.setdefault(item.rule, set()).add(item.key)
        return {rule: frozenset(keys) for rule, keys in found.items()}

    def count(self, rule: Rule) -> int:
        return sum(1 for item in self.items if item.rule is rule)

    def problems(self, measurements: Measurements) -> tuple[str, ...]:
        """Негодные исключения против замеров без исключений."""
        found: tuple[str | None, ...] = tuple(item.problem(measurements) for item in self.items)
        return tuple(problem for problem in found if problem is not None)
