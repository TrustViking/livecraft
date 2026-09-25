"""Отказ ответа модели на merge: код причины и подробность — значение, а не исключение (CLAUDE.md §14 решение 23).

У донора причина закодирована текстом исключения и разбирается обратно по подстрокам
(`merge_validation.py::_reason_code_from_error`, `_reason_codes_from_error`). Здесь код ставится в момент отказа;
значения кодов — ровно те `reason_code`, которые донорский разбор даёт на путях разбора ответа и проверки покрытия
(`merge_validation.py::_validate_coverage_preserving_merge_or_raise`), — это держит сверка с донором.

Отказ semantic gate несёт коды гейта (`MergeReject.validation_codes`) после нормализации донора
(`_normalize_description_validation_reason_codes`): первый из них — `reason_code` донора.
"""
from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Final

from app.ui import messages_ru as msg

# Повторяемые причины донора (`merge_constants.py::RECOVERABLE_REJECT_CODES`) целиком: часть их даёт разбор ответа,
# остальные — проверка покрытия (`check.py`).
RECOVERABLE_REJECT_CODES: Final[frozenset[str]] = frozenset(
    {
        "overloaded_bullet",
        "compact_bullet_overflow",
        "duplicate_paragraph",
        "hook_echo_in_body",
        "cta_as_first_paragraph",
        "cta_in_hook",
        "paragraph_underflow",
        "paragraph_overflow",
    }
)
# Коды гейта, которые донор сводит к общим (`_normalize_description_validation_reason_code`).
SOURCE_COVERAGE_CODE_PATTERN: Final[re.Pattern[str]] = re.compile(r"semantic_source_\d+_coverage_missing")
WEAK_SOURCE_COVERAGE: Final[str] = "weak_source_coverage"
VALIDATION_CODE_ALIASES: Final[dict[str, str]] = {
    "semantic_source_grounding_too_low": WEAK_SOURCE_COVERAGE,
    "semantic_too_generic": "overly_generic_body",
}
LOG_NONE: Final[str] = "-"
CODES_JOINER: Final[str] = ","
DETAIL_MAX_CHARS: Final[int] = 200


class MergeRejectStage(str, Enum):
    """Шаг, на котором ответ модели отвергается."""

    ANSWER = "answer"       # разбор ответа модели — `answer.py::MergeAnswer.parse`
    CHECK = "check"         # проверка описания — `check.py::MergeCheck`, `FormattingRecovery`


class MergeRejectCode(str, Enum):
    """Почему ответ модели не принят. Значения — `reason_code` донора."""

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
    # Проверка покрытия (`check.py::MergeCheck`), порядок — донорский порядок проверок.
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
    # Название или описание — список или объект JSON. Донорский разбор текста отказа не узнаёт эту причину
    # и отдаёт общий код; код сохранён, подробность (`invalid_type:<ключ>`) — в `MergeReject.detail`.
    UNEXPECTED = "unexpected_error"

    @property
    def is_recoverable(self) -> bool:
        """Повтор с подсказкой модели может помочь (донор: `RECOVERABLE_REJECT_CODES`)."""
        return self.value in RECOVERABLE_REJECT_CODES

    @property
    def is_description_validation(self) -> bool:
        """Отказ проверки описания: у донора такие причины идут отдельным списком `reason_codes`."""
        return self in _DESCRIPTION_VALIDATION_CODES

    @property
    def stages(self) -> frozenset[MergeRejectStage]:
        """Шаги, которые выдают этот код (`CODE_STAGES`); призыв в начале и повтор абзацев выдают оба."""
        return CODE_STAGES.get(self, frozenset())

    @property
    def human(self) -> str:
        return msg.MERGE_REJECT_TEXT[self.value]


_ANSWER: Final[frozenset[MergeRejectStage]] = frozenset({MergeRejectStage.ANSWER})
_CHECK: Final[frozenset[MergeRejectStage]] = frozenset({MergeRejectStage.CHECK})
_BOTH: Final[frozenset[MergeRejectStage]] = frozenset({MergeRejectStage.ANSWER, MergeRejectStage.CHECK})
# Единственное место, где записано, какой шаг какой код выдаёт; полноту каждого шага держит свой тест.
CODE_STAGES: Final[Mapping[MergeRejectCode, frozenset[MergeRejectStage]]] = MappingProxyType(
    {
        MergeRejectCode.NOT_JSON_OBJECT: _ANSWER,
        MergeRejectCode.MISSING_KEYS: _ANSWER,
        MergeRejectCode.EXTRA_KEYS: _ANSWER,
        MergeRejectCode.INVALID_TITLE: _ANSWER,
        MergeRejectCode.INVALID_DESCRIPTION: _ANSWER,
        MergeRejectCode.CTA_AS_FIRST_PARAGRAPH: _BOTH,
        MergeRejectCode.DUPLICATE_PARAGRAPH: _BOTH,
        MergeRejectCode.DESCRIPTION_EMPTY: _ANSWER,
        MergeRejectCode.PARAGRAPH_UNDERFLOW: _ANSWER,
        MergeRejectCode.PARAGRAPH_OVERFLOW: _ANSWER,
        MergeRejectCode.PER_SOURCE_ENUMERATION: _CHECK,
        MergeRejectCode.HOOK_ECHO_IN_BODY: _CHECK,
        MergeRejectCode.CTA_IN_HOOK: _CHECK,
        MergeRejectCode.INSUFFICIENT_BULLET_COVERAGE: _CHECK,
        MergeRejectCode.COMPACT_BULLET_OVERFLOW: _CHECK,
        MergeRejectCode.EXCESSIVE_EMOJI_USAGE: _CHECK,
        MergeRejectCode.OVERLOADED_BULLET: _CHECK,
        MergeRejectCode.NUMBERED_TITLE_DUMP: _CHECK,
        MergeRejectCode.SEMANTIC_GATE: _CHECK,
        MergeRejectCode.UNEXPECTED: _ANSWER,
    }
)

