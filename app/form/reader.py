"""Чтение формы ключей по ссылке (CLAUDE.md §6 инвариант 2, §3 шаг 7).

GET страницы с редиректами (короткая ссылка forms.gle ведёт на viewform), повторы — `FormHttp`. Ответ не 200 —
«форма недоступна»; на странице нет FB_PUBLIC_LOAD_DATA_ или вопросов — «форма не прочиталась», и страница
сохраняется в logs\\ для разбора. Пока форма не прочиталась, её заголовка нет — отказ называет форму ссылкой.
"""
from __future__ import annotations

from dataclasses import dataclass
from http import HTTPStatus
from pathlib import Path

from app.core.retry import AttemptFailure
from app.form.diagnostic import DiagnosticKind, DiagnosticPage, FormDiagnostic
from app.form.failure import FormFailure, FormLogDetail, FormProblem
from app.form.payload import FormPayload
from app.form.structure import FormStructure
from app.form.transport import FormHttp, HttpAnswer, HttpRequest
from app.observability.log_event import LogArea, get_logger

LOGGER = get_logger(LogArea.FORM)


@dataclass(frozen=True)
class FormReader:
    """Чтение страницы формы и её структуры: обмен той же сессией, что отправляет ответы, и страницы в logs\\."""

    http: FormHttp
    diagnostic: FormDiagnostic

    def read(self, url: str) -> FormStructure | FormFailure:
        """Структура формы по ссылке или отказ."""
        answer: HttpAnswer | AttemptFailure = self.http.exchange(HttpRequest(url))
        if isinstance(answer, AttemptFailure):
            return FormFailure.of_attempt(url, answer)
        if answer.status != HTTPStatus.OK:
            return FormFailure.of_status(FormProblem.TRANSPORT_FAILED, url, answer.status)
        payload: FormPayload | None = FormPayload.of(answer.text)
        if payload is None:
            return self._unreadable(url, answer, FormLogDetail.NO_SCRIPT)
        structure: FormStructure = FormStructure.of(payload, answer.url)
        if not structure.questions:
            return self._unreadable(url, answer, FormLogDetail.NO_QUESTIONS)
        structure.read_event.emit(LOGGER)
        return structure

    def _unreadable(self, url: str, answer: HttpAnswer, log_detail: FormLogDetail) -> FormFailure:
        """Страница без структуры формы — в logs\\: без неё раскладку нечем разобрать."""
        saved: Path | None = self.diagnostic.save(DiagnosticPage(DiagnosticKind.PAGE, url, answer.text))
        return FormFailure(
            problem=FormProblem.STRUCTURE_UNREADABLE, form=url, detail="", log_detail=log_detail.value, diagnostic=saved
        )
