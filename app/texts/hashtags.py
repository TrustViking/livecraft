"""Хештеги в тексте описания: одно тело хештега и шаблоны мест, где его ищут (CLAUDE.md §11, E9).

Тело хештега — `#` и дальше всё до пробела или следующей `#`. Где он стоит, решают шаблоны: внутри текста (не
приклеен к слову слева), после начала строки или пробела, словом целиком, цепочкой хештегов в конце абзаца.
"""
from __future__ import annotations

import re
from typing import Final

HASHTAG_BODY: Final[str] = r"#[^\s#]+"
HASHTAG_PATTERN: Final[re.Pattern[str]] = re.compile(rf"(?<!\w){HASHTAG_BODY}")               # в тексте
HASHTAG_AFTER_SPACE_PATTERN: Final[re.Pattern[str]] = re.compile(rf"(?:^|\s)({HASHTAG_BODY})")  # хештег — группа 1
HASHTAG_WORD_PATTERN: Final[re.Pattern[str]] = re.compile(rf"^{HASHTAG_BODY}$")                # слово целиком
# Хештеги через пробел в конце абзаца — группа 1.
HASHTAG_TAIL_PATTERN: Final[re.Pattern[str]] = re.compile(rf"(?is)({HASHTAG_BODY}(?:\s+{HASHTAG_BODY})*)\s*$")


def is_hashtags_line(text: str) -> bool:
    """Строка или абзац — только хештеги через пробел."""
    words: list[str] = (text or "").split()
    return bool(words) and all(HASHTAG_WORD_PATTERN.fullmatch(word) for word in words)
