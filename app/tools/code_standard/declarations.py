"""Одно значение — одно объявление (E8) и регулярные выражения (E9), REFACTORING_STANDARD.md §5.

Константа — присваивание уровня модуля или класса: имя прописными, значение — литерал. Строка (не член
перечисления) нарушает E8, если та же строка объявлена константой в другом модуле; число — если в другом
модуле объявлено то же имя с тем же значением (члены перечислений считаются). Шаблон E9 — первый аргумент
`re.<функция>(…)`, если это литерал: внутри функции он запрещён, а во всём app встречается один раз.
Повторы E8 и E9 ищутся отдельно в каждом изолированном пакете стандарта и отдельно в остальном app.
Проверяется код app без `app\\tests`.
"""
from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property
from typing import Final

from app.tools.code_standard.literals import NUMBER_TYPES, TEXT_TYPES
from app.tools.code_standard.measurement import Finding
from app.tools.code_standard.rule import Sign
from app.tools.code_standard.signature import CalleeName
from app.tools.code_standard.source import DefinitionSite, ModuleSource, SourceTree
from app.tools.code_standard.standard import ValueRules

ENUM_BASES: Final[frozenset[str]] = frozenset({"Enum", "IntEnum", "StrEnum", "Flag", "IntFlag"})
NUMBER_KEY: Final[str] = "{name}={value!r}"
PATTERN_MODULE: Final[str] = "re"
PATTERN_FUNCTIONS: Final[frozenset[str]] = frozenset(
    {"compile", "search", "match", "fullmatch", "sub", "subn", "split", "findall", "finditer"}
)


@dataclass(frozen=True)
class ConstantDeclaration:
    """Константа: модуль, имя, литерал и то, объявлена ли она членом перечисления."""

    module: ModuleSource
    name: str
    value: object
    in_enum: bool

    @property
    def is_text(self) -> bool:
        return isinstance(self.value, TEXT_TYPES)

    @property
    def counts(self) -> bool:
        """Строка-член перечисления правилом не считается."""
        return not (self.is_text and self.in_enum)

    @property
    def key(self) -> str:
        """Строка — её значение; число — имя и значение."""
        return repr(self.value) if self.is_text else NUMBER_KEY.format(name=self.name, value=self.value)

    @property
    def sign(self) -> Sign:
        return Sign.TEXT_CONSTANT if self.is_text else Sign.NUMBER_CONSTANT


@dataclass(frozen=True)
class ModuleConstants:
    """Константы модуля: тело модуля и тела всех его классов."""

    module: ModuleSource

    def declarations(self) -> Iterator[ConstantDeclaration]:
        yield from self._scan(self.module.tree.body, False)
        for site in self.module.definitions:
            if site.is_class:
                yield from self._scan(site.node.body, self._is_enum(site.node))

    def _is_enum(self, node: ast.ClassDef) -> bool:
        return any(CalleeName(base).name in ENUM_BASES for base in node.bases)

    def _scan(self, body: list[ast.stmt], in_enum: bool) -> Iterator[ConstantDeclaration]:
        for statement in body:
            targets: list[ast.expr] = []
            value: ast.expr | None = None
            if isinstance(statement, ast.Assign):
                targets, value = statement.targets, statement.value
            elif isinstance(statement, ast.AnnAssign):
                targets, value = [statement.target], statement.value
            if not isinstance(value, ast.Constant) or not self._is_literal(value.value):
                continue
            for target in targets:
                if isinstance(target, ast.Name) and target.id.isupper():
                    yield ConstantDeclaration(self.module, target.id, value.value, in_enum)

    def _is_literal(self, value: object) -> bool:
        return isinstance(value, NUMBER_TYPES + TEXT_TYPES) and not isinstance(value, bool)


@dataclass(frozen=True)
class PatternCall:
    """Вызов `re.<функция>(<литерал>, …)`: модуль, шаблон и ключ определения вокруг вызова."""

    module: ModuleSource
    pattern: object
    owner: str

    @property
    def in_function(self) -> bool:
        site: DefinitionSite | None = self.module.site_of(self.owner)
        return site is not None and site.is_function


@dataclass(frozen=True)
class Declarations:
    """Повторы констант (E8) и шаблонов (E9) по областям стандарта."""

    tree: SourceTree
    rules: ValueRules

    def constants(self) -> Iterator[Finding]:
        """E8: одно значение объявлено в нескольких модулях одной области."""
        groups: dict[tuple[str, str], list[ConstantDeclaration]] = {}
        for module in self.tree.production:
            for item in ModuleConstants(module).declarations():
                if item.counts:
                    groups.setdefault((self.rules.area_of(module.key), item.key), []).append(item)
        for (_, key), items in groups.items():
            modules: frozenset[str] = frozenset(item.module.key.text for item in items)
            if len(modules) > 1:
                yield Finding(key, len(modules), frozenset({items[0].sign}), places=modules)

    def repeated_patterns(self) -> Iterator[Finding]:
        """E9: один шаблон объявлен больше одного раза в одной области; величина — число объявлений."""
        groups: dict[tuple[str, str], list[PatternCall]] = {}
        for call in self._calls:
            groups.setdefault((self.rules.area_of(call.module.key), repr(call.pattern)), []).append(call)
        for (_, key), calls in groups.items():
            if len(calls) > 1:
                places: frozenset[str] = frozenset(call.module.key.text for call in calls)
                yield Finding(key, len(calls), frozenset({Sign.REPEATED_PATTERN}), places=places)

    def patterns_in_functions(self) -> Iterator[Finding]:
        """E9: шаблон-литерал внутри функции; величина — число таких вызовов в функции."""
        counts: dict[str, int] = {}
        for call in self._calls:
            if call.in_function:
                counts[call.owner] = counts.get(call.owner, 0) + 1
        return (Finding(owner, count, frozenset({Sign.PATTERN_IN_FUNCTION})) for owner, count in counts.items())

    @cached_property
    def _calls(self) -> tuple[PatternCall, ...]:
        found: list[PatternCall] = []
        for module in self.tree.production:
            for node in ast.walk(module.tree):
                pattern: ast.expr | None = self._pattern_of(node)
                if pattern is not None:
                    found.append(PatternCall(module, pattern.value, module.owner_of(node)))
        return tuple(found)

    def _pattern_of(self, node: ast.AST) -> ast.Constant | None:
        """Первый аргумент `re.<функция>(…)`, если это строка-литерал."""
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or not node.args:
            return None
        func: ast.Attribute = node.func
        is_pattern_call: bool = isinstance(func.value, ast.Name) and func.value.id == PATTERN_MODULE
        first: ast.expr = node.args[0]
        is_literal: bool = isinstance(first, ast.Constant) and isinstance(first.value, TEXT_TYPES)
        return first if is_pattern_call and func.attr in PATTERN_FUNCTIONS and is_literal else None
