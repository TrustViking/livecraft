"""Источник ряда плана: данные видео и обложка (CLAUDE.md §3 шаг 2.4).

`SourceVideo` — допущенный ряд таблицы (`PlanRow`) вместе с тем, что о его видео сказал yt-dlp, и с обложкой.
Отказ не выбрасывает источник: объект остаётся с причиной, пишется в лог и дальше по конвейеру не идёт (§0).
Обложка не обязательна: без неё эфир ставится без своей обложки, причина — в лог.

`SourceCatalog` готовит источники одного запуска: одно обращение к yt-dlp и одно скачивание обложки
на уникальную ссылку (две строки таблицы с одним видео — один вызов), порядок — порядок рядов.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Final

from app.observability.logging_setup import get_logger
from app.paths import LivecraftPaths
from app.sheets.rows import PlanRow
from app.sources.fetcher import MetadataFetcher, SourceFailureReason, SourceFetch
from app.sources.metadata import SourceMetadata
from app.sources.preview import Preview, PreviewDownloader, PreviewProblem, PreviewResult
from app.sources.ytdlp import YtDlpFetcher

LOGGER_NAME: Final[str] = "sources"
LOGGER = get_logger(LOGGER_NAME)

READY_MARK: Final[str] = "ok"
NO_VALUE: Final[str] = "-"


@dataclass(frozen=True)
class SourceVideo:
    """Видео одного допущенного ряда: метаданные, обложка и причины, если чего-то нет."""

    row: PlanRow
    metadata: SourceMetadata | None
    preview: Preview | None
    failure: SourceFailureReason | None
    preview_problem: PreviewProblem | None

    @classmethod
    def of(cls, row: PlanRow, fetched: SourceFetch, preview: PreviewResult | None) -> SourceVideo:
        """Источник из итога yt-dlp и итога обложки; обложки нет, если данных видео нет."""
        return cls(
            row=row,
            metadata=fetched.metadata,
            preview=preview.preview if preview is not None else None,
            failure=fetched.failure,
            preview_problem=preview.problem if preview is not None else None,
        )

    @property
    def link(self) -> str:
        """Нормализованная ссылка ряда; у допущенного ряда есть всегда."""
        return self.row.link or ""

    @property
    def is_ready(self) -> bool:
        """Годен для слота: данные видео есть и без проблемы. Обложка не обязательна."""
        return self.failure is None and self.metadata is not None and self.metadata.problem is None

    @property
    def refusal(self) -> SourceFailureReason | None:
        """Почему источник не годен; годен — None. Данные без названия — NO_TITLE, даже без `failure`."""
        if self.is_ready:
            return None
        return self.failure if self.failure is not None else SourceFailureReason.NO_TITLE

    @property
    def log_line(self) -> str:
        """row, link и `ok` либо `reason=…`; обложка — `preview=ok` или её причина."""
        refusal: SourceFailureReason | None = self.refusal
        state: str = READY_MARK if refusal is None else f"reason={refusal.value}"
        return f"row={self.row.row_number} link={self.link} {state} preview={self._preview_state}"

    @property
    def _preview_state(self) -> str:
        if self.preview is not None:
            return READY_MARK
        return self.preview_problem.value if self.preview_problem is not None else NO_VALUE


@dataclass(frozen=True)
class SourceTally:
    """Итог подготовки источников запуска для лога: сколько годных, отказов по причинам, без обложки."""

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
    def log_line(self) -> str:
        by_reason: str = ",".join(
            f"{reason.value}:{count}" for reason, count in self.failures.items()
        ) or NO_VALUE
        links: int = len({video.link for video in self.videos})
        return (
            f"sources={len(self.videos)} links={links} ready={self.ready} "
            f"failed={len(self.videos) - self.ready} failures={by_reason} no_preview={self.no_preview}"
        )


@dataclass
class SourceCatalog:
    """Источники одного запуска. Кеши по ссылке: итог yt-dlp и итог обложки — по одному на ссылку."""

    fetcher: MetadataFetcher
    downloader: PreviewDownloader
    fetches: dict[str, SourceFetch] = field(default_factory=dict)
    previews: dict[str, PreviewResult] = field(default_factory=dict)

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> SourceCatalog:
        return cls(fetcher=YtDlpFetcher.from_paths(paths), downloader=PreviewDownloader())

    def prepare(self, rows: tuple[PlanRow, ...]) -> tuple[SourceVideo, ...]:
        """Источники допущенных рядов в порядке рядов; отсеянные ряды сюда не попадают."""
        videos: tuple[SourceVideo, ...] = tuple(
            self._video(row) for row in rows if row.is_admitted and row.link is not None
        )
        LOGGER.info("sources_prepared %s", SourceTally(videos).log_line)
        return videos

    def _video(self, row: PlanRow) -> SourceVideo:
        link: str = row.link or ""
        fetched: SourceFetch = self._fetch(link)
        preview: PreviewResult | None = self._preview(link, fetched) if fetched.is_ok else None
        video: SourceVideo = SourceVideo.of(row, fetched, preview)
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

    def _preview(self, link: str, fetched: SourceFetch) -> PreviewResult:
        """Обложка по ссылке: из кеша или одним скачиванием адреса, который дал yt-dlp."""
        cached: PreviewResult | None = self.previews.get(link)
        if cached is not None:
            return cached
        thumbnail_url: str = fetched.metadata.thumbnail_url if fetched.metadata is not None else ""
        result: PreviewResult = self.downloader.preview(thumbnail_url)
        self.previews[link] = result
        return result
