"""Источник ряда плана: данные видео, язык и обложка (CLAUDE.md §3 шаги 2.3–2.4).

`SourceVideo` — допущенный ряд таблицы (`PlanRow`) вместе с тем, что о его видео сказал yt-dlp, с языком
и с обложкой. Отказ не выбрасывает источник: объект остаётся с причиной, пишется в лог и дальше по конвейеру
не идёт (§0). Обложка не обязательна: без неё эфир ставится без своей обложки, причина — в лог.
Язык обязателен: он решается один раз по данным видео (§14 решение 12) и станет языком слота;
не определился — источник не годен с причиной NO_LANGUAGE.

`SourceCatalog` готовит источники одного запуска: одно обращение к yt-dlp, одно решение языка и одно
скачивание обложки на уникальную ссылку (две строки таблицы с одним видео — один вызов), порядок — порядок рядов.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Final

from app.observability.logging_setup import get_logger
from app.paths import LivecraftPaths
from app.sheets.rows import PlanRow
from app.sources.fetcher import MetadataFetcher, SourceFailureReason, SourceFetch
from app.sources.language import LanguageDecision, LanguageResolver
from app.sources.metadata import SourceMetadata
from app.sources.preview import Preview, PreviewDownloader, PreviewProblem, PreviewResult
from app.sources.ytdlp import YtDlpFetcher

LOGGER_NAME: Final[str] = "sources"
LOGGER = get_logger(LOGGER_NAME)

READY_MARK: Final[str] = "ok"
NO_VALUE: Final[str] = "-"
COUNT_JOINER: Final[str] = ","


@dataclass(frozen=True)
class SourceVideo:
    """Видео одного допущенного ряда: метаданные, язык, обложка и причины, если чего-то нет."""

    row: PlanRow
    metadata: SourceMetadata | None
    preview: Preview | None
    failure: SourceFailureReason | None
    preview_problem: PreviewProblem | None
    language: LanguageDecision | None       # None — язык не решался: данных видео нет или они не годны

    @classmethod
    def of(
        cls, row: PlanRow, fetched: SourceFetch, preview: PreviewResult | None, language: LanguageDecision | None
    ) -> SourceVideo:
        """Источник из итога yt-dlp, решения языка и итога обложки."""
        return cls(
            row=row,
            metadata=fetched.metadata,
            preview=preview.preview if preview is not None else None,
            failure=fetched.failure,
            preview_problem=preview.problem if preview is not None else None,
            language=language,
        )

    @property
    def link(self) -> str:
        """Нормализованная ссылка ряда; у допущенного ряда есть всегда."""
        return self.row.link or ""

    @property
    def is_ready(self) -> bool:
        """Годен для слота: данные видео есть, без проблемы, язык определён. Обложка не обязательна."""
        return self.refusal is None

    @property
    def refusal(self) -> SourceFailureReason | None:
        """Почему источник не годен, по порядку: отказ yt-dlp → нет названия → не определился язык."""
        if self.failure is not None:
            return self.failure
        if self.metadata is None or self.metadata.problem is not None:
            return SourceFailureReason.NO_TITLE
        if self.language is None or not self.language.is_resolved:
            return SourceFailureReason.NO_LANGUAGE
        return None

    @property
    def language_code(self) -> str | None:
        """Код языка источника; не определился или не решался — None."""
        return self.language.language if self.language is not None else None

    @property
    def log_line(self) -> str:
        """row, link и `ok` либо `reason=…`; обложка — `preview=ok` или её причина; язык и его правило."""
        refusal: SourceFailureReason | None = self.refusal
        state: str = READY_MARK if refusal is None else f"reason={refusal.value}"
        rule: str = self.language.source.value if self.language is not None else NO_VALUE
        return (
            f"row={self.row.row_number} link={self.link} {state} preview={self._preview_state} "
            f"language={self.language_code or NO_VALUE} language_source={rule}"
        )

    @property
    def _preview_state(self) -> str:
        if self.preview is not None:
            return READY_MARK
        return self.preview_problem.value if self.preview_problem is not None else NO_VALUE


@dataclass(frozen=True)
class SourceTally:
    """Итог подготовки источников запуска для лога: сколько годных, отказов по причинам, без обложки, языки."""

    videos: tuple[SourceVideo, ...]

    @property
    def ready(self) -> int:
        return sum(1 for video in self.videos if video.is_ready)

    @property
    def no_preview(self) -> int:
        """Годные источники без обложки: эфир встанет без своей обложки."""
        return sum(1 for video in self.videos if video.is_ready and video.preview is None)

    @property
    def failures(self) -> Counter[SourceFailureReason]:
        return Counter(video.refusal for video in self.videos if video.refusal is not None)

    @property
    def languages(self) -> Counter[str]:
        """Годные источники по языкам в порядке первого появления."""
        return Counter(video.language_code for video in self.videos if video.is_ready and video.language_code)

    @property
    def log_line(self) -> str:
        by_reason: str = COUNT_JOINER.join(
            f"{reason.value}:{count}" for reason, count in self.failures.items()
        ) or NO_VALUE
        by_language: str = COUNT_JOINER.join(
            f"{code}:{count}" for code, count in self.languages.items()
        ) or NO_VALUE
        links: int = len({video.link for video in self.videos})
        return (
            f"sources={len(self.videos)} links={links} ready={self.ready} "
            f"failed={len(self.videos) - self.ready} failures={by_reason} no_preview={self.no_preview} "
            f"languages={by_language}"
        )


@dataclass
class SourceCatalog:
    """Источники одного запуска. Кеши по ссылке: итог yt-dlp, решение языка и итог обложки — по одному."""

    fetcher: MetadataFetcher
    downloader: PreviewDownloader
    resolver: LanguageResolver
    fetches: dict[str, SourceFetch] = field(default_factory=dict)
    languages: dict[str, LanguageDecision] = field(default_factory=dict)
    previews: dict[str, PreviewResult] = field(default_factory=dict)

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> SourceCatalog:
        return cls(
            fetcher=YtDlpFetcher.from_paths(paths),
            downloader=PreviewDownloader(),
            resolver=LanguageResolver.from_resources(),
        )

    def prepare(self, rows: tuple[PlanRow, ...]) -> tuple[SourceVideo, ...]:
        """Источники допущенных рядов в порядке рядов; отсеянные ряды сюда не попадают."""
        videos: tuple[SourceVideo, ...] = tuple(
            self._video(row) for row in rows if row.is_admitted and row.link is not None
        )
        LOGGER.info("sources_prepared %s", SourceTally(videos).log_line)
        return videos

    def _video(self, row: PlanRow) -> SourceVideo:
        """Язык решается только по годным данным видео; обложка качается только источнику с языком."""
        link: str = row.link or ""
        fetched: SourceFetch = self._fetch(link)
        language: LanguageDecision | None = self._language(link, fetched) if fetched.is_ok else None
        has_language: bool = language is not None and language.is_resolved
        preview: PreviewResult | None = self._preview(link, fetched) if has_language else None
        video: SourceVideo = SourceVideo.of(row, fetched, preview, language)
        if video.is_ready:
            LOGGER.info("source %s", video.log_line)
        else:
            LOGGER.warning("source %s detail=%r", video.log_line, fetched.detail)
        return video

    def _fetch(self, link: str) -> SourceFetch:
        """Итог yt-dlp по ссылке: из кеша или одним новым обращением."""
        cached: SourceFetch | None = self.fetches.get(link)
        if cached is not None:
            return cached
        fetched: SourceFetch = self.fetcher.fetch(link)
        self.fetches[link] = fetched
        return fetched

    def _language(self, link: str, fetched: SourceFetch) -> LanguageDecision | None:
        """Язык видео по ссылке: из кеша или одним решением по данным yt-dlp; данных нет — None."""
        cached: LanguageDecision | None = self.languages.get(link)
        if cached is not None or fetched.metadata is None:
            return cached
        decision: LanguageDecision = self.resolver.resolve(fetched.metadata)
        self.languages[link] = decision
        return decision

    def _preview(self, link: str, fetched: SourceFetch) -> PreviewResult:
        """Обложка по ссылке: из кеша или одним скачиванием адреса, который дал yt-dlp."""
        cached: PreviewResult | None = self.previews.get(link)
        if cached is not None:
            return cached
        thumbnail_url: str = fetched.metadata.thumbnail_url if fetched.metadata is not None else ""
        result: PreviewResult = self.downloader.preview(thumbnail_url)
        self.previews[link] = result
        return result
