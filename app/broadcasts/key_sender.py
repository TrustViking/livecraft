"""Ключ эфира — в форму сразу после действий по своему объекту (CLAUDE.md §6 инварианты 1a, 2).

Ключ взят с площадки: запись в память → объект сам решает, должен ли ключ уйти (`decide_key_delivery`: «новые | все»,
§14 решение 49) → в память ещё одна неподтверждённая отправка (`remember_send`) — до POST: обрыв посреди отправки её не
теряет, и следующий запуск пошлёт ключ повтором → ответ формы этого эфира → подтверждение формы снимает счёт и пишется в
память. Неполный ответ — без POST, причина — отказом формы (`FormAnswers.failure`), и это тоже неподтверждённая
отправка. Ошибка другого шага отправку уже взятого ключа не отменяет: отправка идёт после действий, что бы с ними ни
случилось. Обрыв запуска не теряет уже отправленные ключи.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass

from app.broadcasts.event import BroadcastsEvent
from app.broadcasts.record_keeper import RecordKeeper
from app.core.clock import Clock
from app.form.answers import FormAnswers
from app.form.failure import FormFailure
from app.form.sender import FormConfirmation, FormSender
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.observability.logging_setup import mask_stream_key
from app.pipeline.plan import KeyRoute, PlannedBroadcast
from app.pipeline.progress import RunProgress
from app.records.slot_record import SlotStage

LOGGER = get_logger(LogArea.BROADCASTS)


@dataclass(frozen=True)
class KeySender:
    """Память, отправитель ответов формы, часы, строки прогресса одного прогона и правила ключей запуска (`KeyRoute`:
    идут ли ключи в форму, включена ли повторная передача)."""

    keeper: RecordKeeper
    sender: FormSender
    clock: Clock
    progress: RunProgress
    route: KeyRoute

    def deliver(self, item: PlannedBroadcast) -> None:
        """Ключ допущенного объекта, взятый с площадки: записать → решить → в форму → записать итог отправки."""
        if not item.match.stream_key or not item.admission.is_admitted or item.is_too_late:
            return
        self.keeper.save(item, SlotStage.PUBLISHED)
        item.decide_key_delivery(self.route)
        if not item.outcome.should_send_key:
            return
        item.remember_send(self.clock)          # до ответа формы отправка не подтверждена: обрыв её не потеряет
        self.keeper.save(item, SlotStage.PUBLISHED)
        if self._send(item):
            item.remember_send(self.clock)
            self.keeper.save(item, SlotStage.KEY_CONFIRMED)

    def _send(self, item: PlannedBroadcast) -> bool:
        """Ключ — в форму сейчас; ответ неполный — без POST. True — форма подтвердила."""
        if not item.is_key_ready_to_send:
            self._skip(item)
            return False
        self.progress.key_send_started(item)
        reply: FormConfirmation | FormFailure = self.sender.send(item.submission())
        confirmed: bool = item.outcome.take_form_reply(reply, self.clock.now())
        masked: str = mask_stream_key(item.match.stream_key)
        BroadcastsEvent.FORM_SEND.of(item, confirmed=confirmed, stream_key=masked).emit(LOGGER)
        return confirmed

    def _skip(self, item: PlannedBroadcast) -> None:
        """Ответ неполный: почему ключ не ушёл — отказом формы в объект и строкой лога."""
        answers: FormAnswers | None = item.admission.answers
        failure: FormFailure | None = None if answers is None else answers.failure
        if failure is None:
            return
        item.outcome.form_failure = failure
        skipped: LogEvent = BroadcastsEvent.FORM_SEND_SKIPPED.of(item, problem=failure.problem)
        skipped.extended(text=Quoted(failure.human)).emit(LOGGER, logging.WARNING)
