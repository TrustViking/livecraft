"""Итог разбора одного ряда таблицы плана: допущен или отсеян с причиной (CLAUDE.md §3 шаг 2.3).

`PlanRow` — то, во что ряд `SheetRow` превращает своё правило `SheetRow.plan`. Допущенный ряд несёт
нормализованную ссылку YouTube и момент старта в зоне программы; отсеянный — причину `RowSkipReason`.
Отсеянный ряд не выбрасывается: он остаётся в плане, пишется в лог и дальше по конвейеру не идёт (§0).
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import Enum
from typing import TYPE_CHECKING, Final

from app.core.dates import format_date, format_time
from app.ui import messages_ru as msg

if TYPE_CHECKING:      # только для аннотаций: plan.py импортирует этот модуль в рантайме
    from app.sheets.plan import SheetRow

ROW_LOG_TEMPLATE: Final[str] = "row={row} reason={reason} link={link!r} date={date!r} time={time!r}"
START_LOG_TEMPLATE: Final[str] = " start={start}"
DUPLICATE_LOG_TEMPLATE: Final[str] = " duplicate_of={row}"


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


@dataclass(frozen=True)
class PlanRow:
    """Ряд таблицы после разбора.

    `start` — момент старта, если дата и время разобрались (у допущенного есть всегда);
    `link` — нормализованная ссылка `https://youtu.be/<id>`, если её пришлось и удалось построить;
    `skip` — причина отсева, у допущенного None; `duplicate_of` — номер оставленного ряда у повтора.
    """

    row: SheetRow
    start: datetime | None
    link: str | None
    skip: RowSkipReason | None
    duplicate_of: int | None = None

    @classmethod
    def admitted(cls, row: SheetRow, start: datetime, link: str) -> PlanRow:
        return cls(row=row, start=start, link=link, skip=None)

    @classmethod
    def skipped(
        cls, row: SheetRow, reason: RowSkipReason, start: datetime | None = None
    ) -> PlanRow:
        return cls(row=row, start=start, link=None, skip=reason)

    @property
    def is_admitted(self) -> bool:
        return self.skip is None

    @property
    def row_number(self) -> int:
        return self.row.row_number

    @property
    def identity(self) -> tuple[str, datetime] | None:
        """Что делает два ряда повтором: та же нормализованная ссылка и тот же момент. Только у допущенного.

        Момент сравнивается как момент (aware datetime), а не как текст: 19:00 по Киеву и 17:00 UTC равны.
        """
        if not self.is_admitted or self.link is None or self.start is None:
            return None
        return (self.link, self.start)

    def as_duplicate_of(self, kept_row_number: int) -> PlanRow:
        """Этот же ряд, отсеянный как повтор ряда `kept_row_number`; ссылка и момент сохраняются для лога."""
        return replace(self, skip=RowSkipReason.DUPLICATE, duplicate_of=kept_row_number)

    @property
    def date_text(self) -> str | None:
        """Дата старта DD-MM-YYYY в зоне момента (§6 инвариант 4); только у допущенного, иначе None."""
        if not self.is_admitted or self.start is None:
            return None
        return format_date(self.start.date())

    @property
    def time_text(self) -> str | None:
        """Время старта HH:MM в зоне момента; только у допущенного, иначе None."""
        if not self.is_admitted or self.start is None:
            return None
        return format_time(self.start.time())

    @property
    def log_line(self) -> str:
        """Строка лога отсеянного ряда key=value: номер, причина, ячейки как в таблице (ссылка — не секрет)."""
        reason: str = self.skip.value if self.skip is not None else "-"
        line: str = ROW_LOG_TEMPLATE.format(
            row=self.row.row_number,
            reason=reason,
            link=self.row.link,
            date=self.row.date_raw,
            time=self.row.time_raw,
        )
        if self.start is not None:
            line += START_LOG_TEMPLATE.format(start=self.start.isoformat())
        if self.duplicate_of is not None:
            line += DUPLICATE_LOG_TEMPLATE.format(row=self.duplicate_of)
        return line
