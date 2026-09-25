"""Замер правила: ключ нарушения → величина, признаки и места нарушений (REFACTORING_STANDARD.md §6).

Место нарушения — модуль, в котором оно стоит. У ключа `путь::имя` место — сам путь; у ключей, которые
называют значение (E8, E9), группу (E11) или пакеты (E16), места перечисляет само нарушение: по ним
`--files` и проверка пакета замка находят долги файла.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final

from app.tools.code_standard.rule import Rule, Sign
from app.tools.code_standard.source import KEY_JOINER, SourceKey

GROUP_JOINER: Final[str] = " | "  # участники одного нарушения в ключе: клоны E11, кольца E16
VIOLATION: Final[int] = 1  # величина нарушения «есть или нет»


@dataclass(frozen=True)
class Finding:
    """Одно нарушение: ключ, величина, признаки, доли величины по признакам и модули-места."""

    key: str
    value: int
    signs: frozenset[Sign] = field(default_factory=frozenset)
    parts: Mapping[Sign, int] = field(default_factory=dict)
    places: frozenset[str] = field(default_factory=frozenset)

    @property
    def tally(self) -> Mapping[Sign, int]:
        """Доли по признакам; без явных долей каждый признак — одно нарушение."""
        return self.parts or {sign: 1 for sign in self.signs}

    @property
    def sites(self) -> frozenset[str]:
        """Модули, где стоит нарушение; без явных мест — путь из ключа."""
        return self.places or frozenset({self.key.partition(KEY_JOINER)[0]})


@dataclass(frozen=True)
class Measurement:
    """Нарушения одного правила: величина, доли по признакам и места по ключу."""

    rule: Rule
    values: Mapping[str, int]
    parts: Mapping[str, Mapping[Sign, int]] = field(default_factory=dict)
    places: Mapping[str, frozenset[str]] = field(default_factory=dict)

    @classmethod
    def of(cls, rule: Rule, findings: Iterable[Finding]) -> Measurement:
        """Нарушения с одним ключом сливаются: величина и доли — наибольшие, места — все."""
        values: dict[str, int] = {}
        parts: dict[str, dict[Sign, int]] = {}
        places: dict[str, frozenset[str]] = {}
        for finding in findings:
            values[finding.key] = max(values.get(finding.key, 0), finding.value)
            merged: dict[Sign, int] = parts.setdefault(finding.key, {})
            for sign, count in finding.tally.items():
                merged[sign] = max(merged.get(sign, 0), count)
            places[finding.key] = places.get(finding.key, frozenset()) | finding.sites
        return cls(rule, dict(sorted(values.items())), parts, places)

    @property
    def count(self) -> int:
        return len(self.values)

    def without(self, keys: frozenset[str]) -> Measurement:
        """Замер без этих ключей: так из замера уходят постоянные исключения."""
        kept: dict[str, int] = {key: value for key, value in self.values.items() if key not in keys}
        return Measurement(
            self.rule, kept, {key: self.parts_of(key) for key in kept}, {key: self.sites_of(key) for key in kept}
        )

    def under(self, paths: tuple[SourceKey, ...]) -> Measurement:
        """Только нарушения в этих файлах и папках."""
        return self.without(frozenset(key for key in self.values if not self.is_under(key, paths)))

    def is_under(self, key: str, paths: tuple[SourceKey, ...]) -> bool:
        """Хотя бы одно место нарушения лежит в этих файлах и папках."""
        return any(path.covers(site) for path in paths for site in self.sites_of(key))

    def sites_of(self, key: str) -> frozenset[str]:
        """Места нарушения; ключ, которого в замере нет, — путь из самого ключа."""
        return self.places.get(key) or frozenset({key.partition(KEY_JOINER)[0]})

    def parts_of(self, key: str) -> Mapping[Sign, int]:
        return self.parts.get(key, {})

    def signs_of(self, key: str) -> tuple[Sign, ...]:
        """Признаки нарушения в порядке признаков."""
        found: Mapping[Sign, int] = self.parts_of(key)
        return tuple(sign for sign in Sign if sign in found)

    def sign_counts(self) -> Mapping[Sign, int]:
        """Сумма долей по каждому признаку, в порядке признаков."""
        counts: dict[Sign, int] = {sign: 0 for sign in Sign}
        for parts in self.parts.values():
            for sign, count in parts.items():
                counts[sign] += count
        return {sign: count for sign, count in counts.items() if count}


@dataclass(frozen=True)
class Measurements:
    """Замеры всех проверяемых правил в порядке правил."""

    items: tuple[Measurement, ...]

    @property
    def rules(self) -> tuple[Rule, ...]:
        return tuple(sorted((item.rule for item in self.items), key=lambda rule: rule.order))

    def of(self, rule: Rule) -> Measurement:
        """Замер правила; правило без замера — пустой замер."""
        for item in self.items:
            if item.rule is rule:
                return item
        return Measurement(rule, {})

    def without(self, excepted: Mapping[Rule, frozenset[str]]) -> Measurements:
        """Замеры без постоянных исключений."""
        return Measurements(tuple(item.without(excepted.get(item.rule, frozenset())) for item in self.items))

    def under(self, paths: tuple[SourceKey, ...]) -> Measurements:
        """Замеры только по этим файлам и папкам."""
        return Measurements(tuple(item.under(paths) for item in self.items))
