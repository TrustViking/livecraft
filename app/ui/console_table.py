"""Таблица консоли и ширина окна консоли (CLAUDE.md §14 решение 78).

Часть запуска или блок из нескольких строк печатается таблицей: заголовок посередине линии из «=», строки, «-» между
записями, если записи надо различать (сообщения ВНИМАНИЕ, каналы в блоках эфиров), и закрывающая линия из «=». Одна
строка содержимого — без рамки: у блока итога эфиров — одной строкой с названием блока впереди («ВНИМАНИЕ — …»: название
несёт смысл строки), у части запуска — как есть; нет строк — нет таблицы. Ширина линий — ширина окна консоли
(`ConsoleWidth`): в терминале — по окну, не шире 120 знаков, не в терминале (файл, перенаправление, тесты) — 80.
"""
from __future__ import annotations

import shutil
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final, TextIO

from app.ui.messages import msg

MAX_WIDTH: Final[int] = 120       # шире таблица в широком окне не становится: строки читаются глазом
PLAIN_WIDTH: Final[int] = 80      # ширина вывода не в терминал


class TableMark(str, Enum):
    """Знаки таблицы консоли: линия заголовка и закрывающая, разделитель записей и вид заголовка на линии."""

    RULE = "="
    SEPARATOR = "-"
    TITLE = " {title} "


@dataclass(frozen=True)
class ConsoleWidth:
    """Ширина вывода в знаках: у терминала — по окну консоли, не больше `MAX_WIDTH`; не терминал — `PLAIN_WIDTH`."""

    columns: int

    @classmethod
    def of(cls, stream: TextIO | None) -> ConsoleWidth:
        if stream is None or not stream.isatty():
            return cls(PLAIN_WIDTH)
        return cls(min(shutil.get_terminal_size().columns, MAX_WIDTH))

    @classmethod
    def system(cls) -> ConsoleWidth:
        """Ширина консоли процесса — тот же поток, что у `Console.system`: так строит таблицы тот, кто готовит строки
        заранее, не зная консоли (итог эфиров — app\\output\\console.py)."""
        return cls.of(sys.stdout)


@dataclass(frozen=True)
class ConsoleTable:
    """Таблица консоли: заголовок, записи (у каждой — свои строки), нужен ли «-» между записями и печатается ли одна
    строка содержимого с названием впереди."""

    title: str
    entries: tuple[tuple[str, ...], ...]
    is_separated: bool = False
    is_titled_line: bool = False

    @classmethod
    def of_lines(cls, title: str, lines: Sequence[str]) -> ConsoleTable:
        """Строки одной записью; пустые строки по краям не нужны — края рисует таблица."""
        kept: list[str] = list(lines)
        while kept and not kept[0]:
            kept.pop(0)
        while kept and not kept[-1]:
            kept.pop()
        return cls(title, (tuple(kept),))

    def lines(self, width: int) -> tuple[str, ...]:
        """Строки таблицы шириной `width`; одна строка содержимого — она сама или «<название> — <строка>»."""
        content: tuple[str, ...] = tuple(line for entry in self.entries for line in entry)
        if len(content) == 1 and self.is_titled_line:
            return (msg.CONSOLE_TITLED_LINE.format(title=self.title, text=content[0].lstrip()),)
        if len(content) <= 1:
            return content
        separator: tuple[str, ...] = (TableMark.SEPARATOR.value * width,) if self.is_separated else ()
        body: list[str] = []
        for entry in (entry for entry in self.entries if entry):
            body.extend((*(separator if body else ()), *entry))
        head: str = TableMark.TITLE.value.format(title=self.title).center(width, TableMark.RULE.value)
        return (head, *body, TableMark.RULE.value * width)
