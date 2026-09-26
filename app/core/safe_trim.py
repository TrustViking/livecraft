"""Безопасная обрезка текста справа: текст не рвётся посреди слова, если этого можно избежать (CLAUDE.md §2, §4).

Граница обрезки ищется по порядку `TrimBoundary`: конец предложения (не раньше 60 % предела), граница слова
(не раньше 50 %), любой не-словесный символ; не нашлось ни одной — текст целиком отбрасывается (`DROP_LONG_TOKEN`):
длинный токен без границ (ссылка, строка без пробелов) обрезанным бесполезен. `safe_trim_right` — чистое
преобразование строки, разрешённое §0 исключение.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, StrEnum
from typing import Final

SENTENCE_END_CHARS: Final[str] = ".!?…"          # конец предложения: по нему режут текст и делят абзац на фразы
WORD_BOUNDARY_CHARS: Final[str] = " \t\r\n,;:)]}\"'»"
WORD_CHAR_PATTERN: Final[re.Pattern[str]] = re.compile(r"\w")
SENTENCE_MIN_SHARE: Final[float] = 0.6           # конец предложения — не раньше этой доли предела
WORD_MIN_SHARE: Final[float] = 0.5               # граница слова — не раньше этой доли предела


class TrimReason(StrEnum):
    """Чем кончилась обрезка; в строке лога — значением (`not_trimmed`)."""

    EMPTY_LIMIT = "empty_limit"                  # предел не больше нуля — текста нет
    NOT_TRIMMED = "not_trimmed"                  # текст в пределе
    SENTENCE_BOUNDARY = "sentence_boundary"
    WORD_BOUNDARY = "word_boundary"
    SYMBOL_BOUNDARY = "symbol_boundary"
    DROP_LONG_TOKEN = "drop_long_token"          # границы нет — текст отброшен


class TrimBoundary(Enum):
    """Граница обрезки в порядке предпочтения: причина итога и доля предела, раньше которой граница не годится."""

    SENTENCE = (TrimReason.SENTENCE_BOUNDARY, SENTENCE_MIN_SHARE)
    WORD = (TrimReason.WORD_BOUNDARY, WORD_MIN_SHARE)
    SYMBOL = (TrimReason.SYMBOL_BOUNDARY, 0)

    def __init__(self, reason: TrimReason, min_share: float) -> None:
        self.reason: TrimReason = reason
        self.min_share: float = min_share

    def is_boundary(self, char: str) -> bool:
        """Можно ли резать сразу после этого символа."""
        if self is TrimBoundary.SENTENCE:
            return char in SENTENCE_END_CHARS
        if self is TrimBoundary.WORD:
            return char.isspace() or char in WORD_BOUNDARY_CHARS
        return WORD_CHAR_PATTERN.fullmatch(char) is None

    def cut(self, text: str, max_length: int) -> int:
        """Длина, до которой режется текст: самая дальняя граница в пределе и не раньше своей доли; нет — 0."""
        earliest: int = max(1, int(max_length * self.min_share))
        for index in range(min(max_length, len(text)), earliest - 1, -1):
            if self.is_boundary(text[index - 1]):
                return index
        return 0


@dataclass(frozen=True)
class SafeTrimResult:
    """Текст после обрезки, изменился ли он и почему."""

    text: str
    trimmed: bool
    reason: TrimReason


def safe_trim_right(text: str, *, max_length: int) -> SafeTrimResult:
    """Текст не длиннее `max_length`, обрезанный по лучшей найденной границе; None — пустой текст."""
    whole: str = text or ""
    if max_length <= 0:
        return SafeTrimResult(text="", trimmed=bool(whole), reason=TrimReason.EMPTY_LIMIT)
    if len(whole) <= max_length:
        return SafeTrimResult(text=whole, trimmed=False, reason=TrimReason.NOT_TRIMMED)
    for boundary in TrimBoundary:
        kept: str = whole[: boundary.cut(whole, max_length)].rstrip()
        if kept:
            return SafeTrimResult(text=kept, trimmed=kept != whole, reason=boundary.reason)
    return SafeTrimResult(text="", trimmed=True, reason=TrimReason.DROP_LONG_TOKEN)
