"""Вкладка «Логи» без окна: «Сохранить архив логов» (§8.2 п.11, §14 решения 20, 46, 62). Архив ложится в папку logs,
итог несёт его путь — по нему окно открывает папку; бота и чата поддержки нет."""
from __future__ import annotations

import zipfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from app.observability.log_event import LogArea
from app.paths import DataDir, LivecraftPaths
from app.setup.panels.logs_panel import LogsPanel, LogsVerdict
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

MOMENT: datetime = datetime(2026, 9, 29, 12, 0, tzinfo=timezone.utc)      # 15:00 по Киеву
ARCHIVE: str = "livecraft_logs_29-09-2026_150000.zip"
LOG_TEXT: bytes = b"run_started version=7.2\n"


@pytest.fixture
def panel(ready_paths: LivecraftPaths) -> LogsPanel:
    """Установка с одним файлом лога."""
    (ready_paths.dir(DataDir.LOGS) / "29-09-2026_140000_livecraft.log").write_bytes(LOG_TEXT)
    return LogsPanel(paths=ready_paths, clock=StoppedClock.at(MOMENT))


def _saved(paths: LivecraftPaths) -> Path:
    return paths.dir(DataDir.LOGS) / ARCHIVE


def _saved_line(paths: LivecraftPaths) -> str:
    """Строка записи архива в logs\\: путь — от корня программы, размер — как у записанного файла."""
    saved: Path = _saved(paths)
    line: str = msg.SETUP_LOGS_SAVED.format(
        path=paths.shown(saved), files=1, megabytes=saved.stat().st_size / 1024 / 1024
    )
    return msg.CHECK_OK_LINE.format(line=line)


def test_the_archive_lies_in_the_logs_folder_and_the_verdict_names_its_path(
    panel: LogsPanel, ready_paths: LivecraftPaths
) -> None:
    with LogCapture.on(LogArea.SETUP) as capture:
        verdict: LogsVerdict = panel.run()
    saved: Path = _saved(ready_paths)
    assert verdict == LogsVerdict(is_ok=True, lines=(_saved_line(ready_paths),), archive=saved)
    assert verdict.text == _saved_line(ready_paths) and ready_paths.shown(saved) == f"logs\\{ARCHIVE}"
    with zipfile.ZipFile(saved) as archive:
        assert archive.namelist() == ["diagnostics.txt", "29-09-2026_140000_livecraft.log"]
        assert archive.read("29-09-2026_140000_livecraft.log") == LOG_TEXT
    assert any(line.startswith("logs_saved path=") for line in capture.messages())


def test_a_second_archive_leaves_the_first_one_out(panel: LogsPanel, ready_paths: LivecraftPaths) -> None:
    """Прежний архив лежит в той же папке logs, но в новый не входит (§14 решение 46)."""
    earlier: Path = ready_paths.dir(DataDir.LOGS) / "livecraft_logs_28-09-2026_120000.zip"
    earlier.write_bytes(b"PK old archive")
    panel.run()
    with zipfile.ZipFile(_saved(ready_paths)) as archive:
        assert archive.namelist() == ["diagnostics.txt", "29-09-2026_140000_livecraft.log"]


def test_an_archive_that_does_not_write_is_named_and_has_no_path(panel: LogsPanel, ready_paths: LivecraftPaths) -> None:
    """На месте архива — папка: архив не записан, строка — с причиной ОС, пути нет — окну нечего открывать."""
    _saved(ready_paths).mkdir()
    with LogCapture.on(LogArea.SETUP) as capture:
        verdict: LogsVerdict = panel.run()
    assert not verdict.is_ok and len(verdict.lines) == 1 and verdict.archive is None
    assert verdict.lines[0].startswith(msg.CHECK_MARK_PROBLEM)
    assert any(line.startswith("logs_not_saved path=") for line in capture.messages())
