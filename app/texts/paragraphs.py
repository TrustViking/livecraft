"""Абзацы и строки текста: чистые преобразования строки (CLAUDE.md §0 — свободные функции без предметных объектов).

Абзацы разделяет пустая строка (в том числе строка из одних пробелов); перевод строки `\\r\\n` и одиночный `\\r`
приводятся к `\\n`. Фразы абзаца делит пробел после знака конца предложения — того же, по которому режет
`safe_trim_right`. Повтор абзацев — одинаковые или почти одинаковые (по доле общих слов) абзацы не короче шести слов.
"""
from __future__ import annotations

import re
from typing import Final

from app.core.safe_trim import SENTENCE_END_CHARS
from app.core.text_format import NEWLINE, PARAGRAPH_BREAK_PATTERN, SPACE, WHITESPACE_RUN_PATTERN
from app.texts.similarity import TextPair, WordRule

WINDOWS_NEWLINE: Final[str] = "\r\n"
OLD_MAC_NEWLINE: Final[str] = "\r"
SENTENCE_BREAK_PATTERN: Final[re.Pattern[str]] = re.compile(rf"(?<=[{re.escape(SENTENCE_END_CHARS)}])\s+")
# Повтор абзацев: доля общих слов не меньше 0.72 у абзацев не короче шести слов.
DUPLICATE_JACCARD_THRESHOLD: Final[float] = 0.72
DUPLICATE_MIN_TOKENS: Final[int] = 6


def normalize_newlines(text: str) -> str:
    """Все переводы строки — `\\n`; None — пустой текст."""
    return (text or "").replace(WINDOWS_NEWLINE, NEWLINE).replace(OLD_MAC_NEWLINE, NEWLINE)


def normalize_multiline_text(text: str) -> str:
    """Переводы строки — `\\n`, края текста без пробелов."""
    return normalize_newlines(text).strip()


def split_paragraphs(text: str) -> list[str]:
    """Непустые абзацы текста без краевых пробелов, по порядку."""
    normalized_text: str = normalize_multiline_text(text)
    return [part.strip() for part in PARAGRAPH_BREAK_PATTERN.split(normalized_text) if part.strip()]


def nonempty_lines(text: str) -> list[str]:
    """Непустые строки текста (по `\\n`) без краевых пробелов, по порядку."""
    return [line.strip() for line in (text or "").split(NEWLINE) if line.strip()]


def collapse_spaces(text: str) -> str:
    """Любые пробелы подряд — один пробел, края — без пробелов."""
    return WHITESPACE_RUN_PATTERN.sub(SPACE, text or "").strip()


def has_duplicate_paragraphs(text: str) -> bool:
    """Есть ли среди абзацев не короче шести слов одинаковые или почти одинаковые (по доле общих слов)."""
    seen: list[str] = []
    for paragraph in split_paragraphs(text):
        normalized: str = collapse_spaces(paragraph).lower()
        if len(WordRule.SPACED.words(normalized)) < DUPLICATE_MIN_TOKENS:
            continue
        for previous in seen:
            similarity: float | None = TextPair(normalized, previous, WordRule.SPACED).jaccard
            if normalized == previous or (similarity is not None and similarity >= DUPLICATE_JACCARD_THRESHOLD):
                return True
        seen.append(normalized)
    return False
