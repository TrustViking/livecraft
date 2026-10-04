"""Каркас пробников разработки (CLAUDE.md §5 tools\\): общий запуск и общий вывод. В поставку не идёт.

`ProbeLauncher` делает то, что нужно каждому пробнику до его работы: корень, папки данных, лог на время прогона —
и отдаёт пробнику `ProbeSession`. `ProbeConsole` — вывод пробника: строки и отказ «настройка не готова»
(строка причины, строка «что сделать», код 2). Пробник, прочитавший сейф, сам защищает лог фильтром сейфа
(`ProbeSession.log.protect`) до первого обращения к сети.
"""
from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.config.files import ShippedSettings
from app.observability.logging_setup import RunLog
from app.paths import LivecraftPaths
from app.run.exit_code import ExitCode
from app.ui.console import Console
from app.ui.messages import msg

# Настройки ещё не прочитаны: время лога пробника — в поясе поставочного шаблона.
SHIPPED_SETTINGS: Final[ShippedSettings] = ShippedSettings()


@dataclass(frozen=True)
class ProbeConsole:
    """Вывод пробника в консоль оператора."""

    console: Console

    def say(self, text: str) -> None:
        self.console.say(text)

    def say_lines(self, lines: Iterable[str]) -> None:
        self.console.say_lines(lines)

    def refuse(self, problem: str) -> int:
        """Настройка не готова: причина, что сделать — и код 2, к сети не обращались."""
        self.console.say(problem)
        self.console.say(msg.SETUP_REQUIRED)
        return int(ExitCode.CONFIG)


@dataclass(frozen=True)
class ProbeSession:
    """Что пробник получает от запуска: корень, вывод, лог прогона и момент начала по часам программы."""

    paths: LivecraftPaths
    console: ProbeConsole
    log: RunLog
    started: datetime


@dataclass(frozen=True)
class ProbeLauncher:
    """Общий запуск пробника: корень, папки, лог на время прогона; код выхода — код пробника."""

    console: ProbeConsole

    @classmethod
    def system(cls) -> ProbeLauncher:
        return cls(console=ProbeConsole(Console.system()))

    def run(self, probe: Callable[[ProbeSession], int]) -> int:
        paths: LivecraftPaths = LivecraftPaths.locate()
        paths.ensure_dirs()
        started: datetime = SHIPPED_SETTINGS.clock.now()
        log: RunLog = RunLog.open(paths.logs_dir, debug=False, started=started)
        try:
            return probe(ProbeSession(paths=paths, console=self.console, log=log, started=started))
        finally:
            log.close()
