"""Реестр долгов: нарушения, которые были в коде, когда их зафиксировали (REFACTORING_STANDARD.md §6).

Файл — `правило -> ключ -> величина`. Реестр может только сокращаться: новое и выросшее нарушение —
ошибка, снятое в коде, но оставшееся в реестре, — устаревшая запись. Раздел правила есть в файле, даже
когда он пуст: так видно, какие правила реестр уже покрывает.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.tools.code_standard.json_file import JsonDocument, JsonObject
from app.tools.code_standard.measurement import Measurements
from app.tools.code_standard.rule import Rule
from app.tools.code_standard.source import SourceKey
from app.ui import messages_ru as msg


class ChangeKind(str, Enum):
    """Как запись реестра изменилась между двумя версиями."""

    NEW = "new"
    GROWN = "grown"
    SHRUNK = "shrunk"
    GONE = "gone"
    SAME = "same"


@dataclass(frozen=True)
class LedgerChange:
    """Запись, которая есть хотя бы в одной версии: величина до и после (0 — записи нет)."""

    rule: Rule
    key: str
    before: int
    after: int

    @property
    def kind(self) -> ChangeKind:
        if not self.before:
            return ChangeKind.NEW
        if not self.after:
            return ChangeKind.GONE
        if self.after > self.before:
            return ChangeKind.GROWN
        return ChangeKind.SHRUNK if self.after < self.before else ChangeKind.SAME

    @property
    def line(self) -> str:
        """Строка для человека: правило, ключ, было и стало."""
        template: str = msg.CODE_STANDARD_CHANGE_LINES[self.kind.value]
        return template.format(rule=self.rule.value, key=self.key, before=self.before, after=self.after)


@dataclass(frozen=True)
class LedgerDiff:
    """Разница двух версий реестра по видам изменений."""

    changes: tuple[LedgerChange, ...]

    def of_kind(self, kind: ChangeKind) -> tuple[LedgerChange, ...]:
        return tuple(change for change in self.changes if change.kind is kind)

    @property
    def new(self) -> tuple[LedgerChange, ...]:
        return self.of_kind(ChangeKind.NEW)

    @property
    def grown(self) -> tuple[LedgerChange, ...]:
        return self.of_kind(ChangeKind.GROWN)

    @property
    def shrunk(self) -> tuple[LedgerChange, ...]:
        return self.of_kind(ChangeKind.SHRUNK)

    @property
    def gone(self) -> tuple[LedgerChange, ...]:
        return self.of_kind(ChangeKind.GONE)

    @property
    def growth(self) -> tuple[LedgerChange, ...]:
        """Появилось и выросло: реестр так меняться не может."""
        return self.new + self.grown

    @property
    def reduction(self) -> tuple[LedgerChange, ...]:
        """Уменьшилось и снято: долг снят в коде."""
        return self.shrunk + self.gone


@dataclass(frozen=True)
class Ledger:
    """Реестр долгов: раздел на правило, в разделе — ключ и величина."""

    sections: Mapping[Rule, Mapping[str, int]]

    @classmethod
    def of(cls, measurements: Measurements) -> Ledger:
        """Реестр по замерам: раздел на каждое проверяемое правило, в том числе пустой."""
        return cls({rule: dict(measurements.of(rule).values) for rule in measurements.rules})

    @classmethod
    def load(cls, path: Path) -> Ledger:
        return cls.from_json(JsonObject.read(path))

    @classmethod
    def parse(cls, text: str, origin: str) -> Ledger:
        return cls.from_json(JsonObject.parse(text, origin))

    @classmethod
    def from_json(cls, data: JsonObject) -> Ledger:
        """Разделы по кодам правил; неизвестный код — `StandardFileError`."""
        sections: Mapping[str, JsonObject] = data.children(Rule.codes())
        return cls({Rule(code): {key: section.integer(key) for key in section.keys} for code, section in sections.items()})

    @property
    def rules(self) -> tuple[Rule, ...]:
        return tuple(sorted(self.sections, key=lambda rule: rule.order))

    @property
    def count(self) -> int:
        return sum(len(section) for section in self.sections.values())

    def section(self, rule: Rule) -> Mapping[str, int]:
        return self.sections.get(rule, {})

    def with_sections_of(self, other: Ledger) -> Ledger:
        """Этот реестр плюс разделы тех правил другого, которых здесь нет; свои разделы не меняются."""
        added: dict[Rule, Mapping[str, int]] = {rule: other.section(rule) for rule in other.rules if rule not in self.sections}
        return Ledger({**self.sections, **added})

    def under(self, paths: tuple[SourceKey, ...], measurements: Measurements) -> Ledger:
        """Только записи, у которых хотя бы одно место нарушения в коде лежит в этих файлах и папках.

        Место берётся из замеров (у ключей-значений E8, E9, групп E11 и рёбер E16 мест несколько); записи,
        которой в замерах уже нет, место — путь из её ключа.
        """
        return Ledger({
            rule: {key: value for key, value in self.section(rule).items() if measurements.of(rule).is_under(key, paths)}
            for rule in self.rules
        })

    def diff(self, current: Ledger) -> LedgerDiff:
        """Что изменилось от этого реестра к `current`; записи без изменений в разницу не входят."""
        rules: list[Rule] = sorted(set(self.sections) | set(current.sections), key=lambda rule: rule.order)
        changes: list[LedgerChange] = []
        for rule in rules:
            before: Mapping[str, int] = self.section(rule)
            after: Mapping[str, int] = current.section(rule)
            for key in sorted(set(before) | set(after)):
                changes.append(LedgerChange(rule, key, before.get(key, 0), after.get(key, 0)))
        return LedgerDiff(tuple(change for change in changes if change.kind is not ChangeKind.SAME))

    def save(self, path: Path) -> None:
        """Разделы в порядке правил, ключи по алфавиту."""
        data: dict[str, object] = {rule.value: dict(sorted(self.section(rule).items())) for rule in self.rules}
        JsonDocument(data).save(path)
