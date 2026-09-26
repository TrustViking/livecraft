"""Консоль оператора в памяти: тест читает, что запуск напечатал в stdout и в stderr (CLAUDE.md §11)."""
from __future__ import annotations

import io
from dataclasses import dataclass, field

from app.ui.console import Console


@dataclass(frozen=True)
class ConsoleRecord:
    """Потоки консоли в памяти и сама консоль на них."""

    out: io.StringIO = field(default_factory=io.StringIO)
    err: io.StringIO = field(default_factory=io.StringIO)

    @property
    def console(self) -> Console:
        return Console(out=self.out, err=self.err)

    @property
    def lines(self) -> list[str]:
        """Строки stdout по порядку."""
        return self.out.getvalue().splitlines()

    @property
    def error_lines(self) -> list[str]:
        """Строки stderr по порядку."""
        return self.err.getvalue().splitlines()
