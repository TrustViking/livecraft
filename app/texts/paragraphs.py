"""Абзацы текста: чистые преобразования строки (CLAUDE.md §0 — свободные функции без предметных объектов).

Перенесены из restreamer как есть (`app\\core\\text_utils.py`: `normalize_newlines`, `normalize_multiline_text`,
`split_paragraphs`, `starts_with_any_prefix`, `has_duplicate_paragraphs`). Абзацы разделяет пустая строка
(в том числе строка из одних пробелов); перевод строки `\\r\\n` и одиночный `\\r` приводятся к `\\n`.
"""
from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Final

PARAGRAPH_BREAK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\n\s*\n")
WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
# Порог повтора абзацев донора: доля общих слов (Жаккар) и минимум слов, при котором абзац сравнивается.
DUPLICATE_JACCARD_THRESHOLD: Final[float] = 0.72
DUPLICATE_MIN_TOKENS: Final[int] = 6


def normalize_newlines(text: str) -> str:
    """Все переводы строки — `\\n`."""
    return str(text or "").replace("\r\n", "\n").replace("\r", "\n")


def normalize_multiline_text(text: str) -> str:
    """Переводы строки — `\\n`, края текста без пробелов."""
    return normalize_newlines(text).strip()


def split_paragraphs(text: str) -> list[str]:
    """Непустые абзацы текста без краевых пробелов, по порядку."""
    normalized_text: str = normalize_multiline_text(text)
    if not normalized_text:
        return []
    return [part.strip() for part in PARAGRAPH_BREAK_PATTERN.split(normalized_text) if part.strip()]


def starts_with_any_prefix(
    text: str,
    prefixes: Sequence[str],
    *,
    use_casefold: bool = False,
    collapse_whitespace: bool = False,
) -> bool:
    """Начинается ли текст (без краёв, без учёта регистра) с одного из непустых префиксов."""
    normalized_text: str = str(text or "").strip()
    if collapse_whitespace:
        normalized_text = WHITESPACE_RUN_PATTERN.sub(" ", normalized_text)
    if not normalized_text:
        return False
    comparable_text: str = normalized_text.casefold() if use_casefold else normalized_text.lower()
    for raw_prefix in prefixes:
        normalized_prefix: str = str(raw_prefix or "").strip()
        if not normalized_prefix:
            continue
        comparable_prefix: str = normalized_prefix.casefold() if use_casefold else normalized_prefix.lower()
        if comparable_text.startswith(comparable_prefix):
            return True
    return False


def has_duplicate_paragraphs(
    text: str,
    *,
    jaccard_threshold: float = DUPLICATE_JACCARD_THRESHOLD,
    min_tokens: int = DUPLICATE_MIN_TOKENS,
) -> bool:
    """Есть ли среди абзацев не короче `min_tokens` слов одинаковые или почти одинаковые (по Жаккару)."""
    seen_normalized: set[str] = set()
    token_sets: list[set[str]] = []
    for paragraph in split_paragraphs(text):
        normalized: str = WHITESPACE_RUN_PATTERN.sub(" ", paragraph.strip().lower())
        token_list: list[str] = [token for token in normalized.split(" ") if token]
        if len(token_list) < min_tokens:
            continue
        if normalized in seen_normalized:
            return True
        seen_normalized.add(normalized)
        current_set: set[str] = set(token_list)
        for previous_set in token_sets:
            union_size: int = len(current_set | previous_set)
            if union_size == 0:
                continue
            if len(current_set & previous_set) / union_size >= jaccard_threshold:
                return True
        token_sets.append(current_set)
    return False
