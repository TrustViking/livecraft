"""Пробник источников: ссылка → yt-dlp → данные видео и обложка (CLAUDE.md §5 tools\\).

Запуск из корня репо: `python -m app.tools.source_probe <ссылка> [<ссылка> ...]`. В поставку не идёт.
Сети и yt-dlp в тестах нет — получатель и скачивание подменяются; боевой прогон делает Артур.

Ссылка нормализуется так же, как ссылка ряда таблицы (`https://youtu.be/<id>`), и идёт тем же путём, что
в боевом запуске: `YtDlpFetcher` и `PreviewDownloader`. Сейф пробнику не нужен: ссылки на видео — не секрет.
Коды: 0 — все источники получены и язык каждого определился; 1 — есть отказы или язык не определился;
2 — нет tools\\yt-dlp.exe или не указано ни одной ссылки.
"""
from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

from app.core.sheet_text import normalize_youtube_link
from app.observability.logging_setup import close_logging, get_logger, setup_logging
from app.paths import LivecraftPaths, build_paths, ensure_dirs, resolve_root
from app.sources.fetcher import MetadataFetcher, SourceFailureReason, SourceFetch
from app.sources.language import LanguageDecision, LanguageResolver
from app.sources.metadata import SourceMetadata
from app.sources.preview import Preview, PreviewDownloader, PreviewResult
from app.sources.ytdlp import YtDlpFetcher
from app.ui import messages_ru as msg

LOGGER_NAME: Final[str] = "tools.source_probe"
LOGGER = get_logger(LOGGER_NAME)

LANGUAGES_SHOWN: Final[int] = 10
LANGUAGE_JOINER: Final[str] = ", "
BYTES_PER_KILOBYTE: Final[int] = 1024
SECONDS_PER_MINUTE: Final[int] = 60
MINUTES_PER_HOUR: Final[int] = 60
DURATION_TEMPLATE: Final[str] = "{hours}:{minutes:02d}:{seconds:02d}"


class ProbeExit(IntEnum):
    OK = 0          # все источники получены, язык каждого определился
    ERRORS = 1      # есть отказы или неопределённый язык
    NOT_READY = 2   # нет yt-dlp.exe или нет ссылок — работать не с чем


def _languages(values: tuple[str, ...]) -> str:
    """Первые LANGUAGES_SHOWN кодов через запятую и сколько не показано; пусто — «нет»."""
    if not values:
        return msg.SOURCE_PROBE_NONE
    shown: str = LANGUAGE_JOINER.join(values[:LANGUAGES_SHOWN])
    more: int = len(values) - LANGUAGES_SHOWN
    return msg.SOURCE_PROBE_MORE.format(shown=shown, more=more) if more > 0 else shown


def _duration(seconds: int | None) -> str:
    """Секунды → H:MM:SS; нет длительности — «нет»."""
    if seconds is None:
        return msg.SOURCE_PROBE_NONE
    minutes, rest = divmod(seconds, SECONDS_PER_MINUTE)
    hours, minutes = divmod(minutes, MINUTES_PER_HOUR)
    return DURATION_TEMPLATE.format(hours=hours, minutes=minutes, seconds=rest)


