"""Заголовок повестки в описании («Что в этом стриме:», «In this stream \u2014»): признак пересказа вместо описания.

Заголовки \u2014 ресурс `merge_agenda_headings.txt`, в нижнем регистре.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.core.text_format import NEWLINE, SPACE, WHITESPACE_RUN_PATTERN
from app.resources.loader import TextResource
from app.texts.paragraphs import normalize_newlines

AGENDA_HEADINGS_RESOURCE: Final[str] = "merge_agenda_headings.txt"
# Края строки, которые не мешают узнать заголовок: пробел, тире, двоеточие и знаки конца фразы.
HEADING_EDGE_CHARS: Final[str] = " -\u2013\u2014:;.!?"
# Заголовок, за которым идёт продолжение строки: двоеточие или тире.
HEADING_CONTINUATIONS: Final[tuple[str, ...]] = (":", " -", " \u2013", " \u2014")


@dataclass(frozen=True)
class AgendaLexicon:
    """Заголовки повестки в нижнем регистре."""

    headings: tuple[str, ...]

    @classmethod
    def load(cls) -> AgendaLexicon:
        return cls(headings=TextResource(AGENDA_HEADINGS_RESOURCE).lines)

    def matches(self, text: str) -> bool:
        """Хотя бы одна строка текста \u2014 заголовок повестки или начинается с него и двоеточия либо тире."""
        for raw_line in normalize_newlines(text).split(NEWLINE):
            if not raw_line.strip():
                continue
            line: str = WHITESPACE_RUN_PATTERN.sub(SPACE, raw_line.strip().lower()).strip(HEADING_EDGE_CHARS)
            if self._is_heading(line):
                return True
        return False

    def _is_heading(self, line: str) -> bool:
        """Строка \u2014 сам заголовок или заголовок с продолжением через двоеточие или тире."""
        return any(
            line == heading or any(line.startswith(f"{heading}{tail}") for tail in HEADING_CONTINUATIONS)
            for heading in self.headings
        )
