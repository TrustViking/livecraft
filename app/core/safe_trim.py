"""Безопасная обрезка текста справа: текст не рвётся посреди слова и посреди ссылки (CLAUDE.md §2, §4, §14 решение 30).

Граница обрезки ищется по порядку `TrimBoundary`: конец предложения — знак конца, за которым пробел или конец текста
(не раньше 60 % предела), граница слова (не раньше 50 %), любой не-словесный символ; не нашлось ни одной — текст
целиком отбрасывается (`DROP_LONG_TOKEN`): длинный токен без границ обрезанным бесполезен. Внутри ссылки
(`URL_PATTERN`) границ нет: точка в «youtu.be», двоеточие и косая черта адреса — не место обрезки, поэтому ссылка
остаётся целиком или целиком уходит. Где в тексте ссылки и где можно резать, знает `TrimText`. `safe_trim_right` —
чистое преобразование строки, разрешённое §0 исключение.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum, StrEnum
from functools import cached_property
from typing import Final

from app.core.web_link import URL_PATTERN

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

    def is_boundary(self, text: TrimText, index: int) -> bool:
        """Можно ли резать на месте `index` — сразу после знака `index - 1`; внутри ссылки — нельзя никогда."""
        if text.is_inside_link(index):
            return False
        char: str = text.text[index - 1]
        if self is TrimBoundary.SENTENCE:
            return char in SENTENCE_END_CHARS and text.is_followed_by_space(index)
        if self is TrimBoundary.WORD:
            return char.isspace() or char in WORD_BOUNDARY_CHARS
        return WORD_CHAR_PATTERN.fullmatch(char) is None

    def cut(self, text: TrimText, max_length: int) -> int:
        """Длина, до которой режется текст: самая дальняя граница в пределе и не раньше своей доли; нет — 0."""
        earliest: int = max(1, int(max_length * self.min_share))
        for index in range(min(max_length, len(text.text)), earliest - 1, -1):
            if self.is_boundary(text, index):
                return index
        return 0


@dataclass(frozen=True)
class TrimText:
    """Текст, который режется, и места ссылок в нём: резать можно до ссылки или после неё, но не внутри."""

    text: str

    @cached_property
    def link_insides(self) -> tuple[range, ...]:
        """Места обрезки внутри каждой ссылки: после её первого знака и до последнего."""
        return tuple(range(match.start() + 1, match.end()) for match in URL_PATTERN.finditer(self.text))

    def is_inside_link(self, index: int) -> bool:
        """Обрезка на месте `index` разорвала бы ссылку."""
        return any(index in inside for inside in self.link_insides)

    def is_followed_by_space(self, index: int) -> bool:
        """За местом `index` — пробел или конец текста: знак перед ним кончает предложение, а не «v1.2»."""
        return index >= len(self.text) or self.text[index].isspace()


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
    text: TrimText = TrimText(whole)
    for boundary in TrimBoundary:
        kept: str = whole[: boundary.cut(text, max_length)].rstrip()
        if kept:
            return SafeTrimResult(text=kept, trimmed=kept != whole, reason=boundary.reason)
    return SafeTrimResult(text="", trimmed=True, reason=TrimReason.DROP_LONG_TOKEN)
