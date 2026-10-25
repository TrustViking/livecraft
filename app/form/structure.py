"""Структура прочитанной формы: адреса, вопросы, переходы по разделам, заголовок (CLAUDE.md §6 инвариант 2).

Строится один раз на форму за запуск из массива страницы (`FormPayload`) и конечного адреса страницы после
редиректа forms.gle. Адрес отправки — тот же адрес с formResponse вместо viewform.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from app.form.failure import FormEvent
from app.form.payload import FormPayload
from app.form.question import PageQuestion, SectionJump
from app.observability.log_event import LogEvent, Quoted


class FormAddress(str, Enum):
    """Части адреса формы: страница вопросов, адрес отправки и разделители."""

    VIEW = "viewform"
    RESPONSE = "formResponse"
    QUERY = "?"
    PATH = "/"


@dataclass(frozen=True)
class FormStructure:
    """Что есть в форме: вопросы с entry-ID и вариантами, переходы вариантов на разделы, число разделов, заголовок."""

    view_url: str                                          # конечный адрес страницы после редиректа forms.gle
    response_url: str                                      # тот же адрес с formResponse вместо viewform
    fbzx: str
    questions: tuple[PageQuestion, ...]
    navigation: Mapping[str, Mapping[str, SectionJump]]    # entry-ID вопроса → текст варианта → переход
    page_count: int                                        # разрывов страниц и ещё один
    title: str                                             # заголовок для отвечающего; нет в массиве — пусто

    @classmethod
    def of(cls, payload: FormPayload, view_url: str) -> FormStructure:
        return cls(
            view_url=view_url,
            response_url=cls.response_url_of(view_url),
            fbzx=payload.fbzx,
            questions=payload.questions,
            navigation=payload.navigation,
            page_count=payload.page_count,
            title=payload.title,
        )

    @classmethod
    def response_url_of(cls, view_url: str) -> str:
        """Адрес отправки: строка запроса отбрасывается, viewform меняется на formResponse."""
        base: str = view_url.split(FormAddress.QUERY.value, 1)[0]
        if base.endswith(FormAddress.VIEW.value):
            return base[: -len(FormAddress.VIEW.value)] + FormAddress.RESPONSE.value
        return base.rstrip(FormAddress.PATH.value) + FormAddress.PATH.value + FormAddress.RESPONSE.value

    def question_by_title(self, title: str) -> PageQuestion | None:
        """Вопрос с ровно этим названием; нет такого — None."""
        return next((question for question in self.questions if question.title == title), None)

    def jump_for(self, entry_id: str, option: str) -> SectionJump | None:
        """Куда ведёт вариант вопроса; перехода нет — None."""
        return self.navigation.get(entry_id, {}).get(option)

    def has_page(self, page: int | None) -> bool:
        """pageHistory принимает только номера существующих разделов: всё прочее Google отвергает 400."""
        return page is not None and 0 <= page < self.page_count

    @property
    def read_event(self) -> LogEvent:
        """Строка `form_structure_read`."""
        return LogEvent.of(FormEvent.STRUCTURE_READ, url=self.view_url, title=Quoted(self.title)).extended(
            questions=len(self.questions), pages=self.page_count
        )
