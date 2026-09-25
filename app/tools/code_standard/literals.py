"""Литералы в телах функций: правило E5 (REFACTORING_STANDARD.md §5).

Считаются литералы тела функции и значений её параметров по умолчанию: строки, кроме `""`, и числа, кроме
разрешённых стандартом. Не считаются докстроки, аннотации и декораторы; вложенная функция — отдельное
определение со своим ключом. Части f-строк считаются. Каждый литерал получает вид — признак отчёта:
число; лог (первый аргумент метода логгера или строка со «слово=»); разделитель (только пробелы, знаки
препинания и символы); идентификатор (одно слово); текст — остальное.
"""
from __future__ import annotations

import ast
import re
import unicodedata
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import Final

from app.tools.code_standard.rule import Sign
from app.tools.code_standard.source import FUNCTION_NODES, DefinitionSite
from app.tools.code_standard.standard import ValueRules

LOG_FIELD_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=")
IDENTIFIER_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*")
SEPARATOR_CATEGORIES: Final[frozenset[str]] = frozenset("PSZ")  # знаки препинания, символы, пробелы Юникода
SKIPPED_FIELDS: Final[Mapping[type[ast.AST], frozenset[str]]] = {
    ast.AnnAssign: frozenset({"annotation"}),
    ast.ClassDef: frozenset({"decorator_list"}),
    ast.arg: frozenset({"annotation"}),
}
NUMBER_TYPES: Final[tuple[type, ...]] = (int, float, complex)
TEXT_TYPES: Final[tuple[type, ...]] = (str, bytes)


@dataclass(frozen=True)
class Literal:
    """Литерал тела функции и то, стоит ли он в первом аргументе метода логгера."""

    node: ast.Constant
    in_log_call: bool

    def kind(self, rules: ValueRules) -> Sign | None:
        """Вид литерала; разрешённый стандартом литерал и не-литерал (`None`, `True`, `...`) — `None`."""
        value: object = self.node.value
        if isinstance(value, bool) or not isinstance(value, NUMBER_TYPES + TEXT_TYPES):
            return None
        if isinstance(value, NUMBER_TYPES):
            return None if value in rules.allowed_body_numbers else Sign.NUMBER
        text: str = value if isinstance(value, str) else repr(value)
        return self._text_kind(text) if value else None

    def _text_kind(self, text: str) -> Sign:
        if self.in_log_call or LOG_FIELD_PATTERN.search(text):
            return Sign.LOG
        if all(char.isspace() or unicodedata.category(char)[0] in SEPARATOR_CATEGORIES for char in text):
            return Sign.SEPARATOR
        return Sign.IDENTIFIER if IDENTIFIER_PATTERN.fullmatch(text) else Sign.TEXT


@dataclass(frozen=True)
class FunctionLiterals:
    """Литералы одного определения функции по видам."""

    site: DefinitionSite
    rules: ValueRules

    def kinds(self) -> Mapping[Sign, int]:
        counts: dict[Sign, int] = {}
        for literal in self._literals():
            kind: Sign | None = literal.kind(self.rules)
            if kind is not None:
                counts[kind] = counts.get(kind, 0) + 1
        return counts

    def _roots(self) -> list[ast.AST]:
        """Тело и значения по умолчанию; вложенные функции — свои определения."""
        spec: ast.arguments = self.site.node.args
        defaults: list[ast.AST] = [*spec.defaults, *(value for value in spec.kw_defaults if value is not None)]
        return [*self.site.node.body, *defaults]

    def _literals(self) -> Iterator[Literal]:
        docstrings: frozenset[ast.AST] = self.site.module.docstrings
        stack: list[tuple[ast.AST, bool]] = [(root, False) for root in self._roots()]
        while stack:
            node, in_log = stack.pop()
            if isinstance(node, FUNCTION_NODES) or node in docstrings:
                continue
            if isinstance(node, ast.Constant):
                yield Literal(node, in_log)
            stack.extend(self._children(node, in_log))

    def _children(self, node: ast.AST, in_log: bool) -> Iterator[tuple[ast.AST, bool]]:
        """Дети узла без аннотаций и декораторов; первый аргумент метода логгера помечается."""
        skipped: frozenset[str] = SKIPPED_FIELDS.get(type(node), frozenset())
        first_log_argument: ast.AST | None = self._log_argument(node)
        for name, value in ast.iter_fields(node):
            items: list[object] = value if isinstance(value, list) else [value]
            for item in items if name not in skipped else ():
                if isinstance(item, ast.AST):
                    yield item, in_log or item is first_log_argument

    def _log_argument(self, node: ast.AST) -> ast.AST | None:
        """Первый аргумент вызова `<объект>.<метод логгера>(…)`."""
        if not isinstance(node, ast.Call) or not node.args or not isinstance(node.func, ast.Attribute):
            return None
        return node.args[0] if node.func.attr in self.rules.log_methods else None
