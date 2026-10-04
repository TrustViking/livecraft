"""Отчёт запуска logs\\<DD-MM-YYYY>_<HHMMSS>_report.md по всем частям, которые работали (CLAUDE.md §3 шаг 12, §5).

Отчёт пишет каждый запуск по линиям, дошедший до работы (в том числе остановленный кодом 2 или 3 и пробный), и
--status; отказ до работы, окно настройщика, --check, --auth и --version отчёта не пишут. `RunJournal` собирает его по
ходу запуска: строки, которые запуск сказал сам (часть «Запуск»), и части в порядке работы — каждая говорит в
консоль и кладёт в отчёт свою часть. В конце запуска — файл целиком (`RunReportFile`; штамп имени — момент начала
запуска, тот же, что у лога) и последним выводом — подвал путей: ключи (если часть эфиров писала keys.txt), отчёт,
лог (`RunFooter`).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path

from app.core.dates import format_human_datetime
from app.core.text_format import NEWLINE, TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import LivecraftPaths, write_text_atomically
from app.run.report_section import PartReport
from app.ui.console import Console
from app.ui.messages import msg
from app.version import APP_VERSION

LOGGER = get_logger(LogArea.OUTPUT)


class RunReportEvent(str, Enum):
    """Запись отчёта запуска в логе."""

    WRITTEN = "run_report"


@dataclass(frozen=True)
class RunReportFile:
    """Отчёт запуска: начало запуска, пробный ли он и части в порядке работы."""

    started: datetime
    dry_run: bool
    parts: tuple[PartReport, ...]

    @property
    def text(self) -> str:
        """Шапка с пометкой пробного запуска, затем части; пустая часть не печатается."""
        title: str = msg.REPORT_TITLE.format(version=APP_VERSION, generated_at=format_human_datetime(self.started))
        lines: list[str] = [title + msg.REPORT_TITLE_DRY_RUN if self.dry_run else title, ""]
        for part in self.parts:
            lines.extend(part.lines)
        return NEWLINE.join(lines).rstrip(NEWLINE) + NEWLINE

    def write(self, paths: LivecraftPaths) -> Path:
        """Файл отчёта целиком; сбой записи — OSError вызывающему: отчёт без файла — не отчёт."""
        path: Path = paths.report_file(self.started)
        path.parent.mkdir(parents=True, exist_ok=True)
        write_text_atomically(path, self.text, TEXT_ENCODING)
        shown: tuple[str, ...] = tuple(part.title for part in self.parts if part.lines)
        LogEvent.of(RunReportEvent.WRITTEN, parts=shown, path=paths.shown(path)).emit(LOGGER)
        return path


@dataclass(frozen=True)
class RunFooter:
    """Подвал путей запуска для людей: keys.txt (если его писала часть эфиров), отчёт и лог."""

    keys_file: str | None
    report_file: str
    log_file: str

    @property
    def lines(self) -> tuple[str, ...]:
        labelled: tuple[tuple[str, str | None], ...] = (
            (msg.CONSOLE_LABEL_KEYS, self.keys_file),
            (msg.CONSOLE_LABEL_REPORT, self.report_file),
            (msg.CONSOLE_LABEL_LOG, self.log_file),
        )
        return ("", *(msg.CONSOLE_PATH.format(label=label, path=path) for label, path in labelled if path))


@dataclass
class RunJournal:
    """Что запуск сказал человеку: консоль, пробный ли запуск, строки самого запуска и части в порядке работы."""

    console: Console
    dry_run: bool
    launch_lines: list[str] = field(default_factory=list)
    parts: list[PartReport] = field(default_factory=list)

    def say(self, lines: Sequence[str]) -> None:
        """Строки самого запуска — в консоль и в часть «Запуск»."""
        self.console.say_lines(lines)
        self.launch_lines.extend(lines)

    def part(self, lines: Sequence[str], part: PartReport) -> None:
        """Строки части — в консоль, её часть — в отчёт."""
        self.console.say_lines(lines)
        self.parts.append(part)

    def finish(self, paths: LivecraftPaths, started: datetime, log_file: str) -> Path:
        """Отчёт запуска в logs\\, затем подвал путей — последним выводом запуска; `log_file` — путь лога для людей."""
        launch: PartReport = PartReport(msg.REPORT_PART_RUN, tuple(self.launch_lines))
        written: Path = RunReportFile(started, self.dry_run, (launch, *self.parts)).write(paths)
        keys: str | None = next((part.keys_file for part in self.parts if part.keys_file is not None), None)
        self.console.say_lines(RunFooter(keys, paths.shown(written), log_file).lines)
        return written
