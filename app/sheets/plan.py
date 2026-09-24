"""План стримов из значений диапазона Google-таблицы (CLAUDE.md §2 контур A, §3 шаг 2.3).

Вход — список списков строк, как его отдаёт `values.get`: первая строка — шапка, ряды данных нумеруются
с 2 (как в самой таблице). Сети здесь нет: чтение таблицы — задача `sheets\\client.py`.

Три объекта:
- `SheetColumns` — где в диапазоне колонки ссылки, даты и времени; сам распознаёт их по шапке;
- `SheetRow` — один ряд (ячейки уже обрезаны); сам решает, допущен ли он (`plan` → `PlanRow`);
- `SheetPlan` — шапка и ряды; сам называет свою проблему (`problem`) и отсеивает повторы (`plan_rows`).

Поведение перенесено из restreamer (`google\\sheets_client.py::read_rows`, `planning\\batch_planner.py::
build_prepared_videos`), кроме обратной записи в таблицу — её в livecraft нет (§6 инвариант 3), и кроме
запасного диапазона при ошибке разбора: диапазон — значение пользователя, своё программа не подставляет.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from typing import Final
from zoneinfo import ZoneInfo

from app.core.sheet_text import (
    is_real_local_time,
    normalize_header_name,
    normalize_youtube_link,
    parse_sheet_datetime,
)
from app.observability.logging_setup import get_logger
from app.sheets.rows import PlanRow, RowSkipReason
from app.ui import messages_ru as msg

LOGGER_NAME: Final[str] = "sheets"
LOGGER = get_logger(LOGGER_NAME)

# Псевдонимы колонок шапки (донор): сначала точное совпадение имени, затем вхождение псевдонима в имя.
# У ссылки донор знал только латиницу; «ссылка» и «видео» добавлены по образцу «дата» и «время».
LINK_ALIASES: Final[tuple[str, ...]] = ("links", "link", "url", "video", "youtube", "ссылка", "видео")
DATE_ALIASES: Final[tuple[str, ...]] = ("date", "дата", "day")
TIME_ALIASES: Final[tuple[str, ...]] = ("time", "время", "hour")
FIRST_DATA_ROW_NUMBER: Final[int] = 2        # строка 1 таблицы — шапка
HEADER_JOINER: Final[str] = ", "
HEADER_ITEM_TEMPLATE: Final[str] = "«{name}»"
SUMMARY_COUNT_TEMPLATE: Final[str] = " {reason}={count}"


@dataclass(frozen=True)
class SheetRow:
    """Один ряд таблицы: номер строки в таблице и три ячейки плана, уже обрезанные по краям."""

    row_number: int
    link: str
    date_raw: str
    time_raw: str

    def plan(self, zone: ZoneInfo, now: datetime) -> PlanRow:
        """Допущен ли ряд. Проверки по порядку донора; первая сработавшая — причина отсева.

        `now` — aware datetime (часы — параметром, в тестах фиксированы).
        """
        if now.utcoffset() is None:
            raise ValueError("now must be an aware datetime")
        if not self.link:
            return PlanRow.skipped(self, RowSkipReason.EMPTY_LINK)
        if not self.date_raw or not self.time_raw:
            return PlanRow.skipped(self, RowSkipReason.MISSING_DATE_TIME)
        try:
            start: datetime = parse_sheet_datetime(self.date_raw, self.time_raw, zone)
        except ValueError:
            return PlanRow.skipped(self, RowSkipReason.BAD_DATE_TIME)
        if not is_real_local_time(start):
            return PlanRow.skipped(self, RowSkipReason.NONEXISTENT_TIME)
        if start < now:
            return PlanRow.skipped(self, RowSkipReason.IN_PAST, start)
        link: str | None = normalize_youtube_link(self.link)
        if link is None:
            return PlanRow.skipped(self, RowSkipReason.BAD_LINK, start)
        return PlanRow.admitted(self, start, link)


@dataclass(frozen=True)
class SheetColumns:
    """Индексы (с 0) колонок ссылки, даты и времени в значениях диапазона."""

    link: int
    date: int
    time: int

    @classmethod
    def from_header(cls, header: list[str]) -> SheetColumns | None:
        """Колонки по шапке; не нашлась хотя бы одна — None."""
        names: list[str] = [normalize_header_name(str(cell)) for cell in header]
        link: int | None = cls._find(names, LINK_ALIASES)
        date: int | None = cls._find(names, DATE_ALIASES)
        time: int | None = cls._find(names, TIME_ALIASES)
        if link is None or date is None or time is None:
            return None
        return cls(link=link, date=date, time=time)

    @staticmethod
    def _find(names: list[str], aliases: tuple[str, ...]) -> int | None:
        wanted: tuple[str, ...] = tuple(normalize_header_name(alias) for alias in aliases)
        for index, name in enumerate(names):
            if name in wanted:
                return index
        for index, name in enumerate(names):
            if any(alias in name for alias in wanted if alias):
                return index
        return None

    def row(self, row_number: int, values: list[str]) -> SheetRow:
        """Ряд из значений строки таблицы; ячейки, которых нет (короткий ряд), — пустые."""
        return SheetRow(
            row_number=row_number,
            link=self._cell(values, self.link),
            date_raw=self._cell(values, self.date),
            time_raw=self._cell(values, self.time),
        )

    @property
    def log_line(self) -> str:
        """Колонки для лога key=value, номера — с 0, как в значениях диапазона."""
        return f"link_column={self.link} date_column={self.date} time_column={self.time}"

    @staticmethod
    def _cell(values: list[str], index: int) -> str:
        if index >= len(values):
            return ""
        return str(values[index]).strip()


@dataclass(frozen=True)
class SheetPlan:
    """План из значений диапазона: шапка, распознанные колонки и ряды данных.

    `range_row_count` — сколько строк пришло в диапазоне вместе с шапкой: отличает пустой диапазон от
    диапазона с нераспознанной шапкой. Шапка не распознана — `columns` None и рядов нет: план не падает,
    а называет проблему (`problem`).
    """

    columns: SheetColumns | None
    rows: tuple[SheetRow, ...]
    header: tuple[str, ...]
    range_row_count: int

    @classmethod
    def from_values(cls, values: list[list[str]]) -> SheetPlan:
        if not values:
            return cls(columns=None, rows=(), header=(), range_row_count=0)
        header: tuple[str, ...] = tuple(str(cell).strip() for cell in values[0])
        columns: SheetColumns | None = SheetColumns.from_header(list(header))
        rows: tuple[SheetRow, ...] = ()
        if columns is not None:
            rows = tuple(
                columns.row(row_number, row_values)
                for row_number, row_values in enumerate(values[1:], start=FIRST_DATA_ROW_NUMBER)
            )
        return cls(columns=columns, rows=rows, header=header, range_row_count=len(values))

    @property
    def problem(self) -> str | None:
        """Почему по этому плану нельзя работать — русской строкой; годному плану — None."""
        if self.range_row_count == 0:
            return msg.SHEET_PLAN_EMPTY
        if self.columns is None:
            return msg.SHEET_PLAN_HEADER_UNKNOWN.format(headers=self._header_text)
        return None

    @property
    def _header_text(self) -> str:
        names: list[str] = [HEADER_ITEM_TEMPLATE.format(name=name) for name in self.header if name]
        return HEADER_JOINER.join(names) if names else msg.SHEET_PLAN_HEADER_NONE

    def plan_rows(self, zone: ZoneInfo, now: datetime) -> tuple[PlanRow, ...]:
        """Разбор каждого ряда и отсев повторов «та же ссылка — тот же момент»; порядок — порядок таблицы.

        Из повторов остаётся ранний ряд, поздний получает `DUPLICATE` и номер оставленного.
        Отсеянный ряд — строкой в лог, итог — счётчиками по причинам.
        """
        if self.problem is not None:
            LOGGER.warning("sheet_plan_problem range_rows=%d header=%r", self.range_row_count, self.header)
            return ()
        kept: dict[tuple[str, datetime], int] = {}
        planned: list[PlanRow] = []
        for row in self.rows:
            outcome: PlanRow = row.plan(zone, now)
            identity: tuple[str, datetime] | None = outcome.identity
            if identity is not None and identity in kept:
                outcome = outcome.as_duplicate_of(kept[identity])
            elif identity is not None:
                kept[identity] = outcome.row_number
            planned.append(outcome)
        result: tuple[PlanRow, ...] = tuple(planned)
        self._log(result)
        return result

    def _log(self, planned: tuple[PlanRow, ...]) -> None:
        for outcome in planned:
            if not outcome.is_admitted:
                LOGGER.info("sheet_row_skipped %s", outcome.log_line)
        LOGGER.info("sheet_plan_ready %s", self._summary(planned))

    def _summary(self, planned: tuple[PlanRow, ...]) -> str:
        counts: Counter[RowSkipReason] = Counter(
            outcome.skip for outcome in planned if outcome.skip is not None
        )
        admitted: int = sum(1 for outcome in planned if outcome.is_admitted)
        columns: str = self.columns.log_line if self.columns is not None else "-"
        line: str = f"rows={len(planned)} admitted={admitted} {columns}"
        for reason in RowSkipReason:
            if counts[reason]:
                line += SUMMARY_COUNT_TEMPLATE.format(reason=reason.value, count=counts[reason])
        return line
