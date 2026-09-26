"""Последовательности: одно правило «без повторов, в порядке первого появления» (CLAUDE.md §11).

Чистое преобразование без знания о предметных объектах — разрешённое §0 исключение.
"""
from __future__ import annotations

from collections.abc import Hashable, Iterable
from typing import TypeVar

ItemT = TypeVar("ItemT", bound=Hashable)


def unique_in_order(items: Iterable[ItemT]) -> tuple[ItemT, ...]:
    """Элементы без повторов в порядке первого появления."""
    return tuple(dict.fromkeys(items))
