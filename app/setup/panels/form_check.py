"""Форма ключей на вкладке «Форма» без окна: живая проверка (CLAUDE.md §8.2 п.9, §6 инвариант 2).

`FormCheck` читает ссылку и настройки формы из livecraft.json этой установки и читает форму тем же кодом, что запуск
(`FormBook.form_for` → `KeyForm`). Что нашлось, говорит `FormFindings`: название формы, какие вопросы из настроек формы
в ней есть и каких нет, даты «Время стрима» от сегодня; когда линия «Таблица плана» работает — покрытие дат её будущих
эфиров (`TableDates`: таблица читается тем же кодом и по тому же правилу входа оператора, что её проверка,
`TableCheck.read_plan`; строки правила — каким аккаунтом вошли, аккаунту таблица не открыта — идут перед строкой
покрытия; покрытие — `KeyForm.date_coverage`, строка — та же, что у запуска). Итог — `FormVerdict`: строки для окна.
Отказ чтения формы — готовый текст отказа (`FormFailure.human`). Проверка идёт в фоновом потоке окна: модель не знает ни потоков, ни Tk; «открылся браузер» (вход
оператора ради таблицы) она сообщает тем, кого ей дали (`on_login`). Значений сейфа в строках нет: названия вопросов,
даты и тексты отказов.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime

from app.config.files import SettingsFile
from app.config.json_node import ConfigError
from app.config.settings import FormQuestion, LivecraftSettings
from app.core.clock import Clock
from app.core.dates import format_human_date
from app.core.text_format import NEWLINE
from app.form.book import FormBook
from app.form.failure import FormFailure
from app.form.key_form import ANSWER_QUESTIONS, KeyForm
from app.form.question import PageQuestion
from app.paths import LivecraftPaths
from app.run.mode import RunPart
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.store import VaultStore
from app.secretsafe.vault import Vault
from app.setup.panels.table_check import TableCheck
from app.sheets.client import SheetsReadError
from app.sheets.plan import SheetPlan
from app.sheets.rows import PlannedRows
from app.ui.messages import msg

# Формы на часах программы (страницы разбора — в logs\ по её поясу): в программе — по сети, в тестах — подделка.
FormsSource = Callable[[Clock], FormBook]


@dataclass(frozen=True)
class TableDates:
    """Будущие эфиры таблицы плана для покрытия дат формы: их старты либо почему таблица не прочиталась, и строки
    правила входа оператора `notes` — каким аккаунтом вошли, аккаунту таблица не открыта."""

    starts: tuple[datetime, ...]
    problem: str | None
    notes: tuple[str, ...] = ()

    @classmethod
    def read(cls, table: TableCheck, settings: LivecraftSettings, on_login: Callable[[], None]) -> TableDates:
        """Таблица — по правилу входа оператора и часами проверки таблицы; допущенные ряды — по тем же правилам, что
        у запуска."""
        notes: list[str] = []
        try:
            vault: Vault = VaultStore.open(table.paths).load().vault
            plan: SheetPlan = table.read_plan(vault, on_login, notes.append)
        except (VaultFormatError, SheetsReadError) as error:
            return cls(starts=(), problem=error.human, notes=tuple(notes))
        if plan.columns is None or plan.problem is not None:
            return cls(starts=(), problem=plan.problem_text, notes=tuple(notes))
        rows: PlannedRows = plan.plan_rows(settings.zone, table.clock.now())
        return cls(starts=tuple(row.start for row in rows.admitted), problem=None, notes=tuple(notes))

    def line(self, form: KeyForm) -> str:
        """Строка покрытия: таблица не прочиталась — причина; будущих эфиров нет — сказать; иначе строка запуска со
        знаком окна: все даты есть — «✓», нет какой-то — «✗»."""
        if self.problem is not None:
            return msg.SETUP_FORM_TABLE_UNREAD.format(problem=self.problem)
        coverage_line: str | None = form.date_coverage(self.starts).line
        if not self.starts or coverage_line is None:
            return msg.SETUP_FORM_TABLE_EMPTY
        marked: str = msg.CHECK_OK_LINE if self.covers(form) else msg.CHECK_PROBLEM_LINE
        return marked.format(line=coverage_line)

    def covers(self, form: KeyForm) -> bool:
        """Таблица прочиталась и на каждую дату её эфиров в форме есть вариант."""
        return self.problem is None and form.date_coverage(self.starts).is_complete


@dataclass(frozen=True)
class FormFindings:
    """Что нашлось в прочитанной форме: форма, сегодня (в поясе программы) и эфиры таблицы (None — покрытие дат не
    проверяется: таблица плана не работает или даты «Время стрима» не сверяются, `checks_dates`)."""

    form: KeyForm
    today: date
    table: TableDates | None

    @property
    def missing(self) -> tuple[str, ...]:
        """Названия вопросов из настроек формы, которых в форме нет."""
        return tuple(title for item, title in self._titles.items() if self.form.questions[item] is None)

    @property
    def found(self) -> tuple[str, ...]:
        return tuple(title for item, title in self._titles.items() if self.form.questions[item] is not None)

    @property
    def checks_dates(self) -> bool:
        """Даты сверяются: вопрос «Время стрима» есть в форме и он с вариантами (текстом подходит любая дата)."""
        question: PageQuestion | None = self.form.questions[FormQuestion.DATE]
        return question is not None and not question.is_text

    @property
    def is_ok(self) -> bool:
        """Все вопросы настроек на месте и, если таблица проверяется, все её даты покрыты."""
        return not self.missing and (self.table is None or self.table.covers(self.form))

    @property
    def lines(self) -> tuple[str, ...]:
        """Вопросы, затем даты «Время стрима» от сегодня, затем строки входа оператора и покрытие дат таблицы."""
        name: str = self.form.display_name
        lines: list[str] = [msg.SETUP_FORM_OK.format(form=name, questions=self._quoted(self.found))]
        if self.missing:
            lines.append(msg.SETUP_FORM_QUESTIONS_MISSING.format(form=name, questions=self._quoted(self.missing)))
        question: PageQuestion | None = self.form.questions[FormQuestion.DATE]
        if question is None:
            return tuple(lines)
        if question.is_text:
            return (*lines, msg.SETUP_FORM_DATE_ANY.format(question=question.title))
        lines.append(self._dates_line(question))
        if self.table is None:
            return tuple(lines)
        return (*lines, *self.table.notes, self.table.line(self.form))

    @property
    def _titles(self) -> dict[FormQuestion, str]:
        """Вопросы, на которые отвечает форма, с названиями из настроек; вопрос без названия в настройках не нужен."""
        titles: dict[FormQuestion, str | None] = {
            item: self.form.settings.fields.get(item.value) for item in ANSWER_QUESTIONS
        }
        return {item: title for item, title in titles.items() if title is not None}

    def _dates_line(self, question: PageQuestion) -> str:
        """Даты вариантов «Время стрима» от сегодня — для людей; таких нет — строка об этом."""
        date_format: str = self.form.settings.date_format
        days: list[date] = sorted(datetime.strptime(text, date_format).date() for text in self.form.accepted_dates)
        coming: tuple[str, ...] = tuple(format_human_date(day) for day in days if day >= self.today)
        if not coming:
            return msg.SETUP_FORM_NO_DATES.format(question=question.title)
        return msg.SETUP_FORM_DATES.format(question=question.title, dates=msg.LIST_JOINER.join(coming))

    def _quoted(self, titles: tuple[str, ...]) -> str:
        return msg.LIST_JOINER.join(msg.SETUP_FORM_QUESTION.format(title=title) for title in titles)


@dataclass(frozen=True)
class FormVerdict:
    """Итог проверки: годится ли форма и строки для окна."""

    is_ok: bool
    lines: tuple[str, ...]

    @classmethod
    def failed(cls, problem: str) -> FormVerdict:
        return cls(is_ok=False, lines=(msg.SETUP_FORM_FAILED.format(problem=problem),))

    @classmethod
    def of_findings(cls, findings: FormFindings) -> FormVerdict:
        return cls(is_ok=findings.is_ok, lines=findings.lines)

    @property
    def text(self) -> str:
        return NEWLINE.join(self.lines)


@dataclass(frozen=True)
class FormCheck:
    """Проверка формы ключей этой установки: livecraft.json — с диска, формы — `open_forms`, таблица плана и «сейчас» —
    проверкой таблицы `table`."""

    table: TableCheck
    open_forms: FormsSource

    @classmethod
    def of(cls, paths: LivecraftPaths) -> FormCheck:
        """Боевая проверка: форма — по сети, таблица — входом оператора этой установки."""
        return cls(table=TableCheck.of(paths), open_forms=lambda clock: FormBook.for_run(paths, clock))

    def run(self, on_login: Callable[[], None]) -> FormVerdict:
        """Прочитать форму и сказать, что нашлось; настройки не прочитались, ссылки нет или форма не прочиталась —
        строка с причиной. Таблица плана читается, только когда её линия работает и даты формы сверяются."""
        try:
            settings: LivecraftSettings = SettingsFile.of(self.table.paths).load()
        except ConfigError as error:
            return FormVerdict.failed(error.human)
        if not settings.form.is_configured:
            return FormVerdict.failed(msg.SETUP_FORM_NOT_SET)
        form: KeyForm | FormFailure = self.open_forms(Clock(settings.zone)).form_for(settings.form)
        if isinstance(form, FormFailure):
            return FormVerdict.failed(form.human)
        today: date = self.table.clock.now().astimezone(settings.zone).date()
        findings: FormFindings = FormFindings(form=form, today=today, table=None)
        if findings.checks_dates and settings.lines.line_plan.works(RunPart.PLAN):
            findings = dataclasses.replace(findings, table=TableDates.read(self.table, settings, on_login))
        return FormVerdict.of_findings(findings)
