"""Отказ ответа модели на merge: код причины и подробность — значение, а не исключение (CLAUDE.md §14 решение 23).

У донора причина закодирована текстом исключения и разбирается обратно по подстрокам
(`merge_validation.py::_reason_code_from_error`, `_reason_codes_from_error`). Здесь код ставится в момент отказа;
значения кодов — ровно те `reason_code`, которые донорский разбор даёт на путях разбора ответа, — это держит
сверка с донором.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.ui import messages_ru as msg

# Повторяемые причины донора (`merge_constants.py::RECOVERABLE_REJECT_CODES`) целиком: часть их даёт этот слой,
# остальные — проверка покрытия и качества (задачи 3.11b, 3.12b).
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
LOG_NONE: Final[str] = "-"
CODES_JOINER: Final[str] = ","
DETAIL_MAX_CHARS: Final[int] = 200


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
    def human(self) -> str:
        return msg.MERGE_REJECT_TEXT[self.value]


_DESCRIPTION_VALIDATION_CODES: Final[frozenset[MergeRejectCode]] = frozenset(
    {
        MergeRejectCode.CTA_AS_FIRST_PARAGRAPH,
        MergeRejectCode.DUPLICATE_PARAGRAPH,
        MergeRejectCode.DESCRIPTION_EMPTY,
    }
)


@dataclass(frozen=True)
class MergeReject:
    """Ответ модели не принят. `detail` — подробность для лога (какие ключи, сколько абзацев), без текста ответа."""

    code: MergeRejectCode
    detail: str = ""

    @property
    def reason_codes(self) -> tuple[str, ...]:
        """Причины проверки описания — как `_reason_codes_from_error` донора; у прочих отказов список пуст."""
        return (self.code.value,) if self.code.is_description_validation else ()

    @property
    def is_recoverable(self) -> bool:
        return self.code.is_recoverable

    @property
    def human(self) -> str:
        return self.code.human

    @property
    def log_line(self) -> str:
        detail: str = self.detail[:DETAIL_MAX_CHARS]
        return (
            f"reason_code={self.code.value} reason_codes={CODES_JOINER.join(self.reason_codes) or LOG_NONE} "
            f"recoverable={'yes' if self.is_recoverable else 'no'} "
            f"detail={json.dumps(detail, ensure_ascii=False) if detail else LOG_NONE}"
        )
