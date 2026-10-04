"""Вопрос страницы формы и выбор варианта ответа (CLAUDE.md §6 инвариант 2).

Железное правило: значение, которого нет среди вариантов вопроса, в ответ не попадает — выбор даёт «варианта нет»
(`OptionChoice.chosen is None`) и то, что искали. Вопрос с вводом текста принимает значение как есть. Дата
опознаётся по началу варианта («13.09.2026 Дата стрима …»): одним правилом и для отправки, и для покрытия дат.
Адрес потока сравнивается без пробелов по краям, без «/» в конце и без регистра, а уходит текст варианта как в форме.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.observability.log_event import LogValue


class QuestionKind(str, Enum):
    """Вид вопроса: ввод текста или выбор варианта (радио, список, флажки)."""

    TEXT = "text"
    CHOICE = "choice"


class UrlMark(str, Enum):
    """Хвост адреса, который сравнение адресов потока не различает."""

    TRAILING_SLASH = "/"


# Искомого значения нет вовсе (настройки не дали текста варианта, адрес потока пуст): в подробности — «-».
NO_VALUE: str = LogValue.EMPTY.value


@dataclass(frozen=True)
class OptionChoice:
    """Выбор ответа: что уходит в форму (`chosen`; None — варианта нет) и что искали (`wanted`)."""

    chosen: str | None
    wanted: str

    @classmethod
    def of(cls, value: str) -> OptionChoice:
        """Значение уходит как есть."""
        return cls(chosen=value, wanted=value)

    @classmethod
    def absent(cls, wanted: str) -> OptionChoice:
        """Такого варианта в вопросе нет."""
        return cls(chosen=None, wanted=wanted)


@dataclass(frozen=True)
class SectionJump:
    """Переход варианта: в форме он задан идентификатором раздела, а pageHistory ждёт номер раздела.

    `section_id` — как записан у варианта (id разрыва, открывающего раздел); `page_index` — номер этого раздела
    с нуля, None — такого разрыва в форме нет.
    """

    section_id: int
    page_index: int | None


@dataclass(frozen=True)
class PageQuestion:
    """Вопрос страницы формы: название, как его видит владелец, entry-ID, обязательность, вид, варианты, раздел."""

    title: str
    entry_id: str               # "entry.NNN"
    is_required: bool
    kind: QuestionKind
    options: tuple[str, ...]    # тексты вариантов; у вопроса с вводом текста — пусто
    page_index: int             # номер раздела с нуля

    @property
    def is_text(self) -> bool:
        return self.kind is QuestionKind.TEXT

    def option_for_text(self, wanted: str | None) -> OptionChoice:
        """Вариант с ровно этим текстом; текста нет (настройки его не дали) — «варианта нет» со значением «-»."""
        if wanted is None:
            return OptionChoice.absent(NO_VALUE)
        if self.is_text or wanted in self.options:
            return OptionChoice.of(wanted)
        return OptionChoice.absent(wanted)

    def date_option(self, wanted: str) -> OptionChoice:
        """Первый вариант, начинающийся с даты; одно правило и для отправки, и для покрытия дат."""
        if self.is_text:
            return OptionChoice.of(wanted)
        for option in self.options:
            if option.startswith(wanted):
                return OptionChoice(chosen=option, wanted=wanted)
        return OptionChoice.absent(wanted)

    def url_option(self, url: str) -> OptionChoice:
        """Вариант с тем же адресом потока без пробелов по краям, «/» в конце и регистра; уходит текст варианта."""
        if not url:
            return OptionChoice.absent(NO_VALUE)
        if self.is_text:
            return OptionChoice.of(url)
        for option in self.options:
            if self._url_key(option) == self._url_key(url):
                return OptionChoice(chosen=option, wanted=url)
        return OptionChoice.absent(url)

    def _url_key(self, value: str) -> str:
        return value.strip().rstrip(UrlMark.TRAILING_SLASH.value).lower()