_DESCRIPTION_VALIDATION_CODES: Final[frozenset[MergeRejectCode]] = frozenset(
    {
        MergeRejectCode.CTA_AS_FIRST_PARAGRAPH,
        MergeRejectCode.DUPLICATE_PARAGRAPH,
        MergeRejectCode.DESCRIPTION_EMPTY,
        MergeRejectCode.PER_SOURCE_ENUMERATION,
        MergeRejectCode.HOOK_ECHO_IN_BODY,
        MergeRejectCode.CTA_IN_HOOK,
        MergeRejectCode.INSUFFICIENT_BULLET_COVERAGE,
        MergeRejectCode.COMPACT_BULLET_OVERFLOW,
        MergeRejectCode.EXCESSIVE_EMOJI_USAGE,
        MergeRejectCode.OVERLOADED_BULLET,
        MergeRejectCode.NUMBERED_TITLE_DUMP,
        MergeRejectCode.SEMANTIC_GATE,
    }
)


@dataclass(frozen=True)
class MergeReject:
    """Ответ модели не принят. `detail` — подробность для лога (какие ключи, сколько абзацев), без текста ответа.

    `validation_codes` — причины, которые у отказа свои, а не из его кода: коды semantic gate после нормализации.
    `paragraph_count` — сколько абзацев тела насчитал отказ по числу абзацев (недобор, перебор); у прочих None.
    Повтор после перебора называет модели это число (у донора — разбором «got N» из текста исключения).
    """

    code: MergeRejectCode
    detail: str = ""
    validation_codes: tuple[str, ...] = ()
    paragraph_count: int | None = field(default=None, compare=False)

    @classmethod
    def semantic_gate(cls, gate_codes: Sequence[str]) -> MergeReject:
        """Отказ semantic gate: коды гейта нормализованы как у донора; кодов нет — общий `semantic_gate`."""
        codes: tuple[str, ...] = cls.normalized_validation_codes(gate_codes)
        return cls(MergeRejectCode.SEMANTIC_GATE, validation_codes=codes or (MergeRejectCode.SEMANTIC_GATE.value,))

    @staticmethod
    def normalized_validation_codes(codes: Sequence[str]) -> tuple[str, ...]:
        """Коды проверки описания без краёв и пустых, частные — общими (`weak_source_coverage`,
        `overly_generic_body`), без повторов, в исходном порядке."""
        normalized: list[str] = []
        for raw_code in codes:
            code: str = str(raw_code or "").strip()
            if SOURCE_COVERAGE_CODE_PATTERN.fullmatch(code):
                code = WEAK_SOURCE_COVERAGE
            code = VALIDATION_CODE_ALIASES.get(code, code)
            if code and code not in normalized:
                normalized.append(code)
        return tuple(normalized)

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """Причины проверки описания — как `_reason_codes_from_error` донора; у прочих отказов список пуст."""
        if self.validation_codes:
            return self.validation_codes
        return (self.code.value,) if self.code.is_description_validation else ()

    @property
    def reason_code(self) -> str:
        """Главная причина — `reason_code` донора: первая причина проверки описания, иначе код отказа."""
        codes: tuple[str, ...] = self.reason_codes
        return codes[0] if codes else self.code.value

    @property
    def signals(self) -> tuple[str, ...]:
        """Причины, по которым выбирается повтор и решается его повторяемость: причины проверки описания, а если их
        нет — главная причина (донор: `error.reason_codes or (error.reason_code,)` в `merge_orchestrator.py`)."""
        return self.reason_codes or (self.reason_code,)

    @property
    def is_recoverable(self) -> bool:
        """Повтор с подсказкой может помочь: хотя бы одна причина повторяемая (донор: `merge_orchestrator.py`)."""
        return any(code in RECOVERABLE_REJECT_CODES for code in self.signals)

    @property
    def human(self) -> str:
        return self.code.human

    @property
    def log_line(self) -> str:
        detail: str = self.detail[:DETAIL_MAX_CHARS]
        return (
            f"reason_code={self.reason_code} reason_codes={CODES_JOINER.join(self.reason_codes) or LOG_NONE} "
            f"recoverable={'yes' if self.is_recoverable else 'no'} "
            f"detail={json.dumps(detail, ensure_ascii=False) if detail else LOG_NONE}"
        )
