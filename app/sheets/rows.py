"""Ряды таблицы плана: ряд, его допуск и итог разбора всех рядов (CLAUDE.md §3 шаг 2.3).

`SheetRow` — ряд как в таблице; своё правило `plan` он превращает в `AdmittedRow` (нормализованное видео YouTube
и момент старта в зоне программы) или в `SkippedRow` (причина `RowSkipReason`). Отсеянный ряд не выбрасывается:
он остаётся в итоге, пишется в лог и дальше по конвейеру не идёт (§0). `PlannedRows` — итог разбора: допущенные
и отсеянные ряды в порядке таблицы, повторы «та же ссылка на тот же момент» уже отсеяны.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from zoneinfo import ZoneInfo

from app.core.counts import Counts
from app.core.dates import ISO_TIMESPEC, require_aware
from app.core.sheet_text import is_real_local_time, parse_sheet_datetime
from app.core.youtube_video import YouTubeVideoId
from app.observability.log_event import LogEvent
from app.ui import messages_ru as msg


class RowSkipReason(str, Enum):
    """Почему ряд не идёт в план. Порядок членов — порядок проверок `SheetRow.plan`, последним — повтор."""

    EMPTY_LINK = "empty_link"
    MISSING_DATE_TIME = "missing_date_time"
    BAD_DATE_TIME = "bad_date_time"
    NONEXISTENT_TIME = "nonexistent_time"   # переход на летнее время: такого местного времени нет
    IN_PAST = "in_past"
    BAD_LINK = "bad_link"
    DUPLICATE = "duplicate"                 # та же ссылка на тот же момент, что у более раннего ряда

    @property
    def human(self) -> str:
        """Русская строка причины; текст — в messages_ru (§11)."""
        return msg.SHEET_ROW_SKIP_REASONS[self.value]


class RowsEvent(str, Enum):
    """События разбора рядов в логе."""

    SKIPPED = "sheet_row_skipped"
    PLAN_READY = "sheet_plan_ready"


@dataclass(frozen=True)
class SheetRow:
    """Один ряд таблицы: номер строки в таблице и три ячейки плана, уже обрезанные по краям."""

    row_number: int
    link: str
    date_raw: str
    time_raw: str

    def plan(self, zone: ZoneInfo, now: datetime) -> AdmittedRow | SkippedRow:
        """Допущен ли ряд. Проверки по порядку `RowSkipReason`; первая сработавшая — причина отсева.

        `now` — aware datetime (часы — параметром, в тестах фиксированы).
        """
        require_aware(now)
        if not self.link:
            return SkippedRow(self, RowSkipReason.EMPTY_LINK)
        if not self.date_raw or not self.time_raw:
            return SkippedRow(self, RowSkipReason.MISSING_DATE_TIME)
        try:
            start: datetime = parse_sheet_datetime(self.date_raw, self.time_raw, zone)
        except ValueError:
            return SkippedRow(self, RowSkipReason.BAD_DATE_TIME)
        if not is_real_local_time(start):
            return SkippedRow(self, RowSkipReason.NONEXISTENT_TIME)
        if start < now:
            return SkippedRow(self, RowSkipReason.IN_PAST, start)
        video: YouTubeVideoId | None = YouTubeVideoId.of(self.link)
        if video is None:
            return SkippedRow(self, RowSkipReason.BAD_LINK, start)
        return AdmittedRow(self, start, video)


@dataclass(frozen=True)
class RowIdentity:
    """Что делает два ряда повтором: та же нормализованная ссылка и тот же момент.

    Момент сравнивается как момент (aware datetime), а не как текст: 19:00 по Киеву и 16:00 UTC равны.
    """

    link: str
    start: datetime


@dataclass(frozen=True)
class AdmittedRow:
    """Допущенный ряд: видео YouTube из ячейки ссылки и момент старта в зоне программы."""

    row: SheetRow
    start: datetime
    video: YouTubeVideoId

    @property
    def link(self) -> str:
        """Нормализованная ссылка `https://youtu.be/<id>` — по ней спрашивают yt-dlp и узнают повторы."""
        return self.video.short_url

    @property
    def row_number(self) -> int:
        return self.row.row_number

    @property
    def identity(self) -> RowIdentity:
        return RowIdentity(link=self.link, start=self.start)

    def as_duplicate_of(self, kept_row_number: int) -> SkippedRow:
        """Этот же ряд, отсеянный как повтор ряда `kept_row_number`; момент сохраняется для лога."""
        return SkippedRow(self.row, RowSkipReason.DUPLICATE, self.start, kept_row_number)


@dataclass(frozen=True)
class SkippedRow:
    """Отсеянный ряд: причина, момент старта, если дата и время разобрались, и номер оставленного ряда у повтора."""

    row: SheetRow
    reason: RowSkipReason
    start: datetime | None = None
    duplicate_of: int | None = None

    @property
    def row_number(self) -> int:
        return self.row.row_number

    @property
    def event(self) -> LogEvent:
        """Строка лога: номер, причина, ячейки как в таблице (ссылка — не секрет), момент и оставленный ряд."""
        start: str | None = None if self.start is None else self.start.isoformat(timespec=ISO_TIMESPEC)
        return LogEvent.of(
            RowsEvent.SKIPPED,
            row=self.row_number,
            reason=self.reason,
            link=self.row.link,
            date=self.row.date_raw,
            time=self.row.time_raw,
            start=start,
            duplicate_of=self.duplicate_of,
        )


@dataclass(frozen=True)
class PlannedRows:
    """Итог разбора рядов: допущенные и отсеянные — каждые в порядке таблицы."""

    admitted: tuple[AdmittedRow, ...]
    skipped: tuple[SkippedRow, ...]

    @classmethod
    def of(cls, rows: Sequence[SheetRow], zone: ZoneInfo, now: datetime) -> PlannedRows:
        """Разбор каждого ряда и отсев повторов: из повторов остаётся ранний ряд, поздний — `DUPLICATE`."""
        kept: dict[RowIdentity, int] = {}
        admitted: list[AdmittedRow] = []
        skipped: list[SkippedRow] = []
        for row in rows:
            outcome: AdmittedRow | SkippedRow = row.plan(zone, now)
            if isinstance(outcome, SkippedRow):
                skipped.append(outcome)
                continue
            kept_row: int = kept.setdefault(outcome.identity, outcome.row_number)
            if kept_row == outcome.row_number:
                admitted.append(outcome)
            else:
                skipped.append(outcome.as_duplicate_of(kept_row))
        return cls(admitted=tuple(admitted), skipped=tuple(skipped))

    @property
    def total(self) -> int:
        return len(self.admitted) + len(self.skipped)

    @property
    def counts(self) -> Counts[RowSkipReason]:
        """Отсеянные ряды по причинам в порядке проверок."""
        return Counts.of((row.reason for row in self.skipped), order=tuple(RowSkipReason))

    @property
    def ready_event(self) -> LogEvent:
        """Итог разбора в лог: сколько рядов, сколько допущено и отсеянные по причинам."""
        return LogEvent.of(
            RowsEvent.PLAN_READY, rows=self.total, admitted=len(self.admitted), skipped=self.counts.log_value
        )

    @property
    def console_line(self) -> str:
        """Строка для оператора: сколько рядов прочитано, допущено и отсеяно, причины отсева с числами."""
        reasons: str = self.counts.wrapped(
            msg.INTAKE_TABLE_REASONS, msg.INTAKE_COUNT_ITEM, msg.ITEM_JOINER, lambda reason: reason.human
        )
        return msg.INTAKE_TABLE_LINE.format(
            rows=self.total, admitted=len(self.admitted), skipped=len(self.skipped), reasons=reasons
        )
