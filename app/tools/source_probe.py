"""Пробник источников: ссылка → yt-dlp → данные видео и обложка (CLAUDE.md §5 tools\\).

Запуск из корня репо: `python -m app.tools.source_probe <ссылка> [<ссылка> ...]`. В поставку не идёт.
Сети и yt-dlp в тестах нет — получатель и скачивание подменяются; боевой прогон делает Артур.

Ссылка нормализуется так же, как ссылка ряда таблицы (`https://youtu.be/<id>`), и идёт тем же путём, что
в боевом запуске: `SourceCatalog.facts` — yt-dlp, язык, обложка. Сейф пробнику не нужен: ссылки на видео — не секрет.
Коды: 0 — все источники получены и язык каждого определился; 1 — есть отказы или язык не определился;
2 — нет tools\\yt-dlp.exe или не указано ни одной ссылки.
"""
from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.dates import MINUTES_PER_HOUR, SECONDS_PER_MINUTE
from app.core.youtube_video import YouTubeVideoId
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.run.exit_code import ExitCode
from app.slots.preview import Preview
from app.sources.language import LanguageDecision
from app.sources.metadata import SourceFailureReason, SourceMetadata
from app.sources.preview import PreviewResult
from app.sources.video import SourceCatalog, SourceFacts
from app.tools.probe import ProbeConsole, ProbeLauncher, ProbeSession
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.SOURCE_PROBE)

LANGUAGES_SHOWN: Final[int] = 10
BYTES_PER_KILOBYTE: Final[int] = 1024
DURATION_TEMPLATE: Final[str] = "{hours}:{minutes:02d}:{seconds:02d}"


class SourceProbeEvent(str, Enum):
    """События пробника источников в логе."""

    PROBED = "source_probe"
    BAD_LINK = "source_probe_bad_link"


@dataclass(frozen=True)
class SourceProbeReport:
    """Что показать человеку об одном источнике: поля yt-dlp, язык и обложка либо причина отказа."""

    facts: SourceFacts

    @property
    def is_ok(self) -> bool:
        """Источник годится так же, как в боевом запуске: данные видео есть и язык определился."""
        return self.facts.is_ready

    @property
    def lines(self) -> tuple[str, ...]:
        metadata: SourceMetadata | None = self.facts.fetch.metadata
        head: tuple[str, ...] = (msg.SOURCE_PROBE_SOURCE.format(link=self.facts.fetch.url),)
        fields: tuple[str, ...] = self._metadata_lines(metadata) if metadata is not None else ()
        return (*head, *fields, *self._outcome_lines)

    def _metadata_lines(self, metadata: SourceMetadata) -> tuple[str, ...]:
        return (
            msg.SOURCE_PROBE_ID.format(value=metadata.video_id or msg.NONE_TEXT),
            msg.SOURCE_PROBE_NAME.format(value=metadata.title or msg.NONE_TEXT),
            msg.SOURCE_PROBE_DURATION.format(value=self._duration(metadata.duration_seconds)),
            msg.SOURCE_PROBE_LANGUAGE.format(
                video=metadata.youtube_language or msg.NONE_TEXT,
                channel=metadata.channel_language or msg.NONE_TEXT,
            ),
            msg.SOURCE_PROBE_AUDIO.format(value=self._languages(metadata.audio_languages)),
            msg.SOURCE_PROBE_SUBTITLES.format(value=self._languages(metadata.subtitle_languages)),
            msg.SOURCE_PROBE_AUTO_CAPTIONS.format(value=self._languages(metadata.auto_caption_languages)),
        )

    def _languages(self, values: tuple[str, ...]) -> str:
        """Первые LANGUAGES_SHOWN кодов через запятую и сколько не показано; пусто — «нет»."""
        if not values:
            return msg.NONE_TEXT
        shown: str = msg.LIST_JOINER.join(values[:LANGUAGES_SHOWN])
        more: int = len(values) - LANGUAGES_SHOWN
        return msg.SOURCE_PROBE_MORE.format(shown=shown, more=more) if more > 0 else shown

    def _duration(self, seconds: int | None) -> str:
        """Секунды → H:MM:SS; нет длительности — «нет»."""
        if seconds is None:
            return msg.NONE_TEXT
        minutes, rest = divmod(seconds, SECONDS_PER_MINUTE)
        hours, minutes = divmod(minutes, MINUTES_PER_HOUR)
        return DURATION_TEMPLATE.format(hours=hours, minutes=minutes, seconds=rest)

    @property
    def _outcome_lines(self) -> tuple[str, ...]:
        """Отказ — причина и подробность yt-dlp; удача — строка языка и строка обложки (или почему её нет)."""
        failure: SourceFailureReason | None = self.facts.fetch.failure
        if failure is not None:
            return (
                msg.SOURCE_PROBE_FAILED.format(reason=failure.human),
                msg.SOURCE_PROBE_DETAIL.format(detail=self.facts.fetch.detail),
            )
        return (*self._language_lines, *self._preview_lines)

    @property
    def _preview_lines(self) -> tuple[str, ...]:
        """Язык не определился — обложку не качали, как в боевом запуске; иначе — строка обложки, если она есть."""
        decision: LanguageDecision | None = self.facts.language
        if decision is not None and not decision.is_resolved:
            return (msg.SOURCE_PROBE_PREVIEW_SKIPPED,)
        if self.facts.preview is None:
            return ()
        return (self._preview_line(self.facts.preview),)

    @property
    def _language_lines(self) -> tuple[str, ...]:
        """Решённый язык и правило; не определился — строка об этом; не решался — ничего."""
        decision: LanguageDecision | None = self.facts.language
        if decision is None:
            return ()
        if decision.language is None:
            return (msg.SOURCE_PROBE_SOURCE_LANGUAGE_NONE,)
        return (msg.SOURCE_PROBE_SOURCE_LANGUAGE.format(code=decision.language, source=decision.source.value),)

    def _preview_line(self, result: PreviewResult) -> str:
        """Размеры и вес готовой обложки либо причина, почему её нет."""
        image: Preview | None = result.preview
        if image is None:
            reason: str = result.problem.human if result.problem is not None else msg.NONE_TEXT
            return msg.SOURCE_PROBE_PREVIEW_BAD.format(reason=reason)
        kilobytes: int = round(image.size_bytes / BYTES_PER_KILOBYTE)
        return msg.SOURCE_PROBE_PREVIEW_OK.format(width=image.width, height=image.height, kilobytes=kilobytes)


