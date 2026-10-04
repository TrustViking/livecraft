"""Отказ формы ключей и строки лога формы (CLAUDE.md §11 «Контракт ошибок», §13 задача 5.1).

Итог чтения формы и отправки ответа — значение, как у бота Telegram: форма или подтверждение, либо `FormFailure`.
Отказ несёт причину `FormProblem`, имя формы для людей (заголовок, иначе ссылка — она не секрет, §14 решение 15),
подробность для человека (`detail`: «вопрос: вариант», названия вопросов, код ответа), английскую подробность
только для лога (`log_detail`) и сохранённую страницу в logs\\ (`diagnostic`). Текст для человека — `human` из
каталога `msg`; строка лога — `event` с именем события того, кто пишет строку.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.core.retry import AttemptFailure
from app.observability.log_event import LogEvent, Quoted
from app.ui.messages import msg


class FormProblem(str, Enum):
    """Почему форма не прочиталась или ответ не ушёл. Текст для человека — `msg.FORM_PROBLEMS`."""

    STRUCTURE_UNREADABLE = "structure_unreadable"   # на странице нет FB_PUBLIC_LOAD_DATA_ или вопросов
    MISSING_OPTION = "missing_option"               # значения нет среди вариантов вопроса
    REQUIRED_MISSING = "required_missing"           # обязательный вопрос пройденного раздела без ответа
    TRANSPORT_FAILED = "transport_failed"           # форма не ответила или ответила не 200
    NOT_CONFIRMED = "not_confirmed"                 # страница ответа не подтвердила запись


class FormEvent(str, Enum):
    """События формы ключей в логе."""

    STRUCTURE_READ = "form_structure_read"
    GET_RETRY = "form_get_retry"
    POST_RETRY = "form_post_retry"
    JUMP_UNKNOWN_SECTION = "form_jump_unknown_section"
    DIAGNOSTIC_SAVED = "form_diagnostic_saved"
    DIAGNOSTIC_NOT_SAVED = "form_diagnostic_not_saved"
    READY = "form_ready"
    UNREADABLE = "form_unreadable"
    PAGES_BY_NAVIGATION = "form_pages_by_navigation"
    PAGES_BY_ANSWERS = "form_pages_by_answers"
    PAGE_OUT_OF_RANGE = "form_page_out_of_range"
    DATES_CHECKED = "form_dates_checked"
    DATES_NOT_CHECKED = "form_dates_not_checked"
    POST = "form_post"
    CONFIRMED = "form_confirmed"
    NOT_CONFIRMED = "form_not_confirmed"
    SEND_FAILED = "form_send_failed"


class FormLogDetail(str, Enum):
    """Английская подробность отказа — только в лог."""

    NO_SCRIPT = "FB_PUBLIC_LOAD_DATA_ not found or not JSON"
    NO_QUESTIONS = "no questions in FB_PUBLIC_LOAD_DATA_"
    HTTP_STATUS = "HTTP {status}"
    REQUEST_FAILED = "request failed: {error}"
    MISSING_OPTION = "no option for field {field}"
    REQUIRED_MISSING = "required questions of the visited sections without answer"
    PENDING = "answers expected after publication: {count}"

    def text(self, **values: object) -> str:
        return self.value.format(**values)


@dataclass(frozen=True)
class FormFailure:
    """Отказ формы: причина, имя формы, подробность для человека и для лога, сохранённая страница."""

    problem: FormProblem
    form: str
    detail: str
    log_detail: str
    diagnostic: Path | None = None

    @classmethod
    def of_attempt(cls, form: str, failure: AttemptFailure) -> FormFailure:
        """Обращение не удалось и после повторов: код ответа — человеку, имя исключения — только в лог."""
        if failure.status is not None:
            return cls.of_status(FormProblem.TRANSPORT_FAILED, form, failure.status)
        log_detail: str = FormLogDetail.REQUEST_FAILED.text(error=failure.error_name)
        return cls(problem=FormProblem.TRANSPORT_FAILED, form=form, detail="", log_detail=log_detail)

    @classmethod
    def of_status(cls, problem: FormProblem, form: str, status: int, diagnostic: Path | None = None) -> FormFailure:
        """Отказ по коду ответа формы."""
        return cls(
            problem=problem,
            form=form,
            detail=msg.FORM_STATUS_DETAIL.format(status=status),
            log_detail=FormLogDetail.HTTP_STATUS.text(status=status),
            diagnostic=diagnostic,
        )

    @property
    def human(self) -> str:
        """Что случилось с формой — одной строкой для человека; английской подробности в ней нет."""
        detail: str = msg.FORM_PROBLEM_DETAIL.format(detail=self.detail) if self.detail else ""
        return msg.FORM_PROBLEMS[self.problem.value].format(form=self.form, detail=detail)

    def event(self, name: FormEvent) -> LogEvent:
        """Строка лога отказа под именем события того, кто её пишет; поля вызывающего — через `extended`."""
        return LogEvent.of(name, problem=self.problem, form=Quoted(self.form), detail=Quoted(self.log_detail)).extended(
            saved=self.diagnostic
        )
