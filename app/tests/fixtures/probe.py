"""Сессия пробника в тесте: корень теста, консоль в памяти и лог прогона, который закрывается после блока."""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

from app.observability.logging_setup import RunLog
from app.paths import LivecraftPaths
from app.tests.fixtures.console import ConsoleRecord
from app.tools.probe import ProbeConsole, ProbeSession


@dataclass(frozen=True)
class ProbeRun:
    """Сессия, которую пробник получил бы от `ProbeLauncher`, и то, что он напечатал."""

    session: ProbeSession
    record: ConsoleRecord

    @classmethod
    @contextmanager
    def open(cls, paths: LivecraftPaths, started: datetime) -> Iterator[ProbeRun]:
        """Сессия на корне `paths` с моментом начала `started`; лог прогона закрывается после блока."""
        record: ConsoleRecord = ConsoleRecord()
        log: RunLog = RunLog.open(paths.logs_dir, debug=False, started=started)
        try:
            yield cls(ProbeSession(paths=paths, console=ProbeConsole(record.console), log=log, started=started), record)
        finally:
            log.close()

    @property
    def lines(self) -> list[str]:
        return self.record.lines
