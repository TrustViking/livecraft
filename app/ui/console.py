"""Консоль оператора: тексты из каталога msg — в stdout, отказ запуска — в stderr (CLAUDE.md §10, §11).

Печать в программе — только здесь. Строка уходит сразу (flush): её видно и в собранном exe, а не в конце запуска.
Сырой лог в терминал сюда не идёт — его пишет лог запуска с --debug.

У оконного exe (livecraftw.exe — ярлык настройки, §13 этап 8) консоли нет: потоки процесса — None. Сказанное запуском
тогда теряется (его пишет лог), а отказ запуска (замок занят) показывается окном-сообщением с тем же текстом: иначе
человек не увидел бы ничего. Оконный ли процесс, консоль решает сама — по своим потокам.
"""
from __future__ import annotations

import io
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TextIO

from app.core.dates import format_human_datetime
from app.ui.messages import msg
from app.version import APP_VERSION


class EncodingErrors(str, Enum):
    """Как поток обходится с символом, которого нет в кодировке консоли."""

    REPLACE = "replace"     # заменой, а не падением


@dataclass(frozen=True)
class Console:
    """Потоки вывода оператора: `out` — тексты работающего запуска, `err` — отказ запуска; у оконного процесса — None."""

    out: TextIO | None
    err: TextIO | None

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

    def say(self, text: str) -> None:
        """Строка работающего запуска; без консоли — никуда (её пишет лог)."""
        if self.out is not None:
            print(text, file=self.out, flush=True)

    def say_lines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.say(line)

    def say_error(self, text: str) -> None:
        """Отказ запуска — в stderr: в stdout идут только тексты работающего запуска. Без консоли — окно-сообщение;
        tkinter тянется только сюда."""
        if not self.is_windowed:
            print(text, file=self.err, flush=True)
            return
        from tkinter import messagebox

        messagebox.showerror(msg.SETUP_WINDOW_TITLE.format(version=APP_VERSION), text)

    def title(self, now: datetime) -> None:
        """Шапка — первая строка любого запуска; время — по часам программы, как в отчёте этого запуска."""
        self.say(msg.CONSOLE_TITLE.format(version=APP_VERSION, generated_at=format_human_datetime(now)))
