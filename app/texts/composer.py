"""Сборка описания эфира после санации: тело, рекомендуемые материалы, официальные ссылки, призыв, хештеги.

Порядок частей: тело, рекомендуемые материалы, официальные ссылки, призыв, хештеги — через пустую строку; раскладка
частей (`DescriptionParts.layout`) идёт в строки лога санации. Заголовки блоков — ресурс `publish_headings.json`.

Заголовок блока — по языку описания: пустой, служебный (`unknown`, `other`, `none`, `und`, `xx`) или не двухбуквенный код
— английский; язык, которого нет в файле, — тоже английский и строка лога `heading_fallback_en`: каналов на других
языках нет, заголовок переводится, когда такой канал появится. Рекомендуемое видео — запись из двух строк: «✅ название»
и «👉 ссылка»; заголовок и записи блока — через пустую строку.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.language_code import LanguageCode
from app.core.text_format import NEWLINE, PARAGRAPH_BREAK
from app.core.web_link import WebLink
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.resources.loader import TextResource

LOGGER = get_logger(LogArea.TEXTS)

HEADINGS_RESOURCE: Final[str] = "publish_headings.json"
FALLBACK_LANGUAGE: Final[str] = "en"
INVALID_LANGUAGES: Final[frozenset[str]] = frozenset({"", "unknown", "other", "none", "und", "xx"})
RECOMMENDED_ENTRY: Final[str] = "✅ {title}" + NEWLINE + "👉 {url}"
LAYOUT_JOINER: Final[str] = "_"
LAYOUT_EMPTY: Final[str] = "empty"
LAYOUT_BLANK: Final[str] = "blank"


class ComposerEvent(str, Enum):
    """События сборки описания в логе."""

    INVALID_LANGUAGE = "heading_cache_invalid_language_format"
    FALLBACK_EN = "heading_fallback_en"


class HeadingKind(str, Enum):
    """Блок описания со своим заголовком."""

    OFFICIAL_LINKS = "official_links"
    RECOMMENDED_MATERIALS = "recommended_materials"


class LayoutPart(str, Enum):
    """Части описания в строке раскладки (`tail_layout`)."""

    BODY = "body"
    RECOMMENDED = "recommended_materials"
    OFFICIAL = "official_links"
    CTA = "cta"
    HASHTAGS = "hashtags"


@dataclass(frozen=True)
class PublishHeadings:
    """Заголовки блоков по видам и языкам."""

    headings: Mapping[str, Mapping[str, str]]

    @classmethod
    def load(cls) -> PublishHeadings:
        return cls(headings=TextResource(HEADINGS_RESOURCE).data)

    def official_links(self, language: str) -> str:
        return self.resolve(HeadingKind.OFFICIAL_LINKS, language)

    def recommended_materials(self, language: str) -> str:
        return self.resolve(HeadingKind.RECOMMENDED_MATERIALS, language)

    def resolve(self, kind: HeadingKind, language: str) -> str:
        """Заголовок вида на языке; не знаем языка — английский."""
        by_language: Mapping[str, str] = self.headings[kind.value]
        normalized: str = language.strip().lower()
        if normalized in INVALID_LANGUAGES:
            return by_language[FALLBACK_LANGUAGE]
        if not LanguageCode(normalized).is_shaped:
            LogEvent.of(ComposerEvent.INVALID_LANGUAGE, kind=kind, language=repr(language)).emit(LOGGER, logging.WARNING)
            return by_language[FALLBACK_LANGUAGE]
        heading: str | None = by_language.get(normalized)
        if heading:
            return heading
        LogEvent.of(ComposerEvent.FALLBACK_EN, kind=kind, language=normalized).emit(LOGGER)
        return by_language[FALLBACK_LANGUAGE]


@dataclass(frozen=True)
class RecommendedEntry:
    """Рекомендуемое видео в описании: его название и короткая ссылка `https://youtu.be/<id>`."""

    title: str
    url: str

    @property
    def text(self) -> str:
        """Запись блока: «✅ название», следующей строкой «👉 ссылка»."""
        return RECOMMENDED_ENTRY.format(title=self.title, url=self.url)


@dataclass(frozen=True)
class DescriptionParts:
    """Части описания: тело, строка хештегов, рекомендуемые видео, официальные ссылки, призыв.

    Опубликованное описание призыва не несёт (призыв не публикуется никогда); поле нужно раскладке до отбрасывания.
    """

    body: str
    hashtags_line: str = ""
    recommended: tuple[RecommendedEntry, ...] = ()
    official_urls: tuple[str, ...] = ()
    cta: str = ""

    @property
    def layout(self) -> str:
        """Раскладка частей: `body_blank_official_links_blank_hashtags` и подобное; частей нет — `empty`."""
        parts: list[str] = [LayoutPart.BODY.value] if self.body else []
        for present, part in (
            (bool(self.recommended), LayoutPart.RECOMMENDED),
            (bool(self.official_urls), LayoutPart.OFFICIAL),
            (bool(self.cta), LayoutPart.CTA),
            (bool(self.hashtags_line), LayoutPart.HASHTAGS),
        ):
            if present:
                parts.extend((LAYOUT_BLANK, part.value))
        return LAYOUT_JOINER.join(parts) if parts else LAYOUT_EMPTY

    def compose(self, language: str, headings: PublishHeadings) -> str:
        """Описание: части через пустую строку по порядку — тело, рекомендуемые, официальные, призыв, хештеги."""
        parts: list[str] = []
        if self.body:
            parts.append(self.body.strip())
        if self.recommended:
            parts.append(self._recommended_block(language, headings))
        if self.official_urls:
            parts.append(self._official_block(language, headings))
        if self.cta:
            parts.append(self.cta.strip())
        if self.hashtags_line:
            parts.append(self.hashtags_line.strip())
        return PARAGRAPH_BREAK.join(part for part in parts if part).strip()

    def _official_block(self, language: str, headings: PublishHeadings) -> str:
        urls: list[str] = [WebLink.of(url).official_display for url in self.official_urls if url.strip()]
        return NEWLINE.join([headings.official_links(language), *urls]).strip()

    def _recommended_block(self, language: str, headings: PublishHeadings) -> str:
        entries: list[str] = [entry.text for entry in self.recommended]
        return PARAGRAPH_BREAK.join([headings.recommended_materials(language), *entries])
