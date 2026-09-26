"""Источник слота в промте merge: название и подготовленное описание.

`PreparedSourceDescription` — описание источника, подготовленное для модели: переводы строк приведены, три и больше
подряд — в один пустой абзац, дальше — чистка `AnalysisTextReport` (ссылки, хештеги, заголовки ссылок, служебный
хвост) со счётчиками. Жёсткой обрезки нет (`hard_truncation=disabled`): текст источника идёт в промт целиком.
`MergeSource` — источник в промте: блок по шаблону ресурса `merge_prompt_source.txt` и строка лога.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.text_format import PARAGRAPH_BREAK
from app.llm.merges.prompt_texts import MergePromptTexts
from app.observability.log_event import LogEvent
from app.resources.loader import TextResource
from app.sources.video import SourceVideo
from app.texts.analysis_text import AnalysisTextReport
from app.texts.paragraphs import normalize_multiline_text
from app.texts.phrase_lexicon import ServiceHints

EXTRA_BREAKS_PATTERN: Final[re.Pattern[str]] = re.compile(r"\n{3,}")
SOURCE_BLOCK_RESOURCE: Final[str] = "merge_prompt_source.txt"
HARD_TRUNCATION_DISABLED: Final[str] = "disabled"   # тексты источников в промт идут целиком


class SourceEvent(str, Enum):
    """События источника промта в логе."""

    PREPARED = "merge_source_text_prepared"


@dataclass(frozen=True)
class PreparedSourceDescription:
    """Описание источника, очищенное для модели; `raw_chars` — длина до чистки (после приведения переводов строк)."""

    text: str
    raw_chars: int
    urls_removed: int
    hashtags_removed: int
    service_paragraphs_dropped: int

    @classmethod
    def of(cls, text: str, service_hints: ServiceHints) -> PreparedSourceDescription:
        normalized: str = EXTRA_BREAKS_PATTERN.sub(PARAGRAPH_BREAK, normalize_multiline_text(text))
        if not normalized:
            return cls(text="", raw_chars=0, urls_removed=0, hashtags_removed=0, service_paragraphs_dropped=0)
        report: AnalysisTextReport = AnalysisTextReport.of(normalized, service_hints)
        return cls(
            text=report.text,
            raw_chars=len(normalized),
            urls_removed=report.urls_removed,
            hashtags_removed=report.hashtags_removed,
            service_paragraphs_dropped=report.service_paragraphs_dropped,
        )


@dataclass(frozen=True)
class MergeSource:
    """Источник слота в промте merge.

    `description` подготовлено из описания видео, а пустое описание заменено текстом «нет описания» до чистки.
    """

    title: str
    description: PreparedSourceDescription
    no_description: str
    row_number: int

    @classmethod
    def of(cls, video: SourceVideo, texts: MergePromptTexts) -> MergeSource:
        """Источник из видео слота."""
        description: str = video.text.description.strip()
        return cls(
            title=video.text.title.strip(),
            description=PreparedSourceDescription.of(description or texts.no_description, texts.service_hints),
            no_description=texts.no_description,
            row_number=video.row_number,
        )

    @property
    def prompt_description(self) -> str:
        """Описание в промте: очищенное, а если после чистки пусто — «нет описания»."""
        return self.description.text or self.no_description

    def prompt_block(self, index: int) -> str:
        """Блок источника: номер, название, описание — по шаблону ресурса."""
        template: str = TextResource(SOURCE_BLOCK_RESOURCE).body.strip()
        return template.format(index=index, title=self.title, description=self.prompt_description)

    def event(self, index: int, language: str) -> LogEvent:
        """Строка `merge_source_text_prepared` — счётчики без текста источника."""
        prepared: LogEvent = LogEvent.of(
            SourceEvent.PREPARED, language=language, source_index=index, row=self.row_number
        )
        return prepared.extended(
            raw_chars=self.description.raw_chars,
            cleaned_chars=len(self.prompt_description),
            urls_removed=self.description.urls_removed,
            hashtags_removed=self.description.hashtags_removed,
            service_paragraphs_dropped=self.description.service_paragraphs_dropped,
            hard_truncation=HARD_TRUNCATION_DISABLED,
        )
