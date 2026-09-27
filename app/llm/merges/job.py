"""Merge одного слота: попытки с повторами, итог — тексты слота (CLAUDE.md §3 шаг 5, §14 решение 23).

- merge — только при двух и больше непустых описаниях источников (`MergeSources.needs_merge` — то же правило
  спрашивает запуск до выбора модели), иначе тексты источников (`merge_input_summary`, пропуск); merge запуска уже
  остановлен — слот без запроса (`merge_branch_aborted_quota_exhausted`);
- две попытки, три — если хоть одна отвергнута по повторяемой причине (`AttemptHistory`); профиль повтора выбирает
  итог отвергнутой попытки; квота или настройка модели — стоп слота и merge запуска; прочий отказ нейросети —
  `unexpected_error` и обычный повтор;
- принятое описание слота из нескольких источников выравнивается (`ParagraphEnforcement`, строка
  `merge_post_enforcement`), проходит санацию (`MergePublication`); блок с повтором абзацев или призывом в начале не
  публикуется — слот получает тексты источников, строка `merge_publish_gate_blocked` (`target=package`). Успех merge
  и настоящие блоки в счётчиках — по принятому ответу: они считаются до санации.

Предел абзацев тела и пределы пунктов в подсказке повтора — из контракта промта этой попытки. Порядок источников в
промте — порядок рядов слота: все источники слота имеют одно время. Строки лога слота начинаются полями
`slot=<slot_id> language=<язык>`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.llm.errors import LlmFailure
from app.llm.merges.attempt import STAGE_PRIMARY, AcceptedMerge, MergeAttempt, MergeAttemptResult
from app.llm.merges.check import MergeAttemptLabel
from app.llm.merges.description import MergedDescription
from app.llm.merges.layout import DescriptionLayout
from app.llm.merges.outcome import AttemptHistory, MergeOutcome
from app.llm.merges.prompt import MergePrompt
from app.llm.merges.publication import MergePublication, PublicationSlot
from app.llm.merges.retry import RetryProfile
from app.llm.merges.rules import MIN_DESCRIBED_SOURCES, POST_ENFORCEMENT_MAX_BODY_PARAGRAPHS
from app.llm.merges.run import MergeRun, MergeStopReason
from app.llm.merges.source import HARD_TRUNCATION_DISABLED
from app.observability.log_event import MESSAGE_TEMPLATE, LogArea, LogEvent, get_logger
from app.slots.slot import SlotKey
from app.slots.texts import SlotTexts
from app.sources.video import SourceVideo
from app.texts.paragraphs import normalize_multiline_text

LOGGER: logging.Logger = get_logger(LogArea.LLM)

NOT_APPLICABLE: Final[str] = "not_applicable"
EMPTY_DESCRIPTION_NOTE: Final[str] = "empty_description"
PUBLISH_TARGET: Final[str] = "package"         # куда уходят тексты слота до этапа «Публикация»
SOURCE_TEXTS_FALLBACK: Final[str] = "nomerge"  # чем заменён заблокированный блок: тексты источников
# С четырёх источников направленный повтор называется «четыре и больше, со структурой».
STRUCTURED_RETRY_MIN_SOURCES: Final[int] = 4


class JobEvent(str, Enum):
    """События merge слота в логе."""

    INPUT_SUMMARY = "merge_input_summary"
    PRIMARY_ATTEMPT = "merge_llm_primary_attempt"
    RETRY = "merge_llm_retry"
    FATAL_MODEL_ERROR = "merge_llm_fatal_model_error"
    BRANCH_READY = "merge_branch_ready"
    PROVIDER_SUMMARY = "merge_provider_summary"
    POST_ENFORCEMENT = "merge_post_enforcement"
    PUBLISH_GATE_BLOCKED = "merge_publish_gate_blocked"
    FINAL_FAILURE = "merge_llm_final_failure"
    SKIPPED = "merge_skipped"
    ABORTED_QUOTA = "merge_branch_aborted_quota_exhausted"
    ABORTED_MODEL = "merge_branch_aborted_model_error"


class RetryStructure(str, Enum):
    """Вид направленного повтора по числу источников."""

    FOUR_PLUS = "four_plus_structured"
    STANDARD = "standard"


class FinalStatus(str, Enum):
    """Итог обращений к нейросети по слоту."""

    SUCCESS = "success"
    FAILED = "failed"


# Строка слота, который остался без запроса, потому что merge запуска остановлен.
ABORTED_EVENTS: Final[dict[MergeStopReason, JobEvent]] = {
    MergeStopReason.QUOTA: JobEvent.ABORTED_QUOTA,
    MergeStopReason.MODEL: JobEvent.ABORTED_MODEL,
}


@dataclass(frozen=True)
class ParagraphEnforcement:
    """Выравнивание принятого описания: тело и хвост заново, число абзацев тела — к пределу по умолчанию. Описание,
    число абзацев до и после, что произошло."""

    description: MergedDescription
    mutated: bool
    recovery_applied: bool
    note: str
    body_paragraphs_before: int
    body_paragraphs_after: int

    @classmethod
    def of(cls, description: MergedDescription) -> ParagraphEnforcement:
        original: str = description.text.strip()
        layout: DescriptionLayout = DescriptionLayout.of(original, POST_ENFORCEMENT_MAX_BODY_PARAGRAPHS)
        if not layout.body_text.strip():
            return cls(MergedDescription(original), False, False, EMPTY_DESCRIPTION_NOTE, 0, 0)
        normalized: str = layout.full_text or original
        mutated: bool = normalized != original
        return cls(
            description=MergedDescription(normalized) if mutated else description,
            mutated=mutated,
            recovery_applied=layout.recovery_applied and mutated,
            note=layout.recovery.value,
            body_paragraphs_before=layout.body_paragraph_count,
            body_paragraphs_after=layout.body_paragraph_count_after_recovery,
        )

    def extend(self, event: LogEvent) -> LogEvent:
        """Поля строки `merge_post_enforcement`."""
        return event.extended(
            body_paragraphs_before=self.body_paragraphs_before,
            body_paragraphs_after=self.body_paragraphs_after,
            mutated=self.mutated,
            recovery_applied=self.recovery_applied,
            reason=self.note,
        )


@dataclass(frozen=True)
class MergeSources:
    """Источники слота в порядке рядов и правило «слоту нужен merge»: непустых описаний не меньше
    `MIN_DESCRIBED_SOURCES`. Сводить одно описание не с чем — модель не спрашивается, а если merge не нужен ни одному
    слоту запуска, модель не выбирается вовсе."""

    videos: tuple[SourceVideo, ...]

    @property
    def descriptions(self) -> tuple[str, ...]:
        """Описания источников без краёв; видео без данных — пустое."""
        return tuple(video.text.description.strip() for video in self.videos)

    @property
    def described(self) -> int:
        """Сколько источников с непустым описанием."""
        return sum(1 for description in self.descriptions if description)

    @property
    def needs_merge(self) -> bool:
        return self.described >= MIN_DESCRIBED_SOURCES


@dataclass(frozen=True)
class MergeJob:
    """Merge одного слота: ключ слота, его источники в порядке рядов и merge запуска (нейросеть, модель, настройки,
    правила, счётчики)."""

    key: SlotKey
    videos: tuple[SourceVideo, ...]
    merge_run: MergeRun = field(repr=False)

    def event(self, name: Enum) -> LogEvent:
        """Строка лога о слоте: имя события, слот, язык."""
        return LogEvent.of(name, slot=self.key.slot_id, language=self.key.language)

    @property
    def sources(self) -> MergeSources:
        return MergeSources(self.videos)

    @property
    def skip_reason(self) -> MergeStopReason | None:
        """Почему модель не спрашивается: мало описаний (раньше), merge запуска остановлен."""
        if not self.sources.needs_merge:
            return MergeStopReason.INSUFFICIENT_DESCRIPTIONS
        return self.merge_run.stop_reason

    def run(self) -> MergeOutcome:
        """Merge слота; итог учитывается в счётчиках запуска и пишется строкой лога."""
        self.input_event.emit(LOGGER)
        outcome: MergeOutcome = self._outcome()
        self.merge_run.tally.record(outcome.count)
        outcome.event.emit(LOGGER)
        return outcome

    def _outcome(self) -> MergeOutcome:
        skip: MergeStopReason | None = self.skip_reason
        if skip is not None:
            return self._skipped(skip)
        history: AttemptHistory = self._attempts(MergePrompt.of(self.key.language, self.videos, self.merge_run.rules.texts))
        accepted: AcceptedMerge | None = history.accepted
        if accepted is None:
            return self._failed(history)
        return self._merged(history, accepted)

    def _attempts(self, prompt: MergePrompt) -> AttemptHistory:
        """Попытки до принятого ответа, остановки или исчерпания попыток."""
        history: AttemptHistory = AttemptHistory()
        while history.can_try:
            result: MergeAttemptResult = self._attempt(prompt, history)
            history.add(result, prompt, self.merge_run.rules)
            if result.accepted is not None:
                break
            self._note_failure(result)
        return history

    def _attempt(self, prompt: MergePrompt, history: AttemptHistory) -> MergeAttemptResult:
        run: MergeRun = self.merge_run
        label: MergeAttemptLabel = MergeAttemptLabel(self.key.slot_id, self.key.language, run.model, history.next_number)
        label.event(JobEvent.PRIMARY_ATTEMPT).extended(provider=run.backend.name, stage=STAGE_PRIMARY).emit(LOGGER)
        retry: RetryProfile | None = history.next_retry
        if retry is not None:
            self._retry_event(label, retry).emit(LOGGER)
            for line in prompt.log_lines:
                LOGGER.info(MESSAGE_TEMPLATE, line)
        return MergeAttempt(prompt.with_retry(retry), label, self.videos, run).run()

    def _retry_event(self, label: MergeAttemptLabel, retry: RetryProfile) -> LogEvent:
        """Строка `merge_llm_retry`."""
        structured: bool = retry.enabled and len(self.videos) >= STRUCTURED_RETRY_MIN_SOURCES
        return label.event(JobEvent.RETRY).extended(
            provider=self.merge_run.backend.name,
            retry_mode=retry.mode,
            retry_reason_codes=retry.reject_signal_label,
            retry_focus=retry.focus_label,
            retry_structure=RetryStructure.FOUR_PLUS if structured else RetryStructure.STANDARD,
            retry_source_count=len(self.videos),
        )

    def _note_failure(self, result: MergeAttemptResult) -> None:
        """Неудачная попытка: строка лога; квота или настройка модели останавливают merge запуска своим отказом."""
        run: MergeRun = self.merge_run
        failure: LlmFailure | None = result.failure
        if result.is_model_configuration and failure is not None:
            fatal: LogEvent = result.label.event(JobEvent.FATAL_MODEL_ERROR).extended(provider=run.backend.name)
            failure.extend(fatal).emit(LOGGER, logging.ERROR)
            run.stop(MergeStopReason.MODEL, failure)
            return
        result.invalid_event(run.backend.name).emit(LOGGER)
        if result.is_quota and failure is not None:
            run.stop(MergeStopReason.QUOTA, failure)

    def _merged(self, history: AttemptHistory, accepted: AcceptedMerge) -> MergeOutcome:
        """Ответ принят: выравнивание абзацев слота из нескольких источников, санация и проверка перед публикацией;
        блок не прошёл проверку — тексты источников и строка `merge_publish_gate_blocked`."""
        run: MergeRun = self.merge_run
        self.event(JobEvent.BRANCH_READY).extended(generator_model=run.model).emit(LOGGER)
        self._provider_event(FinalStatus.SUCCESS).emit(LOGGER)
        description: MergedDescription = accepted.description
        recoveries: int = int(accepted.tail_recovery_applied)
        if len(self.videos) > 1:
            enforcement: ParagraphEnforcement = ParagraphEnforcement.of(description)
            enforcement.extend(self.event(JobEvent.POST_ENFORCEMENT)).emit(LOGGER)
            description = enforcement.description
            recoveries += int(enforcement.recovery_applied)
        slot: PublicationSlot = PublicationSlot(self.key.language, self.videos, run.rules, run.catalog)
        publication: MergePublication = MergePublication.of(accepted.title, description.text, slot)
        texts: SlotTexts | None = publication.slot_texts
        if texts is None:
            blocked: LogEvent = LogEvent.of(
                JobEvent.PUBLISH_GATE_BLOCKED, target=PUBLISH_TARGET, slot=self.key.slot_id, language=self.key.language
            )
            publication.verdict.extend(blocked).extended(fallback=SOURCE_TEXTS_FALLBACK).emit(LOGGER, logging.WARNING)
        return MergeOutcome(
            self.key,
            len(self.videos),
            texts or self._source_texts,
            history,
            paragraph_recoveries=recoveries,
            publish_blocked=publication.is_blocked,
        )

    def _failed(self, history: AttemptHistory) -> MergeOutcome:
        """Ответ не принят ни в одной попытке: строки итога, тексты источников."""
        run: MergeRun = self.merge_run
        last: MergeAttemptResult | None = history.last
        answered: MergeAttemptResult | None = history.last_answered
        self.event(JobEvent.FINAL_FAILURE).extended(
            provider=run.backend.name,
            stage=STAGE_PRIMARY,
            code=last.code if last is not None else None,
            fallback_used=False,
            raw_response_received=answered is not None and answered.raw_received,
            reason=last.reason if last is not None else None,
            raw_chars=answered.raw_chars if answered is not None else 0,
        ).emit(LOGGER, logging.WARNING)
        self._provider_event(FinalStatus.FAILED).emit(LOGGER)
        if run.stop_reason is not None:
            self.event(ABORTED_EVENTS[run.stop_reason]).emit(LOGGER, logging.ERROR)
        return MergeOutcome(self.key, len(self.videos), self._source_texts, history)

    def _skipped(self, reason: MergeStopReason) -> MergeOutcome:
        """Модель не спрашивается: тексты источников; причина — строкой лога."""
        if reason.stops_the_run:
            self.event(ABORTED_EVENTS[reason]).emit(LOGGER, logging.ERROR)
        else:
            skipped: LogEvent = self.event(JobEvent.SKIPPED).extended(non_empty_descriptions=self.sources.described)
            skipped.extended(reason=reason).emit(LOGGER)
        return MergeOutcome(self.key, len(self.videos), self._source_texts, skipped_reason=reason)

    def _provider_event(self, status: FinalStatus) -> LogEvent:
        """Строка `merge_provider_summary`: нейросеть, модель и итог обращений по слоту."""
        run: MergeRun = self.merge_run
        summary: LogEvent = LogEvent.of(JobEvent.PROVIDER_SUMMARY, provider=run.backend.name, model=run.model)
        return summary.extended(
            structured_ok=status is FinalStatus.SUCCESS, fallback_used=False, parse_repair_used=False, final_status=status
        )

    @property
    def _source_texts(self) -> SlotTexts:
        return SlotTexts.from_sources([video.text for video in self.videos])

    @property
    def input_event(self) -> LogEvent:
        """Строка `merge_input_summary` — счётчики источников, без текста."""
        merge_sources: MergeSources = self.sources
        descriptions: tuple[str, ...] = merge_sources.descriptions
        expected: bool = merge_sources.needs_merge
        sources: LogEvent = self.event(JobEvent.INPUT_SUMMARY).extended(
            source_count=len(self.videos),
            non_empty_descriptions=merge_sources.described,
            titles_non_empty=sum(1 for video in self.videos if video.text.title.strip()),
            source_desc_chars_total=sum(len(text) for text in descriptions),
            source_desc_chars_passed_to_llm=sum(len(normalize_multiline_text(text)) for text in descriptions),
        )
        return sources.extended(
            hard_truncation=HARD_TRUNCATION_DISABLED,
            merge_expected=expected,
            merge_skip_reason=NOT_APPLICABLE if expected else MergeStopReason.INSUFFICIENT_DESCRIPTIONS,
        )