@dataclass(frozen=True)
class SourceProbeReport:
    """Что показать человеку об одном источнике: поля yt-dlp, язык и обложка либо причина отказа."""

    fetched: SourceFetch
    preview: PreviewResult | None
    decision: LanguageDecision | None       # None — язык не решался: данных видео нет

    @property
    def is_ok(self) -> bool:
        """Источник годится так же, как в боевом запуске: данные видео есть и язык определился."""
        return self.fetched.is_ok and self.decision is not None and self.decision.is_resolved

    @property
    def lines(self) -> tuple[str, ...]:
        metadata: SourceMetadata | None = self.fetched.metadata
        head: tuple[str, ...] = (msg.SOURCE_PROBE_SOURCE.format(link=self.fetched.url),)
        fields: tuple[str, ...] = self._metadata_lines(metadata) if metadata is not None else ()
        return (*head, *fields, *self._outcome_lines)

    @staticmethod
    def _metadata_lines(metadata: SourceMetadata) -> tuple[str, ...]:
        return (
            msg.SOURCE_PROBE_ID.format(value=metadata.video_id or msg.SOURCE_PROBE_NONE),
            msg.SOURCE_PROBE_NAME.format(value=metadata.title or msg.SOURCE_PROBE_NONE),
            msg.SOURCE_PROBE_DURATION.format(value=_duration(metadata.duration_seconds)),
            msg.SOURCE_PROBE_LANGUAGE.format(
                video=metadata.youtube_language or msg.SOURCE_PROBE_NONE,
                channel=metadata.channel_language or msg.SOURCE_PROBE_NONE,
            ),
            msg.SOURCE_PROBE_AUDIO.format(value=_languages(metadata.audio_languages)),
            msg.SOURCE_PROBE_SUBTITLES.format(value=_languages(metadata.subtitle_languages)),
            msg.SOURCE_PROBE_AUTO_CAPTIONS.format(value=_languages(metadata.auto_caption_languages)),
        )

    @property
    def _outcome_lines(self) -> tuple[str, ...]:
        """Отказ — причина и подробность yt-dlp; удача — строка языка и строка обложки (или почему её нет)."""
        failure: SourceFailureReason | None = self.fetched.failure
        if failure is not None:
            return (
                msg.SOURCE_PROBE_FAILED.format(reason=failure.human),
                msg.SOURCE_PROBE_DETAIL.format(detail=self.fetched.detail),
            )
        return (*self._language_lines, *self._preview_lines)

    @property
    def _preview_lines(self) -> tuple[str, ...]:
        """Язык не определился — обложку не качали, как в боевом запуске; иначе — строка обложки, если она есть."""
        if self.decision is not None and not self.decision.is_resolved:
            return (msg.SOURCE_PROBE_PREVIEW_SKIPPED,)
        if self.preview is None:
            return ()
        return (self._preview_line(self.preview),)

    @property
    def _language_lines(self) -> tuple[str, ...]:
        """Решённый язык и правило; не определился — строка об этом; не решался — ничего."""
        if self.decision is None:
            return ()
        if self.decision.language is None:
            return (msg.SOURCE_PROBE_SOURCE_LANGUAGE_NONE,)
        line: str = msg.SOURCE_PROBE_SOURCE_LANGUAGE.format(
            code=self.decision.language, source=self.decision.source.value
        )
        return (line,)

    @staticmethod
    def _preview_line(result: PreviewResult) -> str:
        """Размеры и вес готовой обложки либо причина, почему её нет."""
        image: Preview | None = result.preview
        if image is None:
            reason: str = result.problem.human if result.problem is not None else msg.SOURCE_PROBE_NONE
            return msg.SOURCE_PROBE_PREVIEW_BAD.format(reason=reason)
        kilobytes: int = round(image.size_bytes / BYTES_PER_KILOBYTE)
        return msg.SOURCE_PROBE_PREVIEW_OK.format(width=image.width, height=image.height, kilobytes=kilobytes)


@dataclass(frozen=True)
class SourceProbe:
    """Один прогон пробника: получатель, скачивание обложек, язык и вывод `say` — параметрами, в тестах свои."""

    fetcher: MetadataFetcher
    downloader: PreviewDownloader
    resolver: LanguageResolver
    say: Callable[[str], None]

    @classmethod
    def from_paths(cls, paths: LivecraftPaths, say: Callable[[str], None]) -> SourceProbe:
        return cls(
            fetcher=YtDlpFetcher.from_paths(paths),
            downloader=PreviewDownloader(),
            resolver=LanguageResolver.from_resources(),
            say=say,
        )

    def run(self, raw_links: Sequence[str]) -> int:
        self.say(msg.SOURCE_PROBE_TITLE)
        if not raw_links:
            self.say(msg.SOURCE_PROBE_USAGE)
            return int(ProbeExit.NOT_READY)
        failed: int = 0
        for raw in raw_links:
            report: SourceProbeReport | None = self._probe(raw)
            if report is not None and report.fetched.failure is SourceFailureReason.TOOL_MISSING:
                return int(ProbeExit.NOT_READY)
            if report is None or not report.is_ok:
                failed += 1
        self.say(msg.SOURCE_PROBE_SUMMARY.format(total=len(raw_links), ok=len(raw_links) - failed, failed=failed))
        return int(ProbeExit.ERRORS if failed else ProbeExit.OK)

    def _probe(self, raw: str) -> SourceProbeReport | None:
        """Одна ссылка: нормализовать, спросить yt-dlp, решить язык, скачать обложку, напечатать; не YouTube — None.

        Обложка качается только источнику с решённым языком — так же, как `SourceCatalog` в боевом запуске.
        """
        link: str | None = normalize_youtube_link(raw)
        if link is None:
            LOGGER.warning("source_probe_bad_link raw=%r", raw)
            self.say(msg.SOURCE_PROBE_BAD_LINK.format(raw=raw))
            return None
        fetched: SourceFetch = self.fetcher.fetch(link)
        preview: PreviewResult | None = None
        decision: LanguageDecision | None = None
        if fetched.is_ok and fetched.metadata is not None:
            decision = self.resolver.resolve(fetched.metadata)
            if decision.is_resolved:
                preview = self.downloader.preview(fetched.metadata.thumbnail_url)
        LOGGER.info("source_probe link=%s %s", link, fetched.log_line)
        report: SourceProbeReport = SourceProbeReport(fetched=fetched, preview=preview, decision=decision)
        for line in report.lines:
            self.say(line)
        return report


def _say(text: str) -> None:
    print(text, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа пробника: корень, папки, логи; дальше — `SourceProbe`."""
    links: Sequence[str] = sys.argv[1:] if argv is None else argv
    paths: LivecraftPaths = build_paths(resolve_root())
    ensure_dirs(paths)
    setup_logging(paths.logs_dir, debug=False)
    try:
        return SourceProbe.from_paths(paths, say=_say).run(links)
    finally:
        close_logging()


if __name__ == "__main__":
    sys.exit(main())
