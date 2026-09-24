"""Текст видео для определения языка (CLAUDE.md §2: `core\\description_cleaner.py` restreamer).

`clean_text_for_analysis` — правило `clean_description_for_analysis` донора: из каждой строки убираются
ссылки и хештеги, строки-заголовки вида «🌐 …:» выпадают, пустые абзацы выпадают, а с конца текста
снимаются короткие служебные абзацы («подпишитесь», «ссылки ниже» — лексикон `merge_service_hints.txt`).
Лексикон приходит аргументом: функция остаётся чистым преобразованием строки (§0).
"""
from __future__ import annotations

import re
from typing import Final

URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://\S+", flags=re.IGNORECASE)
HASHTAG_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<!\w)#[^\s#]+", flags=re.UNICODE)
SEMANTIC_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[0-9A-Za-zА-Яа-яЁёІіЇїЄєҐґ]{3,}", flags=re.UNICODE)
HEADING_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*🌐\s*[^\s:][^:\n]*:\s*$")
PARAGRAPH_BREAK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\n\s*\n")
REPEATED_SPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s{2,}")
ANY_SPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
EDGE_PUNCTUATION: Final[str] = " ,;:-"
SERVICE_TAIL_MAX_CHARS: Final[int] = 220
SERVICE_TAIL_MAX_TOKENS: Final[int] = 12
LINE_BREAK: Final[str] = "\n"
PARAGRAPH_JOINER: Final[str] = "\n\n"


def _tidy(text: str) -> str:
    """Повторные пробелы — в один, края — без пробелов и знаков `,;:-` (как донор после каждой чистки)."""
    return REPEATED_SPACE_PATTERN.sub(" ", text).strip(EDGE_PUNCTUATION)


def _is_heading_line(text: str) -> bool:
    stripped: str = text.strip()
    return bool(stripped) and bool(HEADING_LINE_PATTERN.fullmatch(stripped))


def _clean_line(raw_line: str) -> str:
    """Строка без ссылок и хештегов; пустая или заголовок «🌐 …:» — пустая строка."""
    line: str = _tidy(URL_PATTERN.sub("", raw_line.strip()))
    line = _tidy(_tidy(HASHTAG_PATTERN.sub("", line)))
    return "" if _is_heading_line(line) else line


def _clean_paragraph(paragraph: str) -> str:
    return LINE_BREAK.join(line for line in map(_clean_line, paragraph.split(LINE_BREAK)) if line).strip()


def _is_service_tail(paragraph: str, service_hints: tuple[str, ...]) -> bool:
    """Короткий абзац с подсказкой служебного хвоста или заголовок ссылок; пустой — тоже служебный."""
    text: str = ANY_SPACE_PATTERN.sub(" ", paragraph.strip()).lower()
    if not text or _is_heading_line(text):
        return True
    return (
        len(text) <= SERVICE_TAIL_MAX_CHARS
        and len(SEMANTIC_TOKEN_PATTERN.findall(text)) <= SERVICE_TAIL_MAX_TOKENS
        and any(hint in text for hint in service_hints)
    )


def clean_text_for_analysis(text: str, service_hints: tuple[str, ...]) -> str:
    """Текст, по которому судят о языке: без ссылок, хештегов, заголовков ссылок и служебного хвоста."""
    normalized: str = str(text or "").replace("\r\n", LINE_BREAK).replace("\r", LINE_BREAK).strip()
    if not normalized:
        return ""
    paragraphs: list[str] = [
        cleaned
        for part in PARAGRAPH_BREAK_PATTERN.split(normalized)
        if part.strip() and (cleaned := _clean_paragraph(part.strip()))
    ]
    while paragraphs and _is_service_tail(paragraphs[-1], service_hints):
        paragraphs.pop()
    return PARAGRAPH_JOINER.join(paragraphs).strip()
