"""Разделы формы, которые проходит ответ (pageHistory), и обязательные вопросы этих разделов (CLAUDE.md §13 5.1).

Вопрос-развилка — тот, у варианта которого есть переход на раздел (в форме ключей — «Платформа»): ответ проходит
раздел развилки и раздел, куда ведёт выбранный вариант (YouTube), а разделы Facebook и Rumble — нет. Перехода нет
или он ведёт вне формы — разделы берутся по ответам. Номер вне формы в pageHistory не попадает никогда: Google
отвергает такой ответ с кодом 400.

Маршрут один на прочитанную форму: формы с той же ссылкой для других настроек (`KeyForm.for_settings`) делят его,
и строка «разделы по переходу» — одна на форму за запуск (у всех ответов одной формы разделы одни).
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

from app.form.answers import FormAnswer, MissingAnswer
from app.form.failure import FormEvent
from app.form.question import PageQuestion, SectionJump
from app.form.structure import FormStructure
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger

LOGGER = get_logger(LogArea.FORM)


@dataclass
class PageRoute:
    """Маршрут по разделам прочитанной формы и отметка «строка разделов по переходу уже выдана»."""

    structure: FormStructure
    is_navigation_logged: bool = False

    def pages(self, answers: Sequence[FormAnswer]) -> tuple[int, ...]:
        """Раздел 0, раздел развилки и раздел её перехода; без перехода — разделы всех ответов."""
        fork: FormAnswer | None = self._fork(answers)
        jump: SectionJump | None = None if fork is None else self.structure.jump_for(fork.entry_id, fork.value)
        pages: list[int] = [0]
        if fork is not None and jump is not None and self.structure.has_page(jump.page_index):
            self._append(pages, fork.question.page_index)
            self._append(pages, jump.page_index)
            self._note_navigation(pages, fork, jump)
            return tuple(pages)
        for answer in answers:
            self._append(pages, answer.question.page_index)
        by_answers: LogEvent = LogEvent.of(FormEvent.PAGES_BY_ANSWERS, pages=pages)
        by_answers.extended(
            section_id=None if jump is None else jump.section_id,
            page=None if jump is None else jump.page_index,
            page_count=self.structure.page_count,
        ).emit(LOGGER)
        return tuple(pages)

    def required_missing(
        self, answers: Sequence[FormAnswer], pages: Sequence[int], skipped: Sequence[PageQuestion]
    ) -> MissingAnswer | None:
        """Обязательные вопросы пройденных разделов без ответа; ожидаемые и уже отмеченные — не повторяются.

        Обязательные вопросы непройденных разделов (Facebook, Rumble) не проверяются.
        """
        answered: set[str] = {answer.entry_id for answer in answers} | {question.entry_id for question in skipped}
        titles: list[str] = [
            question.title
            for question in self.structure.questions
            if question.is_required and question.page_index in pages and question.entry_id not in answered
        ]
        return MissingAnswer.required(titles) if titles else None

    def _fork(self, answers: Sequence[FormAnswer]) -> FormAnswer | None:
        """Ответ на вопрос-развилку — у его вопроса есть переходы по вариантам."""
        return next((answer for answer in answers if answer.entry_id in self.structure.navigation), None)

    def _append(self, pages: list[int], page: int | None) -> None:
        if page is None or not self.structure.has_page(page):
            out_of_range: LogEvent = LogEvent.of(FormEvent.PAGE_OUT_OF_RANGE, page=page)
            out_of_range.extended(page_count=self.structure.page_count).emit(LOGGER, logging.WARNING)
            return
        if page not in pages:
            pages.append(page)

    def _note_navigation(self, pages: list[int], fork: FormAnswer, jump: SectionJump) -> None:
        """Разделы по переходу — DEBUG, один раз на форму за запуск."""
        if self.is_navigation_logged:
            return
        self.is_navigation_logged = True
        navigation: LogEvent = LogEvent.of(FormEvent.PAGES_BY_NAVIGATION, pages=pages, entry=fork.entry_id)
        navigation.extended(
            option=Quoted(fork.value),
            section_id=jump.section_id,
            page=jump.page_index,
            page_count=self.structure.page_count,
        ).emit(LOGGER, logging.DEBUG)
