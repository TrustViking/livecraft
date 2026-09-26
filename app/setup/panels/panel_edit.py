"""Итог правки модели вкладки настройщика — один для всех вкладок (CLAUDE.md §8.2).

Модели вкладок неизменяемые: правка отдаёт новую модель или ту же с проблемой. Негодный ввод — обычный исход
работы с формой, а не сбой, поэтому проблема — поле итога, а не исключение.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, TypeVar

from app.config.json_node import SettingProblem

PanelT = TypeVar("PanelT")


@dataclass(frozen=True)
class PanelEdit(Generic[PanelT]):
    """Модель вкладки после правки и проблема. Негодно — `panel` та же, что была, `problem` называет почему."""

    panel: PanelT
    problem: SettingProblem | None = None

    @property
    def is_applied(self) -> bool:
        """Правка принята: модель содержит новое."""
        return self.problem is None
