"""Итоги стадии по ключам: сколько рядов отсеяно по каждой причине, сколько слотов на каждом языке (CLAUDE.md §11).

Одно правило подсчёта на всю программу: порядок ключей — заданный (члены перечисления по порядку) либо первого
появления; в лог счётчики уходят кортежем «ключ:число», человеку — строкой по шаблону из каталога msg, который
передаёт вызывающий.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, Generic, TypeVar

KeyT = TypeVar("KeyT", bound=Hashable)

LOG_ITEM_TEMPLATE: Final[str] = "{key}:{count}"     # счётчик одного ключа в поле строки лога


@dataclass(frozen=True)
class CountItem(Generic[KeyT]):
    """Счётчик одного ключа."""

    key: KeyT
    count: int

    @property
    def log_value(self) -> str:
        """«ключ:число»; член перечисления пишется своим значением."""
        key: object = self.key.value if isinstance(self.key, Enum) else self.key
        return LOG_ITEM_TEMPLATE.format(key=key, count=self.count)

    def text(self, template: str, name: Callable[[KeyT], str]) -> str:
        """Строка для человека: шаблон с полями `{name}` и `{count}`, имя ключа даёт `name`."""
        return template.format(name=name(self.key), count=self.count)


@dataclass(frozen=True)
class Counts(Generic[KeyT]):
    """Счётчики ключей стадии в их порядке; ключей с нулём нет."""

    items: tuple[CountItem[KeyT], ...]

    @classmethod
    def of(cls, keys: Iterable[KeyT], order: Sequence[KeyT] = ()) -> Counts[KeyT]:
        """Подсчёт ключей: порядок — `order` (например, члены перечисления), без него — первого появления."""
        counted: Counter[KeyT] = Counter(keys)
        ordered: Iterable[KeyT] = [key for key in order if counted[key]] if order else counted
        return cls(items=tuple(CountItem(key, counted[key]) for key in ordered))

    @property
    def total(self) -> int:
        return sum(item.count for item in self.items)

    def count(self, key: KeyT) -> int:
        """Счётчик ключа; ключа нет — 0."""
        return next((item.count for item in self.items if item.key == key), 0)

    @property
    def log_value(self) -> tuple[str, ...]:
        """Поле строки лога: «ключ:число» по порядку; пусто — пустой кортеж (лог пишет «-»)."""
        return tuple(item.log_value for item in self.items)

    def joined(self, template: str, joiner: str, name: Callable[[KeyT], str]) -> str:
        """Строка для консоли: каждый ключ по шаблону, через разделитель; шаблон и разделитель — из каталога msg."""
        return joiner.join(item.text(template, name) for item in self.items)

    def wrapped(self, wrapper: str, template: str, joiner: str, name: Callable[[KeyT], str]) -> str:
        """Часть строки для консоли: перечень `joined` внутри `wrapper` (поле `{items}`); ключей нет — пусто."""
        return wrapper.format(items=self.joined(template, joiner, name)) if self.items else ""
