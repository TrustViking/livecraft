"""Замер правила: ключ нарушения → величина, и признаки нарушений для отчёта (REFACTORING_STANDARD.md §6)."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.tools.code_standard.rule import Rule, Sign
from app.tools.code_standard.source import SourceKey


@dataclass(frozen=True)
class Finding:
    """Одно нарушение: ключ `путь::имя` (или `путь`), величина и признаки."""

    key: str
    value: int
    signs: frozenset[Sign] = field(default_factory=frozenset)


@dataclass(frozen=True)
class Measurement:
    """Нарушения одного правила: величина по ключу и признаки по ключу."""

    rule: Rule
    values: Mapping[str, int]
    signs: Mapping[str, frozenset[Sign]]

    @classmethod
    def of(cls, rule: Rule, findings: Iterable[Finding]) -> Measurement:
        """Нарушения с одним ключом сливаются: величина — наибольшая, признаки — все."""
        values: dict[str, int] = {}
        signs: dict[str, frozenset[Sign]] = {}
        for finding in findings:
            values[finding.key] = max(values.get(finding.key, 0), finding.value)
            signs[finding.key] = signs.get(finding.key, frozenset()) | finding.signs
        return cls(rule, dict(sorted(values.items())), signs)

    @property
    def count(self) -> int:
        return len(self.values)

    def without(self, keys: frozenset[str]) -> Measurement:
        """Замер без этих ключей: так из замера уходят постоянные исключения."""
        kept: dict[str, int] = {key: value for key, value in self.values.items() if key not in keys}
        return Measurement(self.rule, kept, {key: self.signs[key] for key in kept})

    def under(self, paths: tuple[SourceKey, ...]) -> Measurement:
        """Только нарушения в этих файлах и папках."""
        kept: frozenset[str] = frozenset(key for key in self.values if any(path.covers(key) for path in paths))
        return self.without(frozenset(self.values) - kept)

    def signs_of(self, key: str) -> tuple[Sign, ...]:
        """Признаки нарушения в порядке признаков."""
        found: frozenset[Sign] = self.signs.get(key, frozenset())
        return tuple(sign for sign in Sign if sign in found)

    def sign_counts(self) -> Mapping[Sign, int]:
        """Сколько нарушений с каждым признаком, в порядке признаков."""
        counts: dict[Sign, int] = {sign: 0 for sign in Sign}
        for signs in self.signs.values():
            for sign in signs:
                counts[sign] += 1
        return {sign: count for sign, count in counts.items() if count}


@dataclass(frozen=True)
class Measurements:
    """Замеры всех проверяемых правил в порядке правил."""

    items: tuple[Measurement, ...]

    @property
    def rules(self) -> tuple[Rule, ...]:
        return tuple(sorted((item.rule for item in self.items), key=lambda rule: rule.order))

    def of(self, rule: Rule) -> Measurement:
        """Замер правила; правило, которое замок ещё не проверяет, — пустой замер."""
        for item in self.items:
            if item.rule is rule:
                return item
        return Measurement(rule, {}, {})

    def without(self, excepted: Mapping[Rule, frozenset[str]]) -> Measurements:
        """Замеры без постоянных исключений."""
        return Measurements(tuple(item.without(excepted.get(item.rule, frozenset())) for item in self.items))

    def under(self, paths: tuple[SourceKey, ...]) -> Measurements:
        """Замеры только по этим файлам и папкам."""
        return Measurements(tuple(item.under(paths) for item in self.items))
