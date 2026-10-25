"""Вкладка окна «Логи» (CLAUDE.md §8.2 п.11, §14 решения 20, 46, 62).

Вверху — что делает кнопка: архив папки logs и diagnostics.txt ложится в logs\\, что в него входит и что не входит
никогда, и что отправляет его человек сам. Ниже — одна кнопка «Сохранить архив логов» со строкой итога (`CheckLine`:
архив собирается и ложится в logs\\ в фоновом потоке, окно не замирает). Архив записан — окно открывает папку logs с
выделенным архивом открывалкой `reveal` (в программе — Проводник, `FolderOpener`; в тестах — подделка). Своих правил у
вкладки нет.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from tkinter import ttk

from app.runtime.log_archive import LOG_ARCHIVE_LIMIT_MEGABYTES
from app.setup.page import SetupPage
from app.setup.panels.logs_panel import LogsPanel, LogsVerdict
from app.setup.tabs.check_line import CheckLine, CheckRun, CheckTexts
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_shell import TabShell
from app.ui.messages import msg


class LogsTab:
    """Вкладка «Логи»: оболочка, модель архива `panel`, строка сохранения (`save_line`) и открывалка папки архива
    (`reveal`)."""

    def __init__(self, context: SetupContext, panel: LogsPanel, reveal: Callable[[Path], object]) -> None:
        intro: str = msg.SETUP_LOGS_INTRO.format(limit=LOG_ARCHIVE_LIMIT_MEGABYTES)
        self.shell: TabShell = TabShell(context, SetupPage.LOGS, intro)
        self.panel: LogsPanel = panel
        self.reveal: Callable[[Path], object] = reveal
        interrupted: LogsVerdict = LogsVerdict.problem(msg.SETUP_LOGS_INTERRUPTED)
        texts: CheckTexts = CheckTexts(msg.SETUP_LOGS_BUTTON_SAVE, msg.SETUP_LOGS_WORKING, interrupted)
        self.save_line: CheckLine = CheckLine(self.shell.body, texts, self._save_run, self.saved)

    @property
    def frame(self) -> ttk.Frame:
        return self.shell.frame

    @property
    def page(self) -> SetupPage:
        return self.shell.page

    def saved(self) -> None:
        """Итог пришёл: архив записан — папка logs с выделенным архивом; не записался — только строка итога."""
        verdict: object = self.save_line.verdict
        if isinstance(verdict, LogsVerdict) and verdict.archive is not None:
            self.reveal(verdict.archive)

    def _save_run(self) -> CheckRun:
        """Сборка и запись архива — в фоне; поток получает модель, а не вкладку: объекты Tk — только в главном потоке."""
        panel: LogsPanel = self.panel
        return lambda _mail: panel.run()
