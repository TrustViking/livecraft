"""Форма ключей на вкладке «Форма» без окна: живая проверка (CLAUDE.md §8.2 п.9, §14 решение 68).

`FormCheck` читает ссылку и настройки формы из livecraft.json этой установки и читает форму тем же кодом, что запуск
(`FormBook.form_for` → `KeyForm`). Проверяется только сама форма: читается ли она и есть ли в ней вопросы, которые
нужны программе (`FormFindings`). Таблицу плана проверка не читает и с датами эфиров форму не сравнивает: хватает ли
дат в форме, решает запуск при допуске (§6 инвариант 2). Итог — `FormVerdict`: строки для окна. Отказ чтения формы —
готовый текст отказа (`FormFailure.human`). Проверка идёт в фоновом потоке окна: модель не знает ни потоков, ни Tk;
входа в Google у неё нет. Значений сейфа в строках нет: название формы, названия вопросов и тексты отказов.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from app.config.files import SettingsFile
from app.config.json_node import ConfigError
from app.config.settings import FormQuestion, LivecraftSettings
from app.core.clock import Clock
from app.core.text_format import NEWLINE
from app.form.book import FormBook
from app.form.failure import FormFailure
from app.form.key_form import ANSWER_QUESTIONS, KeyForm
from app.paths import LivecraftPaths
from app.ui.messages import msg

# Формы на часах программы (страницы разбора — в logs\ по её поясу): в программе — по сети, в тестах — подделка.
FormsSource = Callable[[Clock], FormBook]


@dataclass(frozen=True)
class FormFindings:
    """Что нашлось в прочитанной форме: есть ли в ней вопросы из настроек формы."""

    form: KeyForm

    @property
    def missing(self) -> tuple[str, ...]:
        """Названия вопросов из настроек формы, которых в форме нет; вопрос без названия в настройках не нужен."""
        titles: dict[FormQuestion, str | None] = {
            item: self.form.settings.fields.get(item.value) for item in ANSWER_QUESTIONS
        }
        return tuple(title for item, title in titles.items() if title is not None and self.form.questions[item] is None)

    @property
    def is_ok(self) -> bool:
        """Все вопросы настроек на месте."""
        return not self.missing

    @property
    def lines(self) -> tuple[str, ...]:
        """Одна строка: форма читается и вопросы на месте — либо каких вопросов нет."""
        name: str = self.form.display_name
        if self.is_ok:
            return (msg.SETUP_FORM_OK.format(form=name),)
        quoted: str = msg.LIST_JOINER.join(msg.SETUP_FORM_QUESTION.format(title=title) for title in self.missing)
        return (msg.SETUP_FORM_QUESTIONS_MISSING.format(form=name, questions=quoted),)


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
    """Проверка формы ключей этой установки: livecraft.json — с диска по путям `paths`, формы — `open_forms`."""

    paths: LivecraftPaths
    open_forms: FormsSource

    @classmethod
    def of(cls, paths: LivecraftPaths) -> FormCheck:
        """Боевая проверка: форма — по сети, как у запуска."""
        return cls(paths=paths, open_forms=lambda clock: FormBook.for_run(paths, clock))

    def run(self, _on_login: Callable[[], None]) -> FormVerdict:
        """Прочитать форму и сказать, что нашлось; настройки не прочитались, ссылки нет или форма не прочиталась —
        строка с причиной. Входа в Google нет: браузер не открывается."""
        try:
            settings: LivecraftSettings = SettingsFile.of(self.paths).load()
        except ConfigError as error:
            return FormVerdict.failed(error.human)
        if not settings.form.is_configured:
            return FormVerdict.failed(msg.SETUP_FORM_NOT_SET)
        form: KeyForm | FormFailure = self.open_forms(Clock(settings.zone)).form_for(settings.form)
        if isinstance(form, FormFailure):
            return FormVerdict.failed(form.human)
        return FormVerdict.of_findings(FormFindings(form=form))
