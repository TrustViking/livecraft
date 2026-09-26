"""Источники ряда плана: данные видео, язык и обложка (CLAUDE.md §3 шаги 2.3–2.4).

`SourceFacts` — всё, что известно по одной ссылке: итог yt-dlp, решение языка, итог обложки. Язык решается только
по годным данным видео (§14 решение 12) и станет языком слота; не определился — источник не годен с причиной
NO_LANGUAGE. Обложка качается только источнику с языком и не обязательна: без неё эфир ставится без своей обложки.

`SourceVideo` — допущенный ряд таблицы (`AdmittedRow`) вместе с фактами о его видео. Негодный источник не
выбрасывается: он остаётся с причиной, пишется в лог и дальше по конвейеру не идёт (§0).

`SourceCatalog` готовит источники одного запуска: на уникальную ссылку одно обращение к yt-dlp, одно решение
языка и одно скачивание обложки (две строки таблицы с одним видео — один вызов). `PreparedSources` — итог: источники
в порядке рядов и счётчики для лога и консоли.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import Enum
from zoneinfo import ZoneInfo

from app.core.counts import Counts
from app.observability.log_event import LogArea, LogEvent, LogValue, get_logger
from app.paths import LivecraftPaths
from app.sheets.rows import AdmittedRow, PlannedRows
from app.slots.preview import Preview
from app.slots.slot import SlotKey
from app.slots.texts import SourceText
from app.sources.fetcher import MetadataFetcher, SourceFetch
from app.sources.language import LanguageDecision, LanguageResolver, LanguageSource
from app.sources.metadata import SourceFailureReason, SourceMetadata
from app.sources.preview import PreviewDownloader, PreviewProblem, PreviewResult
from app.sources.ytdlp import YtDlpFetcher
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.SOURCES)


class SourcesEvent(str, Enum):
    """События подготовки источников в логе."""

    SOURCE = "source"
    PREPARED = "sources_prepared"


@dataclass(frozen=True)
class SourceFacts:
    """Всё, что известно по одной ссылке: итог yt-dlp, решение языка и итог обложки.

    `language` — None, если язык не решался (данных видео нет или они не годны); `preview` — None, если обложку
    не качали (язык не определился).
    """

    fetch: SourceFetch
    language: LanguageDecision | None
    preview: PreviewResult | None

    @property
    def language_code(self) -> str | None:
        """Код языка видео; не решался или не определился — None."""
        return self.language.language if self.language is not None else None

    @property
    def refusal(self) -> SourceFailureReason | None:
        """Почему источник не годен: отказ yt-dlp (в том числе нет названия), затем не определился язык."""
        if self.fetch.failure is not None:
            return self.fetch.failure
        return SourceFailureReason.NO_LANGUAGE if self.language_code is None else None

    @property
    def is_ready(self) -> bool:
        """Годен для слота: данные видео есть и годны, язык определён. Обложка не обязательна."""
        return self.refusal is None

    @property
    def cover(self) -> Preview | None:
        """Готовая обложка; не качали или не вышло — None."""
        return self.preview.preview if self.preview is not None else None

    @property
    def preview_state(self) -> LogValue | PreviewProblem | None:
        """Обложка для строки лога: `ok`, причина, почему её нет, или «-», если её не качали."""
        if self.preview is None:
            return None
        return LogValue.OK if self.preview.problem is None else self.preview.problem

    @property
    def log_fields(self) -> Mapping[str, object]:
        """Итог источника, обложка, язык и правило, которым он решён."""
        rule: LanguageSource | None = self.language.source if self.language is not None else None
        return dict(
            result=self.refusal or LogValue.OK, preview=self.preview_state, language=self.language_code,
            language_source=rule,
        )


@dataclass(frozen=True)
class SourceVideo:
    """Видео одного допущенного ряда и факты о нём."""

    row: AdmittedRow
    facts: SourceFacts

    @property
    def link(self) -> str:
        """Нормализованная ссылка ряда `https://youtu.be/<id>`."""
        return self.row.link

    @property
    def watch_url(self) -> str:
        """Ссылка `https://www.youtube.com/watch?v=<id>` — так ссылка источника уходит в слот."""
        return self.row.video.watch_url

    @property
    def row_number(self) -> int:
        return self.row.row_number

    @property
    def table_link(self) -> str:
        """Ячейка ссылки в таблице как есть."""
        return self.row.row.link

    @property
    def refusal(self) -> SourceFailureReason | None:
        return self.facts.refusal

    @property
    def is_ready(self) -> bool:
        return self.facts.is_ready

    @property
    def language_code(self) -> str | None:
        """Код языка источника; у годного есть всегда, у негодного — None."""
        return self.facts.language_code

    @property
    def preview(self) -> Preview | None:
        return self.facts.cover

    @property
    def text(self) -> SourceText:
        """Название и описание видео для текстов слота; данных видео нет — пустые строки."""
        metadata: SourceMetadata | None = self.facts.fetch.metadata
        if metadata is None:
            return SourceText(title="", description="")
        return SourceText(title=metadata.title, description=metadata.description)

    @property
    def metadata_url(self) -> str:
        """Ссылка, по которой спрашивали yt-dlp; данных видео нет — пусто."""
        metadata: SourceMetadata | None = self.facts.fetch.metadata
        return metadata.url if metadata is not None else ""

    def slot_key(self, zone: ZoneInfo) -> SlotKey | None:
        """Ключ слота: момент старта ряда в зоне программы и язык видео. Язык есть только у годного источника."""
        language: str | None = self.language_code
        if language is None:
            return None
        return SlotKey(start=self.row.start.astimezone(zone), language=language)

    @property
    def event(self) -> LogEvent:
        """Строка лога: ряд, ссылка, итог, обложка, язык; у негодного — подробность отказа yt-dlp."""
        event: LogEvent = LogEvent.of(SourcesEvent.SOURCE, row=self.row_number, link=self.link, **self.facts.log_fields)
        return event if self.is_ready else event.extended(detail=self.facts.fetch.detail)


@dataclass(frozen=True)
class PreparedSources:
    """Источники запуска в порядке рядов и их счётчики."""

    videos: tuple[SourceVideo, ...]

    @property
    def ready(self) -> int:
        return sum(1 for video in self.videos if video.is_ready)

    @property
    def has_ready(self) -> bool:
        return self.ready > 0

    @property
    def no_preview(self) -> int:
        """Годные источники без обложки: эфир встанет без своей обложки."""
        return sum(1 for video in self.videos if video.is_ready and video.preview is None)

    @property
    def failures(self) -> Counts[SourceFailureReason]:
        """Негодные источники по причинам в порядке первого появления."""
        return Counts.of(video.refusal for video in self.videos if video.refusal is not None)

    @property
    def languages(self) -> Counts[str]:
        """Годные источники по языкам в порядке первого появления."""
        return Counts.of(video.language_code for video in self.videos if video.language_code is not None)

    @property
    def has_errors(self) -> bool:
        """Негодный источник — ошибка запуска (§10)."""
        return bool(self.failures.items)

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(
            SourcesEvent.PREPARED,
            sources=len(self.videos),
            links=len({video.link for video in self.videos}),
            ready=self.ready,
            failed=len(self.videos) - self.ready,
            failures=self.failures.log_value,
            no_preview=self.no_preview,
            languages=self.languages.log_value,
        )

    @property
    def console_line(self) -> str:
        """Строка для оператора: сколько годных из скольких, сколько без обложки, почему не годны остальные."""
        failures: str = self.failures.wrapped(
            msg.INTAKE_SOURCES_FAILURES, msg.INTAKE_COUNT_ITEM, msg.ITEM_JOINER, lambda reason: reason.human
        )
        return msg.INTAKE_SOURCES_LINE.format(
            ready=self.ready, total=len(self.videos), no_preview=self.no_preview, failures=failures
        )


@dataclass
class SourceCatalog:
    """Источники одного запуска. Кеш по ссылке: факты о видео — по одному разу на ссылку."""

    fetcher: MetadataFetcher
    downloader: PreviewDownloader
    resolver: LanguageResolver
    known: dict[str, SourceFacts] = field(default_factory=dict)

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> SourceCatalog:
        return cls(
            fetcher=YtDlpFetcher.from_paths(paths),
            downloader=PreviewDownloader(),
            resolver=LanguageResolver.from_resources(),
        )

    def facts(self, link: str) -> SourceFacts:
        """Факты о видео по ссылке: из кеша или одним проходом. Язык решается только по годным данным видео,
        обложка качается только источнику с определённым языком."""
        cached: SourceFacts | None = self.known.get(link)
        if cached is not None:
            return cached
        fetched: SourceFetch = self.fetcher.fetch(link)
        metadata: SourceMetadata | None = fetched.ready_metadata
        facts: SourceFacts = SourceFacts(fetch=fetched, language=None, preview=None)
        if metadata is not None:
            language: LanguageDecision = self.resolver.resolve(metadata)
            preview: PreviewResult | None = None
            if language.is_resolved:
                preview = self.downloader.preview(metadata.thumbnail_url)
            facts = SourceFacts(fetch=fetched, language=language, preview=preview)
        self.known[link] = facts
        return facts

    def prepare(self, rows: PlannedRows) -> PreparedSources:
        """Источники допущенных рядов в порядке рядов: годный — строкой INFO, негодный — WARNING; итог — строкой."""
        videos: list[SourceVideo] = []
        for row in rows.admitted:
            video: SourceVideo = SourceVideo(row=row, facts=self.facts(row.link))
            video.event.emit(LOGGER, logging.INFO if video.is_ready else logging.WARNING)
            videos.append(video)
        prepared: PreparedSources = PreparedSources(tuple(videos))
        prepared.event.emit(LOGGER)
        return prepared
