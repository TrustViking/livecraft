"""Официальные ссылки источников слота: какие ссылки из описаний видео годятся для описания эфира.

Правило — `merge_links.py::_extract_official_links_from_sources` restreamer, поведение как есть (CLAUDE.md §14
решение 23): из каждой строки описания каждого источника берутся ссылки http(s) без меток слежения, YouTube
отбрасывается; каждая ссылка получает оценку (https, контекст строки, частота домена, query, длина); лучшие по оценке
(при равенстве — более ранняя) идут по одной на ключ повтора, не больше трёх. Контекст строки — лексикон
`lexicon_official_link_hints.txt` (побайтно из restreamer).

Не перенесено как мёртвое в бою донора: вставка блока ссылок в описание (`_inject_official_links_block_if_missing`,
`_description_has_official_links_block`) — исполнитель донора всегда ставит `fill_applied=False`.

Официальные ссылки описания после санации (задача 3.14) — своё правило донора, похожее, но не то же:
`publish\\sanitizers\\url_selector.py::AuthoritativeUrlSelector.select_authoritative_non_youtube` и `build_authoritative`
→ `AuthoritativeLinks`. Отличия от отбора выше: свой список подсказок контекста и заголовок «🌐 …:», кандидаты-ссылки самих
видео, чистка ссылок санации (`SourceLink`), вид ссылки блока (`WebLink.official_display`), ссылки хвоста ответа
без предела после трёх лучших. Рекомендуемые видео (`select_recommended_youtube`) — задача 3.14b; счётчики ссылок YouTube
в описаниях источников считаются уже здесь (сети они не требуют).
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
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
from app.observability.log_event import LogArea, get_logger
from app.resources.loader import TextResource
from app.sources.video import SourceVideo
from app.texts.description_marks import is_official_links_heading
from app.texts.paragraphs import normalize_newlines
from app.texts.phrase_lexicon import PhraseLexicon
from app.texts.source_link import SourceLink

LOGGER = get_logger(LogArea.LLM)

OFFICIAL_LINK_HINTS_RESOURCE: Final[str] = "lexicon_official_link_hints.txt"


@dataclass(frozen=True)
class OfficialLinkHints:
    """Подсказки «это официальная ссылка» в строке описания: подстроки в нижнем регистре."""

    hints: PhraseLexicon

    @classmethod
    def load(cls) -> OfficialLinkHints:
        return cls(hints=PhraseLexicon(TextResource(OFFICIAL_LINK_HINTS_RESOURCE).lines))

    def has_context(self, line: str) -> bool:
        """В строке (без краёв, нижний регистр) есть подсказка."""
        normalized_line: str = (line or "").strip().lower()
        return bool(normalized_line) and self.hints.found_in(normalized_line)


@dataclass(frozen=True)
class OfficialLinkCandidate:
    """Ссылка из описания источника (уже нормализованная) и строка, в которой она стоит."""

    url: str
    line: str
    index: int              # порядок в источниках: при равной оценке побеждает более ранняя

    @property
    def domain(self) -> str:
        return WebLink.of(self.url).host

    def score(self, domain_counts: Counter[str], hints: OfficialLinkHints) -> int:
        link: WebLink = WebLink.of(self.url)
        return OfficialLinkScore(link, hints.has_context(self.line), domain_counts.get(self.domain, 1)).value


@dataclass(frozen=True)
class OfficialLinkScore:
    """Оценка ссылки-кандидата в официальные — одна формула обоих отборов: https, контекст строки, частота домена
    (с потолком), штраф за query, короткая ссылка — выше."""

    link: WebLink
    has_context: bool
    domain_count: int

    @property
    def value(self) -> int:
        score: int = OFFICIAL_LINK_HTTPS_SCORE if self.link.is_https else 0
        if self.has_context:
            score += OFFICIAL_LINK_CONTEXT_SCORE
        score += min(OFFICIAL_LINK_DOMAIN_SCORE_CAP, self.domain_count * OFFICIAL_LINK_DOMAIN_SCORE_STEP)
        if self.link.has_query:
            score -= OFFICIAL_LINK_QUERY_PENALTY
        return score + max(0, OFFICIAL_LINK_LENGTH_SCORE - len(self.link.text) // OFFICIAL_LINK_LENGTH_STEP)


@dataclass(frozen=True)
class OfficialLinkSelection:
    """Сколько ссылок (не YouTube) нашлось в описаниях источников и какие из них оставлены (не больше трёх)."""

    found_in_sources: int
    kept_links: tuple[str, ...]

    @classmethod
    def of(cls, descriptions: Sequence[str], hints: OfficialLinkHints) -> OfficialLinkSelection:
        """Отбор по сырым описаниям источников (как `video.metadata.description` у донора)."""
        candidates: list[OfficialLinkCandidate] = cls._candidates(descriptions)
        if not candidates:
            return cls(found_in_sources=0, kept_links=())
        domain_counts: Counter[str] = Counter(candidate.domain for candidate in candidates)
        ranked: list[tuple[int, int, str]] = sorted(
            ((candidate.score(domain_counts, hints), -candidate.index, candidate.url) for candidate in candidates),
            reverse=True,
        )
        kept: list[str] = []
        seen_keys: set[str] = set()
        for _, _, url in ranked:
            key: str = WebLink.of(url).key
            if key in seen_keys:
                continue
            seen_keys.add(key)
            kept.append(url)
            if len(kept) >= OFFICIAL_LINKS_KEPT_MAX:
                break
        return cls(found_in_sources=len(candidates), kept_links=tuple(kept))

    @classmethod
    def for_sources(cls, sources: Sequence[SourceVideo], hints: OfficialLinkHints) -> OfficialLinkSelection:
        """Отбор по описаниям видео слота; видео без данных даёт пустое описание."""
        return cls.of([source.text.description for source in sources], hints)

    @staticmethod
    def _candidates(descriptions: Sequence[str]) -> list[OfficialLinkCandidate]:
        candidates: list[OfficialLinkCandidate] = []
        for description in descriptions:
            for line in normalize_newlines(description).split(NEWLINE):
                for match in URL_PATTERN.finditer(line):
                    url: str | None = WebLink.of(match.group(0)).candidate
                    if url is None or WebLink.of(url).is_youtube:
                        continue
                    candidates.append(OfficialLinkCandidate(url=url, line=line, index=len(candidates)))
        return candidates


# --- официальные ссылки описания после санации (restreamer `url_selector.py::AuthoritativeUrlSelector`)

# Контекст строки у отбора после санации — свой список донора (`select_authoritative_non_youtube`), не лексикон merge.
AUTHORITATIVE_CONTEXT_HINTS: Final[tuple[str, ...]] = ("official", "resource", "resources", "details", "site", "website")
MIN_SOURCE_HITS_REPEATED: Final[int] = 2
URL_SOURCES_MODE: Final[str] = "authoritative_non_youtube_from_inputs_plus_script_selected_recommended_materials"


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
    """Все ссылки описаний источников слота (`_extract_raw_description_urls` донора) и счётчики ссылок YouTube."""

    links: tuple[DescriptionLink, ...]

    @classmethod
    def of(cls, sources: Sequence[SourceVideo]) -> SourceDescriptionLinks:
        links: list[DescriptionLink] = []
        for index, source in enumerate(sources):
            for raw_line in normalize_newlines(source.text.description).split(NEWLINE):
                line: str = raw_line.strip()
                for match in URL_PATTERN.finditer(line):
                    cleaned: SourceLink = SourceLink.of(match.group(0).strip())
                    if cleaned.url is not None:
                        links.append(DescriptionLink(url=cleaned.url, line=line, source_index=index))
        return cls(links=tuple(links))

    @property
    def non_youtube(self) -> tuple[DescriptionLink, ...]:
        return tuple(link for link in self.links if not link.is_youtube)

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
class AuthoritativeCandidate:
    """Кандидат в официальные ссылки: ссылка, строка-контекст, порядок (при равной оценке раньше — выше)."""

    url: str
    context: str
    index: int

    def score(self, domain_counts: Counter[str]) -> int:
        """Оценка донора: https, контекст (заголовок «🌐 …:» или подсказка), частота домена, query, длина."""
        link: WebLink = WebLink.of(self.url)
        context: str = str(self.context or "")
        has_context: bool = is_official_links_heading(context) or any(
            hint in context.lower() for hint in AUTHORITATIVE_CONTEXT_HINTS
        )
        return OfficialLinkScore(link, has_context, domain_counts.get(link.host, 1)).value


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
    """Официальные ссылки описания после санации (`build_authoritative` донора без рекомендуемых видео).

    Сначала — до трёх лучших ссылок описаний источников и самих видео (по одной на ключ повтора), затем — все ссылки
    хвоста ответа модели, которых ещё нет (без предела). Рекомендуемые видео выбираются в задаче 3.14b: здесь их нет,
    но счётчики ссылок YouTube в описаниях источников считаются, как у донора.
    """

    language: str
    urls: tuple[str, ...]
    inspected: int
    emitted_source_video_urls: int
    duplicate_urls_removed: int
    preserved_tail: int
    ignored_llm_youtube_urls: int
    malformed_dropped: int
    raw_youtube_urls_found: int
    deduped_youtube_candidates: int
    repeated_youtube_candidates: int

    @classmethod
    def of(
        cls, language: str, sources: Sequence[SourceVideo], tail_urls: Sequence[str], malformed_tail: int
    ) -> AuthoritativeLinks:
        """Отбор по источникам и ссылкам хвоста; строки лога донора."""
        description_links: SourceDescriptionLinks = SourceDescriptionLinks.of(sources)
        selection: AuthoritativeSelection = AuthoritativeSelection()
        for url in cls._ranked(description_links, sources):
            if selection.offer(url) and len(selection.urls) >= OFFICIAL_LINKS_KEPT_MAX:
                break
        from_sources: int = len(selection.urls)
        tail: list[str] = [url.strip() for url in tail_urls if url.strip()]
        preserved: list[str] = [url for url in tail if WebLink.of(url).is_complete and not WebLink.of(url).unwrapped.is_youtube]
        for url in preserved:
            selection.offer(url)
        links: AuthoritativeLinks = cls(
            language=language,
            urls=tuple(selection.urls),
            inspected=len(sources),
            emitted_source_video_urls=from_sources,
            duplicate_urls_removed=selection.duplicates,
            preserved_tail=len(preserved),
            ignored_llm_youtube_urls=sum(1 for url in tail_urls if WebLink.of(url).unwrapped.is_youtube),
            malformed_dropped=malformed_tail + sum(1 for url in tail_urls if not WebLink.of(url).is_complete),
            raw_youtube_urls_found=description_links.raw_youtube_found,
            deduped_youtube_candidates=len(description_links.youtube_sources),
            repeated_youtube_candidates=description_links.repeated_youtube,
        )
        for line in links.log_lines:
            LOGGER.info("%s", line)
        return links

    @classmethod
    def _ranked(cls, links: SourceDescriptionLinks, sources: Sequence[SourceVideo]) -> list[str]:
        """Ссылки описаний (не YouTube), затем ссылки самих видео (не YouTube, контекст — название видео) — по оценке:
        выше — раньше, при равенстве — более ранний кандидат. Частота домена — только по ссылкам описаний."""
        candidates: list[AuthoritativeCandidate] = [
            AuthoritativeCandidate(url=link.url, context=link.line, index=index)
            for index, link in enumerate(links.non_youtube)
        ]
        for source in sources:
            video_url: str | None = cls._video_url(source)
            if not video_url or WebLink.of(video_url).unwrapped.is_youtube:
                continue
            title: str = source.text.title.strip()
            candidates.append(AuthoritativeCandidate(url=video_url, context=title, index=len(candidates)))
        domain_counts: Counter[str] = Counter(WebLink.of(link.url).host for link in links.non_youtube)
        ranked: list[tuple[int, int, str]] = sorted(
            ((candidate.score(domain_counts), -candidate.index, candidate.url) for candidate in candidates),
            reverse=True,
        )
        return [url for _, _, url in ranked]

    @staticmethod
    def _video_url(source: SourceVideo) -> str | None:
        """Ссылка самого видео (`_normalize_authoritative_video_url` донора): нормализованная ссылка ряда, ссылка
        метаданных, исходная ссылка ряда — первая полная; не YouTube — очищенная, YouTube — короткая ссылка."""
        for candidate in (source.link, source.metadata_url, source.table_link):
            link: SourceLink = SourceLink.of_video(candidate)
            if link.url is not None:
                return link.url
        return None

    @property
    def log_lines(self) -> tuple[str, ...]:
        """Строки донора `merged_source_urls_built` и, если что-то отброшено, `merged_source_urls_cleaned`."""
        built: str = (
            f"merged_source_urls_built lang={self.language} inspected={self.inspected} emitted={len(self.urls)} "
            f"selected_youtube_urls=0 deduped={self.duplicate_urls_removed} "
            f"preserved_non_youtube_tail_urls={self.preserved_tail} raw_youtube_urls_found={self.raw_youtube_urls_found} "
            f"deduped_youtube_candidates={self.deduped_youtube_candidates} "
            f"repeated_youtube_candidates={self.repeated_youtube_candidates} "
            f"ignored_llm_youtube_urls={self.ignored_llm_youtube_urls} source_urls_mode={URL_SOURCES_MODE}"
        )
        if self.malformed_dropped <= 0:
            return (built,)
        return built, f"merged_source_urls_cleaned lang={self.language} malformed_tail_urls_dropped={self.malformed_dropped}"
