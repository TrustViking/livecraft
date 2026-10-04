"""Формы и допуск объектов прогона части «эфиры» (CLAUDE.md §3 шаги 7, 9; §6 инвариант 2).

Даты формы проверяются по прочитанной форме до входов и до площадки: одна проверка и одна строка на форму — ранний
сигнал; допуск она не меняет (объект без варианта даты не допускается сам). Допуск — после фазы входов: каждый объект
получает объект своего канала и свою форму и решает сам (`PlannedBroadcast.admit`). Линия «Ключи в форму» не идёт
(`forms` — None, §14 решение 37) — форма не читается, даты не проверяются, допуск только по каналу. Не допущенный
объект на площадке ничего не создаёт и в форму ничего не шлёт, но остаётся в отчёте, консоли и keys.txt.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.broadcasts.event import BroadcastsEvent
from app.config.settings import FormSettings
from app.form.book import FormBook
from app.form.coverage import DateCoverage
from app.form.failure import FormFailure
from app.form.key_form import KeyForm
from app.form.question import NO_VALUE
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.pipeline.admission import AdmissionReason
from app.pipeline.plan import PlannedBroadcast
from app.pipeline.progress import RunProgress
from app.platforms.channel_book import ChannelBook

LOGGER = get_logger(LogArea.BROADCASTS)
# Причина недопуска в строке slot_not_admitted: вид, код и поле формы.
REASON_LOG_TEMPLATE: Final[str] = "{kind}:{code}:{field}"


@dataclass(frozen=True)
class BroadcastAdmission:
    """Книга каналов, формы ключей (None — ключи в форму не идут) и строки прогресса одного прогона."""

    book: ChannelBook
    forms: FormBook | None
    progress: RunProgress

    def check_form_dates(self, planned: Sequence[PlannedBroadcast]) -> None:
        """Покрывает ли каждая форма даты объектов, которые запуск собирается публиковать (не too_late).

        Форма не прочиталась — это причина недопуска её объектов, а не повод для строки здесь. Ключи в форму не идут —
        форма не читается.
        """
        if self.forms is None:
            return
        forms: dict[str, FormSettings] = {}
        starts: dict[str, list[datetime]] = {}
        for item in planned:
            if item.is_too_late:
                continue
            forms.setdefault(item.form.url, item.form)
            starts.setdefault(item.form.url, []).append(item.slot.start)
        for url, settings in forms.items():
            form: KeyForm | FormFailure = self.forms.form_for(settings)
            if isinstance(form, KeyForm):
                coverage: DateCoverage = form.date_coverage(starts[url])
                coverage.log()
                self.progress.form_dates_checked(coverage)

    def admit_all(self, planned: Sequence[PlannedBroadcast]) -> None:
        """Допуск после фазы входов: объект канала и форма (ключи в форму не идут — без формы) — каждому объекту;
        решает сам объект."""
        for item in planned:
            form: KeyForm | FormFailure | None = None if self.forms is None else self.forms.form_for(item.form)
            item.admit(self.book.channel(item.channel), form)
            if not item.is_too_late:
                self._log(item)

    def _log(self, item: PlannedBroadcast) -> None:
        if item.admission.is_admitted:
            BroadcastsEvent.SLOT_ADMITTED.of(item, form_url=item.form.url).emit(LOGGER)
            return
        reasons: tuple[AdmissionReason, ...] = item.admission.reasons
        summary: tuple[str, ...] = tuple(
            REASON_LOG_TEMPLATE.format(kind=reason.kind.value, code=reason.code, field=reason.field or NO_VALUE)
            for reason in reasons
        )
        BroadcastsEvent.SLOT_NOT_ADMITTED.of(item, reasons=summary).emit(LOGGER, logging.WARNING)
        for reason in reasons:
            detail: LogEvent = BroadcastsEvent.SLOT_NOT_ADMITTED_REASON.of(item, kind=reason.kind, code=reason.code)
            detail.extended(field=reason.field, text=Quoted(reason.text)).emit(LOGGER, logging.WARNING)
