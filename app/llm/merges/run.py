"""Merge на весь запуск: модель, нейросеть, настройки, правила, счётчики и остановка (CLAUDE.md §14 решение 23).

Счётчики запуска — поля объекта `MergeTally`, строка лога `merge_run_summary`. Итог каждого слота добавляет к ним свой
счёт (`SlotCount`); «полные» и «частичные» итоги считаются по дням — по дате слота (`MergeDayBlocks`).

Остановка: квота нейросети исчерпана или виновата настройка модели — merge не делается до конца запуска, оставшиеся
слоты получают тексты источников, запуск идёт дальше (инвариант 9). Почему merge не делается — одно перечисление
`MergeStopReason`: для одного слота (мало описаний) или до конца запуска; отказ нейросети, который остановил merge,
остаётся полем `stop_failure` — его причину запуск называет оператору. Модель выбирает не этот объект: он получает
имя уже выбранной (`ModelChoice.chosen`) и из неё строит запрос каждой попытки (`MergeRun.request`).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from app.config.settings import LlmSettings
from app.llm.backend import LlmBackend, LlmRequest
from app.llm.errors import LlmFailure
from app.llm.merges.answer import MergeAnswer
from app.llm.merges.merge_rules import MergeRules
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.sources.video import SourceCatalog

LOGGER: logging.Logger = get_logger(LogArea.LLM)


class MergeStopReason(str, Enum):
    """Почему merge не делается: у слота мало описаний — только для него; квота или настройка модели — до конца запуска."""

    INSUFFICIENT_DESCRIPTIONS = "insufficient_descriptions"    # непустых описаний меньше двух
    QUOTA = "quota_exhausted"                                  # квота нейросети исчерпана
    MODEL = "model_configuration"                              # ключ, модель или форма запроса не приняты

    @property
    def stops_the_run(self) -> bool:
        return self is not MergeStopReason.INSUFFICIENT_DESCRIPTIONS


class RunEvent(str, Enum):
    """События merge запуска в логе."""

    SUMMARY = "merge_run_summary"
    STOPPED = "merge_run_stopped"


class MergeArtifactStatus(str, Enum):
    """Итог merge по дню."""

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


@dataclass(frozen=True)
class SlotCount:
    """Что итог одного слота добавляет к счётчикам запуска: дата слота, принят ли ответ модели, отвергнутые попытки,
    повторы, провал merge, восстановления абзацев и нужен ли был слоту merge."""

    date: str
    answer_accepted: bool
    rejected_attempts: int
    retries: int
    final_failure: bool
    paragraph_recoveries: int
    is_candidate: bool


@dataclass
class MergeTally:
    """Счётчики merge запуска; блоки слотов — по датам (`days`)."""

    merge_success: int = 0
    validation_rejected: int = 0
    retry_used: int = 0
    final_failure: int = 0
    paragraph_recovery_used: int = 0
    days: dict[str, MergeDayBlocks] = field(default_factory=dict)

    def record(self, count: SlotCount) -> None:
        """Учесть итог одного слота."""
        self.merge_success += int(count.answer_accepted)
        self.validation_rejected += count.rejected_attempts
        self.retry_used += count.retries
        self.final_failure += int(count.final_failure)
        self.paragraph_recovery_used += count.paragraph_recoveries
        if not count.is_candidate:
            return
        day: MergeDayBlocks = self.days.setdefault(count.date, MergeDayBlocks())
        day.candidates += 1
        if count.answer_accepted:
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
    def event(self) -> LogEvent:
        """Строка `merge_run_summary`: счётчики попыток, затем блоки и итоги по дням."""
        attempts: LogEvent = LogEvent.of(
            RunEvent.SUMMARY,
            merge_success=self.merge_success,
            validation_rejected=self.validation_rejected,
            retry_used=self.retry_used,
            final_failure=self.final_failure,
            paragraph_recovery_used=self.paragraph_recovery_used,
        )
        return attempts.extended(
            real_merge_blocks=self.real_merge_blocks,
            merge_candidate_blocks=self.merge_candidate_blocks,
            fallback_merge_blocks=self.fallback_merge_blocks,
            full_merge_artifacts=self.full_merge_artifacts,
            partial_merge_artifacts=self.partial_merge_artifacts,
            had_real_merge_blocks=self.had_real_merge_blocks,
        )


@dataclass
class MergeRun:
    """Merge одного запуска: нейросеть, выбранная модель, настройки `llm`, правила, видео запуска (один кеш данных
    и языка на источники и рекомендуемые видео), счётчики, причина остановки и отказ, который её вызвал."""

    backend: LlmBackend = field(repr=False)
    model: str
    settings: LlmSettings = field(repr=False)
    rules: MergeRules = field(repr=False)
    catalog: SourceCatalog = field(repr=False)
    tally: MergeTally = field(default_factory=MergeTally)
    stop_reason: MergeStopReason | None = None
    stop_failure: LlmFailure | None = None

    def request(self, prompt_text: str, label: str) -> LlmRequest:
        """Запрос попытки: промт, выбранная модель, предел ответа и ожидание из настроек, схема ответа merge."""
        return LlmRequest.from_settings(self.settings, self.model, prompt_text, label).with_schema(MergeAnswer.SCHEMA)

    def stop(self, reason: MergeStopReason, failure: LlmFailure) -> None:
        """Остановить merge до конца запуска отказом `failure`; первая причина и первый отказ остаются."""
        if self.stop_reason is not None:
            return
        self.stop_reason = reason
        self.stop_failure = failure
        stopped: LogEvent = LogEvent.of(RunEvent.STOPPED, provider=self.backend.name, model=self.model, reason=reason)
        stopped.emit(LOGGER, logging.ERROR)

    @property
    def event(self) -> LogEvent:
        """Итог запуска: строка счётчиков и причина остановки."""
        return self.tally.event.extended(stop_reason=self.stop_reason)
