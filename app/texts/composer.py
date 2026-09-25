"""Сборка описания эфира после санации: тело, рекомендуемые материалы, официальные ссылки, призыв, хештеги.

Перенесено из restreamer, поведение как есть: `app\\publish\\sanitizers\\description_composer.py`
(`DescriptionComposer.compose`, `resolve_layout`, `render_recommended_block`) и заголовки блоков
`app\\resources\\heading_resolver.py` (`_HARDCODED_SEED` — ресурс `publish_headings.json` без правки строк).

Заголовок блока — по языку описания: пустой, служебный (`unknown`, `other`, `none`, `und`, `xx`) или не двухбуквенный код
— английский, как у донора; язык, которого нет в файле, — тоже английский и строка лога `heading_fallback_en` (у донора —
перевод нейросетью с кешем на диске; это задача 3.14b). Рекомендуемые материалы рисуются строками «👉 ссылка» — так донор
рисовал их, когда название видео не получено; названия видео — задача 3.14b.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.url_text import normalize_official_link_display
from app.observability.logging_setup import get_logger
from app.resources.loader import TextResource

LOGGER = get_logger("texts")

HEADINGS_RESOURCE: Final[str] = "publish_headings.json"
FALLBACK_LANGUAGE: Final[str] = "en"
LANGUAGE_CODE_LENGTH: Final[int] = 2
INVALID_LANGUAGES: Final[frozenset[str]] = frozenset({"", "unknown", "other", "none", "und", "xx"})
RECOMMENDED_ENTRY: Final[str] = "👉 {url}"
PARAGRAPH_JOINER: Final[str] = "\n\n"
LINE_JOINER: Final[str] = "\n"
LAYOUT_JOINER: Final[str] = "_"
LAYOUT_EMPTY: Final[str] = "empty"
LAYOUT_BLANK: Final[str] = "blank"


class HeadingKind(str, Enum):
    """Блок описания со своим заголовком."""

    OFFICIAL_LINKS = "official_links"
    RECOMMENDED_MATERIALS = "recommended_materials"


class LayoutPart(str, Enum):
    """Части описания в строке раскладки (`tail_layout` донора)."""

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
        normalized: str = str(language or "").strip().lower()
        if normalized in INVALID_LANGUAGES:
            return by_language[FALLBACK_LANGUAGE]
        if not (len(normalized) == LANGUAGE_CODE_LENGTH and normalized.isascii() and normalized.isalpha()):
            LOGGER.warning("heading_cache_invalid_language_format kind=%s language=%r", kind.value, language)
            return by_language[FALLBACK_LANGUAGE]
        heading: str | None = by_language.get(normalized)
        if heading:
            return heading
        LOGGER.info("heading_fallback_en kind=%s language=%s", kind.value, normalized)
        return by_language[FALLBACK_LANGUAGE]


@dataclass(frozen=True)
class DescriptionParts:
    """Части описания: тело, строка хештегов, ссылки рекомендуемых видео, официальные ссылки, призыв.

    Опубликованное описание призыва не несёт (донор отбрасывает его всегда); поле нужно раскладке до отбрасывания.
    """

    body: str
    hashtags_line: str = ""
    recommended_urls: tuple[str, ...] = ()
    official_urls: tuple[str, ...] = ()
    cta: str = ""

    @property
    def layout(self) -> str:
        """Раскладка частей: `body_blank_official_links_blank_hashtags` и подобное; частей нет — `empty`."""
        parts: list[str] = [LayoutPart.BODY.value] if self.body else []
        for present, part in (
            (bool(self.recommended_urls), LayoutPart.RECOMMENDED),
            (bool(self.official_urls), LayoutPart.OFFICIAL),
            (bool(self.cta), LayoutPart.CTA),
            (bool(self.hashtags_line), LayoutPart.HASHTAGS),
        ):
            if present:
                parts.extend((LAYOUT_BLANK, part.value))
        return LAYOUT_JOINER.join(parts) if parts else LAYOUT_EMPTY

    def compose(self, language: str, headings: PublishHeadings) -> str:
        """Описание: части через пустую строку в порядке донора — тело, рекомендуемые, официальные, призыв, хештеги."""
        parts: list[str] = []
        if self.body:
            parts.append(self.body.strip())
        if self.recommended_urls:
            parts.append(self._recommended_block(language, headings))
        if self.official_urls:
            parts.append(self._official_block(language, headings))
        if self.cta:
            parts.append(self.cta.strip())
        if self.hashtags_line:
            parts.append(self.hashtags_line.strip())
        return PARAGRAPH_JOINER.join(part for part in parts if part).strip()

    def _official_block(self, language: str, headings: PublishHeadings) -> str:
        urls: list[str] = [normalize_official_link_display(url.strip()) for url in self.official_urls if url.strip()]
        return LINE_JOINER.join([headings.official_links(language), *urls]).strip()

    def _recommended_block(self, language: str, headings: PublishHeadings) -> str:
        entries: list[str] = [RECOMMENDED_ENTRY.format(url=url.strip()) for url in self.recommended_urls if url.strip()]
        if not entries:
            return ""
        LOGGER.info(
            "recommended_block_rendered_with_titles urls=%d titles_rendered=0 title_fetch_failures=%d",
            len(entries), len(entries),
        )
        return PARAGRAPH_JOINER.join([headings.recommended_materials(language), *entries]).strip()
