"""Источник слота в промте merge: название и подготовленное описание (restreamer `app\\llm\\merges\\merge_prompt.py`).

`PreparedSourceDescription` — `_clean_source_description_for_llm` и `_normalize_source_description_text` донора: переводы
строк приведены, три и больше подряд — в один пустой абзац, дальше — чистка `AnalysisTextReport` (ссылки, хештеги,
заголовки ссылок, служебный хвост) со счётчиками. Жёсткой обрезки нет (`hard_truncation=disabled`, как у донора).
`MergeSource` — источник в промте: блок `SOURCE n` и текст для проверки качества (`_source_texts_for_merge_quality`).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from app.texts.analysis_text import AnalysisTextReport

if TYPE_CHECKING:
    from app.llm.merges.prompt_texts import MergePromptTexts
    from app.sources.video import SourceVideo

EXTRA_BREAKS_PATTERN: Final[re.Pattern[str]] = re.compile(r"\n{3,}")
PARAGRAPH_BREAK: Final[str] = "\n\n"
LINE_BREAK: Final[str] = "\n"
SOURCE_HEADER: Final[str] = "SOURCE {index}"
TITLE_PREFIX: Final[str] = "TITLE: "
DESCRIPTION_PREFIX: Final[str] = "DESCRIPTION: "


@dataclass(frozen=True)
class PreparedSourceDescription:
    """Описание источника, очищенное для модели; `raw_chars` — длина до чистки (после приведения переводов строк)."""

    text: str
    raw_chars: int
    urls_removed: int
    hashtags_removed: int
    service_paragraphs_dropped: int

    @classmethod
    def of(cls, text: str, service_hints: tuple[str, ...]) -> PreparedSourceDescription:
        normalized: str = str(text or "").replace("\r\n", LINE_BREAK).replace("\r", LINE_BREAK).strip()
        normalized = EXTRA_BREAKS_PATTERN.sub(PARAGRAPH_BREAK, normalized)
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

    @property
    def cleaned_chars(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class MergeSource:
    """Источник слота в промте merge.

    `description` подготовлено из описания видео, а пустое описание заменено текстом «нет описания» до чистки — как у
    донора. `has_description` помнит, было ли у видео своё описание: текст для проверки качества его заменой не берёт.
    """

    title: str
    description: PreparedSourceDescription
    has_description: bool
    no_description: str
    row_number: int

    @classmethod
    def of(cls, video: SourceVideo, texts: MergePromptTexts) -> MergeSource:
        """Источник из видео слота; видео без данных (в слот такие не попадают) даёт пустые название и описание."""
        title: str = video.metadata.title if video.metadata is not None else ""
        description: str = (video.metadata.description if video.metadata is not None else "").strip()
        return cls(
            title=title.strip(),
            description=PreparedSourceDescription.of(description or texts.no_description, texts.service_hints),
            has_description=bool(description),
            no_description=texts.no_description,
            row_number=video.row.row_number,
        )

    @property
    def prompt_description(self) -> str:
        """Описание в промте: очищенное, а если после чистки пусто — «нет описания»."""
        return self.description.text or self.no_description

    @property
    def quality_text(self) -> str:
        """Название и очищенное описание — то, с чем проверка качества сверяет ответ модели."""
        description: str = self.description.text if self.has_description else ""
        return f"{self.title}{LINE_BREAK}{description}".strip()

    def prompt_block(self, index: int) -> str:
        return LINE_BREAK.join(
            (
                SOURCE_HEADER.format(index=index),
                f"{TITLE_PREFIX}{self.title}",
                f"{DESCRIPTION_PREFIX}{self.prompt_description}",
            )
        )

    def log_line(self, index: int, language: str) -> str:
        """Строка лога донора `merge_source_text_prepared` — счётчики без текста источника."""
        return (
            f"merge_source_text_prepared language={language} source_index={index} row={self.row_number} "
            f"raw_chars={self.description.raw_chars} cleaned_chars={len(self.prompt_description)} "
            f"urls_removed={self.description.urls_removed} hashtags_removed={self.description.hashtags_removed} "
            f"service_paragraphs_dropped={self.description.service_paragraphs_dropped} hard_truncation=disabled"
        )
