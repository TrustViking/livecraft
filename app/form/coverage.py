"""Покрывает ли вопрос «Время стрима» даты запуска — проверка до входов и до площадки (CLAUDE.md §3 шаг 7).

Даты сопоставляются тем же правилом, что и при отправке (`PageQuestion.date_option`): что здесь названо недостающим,
то при допуске даст «варианта нет», и наоборот. Строка консоли — `line` (даты для людей — 17.03.2027, решение 31),
строка лога — `event`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from enum import Enum

from app.core.dates import format_human_date
from app.form.failure import FormEvent
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.ui.messages import msg

LOGGER = get_logger(LogArea.FORM)


class CoverageSkip(str, Enum):
    """Почему даты не проверялись."""

    NO_DATE_QUESTION = "no_date_question"    # вопроса даты нет в настройках или в форме


@dataclass(frozen=True)
class DateCoverage:
    """Итог проверки дат одной формы."""

    form_url: str
    form_name: str                      # имя формы для людей (KeyForm.display_name)
    question_title: str                 # пусто — вопроса даты нет в настройках или в форме
    is_checkable: bool                  # вопрос есть и он с вариантами (не ввод текста)
    wanted: tuple[str, ...]             # даты запуска в формате даты формы, по возрастанию, без повторов
    missing: tuple[str, ...]            # из wanted — без варианта в форме, тот же порядок
    missing_dates: tuple[date, ...]     # те же даты объектами date, тот же порядок
    accepted_count: int                 # сколько дат форма принимает (KeyForm.accepted_dates)

    @property
    def is_complete(self) -> bool:
        return not self.missing

    @property
    def missing_text(self) -> str:
        """Недостающие даты для людей: 17.03.2027, 18.03.2027."""
        return msg.LIST_JOINER.join(format_human_date(value) for value in self.missing_dates)

    @property
    def line(self) -> str | None:
        """Строка консоли; вопроса даты нет — строки нет: проверять нечего."""
        if not self.question_title:
            return None
        if not self.is_checkable:
            return msg.FORM_DATES_ANY.format(form=self.form_name)
        if self.is_complete:
            return msg.FORM_DATES_OK.format(form=self.form_name, wanted=len(self.wanted), accepted=self.accepted_count)
        return msg.FORM_DATES_MISSING.format(form=self.form_name, dates=self.missing_text)

    @property
    def event(self) -> LogEvent:
        """Строка `form_dates_checked`; вопроса даты нет — `form_dates_not_checked`."""
        if not self.question_title:
            return LogEvent.of(FormEvent.DATES_NOT_CHECKED, url=self.form_url, reason=CoverageSkip.NO_DATE_QUESTION)
        checked: LogEvent = LogEvent.of(FormEvent.DATES_CHECKED, url=self.form_url, title=Quoted(self.form_name))
        return checked.extended(
            question=Quoted(self.question_title), wanted=len(self.wanted), missing=len(self.missing), dates=self.missing
        )

    def log(self) -> None:
        """Строка лога: проверка — INFO, «не проверялось» — DEBUG."""
        self.event.emit(LOGGER, logging.INFO if self.question_title else logging.DEBUG)
