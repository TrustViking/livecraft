"""Официальные ссылки источников слота: какие ссылки из описаний видео годятся для описания эфира.

Оценка ссылки-кандидата — одна формула (`LinkCandidate.score`: https, контекст строки, частота домена с потолком, штраф
за query, короткая ссылка — выше); порядок — один (`RankedLinks`: выше оценка — раньше, при равной — более ранний
кандидат). Строки описаний источников обходит один объект — `SourceDescriptionLines`. Отборов два, у каждого свой
вид ссылки и свой контекст строки:
- при проверке ответа (`OfficialLinkSelection`): ссылки http(s) без меток слежения, YouTube отбрасывается, контекст —
  лексикон `lexicon_official_link_hints.txt`; лучшие по одной на ключ повтора, не больше трёх;
- в описании эфира после санации (`AuthoritativeLinks`): ссылки после чистки санации (`SourceLink`), контекст —
  заголовок «🌐 …:» или подсказка `lexicon_authoritative_link_hints.txt`; до трёх лучших по виду ссылки блока, затем
  все новые ссылки текста ответа (`TextLinks`) без предела. Ссылка самого видео в отбор не идёт: ссылка ряда — всегда
  видео YouTube, а YouTube в официальные ссылки не берётся. Рекомендуемые видео — задача 3.14b; счётчики ссылок YouTube
  в описаниях источников считаются уже здесь (сети они не требуют).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.core.text_format import NEWLINE
from app.core.web_link import URL_PATTERN, WebLink
from app.llm.merges.rules import (
    OFFICIAL_LINK_CONTEXT_SCORE,
    OFFICIAL_LINK_DOMAIN_SCORE_CAP,
    OFFICIAL_LINK_DOMAIN_SCORE_STEP,
    OFFICIAL_LINK_HTTPS_SCORE,
    OFFICIAL_LINK_LENGTH_SCORE,
    OFFICIAL_LINK_LENGTH_STEP,
    OFFICIAL_LINK_QUERY_PENALTY,
    OFFICIAL_LINKS_KEPT_MAX,
)
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.resources.loader import TextResource
from app.sources.video import SourceVideo
from app.texts.description_marks import is_official_links_heading
from app.texts.paragraphs import normalize_newlines
from app.texts.phrase_lexicon import PhraseLexicon
from app.texts.source_link import SourceLink

LOGGER = get_logger(LogArea.LLM)

OFFICIAL_LINK_HINTS_RESOURCE: Final[str] = "lexicon_official_link_hints.txt"
PUBLISH_LINK_HINTS_RESOURCE: Final[str] = "lexicon_authoritative_link_hints.txt"
MIN_SOURCE_HITS_REPEATED: Final[int] = 2
UNKNOWN_DOMAIN_COUNT: Final[int] = 1        # домен, которого нет среди кандидатов, считается встреченным один раз
URL_SOURCES_MODE: Final[str] = "authoritative_non_youtube_from_inputs_plus_script_selected_recommended_materials"


class LinksEvent(str, Enum):
    """События отбора ссылок описания в логе."""

    BUILT = "merged_source_urls_built"
    CLEANED = "merged_source_urls_cleaned"


@dataclass(frozen=True)
class OfficialLinkHints:
    """Подсказки «это официальная ссылка» в строке описания — подстроки в нижнем регистре: `hints` — при проверке
    ответа, `publish_hints` — при отборе ссылок описания эфира."""

    hints: PhraseLexicon
    publish_hints: PhraseLexicon

    @classmethod
    def load(cls) -> OfficialLinkHints:
        return cls(
            hints=PhraseLexicon(TextResource(OFFICIAL_LINK_HINTS_RESOURCE).lines),
            publish_hints=PhraseLexicon(TextResource(PUBLISH_LINK_HINTS_RESOURCE).lines),
        )

    def has_context(self, line: str) -> bool:
        """В строке (без краёв, нижний регистр) есть подсказка проверки ответа."""
        normalized_line: str = line.strip().lower()
        return bool(normalized_line) and self.hints.found_in(normalized_line)

    def has_publish_context(self, line: str) -> bool:
        """Строка — заголовок «🌐 …:» или в ней (нижний регистр) есть подсказка описания эфира."""
        return is_official_links_heading(line) or self.publish_hints.found_in(line.lower())


@dataclass(frozen=True)
class DescriptionLine:
    """Строка описания источника без краёв и номер источника в слоте."""

    text: str
    source_index: int

    @property
    def raw_links(self) -> tuple[str, ...]:
        """Ссылки http(s) строки как есть."""
        return tuple(match.group(0) for match in URL_PATTERN.finditer(self.text))

    @property
    def official_candidates(self) -> tuple[str, ...]:
        """Ссылки строки без меток слежения и обрамления; неполные и YouTube не берутся (проверка ответа)."""
        urls: tuple[str | None, ...] = tuple(WebLink.of(raw).candidate for raw in self.raw_links)
        return tuple(url for url in urls if url is not None and not WebLink.of(url).is_youtube)

    @property
    def sanitized_links(self) -> tuple[str, ...]:
        """Ссылки строки после чистки санации; неполные не берутся."""
        links: tuple[SourceLink, ...] = tuple(SourceLink.of(raw.strip()) for raw in self.raw_links)
        return tuple(link.url for link in links if link.url is not None)


@dataclass(frozen=True)
class SourceDescriptionLines:
    """Все строки описаний источников слота по порядку; видео без данных даёт пустое описание."""

    lines: tuple[DescriptionLine, ...]

    @classmethod
    def of(cls, descriptions: Sequence[str]) -> SourceDescriptionLines:
        return cls(
            tuple(
                DescriptionLine(raw_line.strip(), index)
                for index, description in enumerate(descriptions)
                for raw_line in normalize_newlines(description).split(NEWLINE)
            )
        )

    @classmethod
    def of_sources(cls, sources: Sequence[SourceVideo]) -> SourceDescriptionLines:
        return cls.of([source.text.description for source in sources])


@dataclass(frozen=True)
class LinkCandidate:
    """Кандидат в официальные ссылки: ссылка, есть ли у её строки контекст «официальная», порядок кандидата."""

    url: str
    has_context: bool
    index: int

    @property
    def host(self) -> str:
        return WebLink.of(self.url).host

    def score(self, domain_counts: Counter[str]) -> int:
        """Оценка: https, контекст строки, частота домена (с потолком), штраф за query, короткая ссылка — выше."""
        link: WebLink = WebLink.of(self.url)
        score: int = OFFICIAL_LINK_HTTPS_SCORE if link.is_https else 0
        if self.has_context:
            score += OFFICIAL_LINK_CONTEXT_SCORE
        domain_count: int = domain_counts.get(link.host, UNKNOWN_DOMAIN_COUNT)
        score += min(OFFICIAL_LINK_DOMAIN_SCORE_CAP, domain_count * OFFICIAL_LINK_DOMAIN_SCORE_STEP)
        if link.has_query:
            score -= OFFICIAL_LINK_QUERY_PENALTY
        return score + max(0, OFFICIAL_LINK_LENGTH_SCORE - len(link.text) // OFFICIAL_LINK_LENGTH_STEP)


@dataclass(frozen=True)
class RankedLinks:
    """Кандидаты по оценке: выше — раньше, при равной оценке — более ранний кандидат. Частота домена — по кандидатам."""

    candidates: tuple[LinkCandidate, ...]

    @property
    def urls(self) -> tuple[str, ...]:
        domain_counts: Counter[str] = Counter(candidate.host for candidate in self.candidates)
        ranked: list[LinkCandidate] = sorted(
            self.candidates, key=lambda candidate: (-candidate.score(domain_counts), candidate.index)
        )
        return tuple(candidate.url for candidate in ranked)


@dataclass(frozen=True)
class OfficialLinkSelection:
    """Сколько ссылок (не YouTube) нашлось в описаниях источников и какие из них оставлены (не больше трёх)."""

    found_in_sources: int
    kept_links: tuple[str, ...]

    @classmethod
    def of(cls, lines: SourceDescriptionLines, hints: OfficialLinkHints) -> OfficialLinkSelection:
        """Отбор по сырым описаниям источников: лучшие по одной на ключ повтора."""
        candidates: list[LinkCandidate] = []
        for line in lines.lines:
            for url in line.official_candidates:
                candidates.append(LinkCandidate(url, hints.has_context(line.text), len(candidates)))
        kept: list[str] = []
        seen_keys: set[str] = set()
        for url in RankedLinks(tuple(candidates)).urls:
            key: str = WebLink.of(url).key
            if key not in seen_keys and len(kept) < OFFICIAL_LINKS_KEPT_MAX:
                seen_keys.add(key)
                kept.append(url)
        return cls(found_in_sources=len(candidates), kept_links=tuple(kept))

    @classmethod
    def for_sources(cls, sources: Sequence[SourceVideo], hints: OfficialLinkHints) -> OfficialLinkSelection:
        """Отбор по описаниям видео слота."""
        return cls.of(SourceDescriptionLines.of_sources(sources), hints)


@dataclass(frozen=True)
class DescriptionLink:
    """Ссылка из строки описания источника после чистки: ссылка, строка (без краёв), номер источника."""

    url: str
    line: str
    source_index: int

    @property
    def is_youtube(self) -> bool:
        return WebLink.of(self.url).unwrapped.is_youtube


@dataclass(frozen=True)
class SourceDescriptionLinks:
    """Все ссылки описаний источников слота после чистки санации и счётчики ссылок YouTube."""

    links: tuple[DescriptionLink, ...]

    @classmethod
    def of(cls, lines: SourceDescriptionLines) -> SourceDescriptionLinks:
        return cls(
            tuple(
                DescriptionLink(url=url, line=line.text, source_index=line.source_index)
                for line in lines.lines
                for url in line.sanitized_links
            )
        )

    def candidates(self, hints: OfficialLinkHints) -> RankedLinks:
        """Ссылки описаний (не YouTube) в официальные — по оценке; контекст — строка ссылки."""
        non_youtube: tuple[DescriptionLink, ...] = tuple(link for link in self.links if not link.is_youtube)
        return RankedLinks(
            tuple(
                LinkCandidate(link.url, hints.has_publish_context(link.line), index)
                for index, link in enumerate(non_youtube)
            )
        )

    @property
    def raw_youtube_found(self) -> int:
        return sum(1 for link in self.links if link.is_youtube)

    @property
    def youtube_sources(self) -> dict[str, set[int]]:
        """Разные ссылки YouTube в порядке первого появления и источники, где каждая встретилась."""
        sources: dict[str, set[int]] = {}
        for link in self.links:
            if link.is_youtube:
                sources.setdefault(link.url, set()).add(link.source_index)
        return sources

    @property
    def repeated_youtube(self) -> int:
        """Ссылок YouTube, которые встретились хотя бы в двух источниках."""
        return sum(1 for hits in self.youtube_sources.values() if len(hits) >= MIN_SOURCE_HITS_REPEATED)


@dataclass(frozen=True)
class TextLinks:
    """Ссылки текста ответа модели, снятые санацией (из блоков «🌐 …:» и хвоста), и сколько неполных она отбросила."""

    urls: tuple[str, ...]
    malformed: int = 0

    @property
    def preserved(self) -> tuple[str, ...]:
        """Полные ссылки не YouTube — без краёв: они идут в описание после ссылок источников."""
        stripped: tuple[str, ...] = tuple(url.strip() for url in self.urls if url.strip())
        return tuple(url for url in stripped if WebLink.of(url).is_complete and not WebLink.of(url).unwrapped.is_youtube)

    @property
    def youtube_count(self) -> int:
        """Ссылок YouTube в тексте ответа: в официальные они не идут."""
        return sum(1 for url in self.urls if WebLink.of(url).unwrapped.is_youtube)

    @property
    def malformed_dropped(self) -> int:
        """Неполных ссылок: отброшенных санацией и неполных среди снятых."""
        return self.malformed + sum(1 for url in self.urls if not WebLink.of(url).is_complete)


@dataclass
class AuthoritativeSelection:
    """Отбор официальных ссылок: ссылки в виде блока, ключи повтора, сколько повторов отброшено."""

    urls: list[str] = field(default_factory=list)
    keys: set[str] = field(default_factory=set)
    duplicates: int = 0

    def offer(self, url: str) -> bool:
        """Взять ссылку, если её ключа ещё нет; повтор — посчитать и не брать."""
        display: str = WebLink.of(url).official_display
        key: str = WebLink.of(display).key
        if key in self.keys:
            self.duplicates += 1
            return False
        self.keys.add(key)
        self.urls.append(display)
        return True


@dataclass(frozen=True)
class AuthoritativeLinks:
    """Официальные ссылки описания после санации, без рекомендуемых видео.

    Сначала — до трёх лучших ссылок описаний источников (по одной на ключ повтора), затем — все ссылки текста ответа
    модели, которых ещё нет (без предела). Рекомендуемые видео выбираются в задаче 3.14b: здесь их нет, но счётчики
    ссылок YouTube в описаниях источников считаются.
    """

    language: str
    urls: tuple[str, ...]
    inspected: int
    emitted_source_video_urls: int
    duplicate_urls_removed: int
    text: TextLinks
    description_links: SourceDescriptionLinks = field(repr=False)

    @classmethod
    def of(
        cls, language: str, sources: Sequence[SourceVideo], text: TextLinks, hints: OfficialLinkHints
    ) -> AuthoritativeLinks:
        """Отбор по источникам и ссылкам текста ответа; строки лога отбора."""
        description_links: SourceDescriptionLinks = SourceDescriptionLinks.of(SourceDescriptionLines.of_sources(sources))
        selection: AuthoritativeSelection = AuthoritativeSelection()
        for url in description_links.candidates(hints).urls:
            if selection.offer(url) and len(selection.urls) >= OFFICIAL_LINKS_KEPT_MAX:
                break
        from_sources: int = len(selection.urls)
        for url in text.preserved:
            selection.offer(url)
        links: AuthoritativeLinks = cls(
            language=language,
            urls=tuple(selection.urls),
            inspected=len(sources),
            emitted_source_video_urls=from_sources,
            duplicate_urls_removed=selection.duplicates,
            text=text,
            description_links=description_links,
        )
        for event in links.events:
            event.emit(LOGGER)
        return links

    @property
    def raw_youtube_urls_found(self) -> int:
        return self.description_links.raw_youtube_found

    @property
    def deduped_youtube_candidates(self) -> int:
        return len(self.description_links.youtube_sources)

    @property
    def repeated_youtube_candidates(self) -> int:
        return self.description_links.repeated_youtube

    @property
    def events(self) -> tuple[LogEvent, ...]:
        """Строка `merged_source_urls_built` и, если что-то отброшено, `merged_source_urls_cleaned`."""
        built: LogEvent = LogEvent.of(
            LinksEvent.BUILT,
            lang=self.language,
            inspected=self.inspected,
            emitted=len(self.urls),
            selected_youtube_urls=0,
            deduped=self.duplicate_urls_removed,
            preserved_non_youtube_tail_urls=len(self.text.preserved),
        )
        built = built.extended(
            raw_youtube_urls_found=self.raw_youtube_urls_found,
            deduped_youtube_candidates=self.deduped_youtube_candidates,
            repeated_youtube_candidates=self.repeated_youtube_candidates,
            ignored_llm_youtube_urls=self.text.youtube_count,
            source_urls_mode=URL_SOURCES_MODE,
        )
        if self.text.malformed_dropped <= 0:
            return (built,)
        cleaned: LogEvent = LogEvent.of(
            LinksEvent.CLEANED, lang=self.language, malformed_tail_urls_dropped=self.text.malformed_dropped
        )
        return built, cleaned
