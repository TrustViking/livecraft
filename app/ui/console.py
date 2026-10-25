"""Консоль оператора: тексты из каталога msg — в stdout, отказ запуска — в stderr (CLAUDE.md §10, §11).

Печать в программе — только здесь. Строка уходит сразу (flush): её видно и в собранном exe, а не в конце запуска.
Сырой лог в терминал сюда не идёт — его пишет лог запуска с --debug.

У оконного exe (livecraftw.exe — ярлык настройки, §13 этап 8) консоли нет: потоки процесса — None. Сказанное запуском
тогда теряется (его пишет лог), а отказ запуска (замок занят) показывается окном-сообщением с тем же текстом: иначе
человек не увидел бы ничего. Оконный ли процесс, консоль решает сама — по своим потокам.

Ход этапа (CLAUDE.md §14 решение 78) — одна строка, которая в терминале обновляется на месте (`progress`): возврат
каретки, текст по ширине окна, хвост прежней строки затёрт пробелами, без перевода строки. У шага со счётом «n из N»
справа — полоса из «=», которая растёт от пустой на первом шаге до полной на последнем. Строка хода знает свой этап:
шаг другого этапа и обычная строка запуска сначала закрывают её переводом строки — на экране остаётся последний шаг
каждого этапа. Не в терминал (файл, перенаправление, тесты) строка хода — обычная строка, без полосы. Многострочное —
таблицей (`say_table`, app\\ui\\console_table.py).
"""
from __future__ import annotations

import io
import sys
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Final, TextIO

from app.core.dates import format_human_datetime
from app.ui.console_table import ConsoleTable, ConsoleWidth
from app.ui.messages import msg
from app.version import APP_VERSION


class EncodingErrors(str, Enum):
    """Как поток обходится с символом, которого нет в кодировке консоли."""

    REPLACE = "replace"     # заменой, а не падением


class LineMark(str, Enum):
    """Управляющие знаки строки хода в терминале."""

    CARRIAGE_RETURN = "\r"     # курсор — в начало строки: следующий шаг пишется поверх прежнего
    LINE_FEED = "\n"           # строка хода закрыта: на экране остаётся последний шаг
    GAP = " "                  # между текстом шага и полосой


class BarMark(str, Enum):
    """Знаки полосы хода: края и заполненная доля."""

    OPEN = "["
    FILLED = "="
    EMPTY = " "
    CLOSE = "]"


MIN_BAR_WIDTH: Final[int] = 10     # полоса уже не становится: текст шага укорачивается, полоса остаётся


class ProgressStage(str, Enum):
    """Этап, которому принадлежит строка хода: шаг другого этапа пишется с новой строки, а последний шаг прежнего
    остаётся на экране (§14 решение 78)."""

    TOOLS = "tools"                     # загрузка и самообновление yt-dlp и deno
    SHEETS_RETRY = "sheets_retry"       # повторы чтения таблицы плана
    VIDEOS = "videos"                   # чтение данных видео рядов
    DRIVE_PREVIEWS = "drive_previews"   # копии превью на Google Диск
    MERGE = "merge"                     # обращения к нейросети по эфирам
    DOCS = "docs"                       # документы объявлений по датам
    ANNOUNCE = "announce"               # объявления в Telegram по датам
    PACKAGE_SEND = "package_send"       # отправка пакета в Telegram
    PACKAGES = "packages"               # чтение пакетов папки пакетов
    CHANNEL_CHECK = "channel_check"     # проверка каналов без браузера
    CHANNEL_READ = "channel_read"       # чтение запланированных эфиров каналов
    BROADCASTS = "broadcasts"           # создание и правка эфиров, отправка их ключей
    REPORT = "report"                   # запись отчёта


@dataclass(frozen=True)
class StepCount:
    """Место шага в своём цикле — «n из N», счёт с единицы."""

    place: int
    total: int

    def filled(self, cells: int) -> int:
        """Сколько клеток полосы из `cells` занято: шаг начинается, поэтому на первом шаге — ни одной, на последнем —
        все; этап из одного шага — сразу весь."""
        if self.total == 1:
            return cells
        return cells * (self.place - 1) // (self.total - 1)


@dataclass(frozen=True)
class ProgressBar:
    """Полоса хода шириной `width` вместе с краями: «[» + «=» на пройденную долю этапа + пробелы + «]»."""

    count: StepCount
    width: int

    @property
    def text(self) -> str:
        cells: int = self.width - len(BarMark.OPEN.value + BarMark.CLOSE.value)
        filled: int = self.count.filled(cells)
        inside: str = BarMark.FILLED.value * filled + BarMark.EMPTY.value * (cells - filled)
        return BarMark.OPEN.value + inside + BarMark.CLOSE.value


