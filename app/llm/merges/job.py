"""Merge одного слота: попытки с повторами, итог — тексты слота (CLAUDE.md §3 шаг 5, §14 решение 23).

Перенесено из restreamer, поведение как есть:
- `pipeline\\slot_processing.py` (строки 225–400): merge только при двух и больше непустых описаниях источников, иначе —
  тексты источников (`merge_input_summary`, пропуск); merge уже остановлен — слот без запроса
  (`merge_branch_aborted_quota_exhausted`); принятое описание слота из нескольких источников выравнивается
  (`merge_service.py`, выравнивание абзацев после успеха; строка `merge_post_enforcement`);
- `merge_orchestrator.py::MergeOrchestrator.run`: две попытки, три — если хоть одна отвергнута по повторяемой причине;
  профиль повтора выбирает итог отвергнутой попытки (`MergeAttemptResult.next_retry`); квота — стоп слота и запуска;
  прочий сбой запроса — `unexpected_error` и обычный повтор; строки `merge_llm_primary_attempt`, `merge_llm_retry`,
  `merge_llm_response_invalid`, `merge_branch_ready`, `merge_provider_summary`, `merge_llm_final_failure` — ключи донора,
  контекст — `slot=<slot_id> language=<язык>` вместо `branch`, `date_key`, `slot_key`;
- `pipeline\\slot_processing.py` (строки 456–495) и `publish\\slot_publish_texts.py`: принятое описание проходит санацию
  (`publication.py::MergePublication`); блок с повтором абзацев или призывом в начале не публикуется — слот получает тексты
  источников, строка `merge_publish_gate_blocked` (`target=package`). Успех merge и настоящие блоки в счётчиках — по
  принятому ответу, как у донора: они считаются до санации.

Отличия от донора (решения Коворка к 3.13): виновата настройка модели — merge останавливается до конца запуска, слот
получает тексты источников (у донора исключение роняло весь прогон); предел абзацев тела и пределы пунктов в подсказке
повтора — из контракта промта этой попытки. Порядок источников в промте — порядок рядов группы: все источники слота имеют
одно время, поэтому ключ донора (время слота, номер ряда) даёт тот же порядок.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Final

from app.llm.merges.attempt import AcceptedMerge, MergeAttempt, MergeAttemptResult, MergeRules
from app.llm.merges.check import MergeAttemptLabel
from app.llm.merges.description import MergedDescription
from app.llm.merges.layout import DescriptionLayout
from app.llm.merges.prompt import MergePrompt, MergePromptRefusal
from app.llm.merges.publication import MergePublication
from app.llm.merges.retry import RetryProfile
from app.llm.merges.rules import (
    MIN_DESCRIBED_SOURCES,
    POST_ENFORCEMENT_MAX_BODY_PARAGRAPHS,
    PRIMARY_ATTEMPTS,
    PRIMARY_ATTEMPTS_EXTENDED,
)
from app.llm.merges.run import MergeRun, MergeStopReason
from app.observability.logging_setup import get_logger
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.texts.paragraphs import normalize_multiline_text

if TYPE_CHECKING:
    from app.slots.builder import SlotGroup
    from app.sources.video import SourceVideo

LOGGER: logging.Logger = get_logger("llm")

STAGE_PRIMARY: Final[str] = "primary"
NOT_APPLICABLE: Final[str] = "not_applicable"
EMPTY_DESCRIPTION_NOTE: Final[str] = "empty_description"
# С четырёх источников направленный повтор у донора называется «четыре и больше, со структурой».
STRUCTURED_RETRY_MIN_SOURCES: Final[int] = 4
RETRY_STRUCTURE_FOUR_PLUS: Final[str] = "four_plus_structured"
RETRY_STRUCTURE_STANDARD: Final[str] = "standard"
LOG_NONE: Final[str] = "none"
CODES_JOINER: Final[str] = ","
YES: Final[str] = "yes"
NO: Final[str] = "no"


def _flag(value: bool) -> str:
    return YES if value else NO


class MergeSkipReason(str, Enum):
    """Почему слот не отправлен модели."""

    INSUFFICIENT_DESCRIPTIONS = "insufficient_descriptions"    # непустых описаний меньше двух
    QUOTA_EXHAUSTED = "quota_exhausted"                        # merge запуска остановлен: квота
    MODEL_CONFIGURATION = "model_configuration"                # merge запуска остановлен: настройка модели

    @classmethod
    def of_stop(cls, reason: MergeStopReason) -> MergeSkipReason:
        return cls.QUOTA_EXHAUSTED if reason is MergeStopReason.QUOTA else cls.MODEL_CONFIGURATION

    @property
    def aborted_event(self) -> str:
        """Строка лога пропуска из-за остановки: у квоты — имя донора."""
        if self is MergeSkipReason.QUOTA_EXHAUSTED:
            return "merge_branch_aborted_quota_exhausted"
        return "merge_branch_aborted_model_error"


@dataclass(frozen=True)
class ParagraphEnforcement:
    """Выравнивание принятого описания (`MergeExecutor._enforce_description_structure` донора): тело и хвост заново,
    число абзацев тела — к пределу по умолчанию донора. Описание, число абзацев до и после, что произошло."""

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

    def log_line(self, context: str) -> str:
        """Строка `merge_post_enforcement` с ключами донора."""
        return (
            f"merge_post_enforcement {context} body_paragraphs_before={self.body_paragraphs_before} "
            f"body_paragraphs_after={self.body_paragraphs_after} mutated={_flag(self.mutated)} "
            f"recovery_applied={_flag(self.recovery_applied)} reason={self.note}"
        )


@dataclass
class AttemptHistory:
    """Попытки одного слота по порядку: сколько их можно и профиль следующего повтора."""

    results: list[MergeAttemptResult] = field(default_factory=list)
    max_attempts: int = PRIMARY_ATTEMPTS
    pending: RetryProfile = field(default_factory=RetryProfile.standard)

    def add(self, result: MergeAttemptResult, prompt: MergePrompt, rules: MergeRules) -> None:
        """Учесть попытку: после неудачи — профиль следующей; повторяемый отказ — попыток три."""
        self.results.append(result)
        if result.accepted is not None:
            return
        self.pending = result.next_retry(prompt.contract, len(prompt.sources), rules.texts)
        if result.is_recoverable:
            self.max_attempts = PRIMARY_ATTEMPTS_EXTENDED

    @property
    def next_number(self) -> int:
        return len(self.results) + 1

    @property
    def can_try(self) -> bool:
        last: MergeAttemptResult | None = self.last
        if last is not None and (last.accepted is not None or last.is_quota or last.is_model_configuration):
            return False
        return self.next_number <= self.max_attempts

    @property
    def next_retry(self) -> RetryProfile | None:
        """Профиль следующей попытки; у первой его нет."""
        return self.pending if self.results else None

    @property
    def last(self) -> MergeAttemptResult | None:
        return self.results[-1] if self.results else None

    @property
    def accepted(self) -> AcceptedMerge | None:
        last: MergeAttemptResult | None = self.last
        return last.accepted if last is not None else None

    @property
    def rejected_count(self) -> int:
        return sum(1 for result in self.results if result.rejected is not None)

    @property
    def last_answered(self) -> MergeAttemptResult | None:
        """Последняя отвергнутая попытка: её ответ модели донор помнит для строки итога (`last_raw_response`)."""
        answered: list[MergeAttemptResult] = [result for result in self.results if result.rejected is not None]
        return answered[-1] if answered else None


@dataclass(frozen=True)
class MergeOutcome:
    """Итог merge слота: тексты (модели или источников), попытки, причины последней неудачи, причина пропуска.

    `answer_accepted` — ответ модели принят проверкой (по нему, как у донора, считаются успех merge и настоящие блоки);
    `publish_blocked` — принятый ответ не прошёл проверку перед публикацией, и слот получил тексты источников.
    Тексты — ещё без правил площадки: подгонку под YouTube делает `SlotTexts.for_youtube` по месту сборки слота.
    """

    slot_id: str
    date: str
    language: str
    source_count: int
    texts: SlotTexts = field(repr=False)
    attempts: int = 0
    rejected_attempts: int = 0
    reject_codes: tuple[str, ...] = ()
    skipped_reason: MergeSkipReason | None = None
    paragraph_recoveries: int = 0
    answer_accepted: bool = False
    publish_blocked: bool = False

    @property
    def merged(self) -> bool:
        """Слот получил тексты модели (ответ принят и прошёл проверку перед публикацией)."""
        return self.texts.origin is SlotTextOrigin.MERGED

    @property
    def retries(self) -> int:
        return max(self.attempts - 1, 0)

    @property
    def is_final_failure(self) -> bool:
        """Модель спрашивали, а принятого ответа нет (блок перед публикацией — не провал merge, как у донора)."""
        return self.attempts > 0 and not self.answer_accepted

    @property
    def is_candidate(self) -> bool:
        """Слот, где merge был нужен (донор: `merge_candidate_blocks`): несколько источников и хватило описаний."""
        return self.source_count > 1 and self.skipped_reason is not MergeSkipReason.INSUFFICIENT_DESCRIPTIONS

    @property
    def log_line(self) -> str:
        """Строка `merge_attempt_outcome` — ключи донора плюс происхождение текстов и причины; без текстов."""
        return (
            f"merge_attempt_outcome slot={self.slot_id} language={self.language} source_count={self.source_count} "
            f"success={_flag(self.answer_accepted)} merge_success={int(self.answer_accepted)} "
            f"validation_rejected={self.rejected_attempts} retry_used={self.retries} "
            f"final_failure={int(self.is_final_failure)} publish_blocked={_flag(self.publish_blocked)} "
            f"texts={self.texts.origin.value} "
            f"reject_codes={CODES_JOINER.join(self.reject_codes) or LOG_NONE} "
            f"skipped={self.skipped_reason.value if self.skipped_reason is not None else LOG_NONE}"
        )


@dataclass(frozen=True)
class MergeJob:
    """Merge одного слота: группа источников и merge запуска (нейросеть, модель, настройки, правила, счётчики)."""

    group: SlotGroup
    merge_run: MergeRun = field(repr=False)

    @property
    def videos(self) -> tuple[SourceVideo, ...]:
        return self.group.videos

    @property
    def language(self) -> str:
        return self.group.key.language

    @property
    def slot_id(self) -> str:
        return self.group.key.slot_id

    @property
    def rules(self) -> MergeRules:
        return self.merge_run.rules

    @property
    def context(self) -> str:
        return f"slot={self.slot_id} language={self.language}"

    @property
    def descriptions(self) -> tuple[str, ...]:
        """Описания источников без краёв; видео без данных — пустое."""
        return tuple(video.metadata.description.strip() if video.metadata is not None else "" for video in self.videos)

    @property
    def described_sources(self) -> int:
        return sum(1 for description in self.descriptions if description)

    @property
    def skip_reason(self) -> MergeSkipReason | None:
        """Почему модель не спрашивается: мало описаний (раньше), merge запуска остановлен."""
        if self.described_sources < MIN_DESCRIBED_SOURCES:
            return MergeSkipReason.INSUFFICIENT_DESCRIPTIONS
        if self.merge_run.stop_reason is not None:
            return MergeSkipReason.of_stop(self.merge_run.stop_reason)
        return None

    def run(self) -> MergeOutcome:
        """Merge слота; итог учитывается в счётчиках запуска и пишется строкой лога."""
        LOGGER.info("%s", self.input_summary_line)
        outcome: MergeOutcome = self._outcome()
        self.merge_run.tally.record(outcome)
        LOGGER.info("%s", outcome.log_line)
        return outcome

    def _outcome(self) -> MergeOutcome:
        skip: MergeSkipReason | None = self.skip_reason
        if skip is not None:
            return self._skipped(skip)
        prompt: MergePrompt | MergePromptRefusal = MergePrompt.of(self.language, self.videos, self.rules.texts)
        if isinstance(prompt, MergePromptRefusal):
            return self._skipped(MergeSkipReason.INSUFFICIENT_DESCRIPTIONS)
        history: AttemptHistory = self._attempts(prompt)
        accepted: AcceptedMerge | None = history.accepted
        if accepted is None:
            return self._failed(history)
        return self._merged(history, accepted)

    def _attempts(self, prompt: MergePrompt) -> AttemptHistory:
        """Попытки до принятого ответа, остановки или исчерпания попыток."""
        history: AttemptHistory = AttemptHistory()
        while history.can_try:
            result: MergeAttemptResult = self._attempt(prompt, history)
            history.add(result, prompt, self.rules)
            if result.accepted is not None:
                break
            self._log_failed(result)
        return history

    def _attempt(self, prompt: MergePrompt, history: AttemptHistory) -> MergeAttemptResult:
        run: MergeRun = self.merge_run
        label: MergeAttemptLabel = MergeAttemptLabel(self.slot_id, self.language, run.model, history.next_number)
        LOGGER.info(
            "merge_llm_primary_attempt %s provider=%s stage=%s", label.prefix, run.backend.name, STAGE_PRIMARY
        )
        retry: RetryProfile | None = history.next_retry
        if retry is not None:
            LOGGER.info("%s", self._retry_line(label, retry))
            for line in prompt.log_lines:
                LOGGER.info("%s", line)
        attempt: MergeAttempt = MergeAttempt(
            prompt.with_retry(retry), label, self.videos, run.backend, run.settings, self.rules
        )
        return attempt.run()

    def _retry_line(self, label: MergeAttemptLabel, retry: RetryProfile) -> str:
        """Строка `merge_llm_retry` с ключами донора."""
        structured: bool = retry.enabled and len(self.videos) >= STRUCTURED_RETRY_MIN_SOURCES
        return (
            f"merge_llm_retry {label.prefix} provider={self.merge_run.backend.name} retry_mode={retry.mode.value} "
            f"retry_reason_codes={retry.reject_signal_label} retry_focus={retry.focus_label} "
            f"retry_structure={RETRY_STRUCTURE_FOUR_PLUS if structured else RETRY_STRUCTURE_STANDARD} "
            f"retry_source_count={len(self.videos)}"
        )

    def _log_failed(self, result: MergeAttemptResult) -> None:
        """Неудачная попытка: строка донора; квота или настройка модели останавливают merge запуска."""
        run: MergeRun = self.merge_run
        if result.is_model_configuration and result.error is not None:
            LOGGER.error(
                "merge_llm_fatal_model_error %s provider=%s %s", result.label.prefix, run.backend.name,
                result.error.log_line,
            )
            run.stop(MergeStopReason.MODEL)
            return
        LOGGER.info("%s", result.invalid_line(run.backend.name))
        if result.is_quota:
            run.stop(MergeStopReason.QUOTA)

    def _merged(self, history: AttemptHistory, accepted: AcceptedMerge) -> MergeOutcome:
        """Ответ принят: строки донора, выравнивание абзацев слота из нескольких источников, санация и проверка перед
        публикацией; блок не прошёл проверку — тексты источников и строка `merge_publish_gate_blocked`."""
        run: MergeRun = self.merge_run
        LOGGER.info("merge_branch_ready %s generator_model=%s", self.context, run.model)
        LOGGER.info(
            "merge_provider_summary provider=%s model=%s structured_ok=yes fallback_used=no parse_repair_used=no "
            "final_status=success", run.backend.name, run.model,
        )
        description: MergedDescription = accepted.description
        recoveries: int = int(accepted.tail_recovery_applied)
        if len(self.videos) > 1:
            enforcement: ParagraphEnforcement = ParagraphEnforcement.of(description)
            LOGGER.info("%s", enforcement.log_line(self.context))
            description = enforcement.description
            recoveries += int(enforcement.recovery_applied)
        publication: MergePublication = MergePublication.of(
            accepted.title, description.text, self.videos, self.language, self.rules
        )
        texts: SlotTexts | None = publication.slot_texts
        if texts is None:
            LOGGER.warning(
                "merge_publish_gate_blocked target=package %s has_publish_stage_duplicate=%s "
                "has_publish_stage_opener_cta=%s fallback=nomerge",
                self.context, _flag(publication.has_duplicate), _flag(publication.has_opener_cta),
            )
            texts = SlotTexts.from_sources(self.videos)
        return self._result(texts, history, recoveries, accepted=True, blocked=publication.is_blocked)

    def _failed(self, history: AttemptHistory) -> MergeOutcome:
        """Ответ не принят ни в одной попытке: строки донора, тексты источников."""
        run: MergeRun = self.merge_run
        last: MergeAttemptResult | None = history.last
        answered: MergeAttemptResult | None = history.last_answered
        LOGGER.warning(
            "merge_llm_final_failure %s provider=%s stage=%s code=%s fallback_used=no raw_response_received=%s "
            "reason=%s raw_chars=%d",
            self.context, run.backend.name, STAGE_PRIMARY, last.code if last is not None else LOG_NONE,
            _flag(answered is not None and answered.raw_received), last.reason if last is not None else LOG_NONE,
            answered.raw_chars if answered is not None else 0,
        )
        LOGGER.info(
            "merge_provider_summary provider=%s model=%s structured_ok=no fallback_used=no parse_repair_used=no "
            "final_status=failed", run.backend.name, run.model,
        )
        if run.stop_reason is not None:
            LOGGER.error("%s %s", MergeSkipReason.of_stop(run.stop_reason).aborted_event, self.context)
        return self._result(SlotTexts.from_sources(self.videos), history)

    def _skipped(self, reason: MergeSkipReason) -> MergeOutcome:
        """Модель не спрашивается: тексты источников; причина — строкой лога."""
        if reason is MergeSkipReason.INSUFFICIENT_DESCRIPTIONS:
            LOGGER.info(
                "merge_skipped %s non_empty_descriptions=%d reason=%s", self.context, self.described_sources, reason.value
            )
        else:
            LOGGER.error("%s %s", reason.aborted_event, self.context)
        return MergeOutcome(
            slot_id=self.slot_id,
            date=self.group.key.date_text,
            language=self.language,
            source_count=len(self.videos),
            texts=SlotTexts.from_sources(self.videos),
            reject_codes=(reason.value,) if reason is not MergeSkipReason.INSUFFICIENT_DESCRIPTIONS else (),
            skipped_reason=reason,
        )

    def _result(
        self,
        texts: SlotTexts,
        history: AttemptHistory,
        recoveries: int = 0,
        accepted: bool = False,
        blocked: bool = False,
    ) -> MergeOutcome:
        last: MergeAttemptResult | None = history.last
        return MergeOutcome(
            slot_id=self.slot_id,
            date=self.group.key.date_text,
            language=self.language,
            source_count=len(self.videos),
            texts=texts,
            attempts=len(history.results),
            rejected_attempts=history.rejected_count,
            reject_codes=last.codes if last is not None and not accepted else (),
            paragraph_recoveries=recoveries,
            answer_accepted=accepted,
            publish_blocked=blocked,
        )

    @property
    def input_summary_line(self) -> str:
        """Строка `merge_input_summary` донора — счётчики источников, без текста."""
        descriptions: tuple[str, ...] = self.descriptions
        titles: int = sum(
            1 for video in self.videos if video.metadata is not None and video.metadata.title.strip()
        )
        expected: bool = self.described_sources >= MIN_DESCRIBED_SOURCES
        return (
            f"merge_input_summary {self.context} source_count={len(self.videos)} "
            f"non_empty_descriptions={self.described_sources} titles_non_empty={titles} "
            f"source_desc_chars_total={sum(len(text) for text in descriptions)} "
            f"source_desc_chars_passed_to_llm={sum(len(normalize_multiline_text(text)) for text in descriptions)} "
            f"hard_truncation=disabled merge_expected={_flag(expected)} "
            f"merge_skip_reason={NOT_APPLICABLE if expected else MergeSkipReason.INSUFFICIENT_DESCRIPTIONS.value}"
        )
