"""Отчёт запуска по частям, подвал путей и журнал запуска (app\\run\\run_report.py; CLAUDE.md §3 шаг 12, задача 6.3)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.observability.log_event import LogArea
from app.paths import LivecraftPaths
from app.run.report_section import PartReport, ReportSection
from app.run.run_report import RunFooter, RunJournal, RunReportFile
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg
from app.version import APP_VERSION

STARTED: datetime = datetime(2027, 3, 16, 12, 0, tzinfo=ZoneInfo("Europe/Kyiv"))
LAUNCH: PartReport = PartReport(msg.REPORT_PART_RUN, ("Настройки livecraft:",))
TABLE: PartReport = PartReport(
    msg.REPORT_PART_INTAKE, ("Таблица плана: рядов 1.",), (ReportSection("### Слоты (1)", ("слот",)),)
)
EMPTY: PartReport = PartReport(msg.REPORT_PART_SHELF, ())
KEYS_SHOWN: str = str(Path("keystreams") / "keys.txt")
BROADCASTS: PartReport = PartReport("Эфиры YouTube", ("Итог по эфирам (всего 0).",), (), KEYS_SHOWN)

SAMPLE: str = f"""# Livecraft {APP_VERSION} — отчёт 16.03.2027 12:00

## Запуск

Настройки livecraft:

## Таблица плана и тексты

Таблица плана: рядов 1.

### Слоты (1)
- слот
"""


def test_the_report_is_the_title_and_the_parts_in_the_order_of_the_work() -> None:
    """Пустая часть не печатается; конец файла — один перевод строки."""
    assert RunReportFile(STARTED, False, (LAUNCH, EMPTY, TABLE)).text == SAMPLE


def test_a_dry_run_marks_the_title() -> None:
    text: str = RunReportFile(STARTED, True, (LAUNCH,)).text
    assert text.splitlines()[0] == f"# Livecraft {APP_VERSION} — отчёт 16.03.2027 12:00" + msg.REPORT_TITLE_DRY_RUN


def test_the_report_file_is_stamped_like_the_log(livecraft_paths: LivecraftPaths) -> None:
    report: RunReportFile = RunReportFile(STARTED, False, (LAUNCH, EMPTY, TABLE))
    with LogCapture.on(LogArea.OUTPUT) as capture:
        path: Path = report.write(livecraft_paths)
    assert path == livecraft_paths.logs_dir / "16-03-2027_120000_report.md"
    assert path.read_bytes().decode("utf-8") == SAMPLE
    assert capture.messages() == [
        f"run_report parts=Запуск,Таблица плана и тексты path={Path('logs') / '16-03-2027_120000_report.md'}"
    ]


def test_the_footer_goes_keys_report_log_and_skips_the_keys_without_a_keys_file() -> None:
    assert RunFooter(KEYS_SHOWN, "r.md", "l.log").lines == (
        "",
        msg.CONSOLE_PATH.format(label=msg.CONSOLE_LABEL_KEYS, path=KEYS_SHOWN),
        msg.CONSOLE_PATH.format(label=msg.CONSOLE_LABEL_REPORT, path="r.md"),
        msg.CONSOLE_PATH.format(label=msg.CONSOLE_LABEL_LOG, path="l.log"),
    )
    assert RunFooter(None, "r.md", "l.log").lines[1].startswith("  " + msg.CONSOLE_LABEL_REPORT)


def test_the_journal_says_the_lines_writes_the_report_once_and_prints_the_footer_last(
    livecraft_paths: LivecraftPaths,
) -> None:
    record: ConsoleRecord = ConsoleRecord()
    journal: RunJournal = RunJournal(record.console, dry_run=False)
    journal.say(("Настройки livecraft:",))
    journal.part(("строка таблицы",), TABLE)
    journal.part(("строка эфиров",), BROADCASTS)
    written: Path = journal.finish(livecraft_paths, STARTED, "logs\\run.log")
    assert record.lines == [
        "Настройки livecraft:",
        "строка таблицы",
        "строка эфиров",
        *RunFooter(KEYS_SHOWN, livecraft_paths.shown(written), "logs\\run.log").lines,
    ]
    text: str = written.read_bytes().decode("utf-8")
    assert [line for line in text.splitlines() if line.startswith("## ")] == [
        "## Запуск", "## Таблица плана и тексты", "## Эфиры YouTube"
    ]
    assert list(livecraft_paths.logs_dir.glob("*_report.md")) == [written]
