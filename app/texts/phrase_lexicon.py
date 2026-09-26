"""Лексиконы фраз: фраза узнаётся подстрокой уже нормализованного текста (CLAUDE.md §11, §14 решение 23).

`PhraseLexicon` — одно правило «фраза лексикона — подстрока текста» для всех лексиконов фраз: подсказок служебного
хвоста, признаков негодного тезиса, подсказок официальной ссылки. Как нормализовать текст, решает владелец
лексикона. `ServiceHints` — подсказки служебного хвоста описания («подпишитесь», «ссылки ниже»): ими чистка текста
снимает хвост, промт merge их называет, проверка ответа узнаёт служебную строку. Файл читается один раз за запуск.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cache
from typing import Final

from app.resources.loader import TextResource
from app.texts.description_marks import is_official_links_heading
from app.texts.paragraphs import collapse_spaces
from app.texts.similarity import WordRule

SERVICE_HINTS_RESOURCE: Final[str] = "merge_service_hints.txt"
# Служебный абзац короткий: не длиннее 220 знаков и не больше 12 смысловых слов.
SERVICE_TAIL_MAX_CHARS: Final[int] = 220
SERVICE_TAIL_MAX_TOKENS: Final[int] = 12


@dataclass(frozen=True)
class PhraseLexicon:
    """Фразы лексикона в нижнем регистре."""

    phrases: tuple[str, ...]

    def found_in(self, normalized_text: str) -> bool:
        """Хотя бы одна фраза — подстрока текста, который владелец лексикона уже нормализовал."""
        return any(phrase in normalized_text for phrase in self.phrases)


@dataclass(frozen=True)
class ServiceHints:
    """Подсказки служебного хвоста описания и правило служебного абзаца."""

    phrases: PhraseLexicon

    @classmethod
    @cache
    def load(cls) -> ServiceHints:
        """Подсказки из ресурса программы; один объект на процесс."""
        return cls(PhraseLexicon(TextResource(SERVICE_HINTS_RESOURCE).lines))

    def is_tail_paragraph(self, paragraph: str) -> bool:
        """Служебный абзац: пустой, заголовок «🌐 …:» или короткий абзац с подсказкой (пробелы схлопнуты, нижний регистр)."""
        text: str = collapse_spaces(paragraph).lower()
        if not text or is_official_links_heading(text):
            return True
        is_short: bool = len(text) <= SERVICE_TAIL_MAX_CHARS and len(WordRule.SEMANTIC.words(text)) <= SERVICE_TAIL_MAX_TOKENS
        return is_short and self.phrases.found_in(text)
