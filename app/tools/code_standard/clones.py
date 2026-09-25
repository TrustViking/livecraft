"""Структурные клоны: правило E11 (REFACTORING_STANDARD.md §5, пороги — `standard.json`).

Окно — несколько операторов подряд одного блока функции (тело, ветви `if`/`else`, циклы, `try`, `match`).
Размер окна — число узлов `ast.walk` всех его операторов. Окна сравниваются в нормальной форме: имена,
атрибуты, имена аргументов и значения констант стёрты, тип константы остаётся. Одинаковое окно в двух
и более функциях — нарушение; ключ — участники `путь::имя` по алфавиту, величина — их число. Проверяется
код app без `app\\tests`; вложенная функция — отдельный участник со своими блоками.
"""
from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property
from typing import Final

from app.tools.code_standard.measurement import GROUP_JOINER, Finding, Measurement
from app.tools.code_standard.rule import Rule
from app.tools.code_standard.source import BODY_FIELD, DEFINITION_NODES, DefinitionSite, SourceTree
from app.tools.code_standard.standard import CloneRules

BLOCK_FIELDS: Final[tuple[str, ...]] = (BODY_FIELD, "orelse", "finalbody")
NESTED_BLOCK_FIELDS: Final[tuple[str, ...]] = ("handlers", "cases")


@dataclass(frozen=True)
class NormalForm:
    """Нормальная форма узла, списка узлов или значения поля узла."""

    value: object

    @property
    def form(self) -> object:
        if isinstance(self.value, ast.Constant):
            return type(self.value).__name__, type(self.value.value).__name__
        if isinstance(self.value, ast.AST):
            return (type(self.value).__name__,) + tuple(NormalForm(item).form for _, item in ast.iter_fields(self.value))
        if isinstance(self.value, list):
            return tuple(NormalForm(item).form for item in self.value)
        return "" if isinstance(self.value, str) else self.value


@dataclass(frozen=True)
class FunctionBlocks:
    """Блоки операторов функции без вложенных определений."""

    site: DefinitionSite

    def blocks(self) -> Iterator[list[ast.stmt]]:
        pending: list[list[ast.stmt]] = [self.site.node.body]
        while pending:
            block: list[ast.stmt] = pending.pop()
            yield block
            for statement in block:
                pending.extend(self._inner(statement) if not isinstance(statement, DEFINITION_NODES) else ())

    def _inner(self, statement: ast.stmt) -> list[list[ast.stmt]]:
        """Блоки внутри оператора: тело, `else`, `finally`, тела `except` и `case`."""
        found: list[object] = [getattr(statement, name, None) for name in BLOCK_FIELDS]
        for name in NESTED_BLOCK_FIELDS:
            found.extend(getattr(part, BODY_FIELD, None) for part in getattr(statement, name, ()))
        return [block for block in found if isinstance(block, list) and block and isinstance(block[0], ast.stmt)]


@dataclass(frozen=True)
class StatementWindow:
    """Операторы подряд одного блока одной функции."""

    site: DefinitionSite
    statements: tuple[ast.stmt, ...]

    @cached_property
    def size(self) -> int:
        """Число узлов ast всех операторов окна."""
        return sum(1 for statement in self.statements for _ in ast.walk(statement))

    @property
    def form(self) -> object:
        return NormalForm(list(self.statements)).form


@dataclass(frozen=True)
class CloneFinder:
    """Одинаковые окна операторов в разных функциях app."""

    tree: SourceTree
    rules: CloneRules

    def measurements(self) -> tuple[Measurement, ...]:
        return (Measurement.of(Rule.STRUCTURAL_CLONES, self._groups()),)

    def _windows(self) -> Iterator[StatementWindow]:
        """Окна не меньше порога узлов."""
        width: int = self.rules.window
        for site in self.tree.functions:
            for block in FunctionBlocks(site).blocks():
                windows = (StatementWindow(site, tuple(block[start:start + width])) for start in range(len(block) - width + 1))
                yield from (window for window in windows if window.size >= self.rules.min_nodes)

    def _groups(self) -> Iterator[Finding]:
        """Участники каждого окна, которое встретилось больше чем в одной функции; одна группа на набор участников."""
        owners: dict[object, dict[str, str]] = {}
        for window in self._windows():
            owners.setdefault(window.form, {})[window.site.key] = window.site.module.key.text
        groups: dict[frozenset[str], frozenset[str]] = {
            frozenset(sites): frozenset(sites.values()) for sites in owners.values() if len(sites) > 1
        }
        for sites, modules in groups.items():
            yield Finding(GROUP_JOINER.join(sorted(sites)), len(sites), places=modules)
