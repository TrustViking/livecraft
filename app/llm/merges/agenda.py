"""Заголовок повестки в описании («Что в этом стриме:», «In this stream —»): признак пересказа вместо описания.

Правило — `merge_text_utils.py::_contains_agenda_heading` restreamer; заголовки — ресурс `merge_agenda_headings.txt`
побайтно из restreamer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from app.resources.loader import TextResource
from app.texts.paragraphs import normalize_newlines

AGENDA_HEADINGS_RESOURCE: Final[str] = "merge_agenda_headings.txt"
WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
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
        """Хотя бы одна строка текста — заголовок повестки или начинается с него и двоеточия либо тире."""
        for raw_line in normalize_newlines(text).split("\n"):
            if not raw_line.strip():
                continue
            line: str = WHITESPACE_RUN_PATTERN.sub(" ", raw_line.strip().lower()).strip(HEADING_EDGE_CHARS)
            if any(self._is_heading(line, heading) for heading in self.headings):
                return True
        return False

    @staticmethod
    def _is_heading(line: str, heading: str) -> bool:
        return line == heading or any(line.startswith(f"{heading}{tail}") for tail in HEADING_CONTINUATIONS)
