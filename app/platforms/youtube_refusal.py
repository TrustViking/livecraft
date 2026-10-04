"""Память отказов YouTube за запуск (CLAUDE.md §6 инвариант 9).

Окончательный отказ с поведением «операция», «канал» или «проект» запоминается: следующий такой вызов поднимает ту же
ошибку без обращения к сети и без паузы. Ключ памяти — канал и операция, «любой» — None: отказ проекта
касается всех каналов, отказ канала — всех его операций. Канал, для которого вход сброшен, свои отказы забывает.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from app.platforms.error import PlatformError
from app.platforms.youtube_failure import YouTubeFailure
from app.platforms.youtube_operation import ErrorBehavior, YouTubeOperation


@dataclass(frozen=True)
class RefusalKey:
    """Кому запомнен отказ: ключ канала и операция; None — любой канал, любая операция."""

    channel: str | None
    operation: YouTubeOperation | None

    @classmethod
    def of(cls, failure: YouTubeFailure, channel: str) -> RefusalKey | None:
        """Ключ по поведению отказа; повтор и разовый отказ не запоминаются — None."""
        behavior: ErrorBehavior = failure.behavior
        if behavior is ErrorBehavior.OPERATION:
            return cls(channel, failure.operation)
        if behavior is ErrorBehavior.CHANNEL:
            return cls(channel, None)
        if behavior is ErrorBehavior.PROJECT:
            return cls(None, None)
        return None


@dataclass(frozen=True)
class Refusal:
    """Запомненный отказ: ошибка, которую поднять снова, и поведение, по которому он запомнен."""

    error: PlatformError
    behavior: ErrorBehavior


@dataclass
class RefusalBook:
    """Отказы запуска по ключам."""

    refusals: dict[RefusalKey, Refusal] = field(default_factory=dict)

    def remember(self, channel: str, failure: YouTubeFailure) -> Refusal:
        """Окончательный отказ: запомнить по поведению, если его надо помнить; вернуть его."""
        refusal: Refusal = Refusal(failure.final_error, failure.behavior)
        key: RefusalKey | None = RefusalKey.of(failure, channel)
        if key is not None:
            self.refusals[key] = refusal
        return refusal

    def find(self, channel: str, operation: YouTubeOperation) -> Refusal | None:
        """Отказ проекта, затем канала, затем этой операции на канале; нет — None. Сети не нужно."""
        for key in (RefusalKey(None, None), RefusalKey(channel, None), RefusalKey(channel, operation)):
            found: Refusal | None = self.refusals.get(key)
            if found is not None:
                return found
        return None

    def forget_channel(self, channel: str) -> None:
        """Забыть все отказы канала: вход в него сброшен, следующий запрос — с новым входом."""
        for key in [key for key in self.refusals if key.channel == channel]:
            del self.refusals[key]
