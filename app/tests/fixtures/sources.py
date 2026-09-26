"""Ряды таблицы и источники без сети: допущенный ряд, годный и негодный источник — теми же объектами, что в прогоне;
yt-dlp без сети (`StubFetcher`) и видео запуска на нём."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

from app.core.youtube_video import YouTubeVideoId
from app.sheets.plan import SheetPlan
from app.sheets.rows import AdmittedRow, PlannedRows, SheetRow
from app.slots.preview import Preview
from app.sources.fetcher import SourceFetch
from app.sources.language import LanguageProfile, LanguageResolver, LanguageVoting
from app.sources.metadata import SourceFailureReason, SourceMetadata
from app.sources.preview import PreviewDownloader, PreviewResult
from app.sources.video import SourceCatalog, SourceFacts, SourceVideo

HEADER: list[str] = ["Links", "Date", "Time"]
RESOLVER: LanguageResolver = LanguageResolver.from_resources()


def planned_rows(*rows: list[str], zone: ZoneInfo, now: datetime) -> PlannedRows:
    """Настоящий разбор таблицы: шапка «Links, Date, Time» и ряды → SheetPlan → разобранные ряды."""
    return SheetPlan.from_values([HEADER, *rows]).plan_rows(zone, now)


def admitted_row(row_number: int, link: str, start: datetime) -> AdmittedRow:
    """Допущенный ряд со ссылкой YouTube и моментом старта; ячейки даты и времени пусты — они уже разобраны."""
    video: YouTubeVideoId | None = YouTubeVideoId.of(link)
    assert video is not None
    return AdmittedRow(row=SheetRow(row_number, link, "", ""), start=start, video=video)


def video_metadata(url: str, title: str, description: str, language: str | None) -> SourceMetadata:
    """Данные видео как от yt-dlp: название, описание и язык видео; прочих сигналов языка нет."""
    return SourceMetadata(
        url=url,
        video_id=url.rsplit("/", 1)[-1],
        title=title,
        description=description,
        thumbnail_url="",
        youtube_language=language,
        channel_language=None,
        duration_seconds=None,
        audio_languages=(),
        subtitle_languages=(),
        auto_caption_languages=(),
    )


def ready_source(
    row: AdmittedRow, title: str, description: str, language: str, preview: Preview | None = None
) -> SourceVideo:
    """Годный источник без сети: данные видео как от yt-dlp, язык — настоящим голосованием по языку видео."""
    metadata: SourceMetadata = video_metadata(row.link, title, description, language)
    facts: SourceFacts = SourceFacts(
        fetch=SourceFetch.from_metadata(row.link, metadata),
        language=LanguageVoting(LanguageProfile(video_language=language, channel_language=None)).decide(),
        preview=None if preview is None else PreviewResult.ready(preview),
    )
    return SourceVideo(row=row, facts=facts)


def failed_source(row: AdmittedRow, reason: SourceFailureReason) -> SourceVideo:
    """Источник, за которым yt-dlp отказал: данных видео нет, язык не решался, обложку не качали."""
    facts: SourceFacts = SourceFacts(fetch=SourceFetch.failed(row.link, reason), language=None, preview=None)
    return SourceVideo(row=row, facts=facts)


@dataclass
class StubFetcher:
    """yt-dlp без сети: данные видео по ссылке, прочие ссылки — отказ UNAVAILABLE; обращения запоминаются."""

    videos: dict[str, SourceMetadata] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)

    def fetch(self, url: str) -> SourceFetch:
        self.calls.append(url)
        metadata: SourceMetadata | None = self.videos.get(url)
        if metadata is None:
            return SourceFetch.failed(url, SourceFailureReason.UNAVAILABLE)
        return SourceFetch.from_metadata(url, metadata)


def stub_catalog(*videos: SourceMetadata) -> SourceCatalog:
    """Видео запуска на yt-dlp без сети: эти видео по их ссылкам, язык — настоящим решением по их данным."""
    fetcher: StubFetcher = StubFetcher({video.url: video for video in videos})
    return SourceCatalog(fetcher=fetcher, downloader=PreviewDownloader(), resolver=RESOLVER)


def stub_calls(catalog: SourceCatalog) -> list[str]:
    """Ссылки, по которым видео запуска обращались к yt-dlp без сети."""
    assert isinstance(catalog.fetcher, StubFetcher)
    return catalog.fetcher.calls
