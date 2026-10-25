"""Ответ формы одного эфира, готовый к отправке (CLAUDE.md §3 шаг 11, §13 задача 5.1).

`FormSubmission` строит эфир (5.5): форма, ответы по его значениям, `slot_id` и ник канала — для строк лога.
Тело POST formResponse — ответы пройденных разделов, fvv, pageHistory и fbzx; адрес — адрес отправки формы с hl=en.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlencode

from app.config.settings import FormQuestion
from app.form.answers import FormAnswers
from app.form.failure import FormEvent
from app.form.key_form import KeyForm
from app.form.question import PageQuestion
from app.form.structure import FormAddress
from app.form.transport import ResponseLanguage
from app.observability.log_event import LogEvent
from app.observability.logging_setup import mask_stream_key


class BodyField(str, Enum):
    """Служебные поля тела ответа формы."""

    FVV = "fvv"
    PAGE_HISTORY = "pageHistory"
    FBZX = "fbzx"


class BodyValue(str, Enum):
    """Значения служебных полей тела ответа формы."""

    FVV = "1"
    PAGE_SEPARATOR = ","
    QUERY_JOINER = "&"


@dataclass(frozen=True)
class FormSubmission:
    """Ответ формы для одного эфира: форма, ответы, slot_id и ник канала."""

    form: KeyForm
    answers: FormAnswers
    slot_id: str
    handle: str

    @property
    def body(self) -> dict[str, list[str]]:
        """Тело POST formResponse: ответы пройденных разделов, fvv, pageHistory, fbzx."""
        body: dict[str, list[str]] = {answer.entry_id: [answer.value] for answer in self.answers.answers}
        body[BodyField.FVV.value] = [BodyValue.FVV.value]
        body[BodyField.PAGE_HISTORY.value] = [self.page_history]
        if self.form.structure.fbzx:
            body[BodyField.FBZX.value] = [self.form.structure.fbzx]
        return body

    @property
    def url(self) -> str:
        """Адрес отправки с hl=en: вместе с Accept-Language просит английскую страницу ответа; гарантии нет."""
        response_url: str = self.form.structure.response_url
        has_query: bool = FormAddress.QUERY.value in response_url
        separator: str = BodyValue.QUERY_JOINER.value if has_query else FormAddress.QUERY.value
        query: str = urlencode({ResponseLanguage.QUERY_KEY.value: ResponseLanguage.ENGLISH.value})
        return response_url + separator + query

    @property
    def page_history(self) -> str:
        return BodyValue.PAGE_SEPARATOR.value.join(str(page) for page in self.answers.pages)

    @property
    def stream_key(self) -> str | None:
        """Ключ потока в ответе — его не должно быть ни в логе, ни в сохранённой странице; в ответе нет — None."""
        question: PageQuestion | None = self.form.questions[FormQuestion.STREAM_KEY]
        return next((answer.value for answer in self.answers.answers if answer.question == question), None)

    def event(self, name: FormEvent) -> LogEvent:
        """Строка лога отправки: slot_id и ник канала."""
        return LogEvent.of(name, slot_id=self.slot_id, handle=self.handle)

    @property
    def post_event(self) -> LogEvent:
        """Строка `form_post`: ключ — маской."""
        return self.event(FormEvent.POST).extended(
            url=self.url,
            pages=self.page_history,
            fields=len(self.answers.answers),
            stream_key=mask_stream_key(self.stream_key),
        )
