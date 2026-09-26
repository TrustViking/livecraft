from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta, timezone

import pytest

from app.tests.fixtures.console import ConsoleRecord
from app.ui import messages_ru as msg
from app.ui.console import Console
from app.version import APP_VERSION


def test_say_and_say_lines_go_to_stdout_in_order() -> None:
    record: ConsoleRecord = ConsoleRecord()
    record.console.say("первая")
    record.console.say_lines(("вторая", "третья"))
    assert record.lines == ["первая", "вторая", "третья"]
    assert record.error_lines == []


def test_a_refusal_goes_to_stderr() -> None:
    """В stdout — только тексты работающего запуска; отказ запуска — в stderr."""
    record: ConsoleRecord = ConsoleRecord()
    record.console.say_error("отказ")
    assert record.lines == [] and record.error_lines == ["отказ"]


def test_the_title_carries_the_version_and_the_program_time() -> None:
    record: ConsoleRecord = ConsoleRecord()
    record.console.title(datetime(2026, 9, 26, 18, 5, tzinfo=timezone(timedelta(hours=3))))
    assert record.lines == [msg.CONSOLE_TITLE.format(version=APP_VERSION, generated_at="26-09-2026 18:05")]


def test_configure_replaces_characters_the_console_cannot_encode() -> None:
    """Консоль в cp1251: «→» и эмодзи — заменой, а не падением."""
    buffer: io.BytesIO = io.BytesIO()
    stream: io.TextIOWrapper = io.TextIOWrapper(buffer, encoding="cp1251", errors="strict", newline="\n")
    console: Console = Console(out=stream, err=stream)
    console.configure()
    console.say("таблица → слоты 🌐")
    stream.flush()
    assert buffer.getvalue() == "таблица ? слоты ?\n".encode("cp1251")


def test_the_system_console_takes_the_streams_of_the_moment(monkeypatch: pytest.MonkeyPatch) -> None:
    out: io.StringIO = io.StringIO()
    monkeypatch.setattr(sys, "stdout", out)
    Console.system().say("строка")
    assert out.getvalue() == "строка\n"