@dataclass(frozen=True)
class SourceProbe:
    """Один прогон пробника: источники и вывод — полями, в тестах свои."""

    catalog: SourceCatalog
    console: ProbeConsole

    @classmethod
    def of(cls, session: ProbeSession) -> SourceProbe:
        """Боевые зависимости корня сессии: источники так же, как в боевом запуске (yt-dlp из tools\\)."""
        return cls(catalog=SourceCatalog.from_paths(session.paths), console=session.console)

    def run(self, raw_links: Sequence[str]) -> int:
        self.console.say(msg.SOURCE_PROBE_TITLE)
        if not raw_links:
            self.console.say(msg.SOURCE_PROBE_USAGE)
            return int(ExitCode.CONFIG)
        failed: int = 0
        for raw in raw_links:
            report: SourceProbeReport | None = self._probe(raw)
            if report is not None and report.facts.fetch.failure is SourceFailureReason.TOOL_MISSING:
                return int(ExitCode.CONFIG)
            if report is None or not report.is_ok:
                failed += 1
        total: int = len(raw_links)
        self.console.say(msg.SOURCE_PROBE_SUMMARY.format(total=total, ok=total - failed, failed=failed))
        return int(ExitCode.ERRORS if failed else ExitCode.OK)

    def _probe(self, raw: str) -> SourceProbeReport | None:
        """Одна ссылка: нормализовать, собрать факты о видео тем же путём, что в боевом запуске, напечатать;
        не YouTube — None."""
        video: YouTubeVideoId | None = YouTubeVideoId.of(raw)
        if video is None:
            LogEvent.of(SourceProbeEvent.BAD_LINK, raw=raw).emit(LOGGER, logging.WARNING)
            self.console.say(msg.SOURCE_PROBE_BAD_LINK.format(raw=raw))
            return None
        facts: SourceFacts = self.catalog.facts(video.short_url)
        LogEvent.of(SourceProbeEvent.PROBED, link=video.short_url, **facts.log_fields).emit(LOGGER)
        report: SourceProbeReport = SourceProbeReport(facts=facts)
        self.console.say_lines(report.lines)
        return report


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа пробника: ссылки; корень, папки и лог — у `ProbeLauncher`; дальше — `SourceProbe`."""
    links: Sequence[str] = sys.argv[1:] if argv is None else argv
    return ProbeLauncher.system().run(lambda session: SourceProbe.of(session).run(links))


if __name__ == "__main__":
    sys.exit(main())
