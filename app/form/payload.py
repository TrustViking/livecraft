"""Массив FB_PUBLIC_LOAD_DATA_ страницы формы и правила его чтения (CLAUDE.md §6 инвариант 2).

entry-ID нигде не конфигурируются: форма сама говорит, что у неё есть. Структура живёт в скрипте
FB_PUBLIC_LOAD_DATA_ страницы viewform; раскладка подтверждена живыми прогонами (13-09-2026), но разбор терпимый:
чего не понял — считает отсутствующим. payload[1][1] — элементы формы, payload[1][8] — заголовок формы для
отвечающего; элемент — [id, название, описание, вид, [[entry, варианты, обязательность]]]; разрыв страницы (вид 8)
открывает раздел, и его id — цель переходов вариантов. Модуль-граница: здесь и только здесь сырой JSON (`Any`).
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Final

from app.form.failure import FormEvent
from app.form.question import PageQuestion, QuestionKind, SectionJump
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger

LOGGER = get_logger(LogArea.FORM)

PAYLOAD_NAME: Final[str] = "FB_PUBLIC_LOAD_DATA_"
SCRIPT_PATTERN: Final[re.Pattern[str]] = re.compile(r"FB_PUBLIC_LOAD_DATA_\s*=\s*(\[.*?\])\s*;\s*</script>", re.DOTALL)
FBZX_PATTERN: Final[re.Pattern[str]] = re.compile(r'name="fbzx"\s+value="(-?\d+)"')
ENTRY_TEMPLATE: Final[str] = "entry.{entry_id}"
PAGE_BREAK_TYPE: Final[int] = 8
TEXT_TYPES: Final[frozenset[int]] = frozenset({0, 1})        # короткий ответ и абзац
CHOICE_TYPES: Final[frozenset[int]] = frozenset({2, 3, 4})   # радио, список, флажки
ITEM_MIN_LENGTH: Final[int] = 4                              # у элемента формы есть хотя бы вид


class PayloadField(IntEnum):
    """Места в корне массива."""

    FORM = 1        # сама форма
    FBZX = 3        # запасное место fbzx, если скрытого поля на странице нет


class FormField(IntEnum):
    """Места внутри формы (payload[1])."""

    ITEMS = 1
    TITLE = 8       # заголовок для отвечающего; payload[3] — не он


class ItemField(IntEnum):
    """Места внутри элемента формы."""

    ID = 0
    TITLE = 1
    TYPE = 3
    ENTRIES = 4


class EntryField(IntEnum):
    """Места внутри поля ответа элемента."""

    ID = 0
    OPTIONS = 1
    REQUIRED = 2


class OptionField(IntEnum):
    """Места внутри варианта ответа."""

    TEXT = 0
    TARGET = 2      # id раздела, куда ведёт вариант; отрицательное — служебный код Google


@dataclass(frozen=True)
class FormPayload:
    """Разобранный массив FB_PUBLIC_LOAD_DATA_ и страница, из которой он взят (fbzx лежит в её скрытом поле)."""

    data: Any
    html: str

    @classmethod
    def of(cls, html: str) -> FormPayload | None:
        """Массив страницы; нет скрипта или в нём не JSON — None."""
        match: re.Match[str] | None = SCRIPT_PATTERN.search(html)
        if match is None:
            return None
        try:
            data: Any = json.loads(match.group(1))
        except json.JSONDecodeError:
            return None
        return cls(data=data, html=html)

    @property
    def title(self) -> str:
        """Заголовок формы, как его видит отвечающий; нет в массиве — пусто."""
        title: Any = self._dig(self.data, PayloadField.FORM, FormField.TITLE)
        return title.strip() if isinstance(title, str) else ""

    @property
    def fbzx(self) -> str:
        """Скрытое поле страницы; если его нет — то же значение лежит в самом массиве."""
        match: re.Match[str] | None = FBZX_PATTERN.search(self.html)
        if match is not None:
            return match.group(1)
        value: Any = self._dig(self.data, PayloadField.FBZX)
        return str(value) if isinstance(value, (str, int)) else ""

    @property
    def questions(self) -> tuple[PageQuestion, ...]:
        """Вопросы формы по порядку; номер раздела растёт на каждом разрыве страницы."""
        found: list[PageQuestion] = []
        page_index: int = 0
        for item in self._items:
            if item[ItemField.TYPE] == PAGE_BREAK_TYPE:
                page_index += 1
                continue
            question: PageQuestion | None = self._question(item, page_index)
            if question is not None:
                found.append(question)
        return tuple(found)

    @property
    def page_count(self) -> int:
        """Разделов: разрывов страниц и ещё один."""
        return 1 + sum(1 for item in self._items if item[ItemField.TYPE] == PAGE_BREAK_TYPE)

    @property
    def navigation(self) -> dict[str, dict[str, SectionJump]]:
        """entry-ID вопроса → текст варианта → переход на раздел; вопросы без переходов не входят."""
        sections: dict[int, int] = self._section_ids()
        navigation: dict[str, dict[str, SectionJump]] = {}
        for item in self._items:
            question: PageQuestion | None = self._question(item, 0)
            jumps: dict[str, SectionJump] = self._jumps(item, sections) if question is not None else {}
            if question is not None and jumps:
                navigation[question.entry_id] = jumps
        return navigation

    @property
    def _items(self) -> list[Any]:
        """payload[1][1] — элементы формы; не элемент (не список или короче вида) пропускается."""
        items: Any = self._dig(self.data, PayloadField.FORM, FormField.ITEMS)
        return [item for item in items if self._is_item(item)] if isinstance(items, list) else []

    def _section_ids(self) -> dict[int, int]:
        """id разрыва → номер раздела, который он открывает; раздел 0 — до первого разрыва.

        Отдельным проходом: переход у варианта может вести на раздел, разрыв которого ещё впереди.
        """
        section_ids: dict[int, int] = {}
        page_index: int = 0
        for item in self._items:
            if item[ItemField.TYPE] != PAGE_BREAK_TYPE:
                continue
            page_index += 1
            if self._is_plain_int(item[ItemField.ID]):
                section_ids[item[ItemField.ID]] = page_index
        return section_ids

    def _question(self, item: list[Any], page_index: int) -> PageQuestion | None:
        """Вопрос элемента; вид, которого программа не знает (картинка, разрыв), и элемент без поля — None."""
        entry: Any = self._dig(item, ItemField.ENTRIES, 0)
        kind: QuestionKind | None = self._kind(item[ItemField.TYPE])
        if kind is None or not isinstance(entry, list) or not entry or not isinstance(entry[EntryField.ID], int):
            return None
        return PageQuestion(
            title=str(item[ItemField.TITLE] or ""),
            entry_id=ENTRY_TEMPLATE.format(entry_id=entry[EntryField.ID]),
            is_required=bool(self._dig(entry, EntryField.REQUIRED)),
            kind=kind,
            options=self._options(entry),
            page_index=page_index,
        )

    def _kind(self, type_code: Any) -> QuestionKind | None:
        if not isinstance(type_code, int):
            return None
        if type_code in TEXT_TYPES:
            return QuestionKind.TEXT
        return QuestionKind.CHOICE if type_code in CHOICE_TYPES else None

    def _options(self, entry: list[Any]) -> tuple[str, ...]:
        raw: Any = self._dig(entry, EntryField.OPTIONS)
        if not isinstance(raw, list):
            return ()
        return tuple(str(option[OptionField.TEXT]) for option in raw if self._is_option(option))

    def _jumps(self, item: list[Any], sections: dict[int, int]) -> dict[str, SectionJump]:
        """Переход «вариант → раздел», если он у варианта указан; иначе вариант остаётся без цели.

        Отрицательные цели — служебные коды Google («следующий раздел», «отправить форму»), а не id разделов.
        """
        raw: Any = self._dig(item, ItemField.ENTRIES, 0, EntryField.OPTIONS)
        jumps: dict[str, SectionJump] = {}
        for option in raw if isinstance(raw, list) else []:
            target: Any = self._dig(option, OptionField.TARGET)
            if not self._is_option(option) or not self._is_plain_int(target) or target < 0:
                continue
            jump: SectionJump = SectionJump(section_id=target, page_index=sections.get(target))
            if jump.page_index is None:
                entry: str = ENTRY_TEMPLATE.format(entry_id=self._dig(item, ItemField.ENTRIES, 0, EntryField.ID))
                unknown: LogEvent = LogEvent.of(FormEvent.JUMP_UNKNOWN_SECTION, entry=entry)
                unknown.extended(option=Quoted(str(option[OptionField.TEXT])), section_id=target).emit(
                    LOGGER, logging.WARNING
                )
            jumps[str(option[OptionField.TEXT])] = jump
        return jumps

    def _is_option(self, option: Any) -> bool:
        return isinstance(option, list) and bool(option) and option[OptionField.TEXT] is not None

    def _is_item(self, item: Any) -> bool:
        return isinstance(item, list) and len(item) >= ITEM_MIN_LENGTH

    def _is_plain_int(self, value: Any) -> bool:
        return isinstance(value, int) and not isinstance(value, bool)

    def _dig(self, value: Any, *path: int) -> Any:
        """Значение по пути индексов; путь обрывается (не список или короче) — None."""
        current: Any = value
        for index in path:
            if not isinstance(current, list) or len(current) <= index:
                return None
            current = current[index]
        return current
