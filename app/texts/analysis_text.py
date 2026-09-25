"""Текст видео для определения языка и для промта merge (CLAUDE.md §2: `core\\description_cleaner.py` restreamer).

`clean_text_for_analysis` — правило `clean_description_for_analysis` донора: из каждой строки убираются
ссылки и хештеги, строки-заголовки вида «🌐 …:» выпадают, пустые абзацы выпадают, а с конца текста
снимаются короткие служебные абзацы («подпишитесь», «ссылки ниже» — лексикон `merge_service_hints.txt`).
`AnalysisTextReport` — та же чистка со счётчиками (`_clean_description_for_analysis_report` донора): сколько ссылок
и хештегов убрано и сколько абзацев выпало; счётчики пишет в лог подготовка описаний источников для промта merge.
`is_service_tail_paragraph` — правило служебного абзаца, общее для чистки и проверки ответа merge.
Лексикон приходит аргументом: модуль остаётся чистым преобразованием строки (§0).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
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


def is_service_tail_paragraph(paragraph: str, service_hints: tuple[str, ...]) -> bool:
    """Короткий абзац с подсказкой служебного хвоста или заголовок ссылок; пустой — тоже служебный.

    Правило донора `core\\description_cleaner.py::_looks_like_service_tail_paragraph`: им же чистка снимает хвост
    текста, а проверка ответа merge узнаёт служебную строку в тезисе и в начале описания.
    """
    text: str = ANY_SPACE_PATTERN.sub(" ", paragraph.strip()).lower()
    if not text or _is_heading_line(text):
        return True
    return (
        len(text) <= SERVICE_TAIL_MAX_CHARS
        and len(SEMANTIC_TOKEN_PATTERN.findall(text)) <= SERVICE_TAIL_MAX_TOKENS
        and any(hint in text for hint in service_hints)
    )


@dataclass(frozen=True)
class _CleanedParagraph:
    """Абзац после чистки строк и счётчики убранного в нём."""

    text: str
    urls_removed: int
    hashtags_removed: int

    @classmethod
    def of(cls, paragraph: str) -> _CleanedParagraph:
        """Каждая строка — без ссылок и хештегов; пустая или заголовок «🌐 …:» выпадает."""
        lines: list[str] = []
        urls_removed: int = 0
        hashtags_removed: int = 0
        for raw_line in paragraph.split(LINE_BREAK):
            line, urls = URL_PATTERN.subn("", raw_line.strip())
            line, hashtags = HASHTAG_PATTERN.subn("", _tidy(line))
            urls_removed += urls
            hashtags_removed += hashtags
            line = _tidy(_tidy(line))
            if line and not _is_heading_line(line):
                lines.append(line)
        return cls(text=LINE_BREAK.join(lines).strip(), urls_removed=urls_removed, hashtags_removed=hashtags_removed)


@dataclass(frozen=True)
class AnalysisTextReport:
    """Очищенный текст и что из него убрано: ссылки, хештеги, абзацы (пустые после чистки и служебный хвост)."""

    text: str
    urls_removed: int
    hashtags_removed: int
    service_paragraphs_dropped: int

    @classmethod
    def of(cls, text: str, service_hints: tuple[str, ...]) -> AnalysisTextReport:
        normalized: str = str(text or "").replace("\r\n", LINE_BREAK).replace("\r", LINE_BREAK).strip()
        cleaned: list[_CleanedParagraph] = [
            _CleanedParagraph.of(part.strip()) for part in PARAGRAPH_BREAK_PATTERN.split(normalized) if part.strip()
        ]
        paragraphs: list[str] = [paragraph.text for paragraph in cleaned if paragraph.text]
        dropped: int = len(cleaned) - len(paragraphs)
        while paragraphs and is_service_tail_paragraph(paragraphs[-1], service_hints):
            paragraphs.pop()
            dropped += 1
        return cls(
            text=PARAGRAPH_JOINER.join(paragraphs).strip(),
            urls_removed=sum(paragraph.urls_removed for paragraph in cleaned),
            hashtags_removed=sum(paragraph.hashtags_removed for paragraph in cleaned),
            service_paragraphs_dropped=dropped,
        )


def clean_text_for_analysis(text: str, service_hints: tuple[str, ...]) -> str:
    """Текст, по которому судят о языке: без ссылок, хештегов, заголовков ссылок и служебного хвоста."""
    return AnalysisTextReport.of(text, service_hints).text
