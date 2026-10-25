"""Список таймкодов в описании видео (CLAUDE.md §14 решение 79).

Время записи видео не совпадает со временем эфира, а YouTube строит по таймкодам описания главы. Строка — таймкод,
если начинается с времени вида 0:00, 00:00 или 0:00:00 (дальше — пробел, тире или текст, но не цифра). Две и больше
таких строк — список: все они уходят из описания, пустые строки вокруг и между ними сводятся к одной там, где текст
продолжается. Одна такая строка остаётся: «18:00 — эфир» — скорее время, чем глава.

Заголовок списка («Timestamps:», «⏱ Таймкоды —») — строка над первым таймкодом списка (пустые строки между ними не в
счёт), которая без знаков по краям (всё, что не буква и не цифра: двоеточие, тире, эмодзи, пробелы) совпадает с одной
из фраз заголовков без учёта регистра; он уходит вместе со списком. Фразы даёт тот, кто создаёт объект (`of`): слой
core ресурсов не читает.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from app.core.text_format import NEWLINE, SPACE

TIMECODE_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s*\d{1,2}:\d{2}(?::\d{2})?(?!\d)")
TIMECODE_LIST_MIN_LINES: Final[int] = 2     # с двух строк-таймкодов — список глав, одна строка — просто время


@dataclass(frozen=True)
class TimecodeList:
    """Описание и список таймкодов в нём; `headings` — фразы заголовка списка в виде для сравнения (`_phrase`)."""

    text: str
    headings: frozenset[str] = frozenset()

    @classmethod
    def of(cls, text: str, headings: Iterable[str]) -> TimecodeList:
        """Описание `text` и фразы заголовка списка как в ресурсе (одна фраза — строка, регистр не важен)."""
        return cls(text=text, headings=frozenset(cls._phrase(heading) for heading in headings))

    @property
    def lines(self) -> tuple[str, ...]:
        """Строки-таймкоды описания в порядке текста."""
        return tuple(line for line in self.text.split(NEWLINE) if self._is_timecode(line))

    @property
    def is_list(self) -> bool:
        """Строк-таймкодов две и больше: это список глав."""
        return len(self.lines) >= TIMECODE_LIST_MIN_LINES

    @property
    def removed(self) -> int:
        """Сколько строк уходит из описания: список — все таймкоды и его заголовок, одна строка — ни одной."""
        if not self.is_list:
            return 0
        return len(self.lines) + (1 if self._heading_index is not None else 0)

    @property
    def cleaned(self) -> str:
        """Описание без списка таймкодов и его заголовка; списка нет — описание как есть. Участок из этих строк и
        пустых строк уходит целиком; внутри текста на его месте остаётся пустая строка, если она в участке была."""
        if not self.is_list:
            return self.text
        heading: int | None = self._heading_index
        kept: list[str] = []
        removed: bool = False
        had_blank: bool = False
        for index, line in enumerate(self.text.split(NEWLINE)):
            if index == heading or self._is_timecode(line) or (removed and not line.strip()):
                had_blank = had_blank or not line.strip()
                removed = True
                continue
            if removed and had_blank and kept and kept[-1].strip():
                kept.append("")
            kept.append(line)
            removed = had_blank = False
        while kept and not kept[-1].strip():
            kept.pop()
        return NEWLINE.join(kept)

    @property
    def _heading_index(self) -> int | None:
        """Номер строки-заголовка над первым таймкодом (пустые строки между ними пропускаются); заголовка нет — None."""
        lines: list[str] = self.text.split(NEWLINE)
        first: int = next(index for index, line in enumerate(lines) if self._is_timecode(line))
        above: int | None = next((index for index in reversed(range(first)) if lines[index].strip()), None)
        if above is None or self._phrase(lines[above]) not in self.headings:
            return None
        return above

    def _is_timecode(self, line: str) -> bool:
        return TIMECODE_LINE_PATTERN.match(line) is not None

    @classmethod
    def _phrase(cls, line: str) -> str:
        """Строка для сравнения с заголовками: без знаков по краям (не буква и не цифра), пробелы внутри — по одному,
        без учёта регистра."""
        start: int = next((index for index, char in enumerate(line) if char.isalnum()), len(line))
        end: int = next((index for index in range(len(line), start, -1) if line[index - 1].isalnum()), start)
        return SPACE.join(line[start:end].split()).casefold()
