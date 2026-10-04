"""Объект-форма: одна прочитанная форма ключей и правила ответа на неё (CLAUDE.md §6 инвариант 2, §13 задача 5.1).

`KeyForm` строится один раз на форму за запуск из настроек формы (`FormSettings`: названия вопросов, тексты
вариантов, формат даты) и структуры самой формы (вопросы, entry-ID, варианты, разделы). Ответ (`answers`) строится
по значениям эфира, а не по объекту эфира: форма про эфир, канал и площадку не знает.

Форма отвечает на шесть вопросов (`ANSWER_QUESTIONS`); время, ссылка на эфир и slot_id в форму не уходят — времени
в форме нет, только дата (время указано в объявлении). Значение, которого нет среди вариантов вопроса, в ответ не
попадает — поле незаполнено («варианта нет»).
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

from app.config.channel import Platform
from app.config.settings import FormQuestion, FormSettings
from app.form.answers import AnswerValues, FormAnswer, FormAnswers, MissingAnswer
from app.form.coverage import DateCoverage
from app.form.failure import FormEvent
from app.form.question import OptionChoice, PageQuestion
from app.form.route import PageRoute
from app.form.structure import FormStructure
from app.observability.log_event import LogEvent, Quoted

# Вопросы, на которые форма отвечает, — в этом порядке идут ответы.
ANSWER_QUESTIONS: Final[tuple[FormQuestion, ...]] = (
    FormQuestion.LANGUAGE,
    FormQuestion.ACCOUNT_NAME,
    FormQuestion.DATE,
    FormQuestion.PLATFORM,
    FormQuestion.STREAM_KEY,
    FormQuestion.STREAM_URL,
)
# Образец даты для длины начала варианта «Время стрима»: две цифры в каждой части.
DATE_SAMPLE: Final[datetime] = datetime(2000, 12, 28)


@dataclass(frozen=True)
class KeyForm:
    """Форма ключей: вопрос настроек → вопрос формы (None — нет в настройках или в форме); маршрут по разделам."""

    settings: FormSettings
    questions: Mapping[FormQuestion, PageQuestion | None]
    route: PageRoute

    @classmethod
    def build(cls, settings: FormSettings, structure: FormStructure) -> KeyForm:
        return cls.on_route(settings, PageRoute(structure))

    @classmethod
    def on_route(cls, settings: FormSettings, route: PageRoute) -> KeyForm:
        """Форма на готовом маршруте: вопросы находятся по названиям из настроек."""
        titles: dict[FormQuestion, str | None] = {item: settings.fields.get(item.value) for item in ANSWER_QUESTIONS}
        questions: dict[FormQuestion, PageQuestion | None] = {
            item: None if title is None else route.structure.question_by_title(title) for item, title in titles.items()
        }
        return cls(settings=settings, questions=questions, route=route)

    def for_settings(self, settings: FormSettings) -> KeyForm:
        """Та же прочитанная форма для других настроек с той же ссылкой (пакет режима Б): свои названия и варианты,
        маршрут — общий, и строка разделов остаётся одной на форму за запуск."""
        return KeyForm.on_route(settings, self.route)

    @property
    def structure(self) -> FormStructure:
        return self.route.structure

    @property
    def display_name(self) -> str:
        """Имя формы для людей — единственный источник для текстов о форме: заголовок, иначе ссылка из настроек."""
        return self.structure.title or self.settings.url

    @property
    def accepted_dates(self) -> tuple[str, ...]:
        """Даты, на которые в форме есть вариант «Время стрима», — в формате даты формы."""
        question: PageQuestion | None = self._date_question
        if question is None:
            return ()
        width: int = len(DATE_SAMPLE.strftime(self.settings.date_format))
        return tuple(option[:width] for option in question.options if self._is_date(option[:width]))

    @property
    def accepted_languages(self) -> tuple[str, ...]:
        """Коды языков настроек, для которых в форме есть вариант."""
        question: PageQuestion | None = self.questions[FormQuestion.LANGUAGE]
        if question is None:
            return ()
        texts: Mapping[str, str] = self.settings.values.get(FormQuestion.LANGUAGE.value, {})
        return tuple(code for code, text in texts.items() if question.option_for_text(text).chosen is not None)

    @property
    def stream_url_options(self) -> tuple[str, ...]:
        question: PageQuestion | None = self.questions[FormQuestion.STREAM_URL]
        return () if question is None else question.options

    def date_coverage(self, starts: Iterable[datetime]) -> DateCoverage:
        """Есть ли в форме вариант на каждую дату этих стартов; сеть не нужна — форма уже прочитана."""
        question: PageQuestion | None = self.questions[FormQuestion.DATE]
        checked: PageQuestion | None = self._date_question
        by_date: dict[date, str] = {}
        absent: list[date] = []
        if checked is not None:
            by_date = {start.date(): start.strftime(self.settings.date_format) for start in starts}
            absent = [day for day in sorted(by_date) if checked.date_option(by_date[day]).chosen is None]
        ordered: list[date] = sorted(by_date)
        return DateCoverage(
            form_url=self.settings.url,
            form_name=self.display_name,
            question_title="" if question is None else question.title,
            is_checkable=checked is not None,
            wanted=tuple(by_date[day] for day in ordered),
            missing=tuple(by_date[day] for day in absent),
            missing_dates=tuple(absent),
            accepted_count=len(self.accepted_dates),
        )

    def answers(self, values: AnswerValues) -> FormAnswers:
        """Ответ на форму по значениям эфира; ключ и адрес None — «ожидаются после публикации»."""
        answers: list[FormAnswer] = []
        missing: list[MissingAnswer] = []
        pending: list[PageQuestion] = []
        unanswerable: list[PageQuestion] = []   # поля без варианта: в обязательных без ответа не повторяются
        for field, question in self.questions.items():
            if question is None:
                continue            # вопроса нет в настройках или в форме: обязательность проверит маршрут
            if values.is_pending(field):
                pending.append(question)
                continue
            choice: OptionChoice = self._choice(field, question, values)
            if choice.chosen is None:
                missing.append(MissingAnswer.option(field, question, choice.wanted))
                unanswerable.append(question)
            else:
                answers.append(FormAnswer(question, choice.chosen))
        pages: tuple[int, ...] = self.route.pages(answers)
        required: MissingAnswer | None = self.route.required_missing(answers, pages, [*pending, *unanswerable])
        missing.extend([required] if required is not None else [])
        titles: tuple[str, ...] = tuple(question.title for question in pending)
        return FormAnswers(self.display_name, tuple(answers), pages, tuple(missing), titles)

    @property
    def ready_event(self) -> LogEvent:
        """Строка `form_ready`: что форма принимает."""
        ready: LogEvent = LogEvent.of(FormEvent.READY, url=self.structure.view_url, title=Quoted(self.structure.title))
        return ready.extended(
            questions=len(self.structure.questions),
            pages=self.structure.page_count,
            dates=self.accepted_dates,
            languages=self.accepted_languages,
            stream_urls=len(self.stream_url_options),
        )

    @property
    def _date_question(self) -> PageQuestion | None:
        """Вопрос даты с вариантами; нет вопроса или дата вводится текстом — None."""
        question: PageQuestion | None = self.questions[FormQuestion.DATE]
        return None if question is None or question.is_text else question

    def _choice(self, field: FormQuestion, question: PageQuestion, values: AnswerValues) -> OptionChoice:
        """Что уходит в ответ на вопрос этого поля: вариант формы или значение как есть."""
        if field is FormQuestion.LANGUAGE:
            return question.option_for_text(self._option_text(field, values.language))
        if field is FormQuestion.PLATFORM:
            return question.option_for_text(self._option_text(field, Platform.YOUTUBE.value))
        if field is FormQuestion.DATE:
            return question.date_option(values.start.strftime(self.settings.date_format))
        if field is FormQuestion.STREAM_URL:
            return question.url_option(values.given(field) or "")
        return OptionChoice.of(values.given(field) or "")

    def _option_text(self, field: FormQuestion, code: str) -> str | None:
        """Текст варианта из настроек по коду (язык, площадка); настройки его не дали — None."""
        return self.settings.values.get(field.value, {}).get(code)

    def _is_date(self, text: str) -> bool:
        try:
            datetime.strptime(text, self.settings.date_format)
        except ValueError:
            return False
        return True
