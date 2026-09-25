"""Форма модулей и классов: правила E18, E19, E21 (REFACTORING_STANDARD.md §5).

E18 и E19 проверяют app без `app\\tests`; E21 — весь app, включая тесты (перенесено из прежнего
`app\\tests\\test_module_definitions.py` вместе с поведением: `@overload` и вложенные имена не считаются).
"""
from __future__ import annotations

import ast
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Final

from app.tools.code_standard.measurement import Finding, Measurement
from app.tools.code_standard.rule import Rule, Sign
from app.tools.code_standard.source import DEFINITION_NODES, FUNCTION_NODES, DefinitionSite, ModuleSource, SourceTree
from app.tools.code_standard.standard import Standard
from app.tools.code_standard.usage import EXPORTS_NAME

OVERLOAD_DECORATOR: Final[str] = "overload"
MEMBER_NODES: Final[tuple[type[ast.AST], ...]] = FUNCTION_NODES + (ast.AnnAssign,)


@dataclass(frozen=True)
class TopLevelNames:
    """Имена, которые модуль определяет на верхнем уровне: `def`, `class` и присваивания."""

    module: ModuleSource

    def names(self) -> Iterator[str]:
        overload_nodes: frozenset[ast.AST] = frozenset(
            site.node for site in self.module.definitions if not site.scope and OVERLOAD_DECORATOR in site.decorators
        )
        for node in self.module.tree.body:
            if isinstance(node, DEFINITION_NODES) and node not in overload_nodes:
                yield node.name
            elif isinstance(node, (ast.Assign, ast.AnnAssign)):
                yield from self._assigned(node)

    def repeated(self) -> dict[str, int]:
        """Имя → сколько раз определено, только имена, определённые больше одного раза."""
        counts: dict[str, int] = {}
        for name in self.names():
            counts[name] = counts.get(name, 0) + 1
        return {name: count for name, count in counts.items() if count > 1}

    def _assigned(self, node: ast.Assign | ast.AnnAssign) -> Iterator[str]:
        targets: list[ast.expr] = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            names: list[ast.expr] = target.elts if isinstance(target, (ast.Tuple, ast.List)) else [target]
            yield from (name.id for name in names if isinstance(name, ast.Name))


@dataclass(frozen=True)
class ModuleShape:
    """Правила формы модулей над деревом исходников и стандартом."""

    tree: SourceTree
    standard: Standard

    def measurements(self) -> tuple[Measurement, ...]:
        return (
            Measurement.of(Rule.SIZES, self._sizes()),
            Measurement.of(Rule.PACKAGE_INIT, self._package_inits()),
            Measurement.of(Rule.REPEATED_NAMES, self._repeated_names()),
        )

    def _sizes(self) -> Iterator[Finding]:
        """E18: модуль длиннее предела строк (кроме каталогов стандарта), класс больше предела членов."""
        for module in self.tree.production:
            if module.line_count > self.standard.max_module_lines and module.key.text not in self.standard.module_size_exempt:
                yield Finding(module.key.text, module.line_count, frozenset({Sign.MODULE}))
            for site in module.definitions:
                members: int = self._member_count(site) if site.is_class else 0
                if members > self.standard.max_class_members:
                    yield Finding(site.key, members, frozenset({Sign.CLASS}))

    def _member_count(self, site: DefinitionSite) -> int:
        """Методы, свойства и поля с аннотацией прямо в теле класса."""
        return sum(1 for node in site.node.body if isinstance(node, MEMBER_NODES))

    def _package_inits(self) -> Iterator[Finding]:
        """E19: в `__init__.py` — только докстрока, `from __future__`, импорты и `__all__`."""
        for module in self.tree.production:
            extra: int = self._init_extra(module) if module.key.is_package_init else 0
            if extra:
                yield Finding(module.key.text, extra)

    def _init_extra(self, module: ModuleSource) -> int:
        body: list[ast.stmt] = module.tree.body
        has_doc: bool = bool(body) and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant)
        statements: list[ast.stmt] = body[1:] if has_doc else body
        return sum(1 for node in statements if not self._is_allowed_in_init(node))

    def _is_allowed_in_init(self, node: ast.stmt) -> bool:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return True
        if isinstance(node, ast.Assign):
            return all(isinstance(target, ast.Name) and target.id == EXPORTS_NAME for target in node.targets)
        return isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name) and node.target.id == EXPORTS_NAME

    def _repeated_names(self) -> Iterator[Finding]:
        """E21: имя верхнего уровня определено в модуле больше одного раза; весь app, включая тесты."""
        for module in self.tree.modules:
            for name, count in TopLevelNames(module).repeated().items():
                yield Finding(module.key.site(name), count)
