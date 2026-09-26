"""Итог merge одного слота: попытки по порядку и то, что из них вышло (CLAUDE.md §3 шаг 5, §14 решение 23).

`AttemptHistory` — попытки слота: сколько их можно (две, три — если хоть одна отвергнута по повторяемой причине) и
профиль следующего повтора, который выбирает итог отвергнутой попытки. `MergeOutcome` — итог слота поверх истории:
тексты (модели или источников), причина, по которой merge не делался, восстановления абзацев, блок перед публикацией;
отсюда — строка `merge_attempt_outcome` и счёт слота для счётчиков запуска (`SlotCount`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.llm.merges.attempt import AcceptedMerge, MergeAttemptResult
from app.llm.merges.merge_rules import MergeRules
from app.llm.merges.prompt import MergePrompt
from app.llm.merges.retry import RetryProfile
from app.llm.merges.rules import PRIMARY_ATTEMPTS, PRIMARY_ATTEMPTS_EXTENDED
from app.llm.merges.run import MergeStopReason, SlotCount
from app.observability.log_event import LogEvent
from app.slots.slot import SlotKey
from app.slots.texts import SlotTextOrigin, SlotTexts


class OutcomeEvent(str, Enum):
    """События итога слота в логе."""

    OUTCOME = "merge_attempt_outcome"


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
        """Последняя отвергнутая попытка: её ответ модели помнит строка итога слота."""
        answered: list[MergeAttemptResult] = [result for result in self.results if result.rejected is not None]
        return answered[-1] if answered else None


@dataclass(frozen=True)
class MergeOutcome:
    """Итог merge слота: ключ, число источников, тексты (модели или источников), попытки, почему merge не делался,
    восстановления абзацев, блок перед публикацией.

    `answer_accepted` — ответ модели принят проверкой (по нему считаются успех merge и настоящие блоки);
    `publish_blocked` — принятый ответ не прошёл проверку перед публикацией, и слот получил тексты источников.
    Тексты — ещё без правил площадки: подгонку под YouTube делает `SlotTexts.for_youtube` по месту сборки слота.
    """

    key: SlotKey
    source_count: int
    texts: SlotTexts = field(repr=False)
    history: AttemptHistory = field(default_factory=AttemptHistory, repr=False)
    skipped_reason: MergeStopReason | None = None
    paragraph_recoveries: int = 0
    publish_blocked: bool = False

    @property
    def attempts(self) -> int:
        return len(self.history.results)

    @property
    def rejected_attempts(self) -> int:
        return self.history.rejected_count

    @property
    def answer_accepted(self) -> bool:
        return self.history.accepted is not None

    @property
    def reject_codes(self) -> tuple[str, ...]:
        """Причины последней неудачи; merge остановлен до конца запуска — причина остановки; мало описаний — пусто."""
        if self.skipped_reason is not None:
            return (self.skipped_reason.value,) if self.skipped_reason.stops_the_run else ()
        last: MergeAttemptResult | None = self.history.last
        return last.codes if last is not None and not self.answer_accepted else ()

    @property
    def merged(self) -> bool:
        """Слот получил тексты модели (ответ принят и прошёл проверку перед публикацией)."""
        return self.texts.origin is SlotTextOrigin.MERGED

    @property
    def retries(self) -> int:
        return max(self.attempts - 1, 0)

    @property
    def is_final_failure(self) -> bool:
        """Модель спрашивали, а принятого ответа нет (блок перед публикацией — не провал merge)."""
        return self.attempts > 0 and not self.answer_accepted

    @property
    def is_candidate(self) -> bool:
        """Слот, где merge был нужен: несколько источников и хватило описаний."""
        return self.source_count > 1 and self.skipped_reason is not MergeStopReason.INSUFFICIENT_DESCRIPTIONS

    @property
    def count(self) -> SlotCount:
        """Что итог добавляет к счётчикам запуска."""
        return SlotCount(
            date=self.key.date_text,
            answer_accepted=self.answer_accepted,
            rejected_attempts=self.rejected_attempts,
            retries=self.retries,
            final_failure=self.is_final_failure,
            paragraph_recoveries=self.paragraph_recoveries,
            is_candidate=self.is_candidate,
        )

    @property
    def event(self) -> LogEvent:
        """Строка `merge_attempt_outcome`: счётчики, происхождение текстов и причины; без текстов."""
        counts: LogEvent = LogEvent.of(
            OutcomeEvent.OUTCOME,
            slot=self.key.slot_id,
            language=self.key.language,
            source_count=self.source_count,
            success=self.answer_accepted,
            merge_success=int(self.answer_accepted),
            validation_rejected=self.rejected_attempts,
        )
        return counts.extended(
            retry_used=self.retries,
            final_failure=int(self.is_final_failure),
            publish_blocked=self.publish_blocked,
            texts=self.texts.origin,
            reject_codes=self.reject_codes,
            skipped=self.skipped_reason,
        )
