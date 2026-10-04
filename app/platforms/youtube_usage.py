"""Расход YouTube Data API за запуск по операциям (CLAUDE.md §9): попытки, повторы, пустые ответы, отказы, квота.

Цена начисляется за каждую попытку (Google берёт минимум 1 ед. и за отказ): сумма — оценка сверху. Строка консоли о
расходе — `YouTubeUsage.line`: её печатает часть «эфиры».
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.platforms.youtube_operation import YouTubeOperation
from app.ui.messages import msg


@dataclass
class OperationUsage:
    """Счётчики одной операции."""

    operation: YouTubeOperation
    attempts: int = 0
    retries: int = 0
    empty: int = 0        # чтение по id вернуло пустой список
    refusals: int = 0     # окончательные отказы

    @property
    def units(self) -> int:
        """Единицы квоты: цена попытки на число попыток."""
        return self.attempts * self.operation.quota_units


@dataclass
class YouTubeUsage:
    """Счётчики запуска по операциям в порядке первого обращения."""

    operations: dict[YouTubeOperation, OperationUsage] = field(default_factory=dict)

    def of(self, operation: YouTubeOperation) -> OperationUsage:
        """Счётчики операции; первое обращение заводит их."""
        return self.operations.setdefault(operation, OperationUsage(operation))

    def attempted(self, operation: YouTubeOperation) -> None:
        self.of(operation).attempts += 1

    def retried(self, operation: YouTubeOperation) -> None:
        self.of(operation).retries += 1

    def empty_answer(self, operation: YouTubeOperation) -> None:
        self.of(operation).empty += 1

    def refused(self, operation: YouTubeOperation) -> None:
        self.of(operation).refusals += 1

    @property
    def attempts(self) -> int:
        """Обращений к YouTube за запуск."""
        return sum(usage.attempts for usage in self.operations.values())

    @property
    def units(self) -> int:
        """Единиц квоты за запуск."""
        return sum(usage.units for usage in self.operations.values())

    @property
    def line(self) -> str:
        """Строка консоли: обращения и единицы квоты за запуск."""
        return msg.YOUTUBE_USAGE_LINE.format(calls=self.attempts, units=self.units)
