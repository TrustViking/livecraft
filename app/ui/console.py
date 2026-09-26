"""Консоль оператора: тексты из messages_ru — в stdout, отказ запуска — в stderr (CLAUDE.md §10, §11).

Печать в программе — только здесь. Строка уходит сразу (flush): её видно и в собранном exe, а не в конце запуска.
Сырой лог в терминал сюда не идёт — его пишет лог запуска с --debug.
"""
from __future__ import annotations

import io
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import TextIO

from app.core.dates import format_datetime_text
from app.ui import messages_ru as msg
from app.version import APP_VERSION


class EncodingErrors(str, Enum):
    """Как поток обходится с символом, которого нет в кодировке консоли."""

    REPLACE = "replace"     # заменой, а не падением


@dataclass(frozen=True)
class Console:
    """Потоки вывода оператора: `out` — тексты работающего запуска, `err` — отказ запуска."""

    out: TextIO
    err: TextIO

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

    def say(self, text: str) -> None:
        print(text, file=self.out, flush=True)

    def say_lines(self, lines: Iterable[str]) -> None:
        for line in lines:
            self.say(line)

    def say_error(self, text: str) -> None:
        """Отказ запуска — в stderr: в stdout идут только тексты работающего запуска."""
        print(text, file=self.err, flush=True)

    def title(self, now: datetime) -> None:
        """Шапка — первая строка любого запуска; время — по часам программы, как в отчёте этого запуска."""
        self.say(msg.CONSOLE_TITLE.format(version=APP_VERSION, generated_at=format_datetime_text(now)))
