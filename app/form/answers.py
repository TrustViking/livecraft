"""Ответ на форму ключей для одного эфира (CLAUDE.md §6 инвариант 2, §13 задача 5.1).

Значения ответа (`AnswerValues`) даёт эфир (5.5): язык, момент старта, название канала, ключ и адрес потока. Ключа
и адреса до публикации эфира нет — эти поля «ожидаются после публикации», это не ошибка (`FormAnswers.pending`).
`FormAnswers` знает, что уйдёт в форму, какие разделы пройти и чего не хватает; первая причина не отправлять —
`failure`. Память (5.2) сравнивает ответы по entry-ID, названию вопроса и значению (`FormAnswer`).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.config.settings import FormQuestion
from app.form.failure import FormFailure, FormLogDetail, FormProblem
from app.form.question import PageQuestion
from app.ui.messages import msg

# Поля, известные только после публикации эфира.
PUBLISHED_QUESTIONS: Final[frozenset[FormQuestion]] = frozenset({FormQuestion.STREAM_KEY, FormQuestion.STREAM_URL})
OPTION_DETAIL: Final[str] = "{question}: {value}"     # «Время стрима ( Stream time ): 18.03.2027»


@dataclass(frozen=True)
class AnswerValues:
    """Значения эфира для ответа: `start` — с поясом; ключ и адрес None — «ожидаются после публикации»."""

    language: str
    start: datetime
    account_name: str
    stream_key: str | None
    stream_url: str | None

    def given(self, question: FormQuestion) -> str | None:
        """Значение, которое уходит в форму как есть: название канала, ключ и адрес потока."""
        texts: dict[FormQuestion, str | None] = {
            FormQuestion.ACCOUNT_NAME: self.account_name,
            FormQuestion.STREAM_KEY: self.stream_key,
            FormQuestion.STREAM_URL: self.stream_url,
        }
        return texts.get(question)

    def is_pending(self, question: FormQuestion) -> bool:
        """Поле ждёт публикации эфира: ключа или адреса потока ещё нет."""
        return question in PUBLISHED_QUESTIONS and self.given(question) is None


@dataclass(frozen=True)
class FormAnswer:
    """Ответ на один вопрос: вопрос формы и значение, которое уходит в форму."""

    question: PageQuestion
    value: str

    @property
    def entry_id(self) -> str:
        return self.question.entry_id

    @property
    def title(self) -> str:
        return self.question.title


@dataclass(frozen=True)
class MissingAnswer:
    """Незаполненное поле: какое поле настроек (None — обязательные вопросы формы), причина, вопрос и значение.

    Вопрос и значение — по отдельности: человеку они называются вместе (`detail`), а в лог уходит только поле.
    """

    field: FormQuestion | None
    problem: FormProblem
    question: str           # название вопроса формы; у обязательных — названия через запятую
    value: str              # вариант, которого нет; «-» — настройки не дали текста варианта

    @classmethod
    def option(cls, field: FormQuestion, question: PageQuestion, wanted: str) -> MissingAnswer:
        """Значения нет среди вариантов вопроса."""
        return cls(field=field, problem=FormProblem.MISSING_OPTION, question=question.title, value=wanted)

    @classmethod
    def required(cls, titles: Sequence[str]) -> MissingAnswer:
        """Обязательные вопросы пройденных разделов без ответа."""
        return cls(field=None, problem=FormProblem.REQUIRED_MISSING, question=msg.LIST_JOINER.join(titles), value="")

    @property
    def detail(self) -> str:
        """«вопрос: вариант» или названия обязательных вопросов."""
        return OPTION_DETAIL.format(question=self.question, value=self.value) if self.value else self.question

    @property
    def log_detail(self) -> str:
        if self.field is None:
            return FormLogDetail.REQUIRED_MISSING.value
        return FormLogDetail.MISSING_OPTION.text(field=self.field.value)


@dataclass(frozen=True)
class FormAnswers:
    """Ответ формы для одного эфира: что отправить, какие разделы пройти, чего не хватает и чего ещё ждать."""

    form: str                              # имя формы для людей (KeyForm.display_name)
    answers: tuple[FormAnswer, ...]
    pages: tuple[int, ...]                 # pageHistory: номера разделов по порядку
    missing: tuple[MissingAnswer, ...]     # варианта нет — по полям, затем обязательные без ответа
    pending: tuple[str, ...]               # названия вопросов, которые ждут публикации (ключ, адрес потока)

    @property
    def is_complete(self) -> bool:
        return not self.missing and not self.pending

    @property
    def failure(self) -> FormFailure | None:
        """Первая причина не отправлять; ответы полные — None."""
        if self.missing:
            first: MissingAnswer = self.missing[0]
            return FormFailure(problem=first.problem, form=self.form, detail=first.detail, log_detail=first.log_detail)
        if self.pending:
            detail: str = msg.LIST_JOINER.join(self.pending)
            log_detail: str = FormLogDetail.PENDING.text(count=len(self.pending))
            problem: FormProblem = FormProblem.REQUIRED_MISSING
            return FormFailure(problem=problem, form=self.form, detail=detail, log_detail=log_detail)
        return None
