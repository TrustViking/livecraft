"""diagnostics.txt архива логов (CLAUDE.md §13 задача 7.2, §14 решение 20).

Всё, что нужно для разбора сбоя у получателя токена, одним файлом и строками лога (§14 решение 38): версия программы,
момент, система, Python, собранный exe или репо, язык окна, корень программы, снимок запуска (`RunSnapshot` —
livecraft.json, линии, папки, каналы, сейф ярлыками с отпечатками) и строка готовности окна. Значений сейфа нет: здесь
только то, что уже пишет лог (§7.4).
"""
from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from app.core.text_format import NEWLINE
from app.observability.log_event import LogEvent, Quoted
from app.paths import ProcessAttr
from app.setup.readiness import Readiness, RunSnapshot
from app.ui.messages import UI_LANGUAGE
from app.version import APP_VERSION


class DiagnosticsEvent(str, Enum):
    """Строки diagnostics.txt."""

    PROGRAM = "diagnostics_program"
    READINESS = "diagnostics_readiness"


@dataclass(frozen=True)
class Diagnostics:
    """Диагностика установки по готовности `readiness` на момент `moment`."""

    readiness: Readiness
    moment: datetime

    @property
    def text(self) -> str:
        """Строки лога: программа и машина, снимок запуска, готовность окна."""
        program: LogEvent = LogEvent.of(
            DiagnosticsEvent.PROGRAM,
            version=APP_VERSION,
            moment=self.moment.isoformat(),
            system=platform.platform(),
            python=platform.python_version(),
            frozen=bool(getattr(sys, ProcessAttr.FROZEN.value, False)),
            ui_language=UI_LANGUAGE,
            root=Quoted(str(self.readiness.paths.root)),
        )
        readiness: LogEvent = LogEvent.of(DiagnosticsEvent.READINESS, line=Quoted(self.readiness.window_line))
        events: tuple[LogEvent, ...] = (program, *RunSnapshot(self.readiness).events, readiness)
        return NEWLINE.join(event.text for event in events) + NEWLINE
