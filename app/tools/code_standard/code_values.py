"""Значения в коде: правила E5, E6, E7, E8, E9, E10, E14, E15, E17 (REFACTORING_STANDARD.md §5).

Проверяется код app без `app\\tests`. Ключ нарушения — определение вокруг узла (`путь::имя`), вне
определений — путь модуля; у E6 и E10 — всегда путь модуля. Время (E17) ищется по ссылкам вида
`<модуль>.<функция>` (`datetime.now`, `time.monotonic`); имя, взятое импортом `from time import time`,
правило не видит — пропуск, а не ложное нарушение.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Final

from app.tools.code_standard.declarations import Declarations
from app.tools.code_standard.literals import FunctionLiterals
from app.tools.code_standard.measurement import Finding, Measurement
from app.tools.code_standard.rule import Rule, Sign
from app.tools.code_standard.signature import CalleeName
from app.tools.code_standard.source import FUNCTION_NODES, NAME_DOT, ModuleSource, SourceTree
from app.tools.code_standard.standard import ValueRules
from app.tools.code_standard.usage import Annotation

CYRILLIC_PATTERN: Final[re.Pattern[str]] = re.compile(r"[\u0400-\u04FF]")
ANY_NAME: Final[str] = "Any"
TEXT_CAST: Final[str] = "str"
LOGGER_FACTORY: Final[str] = "get_logger"
RAW_LOGGER_FACTORY: Final[str] = "getLogger"


@dataclass(frozen=True)
class NodeCount:
    """Узлы модулей, подошедшие под правило, по местам: определение вокруг узла или модуль целиком."""

    modules: tuple[ModuleSource, ...]
    per_module: bool

    def count(self, match: Callable[[ModuleSource, ast.AST], int]) -> Iterator[Finding]:
        """Величина — сумма того, что `match` насчитал в узлах места."""
        counts: dict[str, int] = {}
        for module, node in self._nodes():
            found: int = match(module, node)
            if found:
                key: str = self._place(module, node)
                counts[key] = counts.get(key, 0) + found
        return (Finding(key, count) for key, count in counts.items())

    def classify(self, match: Callable[[ModuleSource, ast.AST], Sign | None]) -> Iterator[Finding]:
        """Величина — число узлов места, доли — по признакам, которые назвал `match`."""
        parts: dict[str, dict[Sign, int]] = {}
        for module, node in self._nodes():
            sign: Sign | None = match(module, node)
            if sign is not None:
                found: dict[Sign, int] = parts.setdefault(self._place(module, node), {})
                found[sign] = found.get(sign, 0) + 1
        return (Finding(key, sum(found.values()), frozenset(found), found) for key, found in parts.items())

    def _nodes(self) -> Iterator[tuple[ModuleSource, ast.AST]]:
        return ((module, node) for module in self.modules for node in ast.walk(module.tree))

    def _place(self, module: ModuleSource, node: ast.AST) -> str:
        return module.key.text if self.per_module else module.owner_of(node)


@dataclass(frozen=True)
class CodeValues:
    """Правила значений в коде над деревом исходников и частью стандарта о значениях."""

    tree: SourceTree
    rules: ValueRules

    def measurements(self) -> tuple[Measurement, ...]:
        declarations: Declarations = Declarations(self.tree, self.rules)
        by_owner: NodeCount = NodeCount(self.tree.production, False)
        by_module: NodeCount = NodeCount(self.tree.production, True)
        outside: NodeCount = NodeCount(self._outside_boundaries, False)
        return (
            Measurement.of(Rule.BODY_LITERALS, self._body_literals()),
            Measurement.of(Rule.CYRILLIC_IN_CODE, NodeCount(self._outside_cyrillic_modules, True).count(self._cyrillic)),
            Measurement.of(Rule.EXCEPTION_TEXT, by_owner.count(self._exception_text)),
            Measurement.of(Rule.ONE_DECLARATION, declarations.constants()),
            Measurement.of(Rule.PATTERNS, [*declarations.repeated_patterns(), *declarations.patterns_in_functions()]),
            Measurement.of(Rule.LOGGERS, by_module.classify(self._logger)),
            Measurement.of(Rule.RAW_DATA, outside.count(self._any)),
            Measurement.of(Rule.DEFENSIVE_CASTS, outside.count(self._defensive_cast)),
            Measurement.of(Rule.TIME, NodeCount(self._outside_clock, False).count(self._clock_call)),
        )

    @cached_property
    def _outside_boundaries(self) -> tuple[ModuleSource, ...]:
        return tuple(module for module in self.tree.production if not self.rules.is_boundary(module.key))

    @cached_property
    def _outside_cyrillic_modules(self) -> tuple[ModuleSource, ...]:
        return tuple(module for module in self.tree.production if module.key.text not in self.rules.cyrillic_modules)

    @cached_property
    def _outside_clock(self) -> tuple[ModuleSource, ...]:
        return tuple(module for module in self.tree.production if module.key.text != self.rules.clock_module)

    def _body_literals(self) -> Iterator[Finding]:
        """E5: литералы тела функции по видам."""
        for site in self.tree.functions:
            kinds: dict[Sign, int] = dict(FunctionLiterals(site, self.rules).kinds())
            if kinds:
                yield Finding(site.key, sum(kinds.values()), frozenset(kinds), kinds)

    def _cyrillic(self, module: ModuleSource, node: ast.AST) -> int:
        """E6: строка кода с кириллицей; докстроки не считаются."""
        is_text: bool = isinstance(node, ast.Constant) and isinstance(node.value, str)
        return int(is_text and node not in module.docstrings and bool(CYRILLIC_PATTERN.search(node.value)))

    def _exception_text(self, module: ModuleSource, node: ast.AST) -> int:
        """E7: `raise X(…)` с литералом или f-строкой прямым аргументом."""
        if not isinstance(node, ast.Raise) or not isinstance(node.exc, ast.Call):
            return 0
        arguments: list[ast.expr] = [*node.exc.args, *(keyword.value for keyword in node.exc.keywords)]
        return int(any(self._is_text(argument) for argument in arguments))

    def _is_text(self, node: ast.expr) -> bool:
        return isinstance(node, ast.JoinedStr) or (isinstance(node, ast.Constant) and isinstance(node.value, str))

    def _logger(self, module: ModuleSource, node: ast.AST) -> Sign | None:
        """E10: `get_logger` без члена `LogArea`; `logging.getLogger` вне пакета логов."""
        if not isinstance(node, ast.Call):
            return None
        name: str | None = CalleeName(node.func).name
        if name == LOGGER_FACTORY and not self._is_log_area(node):
            return Sign.AREA_MISSING
        is_raw: bool = name == RAW_LOGGER_FACTORY and isinstance(node.func, ast.Attribute)
        return Sign.RAW_LOGGER if is_raw and not self.rules.logger_package.covers(module.key.text) else None

    def _is_log_area(self, call: ast.Call) -> bool:
        first: ast.expr | None = call.args[0] if call.args else None
        is_member: bool = isinstance(first, ast.Attribute) and isinstance(first.value, ast.Name)
        return is_member and first.value.id == self.rules.log_area_class

    def _any(self, module: ModuleSource, node: ast.AST) -> int:
        """E14: `Any` — имя, атрибут или часть строковой аннотации."""
        if isinstance(node, (ast.Name, ast.Attribute)):
            return int(CalleeName(node).name == ANY_NAME)
        if node not in self._annotation_texts.get(module.key.text, frozenset()):
            return 0
        annotation: Annotation | None = Annotation.parsed(node.value)
        return sum(1 for ref in annotation.refs if ref.name == ANY_NAME) if annotation else 0

    @cached_property
    def _annotation_texts(self) -> Mapping[str, frozenset[ast.AST]]:
        """Строки внутри аннотаций параметров, полей и результатов функций — по ключу модуля."""
        return {module.key.text: frozenset(self._texts_in_annotations(module)) for module in self._outside_boundaries}

    def _texts_in_annotations(self, module: ModuleSource) -> Iterator[ast.AST]:
        for node in ast.walk(module.tree):
            annotation: ast.expr | None = self._annotation_of(node)
            for item in ast.walk(annotation) if annotation is not None else ():
                if isinstance(item, ast.Constant) and isinstance(item.value, str):
                    yield item

    def _annotation_of(self, node: ast.AST) -> ast.expr | None:
        """Аннотация параметра, поля или результата функции."""
        if isinstance(node, (ast.arg, ast.AnnAssign)):
            return node.annotation
        return node.returns if isinstance(node, FUNCTION_NODES) else None

    def _defensive_cast(self, module: ModuleSource, node: ast.AST) -> int:
        """E15: `str(<выражение> or "")`."""
        if not isinstance(node, ast.Call) or CalleeName(node.func).name != TEXT_CAST or not isinstance(node.func, ast.Name):
            return 0
        argument: ast.expr | None = node.args[0] if len(node.args) == 1 and not node.keywords else None
        if not isinstance(argument, ast.BoolOp) or not isinstance(argument.op, ast.Or):
            return 0
        last: ast.expr = argument.values[-1]
        return int(isinstance(last, ast.Constant) and last.value == "")

    def _clock_call(self, module: ModuleSource, node: ast.AST) -> int:
        """E17: вызов или ссылка `<модуль>.<функция>` времени вне модуля часов."""
        if not isinstance(node, ast.Attribute):
            return 0
        base: str | None = CalleeName(node.value).name
        return int(base is not None and NAME_DOT.join((base, node.attr)) in self.rules.clock_calls)
