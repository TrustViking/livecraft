"""Рекомендуемые материалы описания эфира: до двух видео YouTube, на которые ссылаются описания источников слота.

Кандидат — видео YouTube из описания источника (канал и плейлист чистка ссылки уже отбросила, ссылка — вида
`https://youtu.be/<id>`). Видео самих источников слота кандидатом не бывает: его и так показывает эфир.

Признаки кандидата: в скольких источниках слота он встретился; сколько слов его контекста совпало со словами ответа
модели (контекст — строка ссылки без ссылок и хештегов, пустая строка — название источника; слова ответа — из названия
и тела после санации; частые слова не считаются); сколько раз он встретился; где впервые. Порядок — по этим признакам
в этом порядке: видео, которое советуют несколько источников, важнее; при равных — то, что ближе к теме эфира.

Порог: у слота из двух источников и меньше — хоть одно общее слово; у слота побольше — видео встретилось в двух
источниках или совпали два слова. Прошедшие порог проверяются по порядку (`SourceCatalog.check`: данные видео и язык),
берутся первые два на языке слота без спора сигналов; не прошедший порог не проверяется — yt-dlp для него не зовётся.
Не взято ни одно — по порядку проверяются ещё не проверенные видео, встреченные в двух источниках, и берётся первое
годное: видео, которое советуют оба источника, уместно и без общих слов.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from enum import Enum

from app.core.sequence import unique_in_order
from app.llm.merges.links import DescriptionLink, LinksBlock, SourceDescriptionLinks
from app.llm.merges.rules import (
    RECOMMENDED_FEW_MIN_OVERLAP,
    RECOMMENDED_FEW_SOURCES,
    RECOMMENDED_MAX,
    RECOMMENDED_MIN_OVERLAP,
    RECOMMENDED_REPEATED_HITS,
)
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.sources.video import SourceCatalog, SourceVideo, VideoCheck, VideoFit
from app.texts.analysis_text import CleanedLine
from app.texts.composer import RecommendedEntry
from app.texts.similarity import StopWords

LOGGER: logging.Logger = get_logger(LogArea.LLM)


class RecommendedEvent(str, Enum):
    """События отбора рекомендуемых материалов в логе."""

    CANDIDATES_BUILT = "recommended_materials_candidates_built"
    LANGUAGE_FILTERED = "recommended_candidate_language_filtered"
    FALLBACK_APPLIED = "recommended_materials_fallback_applied"


@dataclass(frozen=True)
class YouTubeMention:
    """Одно упоминание видео YouTube в описании источника: ссылка, номер источника в слоте, слова темы контекста."""

    link: str
    source_index: int
    words: frozenset[str]

    @classmethod
    def of(cls, link: DescriptionLink, sources: Sequence[SourceVideo], stop_words: StopWords) -> YouTubeMention:
        """Контекст — строка ссылки без ссылок и хештегов; в строке ничего, кроме них, — название источника."""
        context: str = CleanedLine.of(link.line).text or sources[link.source_index].text.title
        return cls(link=link.url, source_index=link.source_index, words=stop_words.topic_words(context))


@dataclass(frozen=True)
class RecommendedCandidate:
    """Кандидат в рекомендуемые: ссылка, в скольких источниках встретился, сколько раз всего, сколько слов его
    контекста совпало со словами ответа, порядок первого появления."""

    link: str
    source_hits: int
    occurrences: int
    overlap: int
    first_seen: int

    @classmethod
    def of(cls, mentions: Sequence[YouTubeMention], summary_words: frozenset[str], first_seen: int) -> RecommendedCandidate:
        """Кандидат по всем упоминаниям одного видео: слова контекста — все слова его упоминаний."""
        words: frozenset[str] = frozenset[str]().union(*(mention.words for mention in mentions))
        return cls(
            link=mentions[0].link,
            source_hits=len({mention.source_index for mention in mentions}),
            occurrences=len(mentions),
            overlap=len(words & summary_words),
            first_seen=first_seen,
        )

    @property
    def is_repeated(self) -> bool:
        """Встретился хотя бы в двух источниках слота."""
        return self.source_hits >= RECOMMENDED_REPEATED_HITS

    def passes(self, few_sources: bool) -> bool:
        """Порог: у слота из двух источников и меньше — хоть одно общее слово; иначе — два источника или два слова."""
        if few_sources:
            return self.overlap >= RECOMMENDED_FEW_MIN_OVERLAP
        return self.is_repeated or self.overlap >= RECOMMENDED_MIN_OVERLAP

    @property
    def sort_key(self) -> tuple[int, ...]:
        """Больше источников — выше; затем больше общих слов; затем чаще; затем раньше."""
        return -self.source_hits, -self.overlap, -self.occurrences, self.first_seen


@dataclass(frozen=True)
class RecommendedCandidates:
    """Кандидаты слота по порядку, число источников слота, число слов ответа и число ссылок YouTube в описаниях."""

    candidates: tuple[RecommendedCandidate, ...]
    source_count: int
    summary_words: int
    raw_youtube: int

    @classmethod
    def of(
        cls, description_links: SourceDescriptionLinks, sources: Sequence[SourceVideo], summary: str, stop_words: StopWords
    ) -> RecommendedCandidates:
        """Кандидаты из ссылок YouTube описаний источников, кроме видео самих источников; `summary` — текст ответа."""
        own: frozenset[str] = frozenset(video.link for video in sources)
        mentions: tuple[YouTubeMention, ...] = tuple(
            YouTubeMention.of(link, sources, stop_words) for link in description_links.youtube if link.url not in own
        )
        summary_words: frozenset[str] = stop_words.topic_words(summary)
        found: tuple[RecommendedCandidate, ...] = tuple(
            RecommendedCandidate.of(tuple(mention for mention in mentions if mention.link == link), summary_words, index)
            for index, link in enumerate(unique_in_order(mention.link for mention in mentions))
        )
        return cls(
            candidates=tuple(sorted(found, key=lambda candidate: candidate.sort_key)),
            source_count=len(sources),
            summary_words=len(summary_words),
            raw_youtube=len(description_links.youtube),
        )

    @property
    def few_sources(self) -> bool:
        """Источников слота не больше двух: порог ниже."""
        return self.source_count <= RECOMMENDED_FEW_SOURCES

    @property
    def passing(self) -> tuple[RecommendedCandidate, ...]:
        """Прошедшие порог, по порядку."""
        return tuple(candidate for candidate in self.candidates if candidate.passes(self.few_sources))

    @property
    def repeated(self) -> tuple[RecommendedCandidate, ...]:
        """Встреченные хотя бы в двух источниках, по порядку."""
        return tuple(candidate for candidate in self.candidates if candidate.is_repeated)


@dataclass
class RecommendedPicks:
    """Отбор по ходу: язык слота, видео запуска, взятые записи и проверенные ссылки."""

    language: str
    catalog: SourceCatalog = field(repr=False)
    entries: list[RecommendedEntry] = field(default_factory=list)
    checked: list[str] = field(default_factory=list)

    @property
    def is_full(self) -> bool:
        return len(self.entries) >= RECOMMENDED_MAX

    def take(self, candidate: RecommendedCandidate) -> bool:
        """Проверить видео кандидата и взять, если оно годится слоту; негодное — строкой лога."""
        check: VideoCheck = self.catalog.check(candidate.link)
        self.checked.append(candidate.link)
        fit: VideoFit = check.fit(self.language)
        if fit is VideoFit.FITS:
            self.entries.append(RecommendedEntry(title=check.title, url=candidate.link))
            return True
        filtered: LogEvent = LogEvent.of(RecommendedEvent.LANGUAGE_FILTERED, url=candidate.link, target=self.language)
        filtered.extended(fit=fit, detected=check.language_code).emit(LOGGER)
        return False

    def fall_back(self, candidates: Iterable[RecommendedCandidate]) -> bool:
        """Первое годное из ещё не проверенных видео `candidates`; взято — строкой лога."""
        for candidate in candidates:
            if candidate.link not in self.checked and self.take(candidate):
                applied: LogEvent = LogEvent.of(RecommendedEvent.FALLBACK_APPLIED, url=candidate.link)
                applied.extended(source_hits=candidate.source_hits, overlap=candidate.overlap).emit(LOGGER)
                return True
        return False


@dataclass(frozen=True)
class RecommendedMaterials:
    """Рекомендуемые материалы слота: язык, записи блока, кандидаты, сколько видео проверено, взято ли запасное."""

    language: str
    entries: tuple[RecommendedEntry, ...]
    candidates: RecommendedCandidates = field(repr=False)
    checked: int
    fallback_applied: bool

    @classmethod
    def select(cls, candidates: RecommendedCandidates, language: str, catalog: SourceCatalog) -> RecommendedMaterials:
        """Первые два годных из прошедших порог; ни одного — первое годное из встреченных в двух источниках."""
        picks: RecommendedPicks = RecommendedPicks(language, catalog)
        for candidate in candidates.passing:
            if picks.is_full:
                break
            picks.take(candidate)
        fallback: bool = not picks.entries and picks.fall_back(candidates.repeated)
        materials: RecommendedMaterials = cls(language, tuple(picks.entries), candidates, len(picks.checked), fallback)
        materials.event.emit(LOGGER)
        return materials

    @property
    def block(self) -> LinksBlock:
        return LinksBlock.EMITTED if self.entries else LinksBlock.ABSENT

    @property
    def event(self) -> LogEvent:
        """Строка `recommended_materials_candidates_built`: кандидаты, порог, проверка и итог."""
        candidates: RecommendedCandidates = self.candidates
        built: LogEvent = LogEvent.of(
            RecommendedEvent.CANDIDATES_BUILT,
            lang=self.language,
            summary_words=candidates.summary_words,
            raw_youtube_urls_found=candidates.raw_youtube,
            candidates=len(candidates.candidates),
        )
        return built.extended(
            repeated=len(candidates.repeated),
            passing=len(candidates.passing),
            checked=self.checked,
            selected=len(self.entries),
            fallback=self.fallback_applied,
        )

    def extend(self, event: LogEvent) -> LogEvent:
        """Поля строки `publish_sanitation_applied` о рекомендуемых материалах."""
        return event.extended(
            raw_youtube_urls_found=self.candidates.raw_youtube,
            deduped_youtube_candidates=len(self.candidates.candidates),
            repeated_youtube_candidates=len(self.candidates.repeated),
            recommended_materials_final_count=len(self.entries),
            recommended_materials_block=self.block,
        )
