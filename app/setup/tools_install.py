"""Недостающие yt-dlp и deno — окно настройки ставит их само при открытии (CLAUDE.md §14 решения 65, 74).

Установщик бинарников не несёт (решение 65): на чистой установке их нет, и первый запуск тратил минуты на загрузку
молча. Поэтому окно при открытии смотрит в tools\\ (`missing`): нет хоть одного — в фоновом потоке ставит только
недостающие тем же кодом, что запуск (`SourceTools.install_missing`: загрузка выпуска с GitHub со строками хода), а
строка внизу окна показывает, что ставится, ход загрузки и итог (`ToolsVerdict`); окно работает, пока идёт загрузка.
Оба на месте — окно их не трогает и не обновляет: обновляет запуск.

Модель не знает ни Tk, ни окна: фоновый поток получает только её и очередь (`work`), окно забирает из очереди строки
хода и итог.
"""
from __future__ import annotations

import functools
import queue
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.core.text_format import NEWLINE
from app.paths import LivecraftPaths
from app.run.progress import SILENT_PROGRESS
from app.runtime.deno_updater import ToolStatus, ToolUpdate
from app.runtime.ytdlp_updater import SourceTools
from app.ui.messages import msg


@dataclass(frozen=True)
class ToolsVerdict:
    """Итог установки: что поставлено и что нет (`updates`); `is_interrupted` — установка оборвалась ошибкой программы
    (причина — в логе запуска)."""

    updates: tuple[ToolUpdate, ...]
    is_interrupted: bool = False

    @property
    def text(self) -> str:
        """Строки итога: не скачанные — «✗» с причиной и тем, что их скачает запуск; скачанные — «✓» с версиями."""
        if self.is_interrupted:
            return msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_TOOLS_INTERRUPTED)
        lines: list[str] = [
            msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_TOOLS_FAILED.format(tool=update.tool, reason=problem.human))
            for update in self.updates if (problem := update.problem) is not None
        ]
        if self.installed:
            installed: str = msg.SETUP_TOOLS_DONE.format(versions=msg.LIST_JOINER.join(self.installed))
            lines.append(msg.CHECK_OK_LINE.format(line=installed))
        return NEWLINE.join(lines)

    @property
    def installed(self) -> tuple[str, ...]:
        """Поставленные бинарники с версиями: «yt-dlp 2026.08.19»."""
        return tuple(
            msg.SETUP_TOOLS_VERSION.format(tool=update.tool, version=update.after)
            for update in self.updates if update.status is ToolStatus.UPDATED
        )


INTERRUPTED: Final[ToolsVerdict] = ToolsVerdict((), is_interrupted=True)


@dataclass(frozen=True)
class ToolsInstall:
    """Установка недостающих бинарников окна: каких нет при открытии окна (`missing`) и установка со строками хода
    (`tools` — `SourceTools` установки, строки — в переданное)."""

    missing: tuple[str, ...]
    tools: Callable[[Callable[[str], None]], SourceTools]

    @classmethod
    def of(cls, paths: LivecraftPaths, settings: LivecraftSettings) -> ToolsInstall:
        """Установка папки tools\\ установки `paths` в поясе и с cookies настроек `settings`."""
        tools: Callable[[Callable[[str], None]], SourceTools] = functools.partial(
            SourceTools.of, paths, Clock(settings.zone), remind_days=settings.cookies.remind_days
        )
        return cls(tools(SILENT_PROGRESS.tool_note).missing, tools)

    @property
    def is_needed(self) -> bool:
        return bool(self.missing)

    @property
    def starting_line(self) -> str:
        """Строка, пока идёт установка: каких бинарников нет, загрузка идёт, подождать."""
        return msg.SETUP_TOOLS_INSTALLING.format(tools=msg.LIST_JOINER.join(self.missing))

    def work(self, inbox: queue.Queue[ToolsVerdict | str]) -> None:
        """Фоновый поток: только модель и очередь. Строки хода — в очередь по ходу, итог — последним и при любом исходе:
        иначе строка окна ждала бы его вечно."""
        verdict: ToolsVerdict = INTERRUPTED
        try:
            verdict = ToolsVerdict(self.tools(inbox.put).install_missing())
        finally:
            inbox.put(verdict)
