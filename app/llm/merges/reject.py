"""Отказ ответа модели на merge: код причины и подробность — значение, а не исключение (CLAUDE.md §14 решение 23).

Код ставится в момент отказа. Что код значит для программы, записано одной таблицей признаков `REJECT_TRAITS`:
на каком шаге он выдаётся (разбор ответа, проверка описания или оба), относится ли он к проверке описания
(такие причины идут отдельным списком `reason_codes`) и может ли помочь повтор с подсказкой модели.

Отказ semantic gate несёт коды гейта (`MergeReject.validation_codes`) как есть: первый из них — главная причина.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final

from app.core.errors import DETAIL_MAX_CHARS
from app.llm.merges import rules
from app.observability.log_event import LogEvent, Quoted
from app.ui.messages import msg

PARAGRAPH_COUNT_DETAIL: Final[str] = "body_paragraphs={count} allowed={low}..{high}"


class MergeRejectStage(str, Enum):
    """Шаг, на котором ответ модели отвергается."""

    ANSWER = "answer"       # разбор ответа модели — `answer.py::MergeAnswer.parse`
    CHECK = "check"         # проверка описания — `check.py::MergeCheck`, `FormattingRecovery`


class MergeRejectCode(str, Enum):
    """Почему ответ модели не принят. Значение — код причины в логе и ключ строк повтора."""

    NOT_JSON_OBJECT = "not_json_object"
    MISSING_KEYS = "missing_keys"
    EXTRA_KEYS = "extra_keys"
    INVALID_TITLE = "invalid_title"
    INVALID_DESCRIPTION = "invalid_description"
    CTA_AS_FIRST_PARAGRAPH = "cta_as_first_paragraph"
    DUPLICATE_PARAGRAPH = "duplicate_paragraph"
    DESCRIPTION_EMPTY = "empty"                  # после снятия строк «title:» и подобных не осталось текста
    PARAGRAPH_UNDERFLOW = "paragraph_underflow"
    PARAGRAPH_OVERFLOW = "paragraph_overflow"
    # Проверка покрытия (`check.py::MergeCheck`), в порядке проверок.
    PER_SOURCE_ENUMERATION = "per_source_enumeration"
    HOOK_ECHO_IN_BODY = "hook_echo_in_body"
    CTA_IN_HOOK = "cta_in_hook"
    INSUFFICIENT_BULLET_COVERAGE = "insufficient_bullet_coverage"
    COMPACT_BULLET_OVERFLOW = "compact_bullet_overflow"
    EXCESSIVE_EMOJI_USAGE = "excessive_emoji_usage"
    OVERLOADED_BULLET = "overloaded_bullet"
    NUMBERED_TITLE_DUMP = "numbered_title_dump"
    # Semantic gate качества описания: настоящие причины — в `MergeReject.validation_codes`.
    SEMANTIC_GATE = "semantic_gate"
    # Название или описание — список или объект JSON; подробность (`invalid_type:<ключ>`) — в `MergeReject.detail`.
    UNEXPECTED = "unexpected_error"

    @classmethod
    def of(cls, value: str) -> MergeRejectCode | None:
        """Код по значению; коды гейта и виды сбоя запроса — не коды отказа: None."""
        return next((code for code in cls if code.value == value), None)

    @property
    def traits(self) -> RejectTraits:
        return REJECT_TRAITS[self]

    @property
    def is_recoverable(self) -> bool:
        """Повтор с подсказкой модели может помочь."""
        return self.traits.is_recoverable

    @property
    def is_description_validation(self) -> bool:
        """Отказ проверки описания: такие причины идут отдельным списком `reason_codes`."""
        return self.traits.is_description_validation

    @property
    def stages(self) -> frozenset[MergeRejectStage]:
        """Шаги, которые выдают этот код; призыв в начале и повтор абзацев выдают оба."""
        return self.traits.stages

    @property
    def human(self) -> str:
        return msg.MERGE_REJECT_TEXT[self.value]


@dataclass(frozen=True)
class RejectTraits:
    """Что код отказа значит для программы: шаги, которые его выдают; причина ли это проверки описания;
    может ли помочь повтор с подсказкой."""

    stages: frozenset[MergeRejectStage]
    is_description_validation: bool
    is_recoverable: bool


_ANSWER: Final[frozenset[MergeRejectStage]] = frozenset({MergeRejectStage.ANSWER})
_CHECK: Final[frozenset[MergeRejectStage]] = frozenset({MergeRejectStage.CHECK})
_BOTH: Final[frozenset[MergeRejectStage]] = frozenset({MergeRejectStage.ANSWER, MergeRejectStage.CHECK})
# Единственное место, где записаны признаки кодов; полноту каждого шага держит свой тест.
REJECT_TRAITS: Final[Mapping[MergeRejectCode, RejectTraits]] = MappingProxyType(
    {
        MergeRejectCode.NOT_JSON_OBJECT: RejectTraits(_ANSWER, False, False),
        MergeRejectCode.MISSING_KEYS: RejectTraits(_ANSWER, False, False),
        MergeRejectCode.EXTRA_KEYS: RejectTraits(_ANSWER, False, False),
        MergeRejectCode.INVALID_TITLE: RejectTraits(_ANSWER, False, False),
        MergeRejectCode.INVALID_DESCRIPTION: RejectTraits(_ANSWER, False, False),
        MergeRejectCode.CTA_AS_FIRST_PARAGRAPH: RejectTraits(_BOTH, True, True),
        MergeRejectCode.DUPLICATE_PARAGRAPH: RejectTraits(_BOTH, True, True),
        MergeRejectCode.DESCRIPTION_EMPTY: RejectTraits(_ANSWER, True, False),
        MergeRejectCode.PARAGRAPH_UNDERFLOW: RejectTraits(_ANSWER, False, True),
        MergeRejectCode.PARAGRAPH_OVERFLOW: RejectTraits(_ANSWER, False, True),
        MergeRejectCode.PER_SOURCE_ENUMERATION: RejectTraits(_CHECK, True, False),
        MergeRejectCode.HOOK_ECHO_IN_BODY: RejectTraits(_CHECK, True, True),
        MergeRejectCode.CTA_IN_HOOK: RejectTraits(_CHECK, True, True),
        MergeRejectCode.INSUFFICIENT_BULLET_COVERAGE: RejectTraits(_CHECK, True, False),
        MergeRejectCode.COMPACT_BULLET_OVERFLOW: RejectTraits(_CHECK, True, True),
        MergeRejectCode.EXCESSIVE_EMOJI_USAGE: RejectTraits(_CHECK, True, False),
        MergeRejectCode.OVERLOADED_BULLET: RejectTraits(_CHECK, True, True),
        MergeRejectCode.NUMBERED_TITLE_DUMP: RejectTraits(_CHECK, True, False),
        MergeRejectCode.SEMANTIC_GATE: RejectTraits(_CHECK, True, False),
        MergeRejectCode.UNEXPECTED: RejectTraits(_ANSWER, False, False),
    }
)


@dataclass(frozen=True)
class MergeReject:
    """Ответ модели не принят. `detail` — подробность для лога (какие ключи, сколько абзацев), без текста ответа.

    `validation_codes` — причины, которые у отказа свои, а не из его кода: коды semantic gate.
    `paragraph_count` — сколько абзацев тела насчитал отказ по числу абзацев (недобор, перебор); у прочих None.
    Повтор после перебора называет модели это число.
    """

    code: MergeRejectCode
    detail: str = ""
    validation_codes: tuple[str, ...] = ()
    paragraph_count: int | None = field(default=None, compare=False)

    @classmethod
    def semantic_gate(cls, gate_codes: Sequence[str]) -> MergeReject:
        """Отказ semantic gate: коды гейта как пришли; кодов нет — общий `semantic_gate`."""
        codes: tuple[str, ...] = tuple(gate_codes)
        return cls(MergeRejectCode.SEMANTIC_GATE, validation_codes=codes or (MergeRejectCode.SEMANTIC_GATE.value,))

    @classmethod
    def of_paragraph_count(cls, count: int, max_body_paragraphs: int) -> MergeReject:
        """Абзацев тела меньше двух — недобор, больше предела — перебор; число абзацев — в отказе."""
        code: MergeRejectCode = (
            MergeRejectCode.PARAGRAPH_UNDERFLOW
            if count < rules.MIN_BODY_PARAGRAPHS
            else MergeRejectCode.PARAGRAPH_OVERFLOW
        )
        detail: str = PARAGRAPH_COUNT_DETAIL.format(count=count, low=rules.MIN_BODY_PARAGRAPHS, high=max_body_paragraphs)
        return cls(code, detail, paragraph_count=count)

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """Причины проверки описания; у прочих отказов список пуст."""
        if self.validation_codes:
            return self.validation_codes
        return (self.code.value,) if self.code.is_description_validation else ()

    @property
    def reason_code(self) -> str:
        """Главная причина: первая причина проверки описания, иначе код отказа."""
        codes: tuple[str, ...] = self.reason_codes
        return codes[0] if codes else self.code.value

    @property
    def signals(self) -> tuple[str, ...]:
        """Причины, по которым выбирается повтор и решается его повторяемость: причины проверки описания, а если их
        нет — главная причина."""
        return self.reason_codes or (self.reason_code,)

    @property
    def is_recoverable(self) -> bool:
        """Повтор с подсказкой может помочь: хотя бы одна причина — повторяемый код отказа."""
        codes: tuple[MergeRejectCode | None, ...] = tuple(MergeRejectCode.of(signal) for signal in self.signals)
        return any(code is not None and code.is_recoverable for code in codes)

    @property
    def human(self) -> str:
        return self.code.human

    def extend(self, event: LogEvent) -> LogEvent:
        """Событие с полями отказа: главная причина, причины проверки, повторяемость и подробность в кавычках JSON."""
        detail: str = self.detail[:DETAIL_MAX_CHARS]
        return event.extended(
            reason_code=self.reason_code,
            reason_codes=self.reason_codes,
            recoverable=self.is_recoverable,
            detail=Quoted(detail),
        )
