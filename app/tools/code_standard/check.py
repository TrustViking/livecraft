"""Проверка кода app по эталону: все классы проверок над одним деревом исходников (REFACTORING_STANDARD.md §6).

Каждый класс проверок отвечает за свою заботу и отдаёт замеры своих правил. Следующие заботы (значения
в коде, структурные клоны, тесты) встают в `StandardCheck.measure` той же формой.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.tools.code_standard.function_shape import FunctionShape
from app.tools.code_standard.measurement import Measurements
from app.tools.code_standard.module_shape import ModuleShape
from app.tools.code_standard.source import SourceTree
from app.tools.code_standard.standard import Standard


@dataclass(frozen=True)
class StandardCheck:
    """Дерево исходников и стандарт; `measure` — замеры всех проверяемых правил."""

    tree: SourceTree
    standard: Standard

    def measure(self) -> Measurements:
        shapes: tuple[FunctionShape | ModuleShape, ...] = (
            FunctionShape(self.tree, self.standard),
            ModuleShape(self.tree, self.standard),
        )
        return Measurements(tuple(item for shape in shapes for item in shape.measurements()))
