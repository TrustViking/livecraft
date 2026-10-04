"""Отправка ответа в форму ключей и подтверждение записи (CLAUDE.md §6 инварианты 1a, 2; §3 шаг 11).

Google-форма — единственный канал передачи ключей стримеру. Неполные ответы (значения нет среди вариантов,
обязательный вопрос без ответа, ключ ещё не опубликован) не отправляются вовсе. POST — с Accept-Language и hl=en;
повторы — `FormHttp` (4xx не повторяются). Страница ответа не подтвердила запись — она сохраняется в logs\\ с маской
ключа, и итог — отказ `not_confirmed`. Итог — значение: `FormConfirmation` или `FormFailure`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.core.retry import AttemptFailure
from app.form.diagnostic import DiagnosticKind, DiagnosticPage, FormDiagnostic
from app.form.failure import FormEvent, FormFailure, FormProblem
from app.form.response_page import ResponsePage
from app.form.submission import FormSubmission
from app.form.transport import FormHttp, HttpAnswer, HttpRequest
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger

LOGGER = get_logger(LogArea.FORM)


@dataclass(frozen=True)
class FormConfirmation:
    """Форма подтвердила запись ответа: что отправлено и какая страница пришла."""

    submission: FormSubmission
    page: ResponsePage


@dataclass(frozen=True)
class FormSender:
    """Отправитель ответов: обмен той же сессией, что читала форму, и сохранение страниц в logs\\."""

    http: FormHttp
    diagnostic: FormDiagnostic

    def send(self, submission: FormSubmission) -> FormConfirmation | FormFailure:
        """Ответ в форму и подтверждение; неполные ответы — отказ без POST."""
        incomplete: FormFailure | None = submission.answers.failure
        if incomplete is not None:
            return self._failed(submission, incomplete)
        submission.post_event.emit(LOGGER)
        answer: HttpAnswer | AttemptFailure = self.http.exchange(HttpRequest(submission.url, submission.body))
        if isinstance(answer, AttemptFailure):
            return self._failed(submission, FormFailure.of_attempt(submission.form.display_name, answer))
        page: ResponsePage = ResponsePage.of(answer)
        if page.is_confirmed:
            page.extend(submission.event(FormEvent.CONFIRMED)).emit(LOGGER)
            return FormConfirmation(submission=submission, page=page)
        return self._failed(submission, self._not_confirmed(submission, answer, page))

    def _not_confirmed(self, submission: FormSubmission, answer: HttpAnswer, page: ResponsePage) -> FormFailure:
        """Страница ответа — в logs\\ с маской ключа; строка `form_not_confirmed` с сигналами страницы."""
        saved: Path | None = self.diagnostic.save(
            DiagnosticPage(DiagnosticKind.RESPONSE, submission.form.settings.url, answer.text, submission.stream_key)
        )
        not_confirmed: LogEvent = page.extend(submission.event(FormEvent.NOT_CONFIRMED))
        not_confirmed.extended(page_title=Quoted(page.title), saved=saved).emit(LOGGER, logging.WARNING)
        return FormFailure.of_status(FormProblem.NOT_CONFIRMED, submission.form.display_name, answer.status, saved)

    def _failed(self, submission: FormSubmission, failure: FormFailure) -> FormFailure:
        """Строка `form_send_failed` со slot_id и ником канала; итог — тот же отказ."""
        failed: LogEvent = failure.event(FormEvent.SEND_FAILED)
        failed.extended(slot_id=submission.slot_id, handle=submission.handle).emit(LOGGER, logging.WARNING)
        return failure