@dataclass(frozen=True)
class ProgressStep:
    """Шаг этапа: текст, этап и место в цикле этапа, если цикл считается (`count`)."""

    text: str
    stage: ProgressStage
    count: StepCount | None = None

    def line(self, width: int) -> str:
        """Строка шага на знак уже окна (иначе терминал перенесёт курсор на новую строку), хвост добит пробелами.
        Со счётом — полоса на остаток окна после текста, не уже `MIN_BAR_WIDTH`; длинный текст укорачивается."""
        room: int = width - 1
        if self.count is None:
            return self.text[:room].ljust(room)
        bar_width: int = max(room - len(self.text) - len(LineMark.GAP.value), MIN_BAR_WIDTH)
        text_room: int = room - bar_width - len(LineMark.GAP.value)
        return self.text[:text_room].ljust(text_room) + LineMark.GAP.value + ProgressBar(self.count, bar_width).text


@dataclass
class ProgressLine:
    """Строка хода, которая сейчас стоит в терминале без перевода строки: `stage` — её этап, None — строки нет."""

    stage: ProgressStage | None = None

    def show(self, out: TextIO, step: ProgressStep, width: int) -> None:
        """Шаг своего этапа — поверх прежнего, хвост прежнего затёрт; шаг другого этапа — с новой строки, прежняя
        строка остаётся на экране."""
        if self.stage is not step.stage:
            self.close(out)
        out.write(LineMark.CARRIAGE_RETURN.value + step.line(width))
        out.flush()
        self.stage = step.stage

    def close(self, out: TextIO) -> None:
        """Перед обычной строкой и шагом другого этапа: строка хода остаётся на экране, следующий текст — с новой
        строки."""
        if self.stage is not None:
            out.write(LineMark.LINE_FEED.value)
            self.stage = None


@dataclass(frozen=True)
class Console:
    """Потоки вывода оператора: `out` — тексты работающего запуска, `err` — отказ запуска; у оконного процесса — None.
    `line` — строка хода в терминале: одна на консоль."""

    out: TextIO | None
    err: TextIO | None
    line: ProgressLine = field(default_factory=ProgressLine, compare=False)

    @classmethod
    def system(cls) -> Console:
        """Консоль процесса: потоки берутся в момент вызова."""
        return cls(out=sys.stdout, err=sys.stderr)

    def configure(self) -> None:
        """Символы, которых нет в кодировке консоли, — заменой, а не падением.

        Настраивается до разбора ключей: --help, --version и ошибку разбора печатает сам argparse, и в консоли
        с кодировкой cp1251 «→» из справки иначе роняет запуск вместо вывода справки.
        """
        for stream in (self.out, self.err):
            if isinstance(stream, io.TextIOWrapper):
                stream.reconfigure(errors=EncodingErrors.REPLACE.value)

    @property
    def is_windowed(self) -> bool:
        """Процесс без консоли: отказ запуска уходит окном-сообщением."""
        return self.err is None

    @property
    def width(self) -> int:
        """Ширина таблиц и строки хода: окно терминала, не шире 120; не терминал — 80."""
        return ConsoleWidth.of(self.out).columns

    def say(self, text: str) -> None:
        """Строка работающего запуска; без консоли — никуда (её пишет лог). Открытая строка хода остаётся над ней."""
        if self.out is not None:
            self.line.close(self.out)
            print(text, file=self.out, flush=True)

    def progress(self, text: str, stage: ProgressStage, step: StepCount | None = None) -> None:
        """Шаг этапа `stage`: в терминале — поверх прежнего шага этого этапа, со счётом `step` — с полосой хода;
        не в терминал — обычной строкой, без полосы."""
        if self.out is None:
            return
        if not self.out.isatty():
            self.say(text)
            return
        self.line.show(self.out, ProgressStep(text, stage, step), self.width)

    def say_lines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.say(line)

    def say_table(self, table: ConsoleTable) -> None:
        """Таблица шириной консоли; одна строка — как есть."""
        self.say_lines(table.lines(self.width))

    def say_error(self, text: str) -> None:
        """Отказ запуска — в stderr: в stdout идут только тексты работающего запуска. Без консоли — окно-сообщение;
        tkinter тянется только сюда."""
        if not self.is_windowed:
            if self.out is not None:
                self.line.close(self.out)
            print(text, file=self.err, flush=True)
            return
        from tkinter import messagebox

        messagebox.showerror(msg.SETUP_WINDOW_TITLE.format(version=APP_VERSION), text)

    def title(self, now: datetime) -> None:
        """Шапка — первая строка любого запуска; время — по часам программы, как в отчёте этого запуска."""
        self.say(msg.CONSOLE_TITLE.format(version=APP_VERSION, generated_at=format_human_datetime(now)))
