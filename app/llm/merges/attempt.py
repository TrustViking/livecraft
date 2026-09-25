"""Одна попытка merge: запрос к модели → разбор → починка алфавита → нормализация → проверка (CLAUDE.md §14 решение 23).

Перенесено из restreamer, поведение как есть: `merge_executor.py::MergeExecutor.execute` (строки 91–305). Шаги строго
донорские: запрос со схемой ответа `merge_summary_v2` и температурой 0 → предварительная проверка переполнения абзацев и
разбор ответа (`MergeAnswer.parse`, предел абзацев — из контракта промта этой попытки, решение Коворка к 3.13) → ссылки
источников и ссылки ответа (`MergeCheckRequest.of`) → починка смешанного алфавита (строка `merge_script_mix_repaired`) →
нормализация качества с числом источников → диагностика (две строки стиля) → проверка покрытия с восстановлением
форматирования → строка `merge_llm_response_valid`. Строки донора о расхождении числа пунктов здесь нет: донор сравнивает
число пунктов текста с числом пунктов того же текста по тому же правилу, и расхождения не бывает.

Итог попытки — значение `MergeAttemptResult`: принятый ответ, отказ или сбой запроса. Сбой запроса — `LlmRequestError`,
его разъём бросает; попытка перехватывает только его и возвращает значением. Какой повтор следующий, решает сам итог
(`MergeAttemptResult.next_retry`): числа для подсказки модели берутся из отвергнутой попытки, а не нулём, как у донора.

Модель merge видит только через разъём `LlmBackend` (решение 22). Текста ответа и описаний в строках лога нет.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final

from app.llm.backend import LlmBackend, LlmRequest, LlmResponse
from app.llm.errors import LlmErrorKind, LlmRequestError
from app.llm.merges.answer import MergeAnswer
from app.llm.merges.check import MergeAttemptLabel, MergeCheck, MergeCheckPassed, MergeCheckRequest, MergeCheckRules
from app.llm.merges.contract import MergeContract
from app.llm.merges.description import HomoglyphRepair, MergedDescription
from app.llm.merges.prompt import MergePrompt
from app.llm.merges.prompt_texts import MergePromptTexts
from app.llm.merges.quality import QualityNormalization, QualityRequest
from app.llm.merges.reject import MergeReject, MergeRejectCode
from app.llm.merges.retry import RetryFacts, RetryProfile
from app.llm.merges.rules import MIN_BULLETS_EXTRA_OVER_SOURCES, MIN_BULLETS_FLOOR
from app.observability.logging_setup import get_logger
from app.texts.composer import PublishHeadings

if TYPE_CHECKING:
    from app.config.loader import LlmSettings
    from app.llm.merges.check import MergeDiagnostics
    from app.sources.language import TextLanguageDetector
    from app.sources.video import SourceVideo

LOGGER: logging.Logger = get_logger("llm")

# Схема ответа merge (донор: `MergeExecutor._STRUCTURED_SCHEMA`): ровно название до 99 знаков и описание.
MERGE_SCHEMA_NAME: Final[str] = "merge_summary_v2"
MERGE_RESPONSE_SCHEMA: Final[dict[str, Any]] = {
    "name": MERGE_SCHEMA_NAME,
    "schema": {
        "type": "object",
        "additionalProperties": False,
        "required": ["title", "description"],
        "properties": {
            "title": {"type": "string", "minLength": 1, "maxLength": 99},
            "description": {"type": "string", "minLength": 1},
        },
    },
}
REQUEST_LABEL: Final[str] = "merge_{language}_primary_{attempt}"
# Сбой запроса, который не квота и не настройка модели: код донора «неожиданная ошибка», повтор — обычный.
UNEXPECTED_CODE: Final[str] = MergeRejectCode.UNEXPECTED.value
# Перегруженных пунктов, когда описания отвергнутой попытки нет, и абзацев перебора, когда число не известно (донор).
OVERLOADED_COUNT_UNKNOWN: Final[int] = 1
OVERFLOW_PARAGRAPHS_UNKNOWN: Final[int] = 8
STAGE_PRIMARY: Final[str] = "primary"
YES: Final[str] = "yes"
NO: Final[str] = "no"


def _flag(value: bool) -> str:
    return YES if value else NO


@dataclass(frozen=True)
class MergeRules:
    """Всё, чем пользуется merge, одним объектом на запуск: правила проверки (в них правила качества, призывы,
    негодный тезис и подсказки официальных ссылок), тексты промта и заголовки блоков описания для санации."""

    check: MergeCheckRules
    texts: MergePromptTexts
    headings: PublishHeadings

    @classmethod
    def load(cls, detector: TextLanguageDetector | None = None) -> MergeRules:
        return cls(check=MergeCheckRules.load(detector), texts=MergePromptTexts.load(), headings=PublishHeadings.load())


@dataclass(frozen=True)
class AcceptedMerge:
    """Ответ модели принят: название, описание после проверки, диагностика, абзацы тела, восстанавливалось ли их число."""

    title: str = field(repr=False)
    description: MergedDescription
    diagnostics: MergeDiagnostics = field(repr=False)
    paragraph_count: int
    tail_recovery_applied: bool

    @property
    def log_fields(self) -> str:
        """Поля строки `merge_llm_response_valid` донора — длины и счётчики, без текста."""
        return (
            f"title_length={len(self.title)} description_length={len(self.description.text)} "
            f"paragraph_count={self.paragraph_count} youtube_links_in_llm_output={self.description.youtube_link_count}"
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
        """Перегруженных пунктов в отвергнутом описании; описания нет — 1 (донор)."""
        if self.description is None or not self.description.text.strip():
            return OVERLOADED_COUNT_UNKNOWN
        return self.description.overloaded_bullet_count

    def facts(self, contract: MergeContract, source_count: int) -> RetryFacts:
        """Числа отвергнутой попытки для строк повтора; пределы — из контракта промта этой попытки."""
        return RetryFacts(
            source_count=source_count,
            actual_bullets=self.bullet_count,
            required_bullets=max(source_count + MIN_BULLETS_EXTRA_OVER_SOURCES, MIN_BULLETS_FLOOR),
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
    """Итог одной попытки: ровно одно из `accepted`, `rejected`, `error`. `raw_chars` — длина текста ответа модели
    (сам текст в лог не идёт); сбой запроса ответа не имеет."""

    label: MergeAttemptLabel
    raw_chars: int = 0
    raw_received: bool = False
    accepted: AcceptedMerge | None = None
    rejected: RejectedMerge | None = None
    error: LlmRequestError | None = None

    @property
    def is_quota(self) -> bool:
        """Квота нейросети исчерпана: дальше в этом запуске merge не делается."""
        return self.error is not None and self.error.kind is LlmErrorKind.QUOTA

    @property
    def is_model_configuration(self) -> bool:
        """Виновата настройка модели или ключа: повтор не поможет, merge останавливается до конца запуска."""
        return self.error is not None and not self.is_quota and self.error.is_model_configuration

    @property
    def code(self) -> str:
        """Главная причина неудачи: код отказа; сбой запроса — его вид для квоты и настройки, иначе
        `unexpected_error` (донор). У принятого ответа — пусто."""
        if self.rejected is not None:
            return self.rejected.reject.reason_code
        if self.error is None:
            return ""
        return self.error.kind.value if self.is_quota or self.is_model_configuration else UNEXPECTED_CODE

    @property
    def codes(self) -> tuple[str, ...]:
        """Все причины неудачи (донор: `last_reason_codes`)."""
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
        """Причина для строки лога: подробность отказа или сбоя без текста ответа, иначе код."""
        detail: str = ""
        if self.rejected is not None:
            detail = self.rejected.reject.detail
        elif self.error is not None:
            detail = self.error.detail
        return json.dumps(detail or self.code, ensure_ascii=False)

    def invalid_line(self, backend_name: str) -> str:
        """Строка `merge_llm_response_invalid` с ключами донора."""
        return (
            f"merge_llm_response_invalid {self.label.prefix} provider={backend_name} stage={STAGE_PRIMARY} "
            f"code={self.code} raw_response_received={_flag(self.raw_received)} reason={self.reason} "
            f"raw_chars={self.raw_chars}"
        )


@dataclass(frozen=True)
class MergeAttempt:
    """Одна попытка merge слота: промт (с профилем повтора или без), метка, источники слота, нейросеть, настройки, правила."""

    prompt: MergePrompt
    label: MergeAttemptLabel
    sources: tuple[SourceVideo, ...] = field(repr=False)
    backend: LlmBackend = field(repr=False)
    settings: LlmSettings = field(repr=False)
    rules: MergeRules = field(repr=False)

    @property
    def request(self) -> LlmRequest:
        """Запрос попытки: промт, модель метки, предел ответа и ожидание из настроек, схема merge, температура 0."""
        label: str = REQUEST_LABEL.format(language=self.label.language, attempt=self.label.attempt)
        return LlmRequest.from_settings(self.settings, self.label.model, self.prompt.text, label, MERGE_RESPONSE_SCHEMA)

    def run(self) -> MergeAttemptResult:
        """Запрос и все шаги донора; сбой запроса — итог со сбоем, отказ на любом шаге — итог с отказом."""
        try:
            response: LlmResponse = self.backend.complete(self.request)
        except LlmRequestError as error:
            return MergeAttemptResult(label=self.label, error=error)
        parsed: MergeAnswer | MergeReject = MergeAnswer.parse(
            response, self.prompt.contract.max_body_paragraphs, self.rules.check.quality.cta
        )
        result: MergeAttemptResult = MergeAttemptResult(
            label=self.label, raw_chars=len(response.text), raw_received=bool(response.text.strip())
        )
        if isinstance(parsed, MergeReject):
            return replace(result, rejected=RejectedMerge(parsed))
        return self._checked(parsed, result)

    def _checked(self, answer: MergeAnswer, result: MergeAttemptResult) -> MergeAttemptResult:
        """Починка алфавита, нормализация, диагностика и проверка разобранного ответа."""
        request: MergeCheckRequest = MergeCheckRequest.of(
            self.label, answer.title, answer.description, self.sources, self.rules.check
        )
        repair: HomoglyphRepair = answer.description.with_homoglyphs_repaired(self.label.language)
        if repair.tokens_repaired > 0:
            LOGGER.info("merge_script_mix_repaired %s %s", self.label.prefix, repair.log_line)
        normalization: QualityNormalization = repair.description.quality_normalized(
            QualityRequest(language=self.label.language, title=answer.title, source_count=len(self.sources)),
            self.rules.check.quality,
        )
        check: MergeCheck = MergeCheck.of(request, normalization, self.rules.check)
        self._log_diagnostics(check)
        verdict: MergeCheckPassed | MergeReject = check.run_with_recovery()
        if isinstance(verdict, MergeReject):
            rejected: RejectedMerge = RejectedMerge(verdict, check.description, check.diagnostics.bullet_points_count)
            return replace(result, rejected=rejected)
        accepted: AcceptedMerge = AcceptedMerge(
            title=answer.title,
            description=verdict.description,
            diagnostics=verdict.diagnostics,
            paragraph_count=answer.paragraph_count,
            tail_recovery_applied=answer.tail_recovery_applied,
        )
        LOGGER.info("merge_llm_response_valid %s %s", self.label.prefix, accepted.log_fields)
        return replace(result, accepted=accepted)

    def _log_diagnostics(self, check: MergeCheck) -> None:
        """Строки стиля и semantic gate."""
        for line in check.diagnostics.log_lines(self.label):
            LOGGER.info("%s", line)

