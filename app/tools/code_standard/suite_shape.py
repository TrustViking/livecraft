"""Тесты тоже эталон: правило E20 (REFACTORING_STANDARD.md §5). Проверяется только `app\\tests`.

Признаки: модуль тестов импортирует другой модуль тестов (общее — только в общих модулях стандарта);
строка — имя логгера `<корень>.<область>` (имена файлов стандарта логгерами не считаются); подмена через
`monkeypatch.setattr` / `delattr` приватного имени или глобальных `os` / `shutil`; `dataclasses.replace`
вне заготовок тестов. Ключ — `путь::признак`, величина — число мест с этим признаком в модуле.
"""
from __future__ import annotations

import ast
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from functools import cached_property
from typing import Final

from app.tools.code_standard.imports import ImportedModules
from app.tools.code_standard.measurement import Finding, Measurement
from app.tools.code_standard.rule import Rule, Sign
from app.tools.code_standard.signature import PRIVATE_PREFIX, CalleeName
from app.tools.code_standard.source import NAME_DOT, ModuleSource, SourceTree
from app.tools.code_standard.standard import SuiteRules

LOGGER_NAME_TEMPLATE: Final[str] = r"{root}(?:\.[a-z_]+)+"
PATCHER: Final[str] = "monkeypatch"
PATCH_METHODS: Final[frozenset[str]] = frozenset({"setattr", "delattr"})
GLOBAL_MODULES: Final[frozenset[str]] = frozenset({"os", "shutil"})
DATACLASSES_MODULE: Final[str] = "dataclasses"
REPLACE_FUNCTION: Final[str] = "replace"


@dataclass(frozen=True)
class SuiteModule:
    """Модуль тестов и признаки E20 в нём."""

    module: ModuleSource
    tree: SourceTree
    rules: SuiteRules

    def counts(self) -> Mapping[Sign, int]:
        found: dict[Sign, int] = {
            Sign.TEST_IMPORT: self._test_imports(),
            Sign.LOGGER_NAME: sum(1 for node in self._nodes if self._is_logger_name(node)),
            Sign.PRIVATE_PATCH: sum(1 for call in self._patches if self._is_private(call)),
            Sign.GLOBAL_PATCH: sum(1 for call in self._patches if self._is_global(call)),
            Sign.DATACLASS_REPLACE: 0 if self.rules.is_fixture(self.module.key) else self._replaces(),
        }
        return {sign: count for sign, count in found.items() if count}

    @cached_property
    def _nodes(self) -> tuple[ast.AST, ...]:
        return tuple(ast.walk(self.module.tree))

    @cached_property
    def _patches(self) -> tuple[ast.Call, ...]:
        """Вызовы `monkeypatch.setattr(…)` и `monkeypatch.delattr(…)` с аргументами."""
        return tuple(
            node for node in self._nodes
            if isinstance(node, ast.Call) and node.args and isinstance(node.func, ast.Attribute)
            and node.func.attr in PATCH_METHODS and CalleeName(node.func.value).name == PATCHER
        )

    def _test_imports(self) -> int:
        """Операторы импорта, которые ведут в другой модуль тестов, кроме общих."""
        statements: set[int] = set()
        for item in ImportedModules(self.module, self.tree).targets:
            target: ModuleSource | None = self.tree.by_name.get(item.target)
            is_test: bool = target is not None and target.key.is_test and not target.key.is_package_init
            if is_test and target is not self.module and not self.rules.is_shared(target.key):
                statements.add(id(item.statement))
        return len(statements)

    @cached_property
    def _logger_pattern(self) -> re.Pattern[str]:
        return re.compile(LOGGER_NAME_TEMPLATE.format(root=re.escape(self.rules.logger_root)))

    def _is_logger_name(self, node: ast.AST) -> bool:
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            return False
        return bool(self._logger_pattern.fullmatch(node.value)) and node.value not in self.rules.logger_file_names

    def _target_parts(self, call: ast.Call) -> list[str]:
        """Что подменяют: `"модуль.имя"` строкой — части пути; `(объект, "имя")` — объект и имя."""
        first: ast.expr = call.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            return first.value.split(NAME_DOT)
        second: ast.expr | None = call.args[1] if len(call.args) > 1 else None
        name: str = second.value if isinstance(second, ast.Constant) and isinstance(second.value, str) else ""
        return [CalleeName(first).name or "", name]

    def _is_private(self, call: ast.Call) -> bool:
        return self._target_parts(call)[-1].startswith(PRIVATE_PREFIX)

    def _is_global(self, call: ast.Call) -> bool:
        return self._target_parts(call)[0] in GLOBAL_MODULES

    def _replaces(self) -> int:
        """Вызовы `dataclasses.replace(…)` и `replace(…)`, взятого из `dataclasses`."""
        aliases: set[str] = {
            alias.asname or alias.name for node in self._nodes if isinstance(node, ast.ImportFrom)
            and node.module == DATACLASSES_MODULE for alias in node.names if alias.name == REPLACE_FUNCTION
        }
        return sum(1 for node in self._nodes if isinstance(node, ast.Call) and self._is_replace(node.func, aliases))

    def _is_replace(self, func: ast.expr, aliases: set[str]) -> bool:
        if isinstance(func, ast.Name):
            return func.id in aliases
        is_module: bool = isinstance(func, ast.Attribute) and CalleeName(func.value).name == DATACLASSES_MODULE
        return is_module and func.attr == REPLACE_FUNCTION


@dataclass(frozen=True)
class SuiteShape:
    """Правило тестов над деревом исходников."""

    tree: SourceTree
    rules: SuiteRules

    def measurements(self) -> tuple[Measurement, ...]:
        return (Measurement.of(Rule.TESTS, self._findings()),)

    def _findings(self) -> Iterator[Finding]:
        for module in self.tree.tests:
            for sign, count in SuiteModule(module, self.tree, self.rules).counts().items():
                yield Finding(module.key.site(sign.value), count, frozenset({sign}), {sign: count})
