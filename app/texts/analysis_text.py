"""Текст видео для определения языка и для промта merge (CLAUDE.md §3 шаги 3–5, §14 решение 12).

Из каждой строки убираются ссылки и хештеги, строка-заголовок «🌐 …:» выпадает (по ней о языке не судят), пустые
строки и абзацы выпадают, а с конца текста снимаются служебные абзацы («подпишитесь», «ссылки ниже» —
`ServiceHints`). `AnalysisTextReport` — очищенный текст и счётчики: сколько ссылок и хештегов убрано и сколько
абзацев выпало; счётчики пишет в лог подготовка описаний источников для промта merge.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from app.core.text_format import NEWLINE, PARAGRAPH_BREAK, REPEATED_SPACE_PATTERN, SPACE
from app.core.web_link import URL_PATTERN
from app.texts.description_marks import is_official_links_heading
from app.texts.hashtags import HASHTAG_PATTERN
from app.texts.paragraphs import split_paragraphs
from app.texts.phrase_lexicon import ServiceHints

EDGE_PUNCTUATION: Final[str] = " ,;:-"      # края строки после чистки: пробелы и знаки, оставшиеся от ссылок


@dataclass(frozen=True)
class CleanedLine:
    """Строка после чистки: текст без ссылок и хештегов, сколько их убрано и была ли строка заголовком ссылок."""

    text: str
    urls_removed: int = 0
    hashtags_removed: int = 0
    is_heading: bool = False

    @classmethod
    def of(cls, raw_line: str) -> CleanedLine:
        """Сначала ссылки (заголовок «🌐 …:» узнаётся по строке без них), затем хештеги; края — после каждой чистки."""
        without_urls, urls = URL_PATTERN.subn("", raw_line.strip())
        line: CleanedLine = cls(without_urls, urls, is_heading=is_official_links_heading(without_urls)).tidied
        without_hashtags, hashtags = HASHTAG_PATTERN.subn("", line.text)
        return replace(line, text=without_hashtags, hashtags_removed=hashtags).tidied

    @property
    def tidied(self) -> CleanedLine:
        """Повторные пробелы — в один, края — без пробелов и знаков `,;:-`."""
        return replace(self, text=REPEATED_SPACE_PATTERN.sub(SPACE, self.text).strip(EDGE_PUNCTUATION))

    @property
    def is_kept(self) -> bool:
        return bool(self.text) and not self.is_heading


@dataclass(frozen=True)
class CleanedParagraph:
    """Абзац после чистки строк и счётчики убранного в нём."""

    text: str
    urls_removed: int
    hashtags_removed: int

    @classmethod
    def of(cls, paragraph: str) -> CleanedParagraph:
        lines: list[CleanedLine] = [CleanedLine.of(raw_line) for raw_line in paragraph.split(NEWLINE)]
        return cls(
            text=NEWLINE.join(line.text for line in lines if line.is_kept).strip(),
            urls_removed=sum(line.urls_removed for line in lines),
            hashtags_removed=sum(line.hashtags_removed for line in lines),
        )


@dataclass(frozen=True)
class AnalysisTextReport:
    """Очищенный текст и что из него убрано: ссылки, хештеги, абзацы (пустые после чистки и служебный хвост)."""

    text: str
    urls_removed: int
    hashtags_removed: int
    service_paragraphs_dropped: int

    @classmethod
    def of(cls, text: str, hints: ServiceHints) -> AnalysisTextReport:
        cleaned: list[CleanedParagraph] = [CleanedParagraph.of(paragraph) for paragraph in split_paragraphs(text)]
        paragraphs: list[str] = [paragraph.text for paragraph in cleaned if paragraph.text]
        dropped: int = len(cleaned) - len(paragraphs)
        while paragraphs and hints.is_tail_paragraph(paragraphs[-1]):
            paragraphs.pop()
            dropped += 1
        return cls(
            text=PARAGRAPH_BREAK.join(paragraphs).strip(),
            urls_removed=sum(paragraph.urls_removed for paragraph in cleaned),
            hashtags_removed=sum(paragraph.hashtags_removed for paragraph in cleaned),
            service_paragraphs_dropped=dropped,
        )
