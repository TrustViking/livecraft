"""Часть «Таблица плана и тексты» отчёта запуска (CLAUDE.md §3 шаги 2.3–2.6, §13 задача 6.3).

Строки части — те же, что прогон контура A сказал в консоли (`IntakeResult.console_lines`); под ними три раздела
уровнем «###»: отсеянные строки таблицы — номер, ссылка и причина; видео — номер строки, ссылка и язык с превью либо
причина отказа; слоты — дата DD.MM.YYYY (§14 решение 31), время, язык, число видео, откуда тексты и название.
Названия и описания видео в отчёт не идут: только название слота, которое уходит в объявления и на YouTube.
"""
from __future__ import annotations

from dataclasses import dataclass

from app.intake.intake import IntakeResult
from app.observability.log_event import LogValue
from app.run.report_section import PartReport, ReportSection
from app.sheets.rows import SkippedRow
from app.slots.slot import StreamSlot
from app.sources.video import SourceVideo
from app.ui.messages import msg


@dataclass(frozen=True)
class IntakeReport:
    """Прогон контура A как часть отчёта запуска."""

    result: IntakeResult

    @property
    def part_report(self) -> PartReport:
        return PartReport(
            msg.REPORT_PART_INTAKE, self.result.console_lines, (self._skipped, self._videos, self._slots)
        )

    @property
    def _skipped(self) -> ReportSection:
        """Отсеянные строки таблицы в порядке таблицы."""
        rows: tuple[SkippedRow, ...] = () if self.result.rows is None else self.result.rows.skipped
        lines: list[str] = [
            msg.REPORT_ROW_LINE.format(
                row=row.row_number, link=row.row.link or LogValue.EMPTY.value, text=row.reason.human
            )
            for row in rows
        ]
        return ReportSection(msg.REPORT_SECTION_SKIPPED_ROWS.format(count=len(lines)), lines)

    @property
    def _videos(self) -> ReportSection:
        """Видео допущенных строк в порядке строк: годное — язык и превью, негодное — причина."""
        videos: tuple[SourceVideo, ...] = () if self.result.sources is None else self.result.sources.videos
        lines: list[str] = [self._video_line(video) for video in videos]
        return ReportSection(msg.REPORT_SECTION_VIDEOS.format(count=len(lines)), lines)

    def _video_line(self, video: SourceVideo) -> str:
        """Годное видео — язык и есть ли превью; негодное — причина отказа."""
        preview: str = msg.REPORT_VIDEO_PREVIEW if video.preview is not None else msg.REPORT_VIDEO_NO_PREVIEW
        text: str = msg.REPORT_VIDEO_READY.format(language=video.language_code, preview=preview)
        if video.refusal is not None:
            text = video.refusal.human
        return msg.REPORT_ROW_LINE.format(row=video.row_number, link=video.link, text=text)

    @property
    def _slots(self) -> ReportSection:
        """Годные слоты, затем слоты с проблемой — каждые в порядке слотов."""
        if self.result.build is None:
            return ReportSection(msg.REPORT_SECTION_SLOTS.format(count=0), ())
        lines: list[str] = [self._slot_line(slot) for slot in self.result.build.slots]
        lines.extend(
            msg.REPORT_SLOT_REFUSED.format(
                date=slot.human_date, time=slot.time, language=slot.language, videos=len(slot.sources),
                problem=slot.problem.human,
            )
            for slot in self.result.build.refused
        )
        return ReportSection(msg.REPORT_SECTION_SLOTS.format(count=len(lines)), lines)

    def _slot_line(self, slot: StreamSlot) -> str:
        """Слот: когда, язык, сколько видео, откуда тексты и название слота."""
        return msg.REPORT_SLOT.format(
            date=slot.human_date,
            time=slot.time,
            language=slot.language,
            videos=len(slot.sources),
            origin=msg.REPORT_TEXT_ORIGINS[slot.text_origin.value],
            title=slot.title,
        )
