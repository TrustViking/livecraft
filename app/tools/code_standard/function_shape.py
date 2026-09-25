"""Форма функций и методов: правила E1, E2, E3, E4, E12, E13 (REFACTORING_STANDARD.md §5).

Проверяется код app без `app\\tests`. Каждое правило — метод, который отдаёт `Measurement`.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from functools import cached_property
from typing import Final

from app.tools.code_standard.measurement import Finding, Measurement
from app.tools.code_standard.rule import Rule, Sign
from app.tools.code_standard.signature import FunctionBody, Signature
from app.tools.code_standard.source import DefinitionSite, ModuleSource, SourceTree
from app.tools.code_standard.standard import Standard
from app.tools.code_standard.usage import ClassScope, FunctionUse, FunctionUses

VIOLATION: Final[int] = 1  # величина нарушения «есть или нет»


@dataclass(frozen=True)
class FunctionShape:
    """Правила формы функций над деревом исходников и стандартом."""

    tree: SourceTree
    standard: Standard

    @cached_property
    def _uses(self) -> FunctionUses:
        return FunctionUses(self.tree)

    @cached_property
    def _scopes(self) -> dict[str, ClassScope]:
        return {module.key.text: ClassScope.of(module, self.tree) for module in self.tree.production}

    def measurements(self) -> tuple[Measurement, ...]:
        return (
            Measurement.of(Rule.FREE_FUNCTIONS, self._free_functions()),
            Measurement.of(Rule.STATIC_METHODS, self._static_methods()),
            Measurement.of(Rule.DEFINITION_LENGTH, self._long_definitions()),
            Measurement.of(Rule.PARAMETERS, self._wide_signatures()),
            Measurement.of(Rule.EMPTY_WRAPPERS, self._wrappers()),
            Measurement.of(Rule.STATE_TUPLES, self._tuple_results()),
        )

    def _free_functions(self) -> Iterator[Finding]:
        """E1: свободная функция с классом app в аннотациях, нужная одному классу или никому."""
        for site in self.tree.functions:
            signs: frozenset[Sign] = self._free_function_signs(site) if site.is_free_function else frozenset()
            if signs:
                yield Finding(site.key, VIOLATION, signs)

    def _free_function_signs(self, site: DefinitionSite) -> frozenset[Sign]:
        scope: ClassScope = self._scopes[site.module.key.text]
        uses: tuple[FunctionUse, ...] = self._uses.of(site)
        owners: set[str | None] = {use.owner for use in uses}
        in_one_class: bool = bool(uses) and len(owners) == 1 and None not in owners
        signs: set[Sign] = set()
        if any(scope.names_class(annotation) for annotation in Signature(site).annotations):
            signs.add(Sign.NAMES_APP_CLASS)
        if in_one_class and all(use.module == site.module.key.dotted for use in uses):
            signs.add(Sign.ONE_CLASS_USE)
        if not uses:
            signs.add(Sign.UNUSED)
        return frozenset(signs)

    def _static_methods(self) -> Iterator[Finding]:
        """E2: каждый `@staticmethod`."""
        return (Finding(site.key, VIOLATION) for site in self.tree.functions if site.is_static)

    def _long_definitions(self) -> Iterator[Finding]:
        """E3: определение длиннее предела строк, включая докстроку."""
        limit: int = self.standard.max_definition_lines
        return (Finding(site.key, site.line_count) for site in self.tree.functions if site.line_count > limit)

    def _wide_signatures(self) -> Iterator[Finding]:
        """E4: параметров без получателя больше предела."""
        for site in self.tree.functions:
            count: int = len(Signature(site).names)
            if count > self.standard.max_parameters:
                yield Finding(site.key, count)

    def _wrappers(self) -> Iterator[Finding]:
        """E12: пересылка, два слоя, чужое тело."""
        for site in self.tree.functions:
            body: FunctionBody = FunctionBody(site, Signature(site))
            signs: set[Sign] = set()
            if body.forwards(self.standard.wrapper_builtins):
                signs.add(Sign.FORWARDING)
            if body.is_two_layers:
                signs.add(Sign.TWO_LAYERS)
            if site.is_method and self._is_foreign_body(site.module, body):
                signs.add(Sign.FOREIGN_BODY)
            if signs:
                yield Finding(site.key, VIOLATION, frozenset(signs))

    def _is_foreign_body(self, module: ModuleSource, body: FunctionBody) -> bool:
        """Тело метода — вызов свободной функции того же модуля, у которой нет других использований в app."""
        name: str | None = body.called_name
        function: DefinitionSite | None = self._uses.function(module, name) if name else None
        return function is not None and len(self._uses.of(function)) == 1

    def _tuple_results(self) -> Iterator[Finding]:
        """E13: результат — кортеж фиксированной длины вместо объекта-значения."""
        return (Finding(site.key, VIOLATION) for site in self.tree.functions if Signature(site).returns_fixed_tuple)
