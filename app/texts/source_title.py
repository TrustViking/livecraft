"""Чистка названия источника от хвоста хештегов (CLAUDE.md §2 контур A: `core\\video_title_cleanup.py`).

Перенесено из restreamer (`app\\core\\video_title_cleanup.py::sanitize_source_video_title`) как есть: чистое
преобразование строки без знания о предметных объектах (§0). Правило донора: с конца названия снимается
сплошной хвост хештегов; хештег с буквой убирается, числовой (`#2`, `#2026`) остаётся; после этого
срезаются висящие разделители `| — – -`. Хештег в середине названия не трогается.
"""
from __future__ import annotations

import re
from typing import Final

from app.observability.logging_setup import get_logger

LOGGER_NAME: Final[str] = "texts"
LOGGER = get_logger(LOGGER_NAME)

HASHTAG_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"#\S+")
NON_WHITESPACE_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\S+")
HASHTAG_LETTER_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^\W\d_]")
HASHTAG_DIGITS_PATTERN: Final[re.Pattern[str]] = re.compile(r"\d+")
TRAILING_SEPARATOR_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:\s*[|—–-]+\s*)+$")
TOKEN_JOINER: Final[str] = " "


def sanitize_source_video_title(raw_title: str) -> str:
    """Название без хвоста буквенных хештегов и без висящего разделителя в конце."""
    stripped_title: str = raw_title.strip()
    if not stripped_title:
        return ""
    zone_start: int | None = _trailing_hashtag_zone_start(stripped_title)
    if zone_start is None:
        return stripped_title
    prefix: str = stripped_title[:zone_start].rstrip()
    zone_tokens: list[str] = NON_WHITESPACE_TOKEN_PATTERN.findall(stripped_title[zone_start:])
    kept_tokens: list[str] = [token for token in zone_tokens if _is_kept_hashtag(token)]
    removed_count: int = len(zone_tokens) - len(kept_tokens)
    result: str = TOKEN_JOINER.join(part for part in (prefix, *kept_tokens) if part)
    result = TRAILING_SEPARATOR_PATTERN.sub("", result).strip()
    if removed_count > 0:
        LOGGER.debug("title_hashtags_removed count=%d title=%r result=%r", removed_count, raw_title, result)
    return result


def _trailing_hashtag_zone_start(title: str) -> int | None:
    """Где начинается сплошной хвост хештегов; хвоста нет — None."""
    zone_start: int | None = None
    for match in reversed(list(NON_WHITESPACE_TOKEN_PATTERN.finditer(title))):
        if HASHTAG_TOKEN_PATTERN.fullmatch(match.group(0)) is None:
            break
        zone_start = match.start()
    return zone_start


def _is_kept_hashtag(token: str) -> bool:
    """Числовой хештег (номер серии) остаётся; хештег с буквой уходит; прочее (`#!`) остаётся, как у донора."""
    body: str = token[1:]
    if HASHTAG_DIGITS_PATTERN.fullmatch(body) is not None:
        return True
    return HASHTAG_LETTER_PATTERN.search(body) is None
