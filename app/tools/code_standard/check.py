"""Проверка кода app по эталону: все классы проверок над одним деревом исходников (REFACTORING_STANDARD.md §6).

Каждый класс проверок отвечает за свою заботу и отдаёт замеры своих правил: форма функций, значения в коде,
структурные клоны, слои импорта, форма модулей, тесты. Вместе они проверяют все правила E1–E21.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.tools.code_standard.clones import CloneFinder
from app.tools.code_standard.code_values import CodeValues
from app.tools.code_standard.function_shape import FunctionShape
from app.tools.code_standard.imports import ImportGraph
from app.tools.code_standard.measurement import Measurement, Measurements
from app.tools.code_standard.module_shape import ModuleShape
from app.tools.code_standard.source import SourceTree
from app.tools.code_standard.standard import Standard
from app.tools.code_standard.suite_shape import SuiteShape


@dataclass(frozen=True)
class StandardCheck:
    """Дерево исходников и стандарт; `measure` — замеры всех правил."""

    tree: SourceTree
    standard: Standard

    def measure(self) -> Measurements:
        shapes: tuple[tuple[Measurement, ...], ...] = (
            FunctionShape(self.tree, self.standard).measurements(),
            CodeValues(self.tree, self.standard.values).measurements(),
            CloneFinder(self.tree, self.standard.clones).measurements(),
            ImportGraph(self.tree, self.standard.layers).measurements(),
            ModuleShape(self.tree, self.standard).measurements(),
            SuiteShape(self.tree, self.standard.suite).measurements(),
        )
        return Measurements(tuple(item for measurements in shapes for item in measurements))
