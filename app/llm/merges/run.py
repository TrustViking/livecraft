"""Merge на весь запуск: модель, нейросеть, настройки, правила, счётчики и остановка (CLAUDE.md §14 решение 23).

Счётчики — `merge_run_summary.py::MergeRunSummary` донора (restreamer): поля объекта `MergeTally`, строка лога
`merge_run_summary` — с ключами донора. Считает их сам итог слота (`MergeTally.record(MergeOutcome)`): донор увеличивал
счётчики по ходу попыток, суммы те же. «Полных» и «частичных» артефактов донор считал по документу дня; здесь — так же,
по дате слота (`MergeDayBlocks`).

Остановка — решение Коворка к 3.13: квота нейросети исчерпана или виновата настройка модели — merge не делается до конца
запуска, оставшиеся слоты получают тексты источников, запуск идёт дальше (у донора ошибка настройки модели роняла весь
прогон — против инварианта 9). Модель выбирает не этот объект: он получает имя уже выбранной (`ModelChoice.chosen`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Final

from app.observability.logging_setup import get_logger

if TYPE_CHECKING:
    from app.config.loader import LlmSettings
    from app.llm.backend import LlmBackend
    from app.llm.merges.attempt import MergeRules
    from app.llm.merges.job import MergeOutcome

LOGGER: logging.Logger = get_logger("llm")

LOG_NONE: Final[str] = "none"
YES: Final[str] = "yes"
NO: Final[str] = "no"


class MergeStopReason(str, Enum):
    """Почему merge остановлен до конца запуска."""

    QUOTA = "quota_exhausted"                  # квота нейросети исчерпана
    MODEL = "model_configuration"              # ключ, модель или форма запроса не приняты


class MergeArtifactStatus(str, Enum):
    """Итог merge по дню (`slot_processing.py::resolve_merge_artifact_status` донора)."""

    NONE = "none"
    FULL = "full"
    PARTIAL = "partial"
    FALLBACK_ONLY = "fallback_only"


@dataclass
class MergeDayBlocks:
    """Слоты одного дня, где merge был нужен: сколько из них получили тексты модели и сколько — тексты источников."""

    candidates: int = 0
    real: int = 0
    fallback: int = 0

    @property
    def status(self) -> MergeArtifactStatus:
        if self.candidates <= 0:
            return MergeArtifactStatus.NONE
        if self.real > 0:
            return MergeArtifactStatus.PARTIAL if self.fallback > 0 else MergeArtifactStatus.FULL
        return MergeArtifactStatus.FALLBACK_ONLY if self.fallback > 0 else MergeArtifactStatus.NONE


@dataclass
class MergeTally:
    """Счётчики merge запуска — поля `MergeRunSummary` донора; блоки слотов — по датам (`days`)."""

    merge_success: int = 0
    validation_rejected: int = 0
    retry_used: int = 0
    final_failure: int = 0
    paragraph_recovery_used: int = 0
    days: dict[str, MergeDayBlocks] = field(default_factory=dict)

    def record(self, outcome: MergeOutcome) -> None:
        """Учесть итог одного слота."""
        self.merge_success += int(outcome.merged)
        self.validation_rejected += outcome.rejected_attempts
        self.retry_used += outcome.retries
        self.final_failure += int(outcome.is_final_failure)
        self.paragraph_recovery_used += outcome.paragraph_recoveries
        if not outcome.is_candidate:
            return
        day: MergeDayBlocks = self.days.setdefault(outcome.date, MergeDayBlocks())
        day.candidates += 1
        if outcome.merged:
            day.real += 1
        else:
            day.fallback += 1

    @property
    def real_merge_blocks(self) -> int:
        return sum(day.real for day in self.days.values())

    @property
    def merge_candidate_blocks(self) -> int:
        return sum(day.candidates for day in self.days.values())

    @property
    def fallback_merge_blocks(self) -> int:
        return sum(day.fallback for day in self.days.values())

    @property
    def full_merge_artifacts(self) -> int:
        return sum(1 for day in self.days.values() if day.status is MergeArtifactStatus.FULL)

    @property
    def partial_merge_artifacts(self) -> int:
        return sum(1 for day in self.days.values() if day.status is MergeArtifactStatus.PARTIAL)

    @property
    def had_real_merge_blocks(self) -> bool:
        return self.real_merge_blocks > 0

    @property
    def log_line(self) -> str:
        """Строка `merge_run_summary` — ключи и порядок донора (`MergeRunSummary.log_summary`)."""
        return (
            f"merge_run_summary merge_success={self.merge_success} validation_rejected={self.validation_rejected} "
            f"retry_used={self.retry_used} final_failure={self.final_failure} "
            f"paragraph_recovery_used={self.paragraph_recovery_used} real_merge_blocks={self.real_merge_blocks} "
            f"merge_candidate_blocks={self.merge_candidate_blocks} fallback_merge_blocks={self.fallback_merge_blocks} "
            f"full_merge_artifacts={self.full_merge_artifacts} partial_merge_artifacts={self.partial_merge_artifacts} "
            f"had_real_merge_blocks={YES if self.had_real_merge_blocks else NO}"
        )


@dataclass
class MergeRun:
    """Merge одного запуска: нейросеть, выбранная модель, настройки `llm`, правила, счётчики и причина остановки."""

    backend: LlmBackend = field(repr=False)
    model: str
    settings: LlmSettings = field(repr=False)
    rules: MergeRules = field(repr=False)
    tally: MergeTally = field(default_factory=MergeTally)
    stop_reason: MergeStopReason | None = None

    def stop(self, reason: MergeStopReason) -> None:
        """Остановить merge до конца запуска; первая причина остаётся."""
        if self.stop_reason is not None:
            return
        self.stop_reason = reason
        LOGGER.error("merge_run_stopped provider=%s model=%s reason=%s", self.backend.name, self.model, reason.value)

    @property
    def is_stopped(self) -> bool:
        return self.stop_reason is not None

    @property
    def log_line(self) -> str:
        """Итог запуска: строка донора и причина остановки."""
        stop: str = self.stop_reason.value if self.stop_reason is not None else LOG_NONE
        return f"{self.tally.log_line} stop_reason={stop}"
