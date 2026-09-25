"""Официальные ссылки источников слота: какие ссылки из описаний видео годятся для описания эфира.

Правило — `merge_links.py::_extract_official_links_from_sources` restreamer, поведение как есть (CLAUDE.md §14
решение 23): из каждой строки описания каждого источника берутся ссылки http(s) без меток слежения, YouTube
отбрасывается; каждая ссылка получает оценку (https, контекст строки, частота домена, query, длина); лучшие по оценке
(при равенстве — более ранняя) идут по одной на ключ повтора, не больше трёх. Контекст строки — лексикон
`lexicon_official_link_hints.txt` (побайтно из restreamer).

Не перенесено как мёртвое в бою донора: вставка блока ссылок в описание (`_inject_official_links_block_if_missing`,
`_description_has_official_links_block`) — исполнитель донора всегда ставит `fill_applied=False`.
"""
from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final
from urllib.parse import SplitResult, urlsplit

from app.core.url_text import canonical_link_key, is_youtube_host, normalize_link_candidate
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
from app.resources.loader import TextResource
from app.texts.description_marks import URL_PATTERN
from app.texts.paragraphs import normalize_newlines

if TYPE_CHECKING:
    from app.sources.video import SourceVideo

OFFICIAL_LINK_HINTS_RESOURCE: Final[str] = "lexicon_official_link_hints.txt"
HTTPS_SCHEME: Final[str] = "https"
LINE_BREAK: Final[str] = "\n"


@dataclass(frozen=True)
class OfficialLinkHints:
    """Подсказки «это официальная ссылка» в строке описания: подстроки в нижнем регистре."""

    hints: tuple[str, ...]

    @classmethod
    def load(cls) -> OfficialLinkHints:
        return cls(hints=TextResource(OFFICIAL_LINK_HINTS_RESOURCE).lines)

    def has_context(self, line: str) -> bool:
        """В строке (без краёв, нижний регистр) есть подсказка."""
        normalized_line: str = str(line or "").strip().lower()
        if not normalized_line:
            return False
        return any(hint in normalized_line for hint in self.hints)


@dataclass(frozen=True)
class OfficialLinkCandidate:
    """Ссылка из описания источника (уже нормализованная) и строка, в которой она стоит."""

    url: str
    line: str
    index: int              # порядок в источниках: при равной оценке побеждает более ранняя

    @property
    def domain(self) -> str:
        return urlsplit(self.url).netloc.lower().strip()

    def score(self, domain_counts: Counter[str], hints: OfficialLinkHints) -> int:
        parts: SplitResult = urlsplit(self.url)
        score: int = OFFICIAL_LINK_HTTPS_SCORE if parts.scheme == HTTPS_SCHEME else 0
        if hints.has_context(self.line):
            score += OFFICIAL_LINK_CONTEXT_SCORE
        score += min(OFFICIAL_LINK_DOMAIN_SCORE_CAP, domain_counts.get(self.domain, 1) * OFFICIAL_LINK_DOMAIN_SCORE_STEP)
        if parts.query:
            score -= OFFICIAL_LINK_QUERY_PENALTY
        return score + max(0, OFFICIAL_LINK_LENGTH_SCORE - len(self.url) // OFFICIAL_LINK_LENGTH_STEP)


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
            key: str = canonical_link_key(url)
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
        return cls.of([source.metadata.description if source.metadata is not None else "" for source in sources], hints)

    @staticmethod
    def _candidates(descriptions: Sequence[str]) -> list[OfficialLinkCandidate]:
        candidates: list[OfficialLinkCandidate] = []
        for description in descriptions:
            for line in normalize_newlines(description).split(LINE_BREAK):
                for match in URL_PATTERN.finditer(line):
                    url: str | None = normalize_link_candidate(match.group(0))
                    if url is None or is_youtube_host(urlsplit(url).netloc):
                        continue
                    candidates.append(OfficialLinkCandidate(url=url, line=line, index=len(candidates)))
        return candidates
