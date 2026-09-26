"""Одна попытка merge: запрос к модели → разбор → починка алфавита → нормализация → проверка (CLAUDE.md §14 решение 23).

Шаги по порядку: запрос merge запуска (`MergeRun.request`: схема ответа `MergeAnswer.SCHEMA`, температура 0) →
предварительная проверка переполнения абзацев и разбор ответа (`MergeAnswer.parse`, предел абзацев — из контракта промта
этой попытки) → починка смешанного алфавита (строка `merge_script_mix_repaired`) → проверка (`MergeCheck`: нормализация
качества с названием и числом источников, диагностика — две строки стиля) → восстановление форматирования при отказе
(`FormattingRecovery`: от трёх источников отказ «много эмодзи» снимается снятием эмодзи и повторной проверкой) →
строка `merge_llm_response_valid`.

Итог попытки — значение `MergeAttemptResult` с одним исходом: принятый ответ, отказ или отказ нейросети (`LlmFailure`).
Сбой запроса разъём бросает исключением `LlmRequestError`; попытка перехватывает только его и хранит значение отказа.
Какой повтор следующий, решает сам итог (`MergeAttemptResult.next_retry`): числа для подсказки модели берутся из
отвергнутой попытки.

Модель merge видит только через разъём `LlmBackend` (решение 22). Текста ответа и описаний в строках лога нет.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.llm.backend import LlmResponse
from app.llm.errors import LlmErrorKind, LlmFailure, LlmRequestError
from app.llm.merges.answer import MergeAnswer
from app.llm.merges.check import MergeAttemptLabel, MergeCheck, MergeCheckPassed, MergeCheckRequest, MergeDiagnostics
from app.llm.merges.contract import MergeContract
from app.llm.merges.description import MergedDescription
from app.llm.merges.emoji import EmojiCleanup, EmojiUsage
from app.llm.merges.prompt import MergePrompt
from app.llm.merges.prompt_texts import MergePromptTexts
from app.llm.merges.quality import QualityNormalization, QualityRequest
from app.llm.merges.reject import MergeReject, MergeRejectCode
from app.llm.merges.retry import RetryFacts, RetryProfile
from app.llm.merges.rules import FORMATTING_RECOVERY_MIN_SOURCES
from app.llm.merges.run import MergeRun
from app.llm.merges.script_mix import HomoglyphRepair
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.sources.video import SourceVideo

LOGGER: logging.Logger = get_logger(LogArea.LLM)

# Отказ нейросети, который не квота и не настройка модели: код «неожиданная ошибка», повтор — обычный.
UNEXPECTED_CODE: Final[str] = MergeRejectCode.UNEXPECTED.value
# Перегруженных пунктов, когда описания отвергнутой попытки нет, и абзацев перебора, когда число не известно.
OVERLOADED_COUNT_UNKNOWN: Final[int] = 1
OVERFLOW_PARAGRAPHS_UNKNOWN: Final[int] = 8
STAGE_PRIMARY: Final[str] = "primary"


class AttemptEvent(str, Enum):
    """События попытки в логе."""

    SCRIPT_MIX_REPAIRED = "merge_script_mix_repaired"
    RESPONSE_VALID = "merge_llm_response_valid"
    RESPONSE_INVALID = "merge_llm_response_invalid"
    SALVAGE = "merge_llm_validation_salvage"


class RecoveryAction(str, Enum):
    """Что восстановление форматирования сделало с текстом."""

    REDUCED_EMOJI = "reduced_non_structural_emoji"
    REAPPLIED_QUALITY = "reapplied_merge_quality_normalization"


class RecoveryOutcome(str, Enum):
    """Чем кончилось восстановление: ответ прошёл или открылся отказ не про форматирование."""

    APPLIED = "applied"
    REVEALED = "revealed_non_formatting_issue"


@dataclass(frozen=True)
class FormattedDraft:
    """Описание отказа «много эмодзи» после снятия эмодзи и нормализации качества и что с ним сделано."""

    description: MergedDescription
    actions: tuple[RecoveryAction, ...]

    @classmethod
    def of(cls, check: MergeCheck) -> FormattedDraft:
        """Эмодзи вне маркеров снимаются, затем качество нормализуется без названия и числа источников."""
        trimmed: MergedDescription = MergedDescription(check.description.text.strip())
        cleanup: EmojiCleanup = EmojiUsage(trimmed).cleaned()
        description: MergedDescription = cleanup.description if cleanup.changed else trimmed
        actions: list[RecoveryAction] = [RecoveryAction.REDUCED_EMOJI] if cleanup.changed else []
        normalized: MergedDescription = QualityNormalization.of(
            description, QualityRequest(language=check.request.label.language), check.lexicons
        ).description
        if normalized.text != description.text:
            description = normalized
            actions.append(RecoveryAction.REAPPLIED_QUALITY)
        return cls(description=description, actions=tuple(actions))


@dataclass(frozen=True)
class FormattingRecovery:
    """Восстановление форматирования после отказа: итог (`verdict` — прошедшая проверка или отказ) и что было
    сделано с текстом (`actions`). Не применялось — итог есть исходный отказ."""

    verdict: MergeCheckPassed | MergeReject
    actions: tuple[RecoveryAction, ...]

    @classmethod
    def of(cls, check: MergeCheck, reject: MergeReject) -> FormattingRecovery:
        """Только от трёх источников и только для отказа «много эмодзи»: снять эмодзи вне маркеров, дважды
        нормализовать качество (сначала без названия и числа источников, затем с названием), построить диагностику
        заново и проверить снова. Текст не изменился — исходный отказ без строки лога."""
        if check.request.source_count < FORMATTING_RECOVERY_MIN_SOURCES:
            return cls(verdict=reject, actions=())
        if MergeRejectCode.EXCESSIVE_EMOJI_USAGE.value not in reject.reason_codes:
            return cls(verdict=reject, actions=())
        draft: FormattedDraft = FormattedDraft.of(check)
        if draft.description.text == check.description.text or not draft.actions:
            return cls(verdict=reject, actions=draft.actions)
        request: MergeCheckRequest = check.request
        normalization: QualityNormalization = QualityNormalization.of(
            draft.description, QualityRequest(language=request.label.language, title=request.title), check.lexicons
        )
        recovered: MergeCheck = MergeCheck.normalized(request, normalization, check.lexicons)
        outcome: FormattingRecovery = cls(verdict=recovered.run(), actions=draft.actions)
        outcome.event(check, reject, recovered.diagnostics.emoji_count).emit(LOGGER)
        return outcome

    @property
    def passed(self) -> MergeCheckPassed | None:
        return self.verdict if isinstance(self.verdict, MergeCheckPassed) else None

    @property
    def reject(self) -> MergeReject | None:
        return self.verdict if isinstance(self.verdict, MergeReject) else None

    @property
    def outcome(self) -> RecoveryOutcome:
        return RecoveryOutcome.APPLIED if self.passed is not None else RecoveryOutcome.REVEALED

    def event(self, check: MergeCheck, original: MergeReject, emoji_after: int) -> LogEvent:
        """Строка `merge_llm_validation_salvage`; при новом отказе — его коды."""
        salvage: LogEvent = check.request.label.event(AttemptEvent.SALVAGE).extended(
            outcome=self.outcome, reason_codes=original.reason_codes
        )
        if self.reject is not None:
            salvage = salvage.extended(replacement_reason_codes=self.reject.reason_codes)
        return salvage.extended(
            actions=self.actions, emoji_before=check.diagnostics.emoji_count, emoji_after=emoji_after
        )


@dataclass(frozen=True)
class AcceptedMerge:
    """Ответ модели принят: название, описание после проверки, диагностика, абзацы тела, восстанавливалось ли их число."""

    title: str = field(repr=False)
    description: MergedDescription
    diagnostics: MergeDiagnostics = field(repr=False)
    paragraph_count: int
    tail_recovery_applied: bool

    def extend(self, event: LogEvent) -> LogEvent:
        """Поля строки `merge_llm_response_valid` — длины и счётчики, без текста."""
        return event.extended(
            title_length=len(self.title),
            description_length=len(self.description.text),
            paragraph_count=self.paragraph_count,
            youtube_links_in_llm_output=self.description.youtube_link_count,
        )


@dataclass(frozen=True)
class RejectedMerge:
    """Ответ модели отвергнут: отказ и то, что нужно подсказке повтора, — описание попытки после нормализации
    (None — отвергнут ещё при разборе) и число пунктов по её диагностике (0 — до диагностики не дошло)."""

    reject: MergeReject
    description: MergedDescription | None = None
    bullet_count: int = 0

    @property
    def overloaded_count(self) -> int:
        """Перегруженных пунктов в отвергнутом описании; описания нет — 1."""
        if self.description is None or not self.description.text.strip():
            return OVERLOADED_COUNT_UNKNOWN
        return self.description.overloaded_bullet_count

    def facts(self, contract: MergeContract, source_count: int) -> RetryFacts:
        """Числа отвергнутой попытки для строк повтора; пределы — из контракта промта этой попытки."""
        return RetryFacts(
            source_count=source_count,
            actual_bullets=self.bullet_count,
            required_bullets=MergeContract.min_bullets(source_count),
            min_bullets=contract.bullet_range_min,
            max_bullets=contract.bullet_range_max,
            overloaded_count=self.overloaded_count,
            actual_paragraphs=(
                self.reject.paragraph_count if self.reject.paragraph_count is not None else OVERFLOW_PARAGRAPHS_UNKNOWN
            ),
            max_paragraphs=contract.max_body_paragraphs,
        )


@dataclass(frozen=True)
class MergeAttemptResult:
    """Итог одной попытки: метка, исход (принятый ответ, отказ или отказ нейросети), длина текста ответа модели
    (сам текст в лог не идёт) и пришёл ли он; у отказа нейросети ответа нет."""

    label: MergeAttemptLabel
    outcome: AcceptedMerge | RejectedMerge | LlmFailure
    raw_chars: int = 0
    raw_received: bool = False

    @property
    def accepted(self) -> AcceptedMerge | None:
        return self.outcome if isinstance(self.outcome, AcceptedMerge) else None

    @property
    def rejected(self) -> RejectedMerge | None:
        return self.outcome if isinstance(self.outcome, RejectedMerge) else None

    @property
    def failure(self) -> LlmFailure | None:
        return self.outcome if isinstance(self.outcome, LlmFailure) else None

    @property
    def is_quota(self) -> bool:
        """Квота нейросети исчерпана: дальше в этом запуске merge не делается."""
        return self.failure is not None and self.failure.kind is LlmErrorKind.QUOTA

    @property
    def is_model_configuration(self) -> bool:
        """Виновата настройка модели или ключа: повтор не поможет, merge останавливается до конца запуска."""
        return self.failure is not None and not self.is_quota and self.failure.is_model_configuration

    @property
    def code(self) -> str:
        """Главная причина неудачи: код отказа; отказ нейросети — его вид для квоты и настройки, иначе
        `unexpected_error`. У принятого ответа — пусто."""
        if self.rejected is not None:
            return self.rejected.reject.reason_code
        if self.failure is None:
            return ""
        return self.failure.kind.value if self.is_quota or self.is_model_configuration else UNEXPECTED_CODE

    @property
    def codes(self) -> tuple[str, ...]:
        """Все причины неудачи."""
        if self.rejected is not None:
            return self.rejected.reject.signals
        return (self.code,) if self.code else ()

    @property
    def is_recoverable(self) -> bool:
        """Отказ с повторяемой причиной: попыток становится три."""
        return self.rejected is not None and self.rejected.reject.is_recoverable

    def next_retry(self, contract: MergeContract, source_count: int, texts: MergePromptTexts) -> RetryProfile:
        """Профиль следующей попытки: после отказа — по его причинам и числам, после сбоя — обычный повтор."""
        if self.rejected is not None:
            return RetryProfile.after_reject(
                self.rejected.reject.signals, self.rejected.facts(contract, source_count), texts
            )
        return RetryProfile.standard(self.codes)

    @property
    def reason(self) -> str:
        """Причина для строки лога: подробность отказа или отказа нейросети без текста ответа, иначе код."""
        detail: str = ""
        if self.rejected is not None:
            detail = self.rejected.reject.detail
        elif self.failure is not None:
            detail = self.failure.detail
        return json.dumps(detail or self.code, ensure_ascii=False)

    def invalid_event(self, backend_name: str) -> LogEvent:
        """Строка `merge_llm_response_invalid`."""
        return self.label.event(AttemptEvent.RESPONSE_INVALID).extended(
            provider=backend_name,
            stage=STAGE_PRIMARY,
            code=self.code,
            raw_response_received=self.raw_received,
            reason=self.reason,
            raw_chars=self.raw_chars,
        )


@dataclass(frozen=True)
class MergeAttempt:
    """Одна попытка merge слота: промт (с профилем повтора или без), метка, источники слота, merge запуска."""

    prompt: MergePrompt
    label: MergeAttemptLabel
    sources: tuple[SourceVideo, ...] = field(repr=False)
    merge_run: MergeRun = field(repr=False)

    def run(self) -> MergeAttemptResult:
        """Запрос и все шаги попытки; отказ нейросети — итог с отказом нейросети, отказ на любом шаге — итог с отказом."""
        try:
            response: LlmResponse = self.merge_run.backend.complete(
                self.merge_run.request(self.prompt.text, self.label.request_label)
            )
        except LlmRequestError as error:
            return MergeAttemptResult(label=self.label, outcome=error.failure)
        parsed: MergeAnswer | MergeReject = MergeAnswer.parse(
            response, self.prompt.contract.max_body_paragraphs, self.merge_run.rules.lexicons.cta
        )
        outcome: AcceptedMerge | RejectedMerge = (
            RejectedMerge(parsed) if isinstance(parsed, MergeReject) else self._checked(parsed)
        )
        return MergeAttemptResult(self.label, outcome, len(response.text), bool(response.text.strip()))

    def _checked(self, answer: MergeAnswer) -> AcceptedMerge | RejectedMerge:
        """Починка алфавита, проверка с нормализацией и восстановление форматирования разобранного ответа."""
        request: MergeCheckRequest = MergeCheckRequest.of(self.label, answer.title, answer.description, self.sources)
        repair: HomoglyphRepair = HomoglyphRepair.of(answer.description, self.label.language)
        if repair.tokens_repaired > 0:
            repair.extend(self.label.event(AttemptEvent.SCRIPT_MIX_REPAIRED)).emit(LOGGER)
        check: MergeCheck = MergeCheck.of(request, repair.description, self.merge_run.rules.lexicons)
        for event in check.diagnostics.events(self.label):
            event.emit(LOGGER)
        verdict: MergeCheckPassed | MergeReject = check.run()
        if isinstance(verdict, MergeReject):
            verdict = FormattingRecovery.of(check, verdict).verdict
        if isinstance(verdict, MergeReject):
            return RejectedMerge(verdict, check.description, check.diagnostics.bullet_points_count)
        accepted: AcceptedMerge = AcceptedMerge(
            title=answer.title,
            description=verdict.description,
            diagnostics=verdict.diagnostics,
            paragraph_count=answer.paragraph_count,
            tail_recovery_applied=answer.tail_recovery_applied,
        )
        accepted.extend(self.label.event(AttemptEvent.RESPONSE_VALID)).emit(LOGGER)
        return accepted
