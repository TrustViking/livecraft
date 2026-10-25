from __future__ import annotations

import io
import sys
from datetime import datetime, timedelta, timezone

import pytest

from app.tests.fixtures.console import ConsoleRecord
from app.ui import messages_ru as msg
from app.ui.console import Console, ProgressStage, StepCount
from app.ui.console_table import ConsoleTable
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
    assert record.lines == [msg.CONSOLE_TITLE.format(version=APP_VERSION, generated_at="26.09.2026 18:05")]


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


def test_a_windowed_process_says_nothing_and_shows_a_refusal_in_a_message_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Оконный exe (livecraftw.exe): потоков нет — строки запуска теряются, отказ запуска — окно-сообщение."""
    from tkinter import messagebox

    shown: list[tuple[str, str]] = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, text: shown.append((title, text)))
    monkeypatch.setattr(sys, "stdout", None)
    monkeypatch.setattr(sys, "stderr", None)
    console: Console = Console.system()
    console.configure()
    console.say("строка")
    console.say_error("замок занят")
    assert console.is_windowed
    assert shown == [(msg.SETUP_WINDOW_TITLE.format(version=APP_VERSION), "замок занят")]


def test_a_console_process_is_not_windowed() -> None:
    assert not ConsoleRecord().console.is_windowed


class TerminalStream(io.StringIO):
    """Поток, который говорит, что он — терминал: так консоль видит окно cmd или PowerShell."""

    def isatty(self) -> bool:
        return True


def test_a_progress_line_in_a_terminal_is_rewritten_in_place(monkeypatch: pytest.MonkeyPatch) -> None:
    """Шаг этапа — возврат каретки и текст по ширине окна без перевода строки; следующий шаг — поверх, хвост прежнего
    затёрт; обычная строка сначала закрывает строку хода (§14 решение 78)."""
    monkeypatch.setenv("COLUMNS", "20")
    stream: TerminalStream = TerminalStream()
    console: Console = Console(out=stream, err=stream)
    console.progress("Видео 1 из 15: длинная ссылка", ProgressStage.VIDEOS)
    console.progress("Видео 2 из 15", ProgressStage.VIDEOS)
    console.say("Итог")
    assert stream.getvalue() == "\rВидео 1 из 15: длин\rВидео 2 из 15      \nИтог\n"


def test_a_refusal_after_a_progress_line_starts_on_a_new_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("COLUMNS", "20")
    stream: TerminalStream = TerminalStream()
    console: Console = Console(out=stream, err=stream)
    console.progress("шаг", ProgressStage.VIDEOS)
    console.say_error("отказ")
    assert stream.getvalue().endswith("шаг" + " " * 16 + "\nотказ\n")


def test_outside_a_terminal_a_progress_line_is_an_ordinary_line() -> None:
    record: ConsoleRecord = ConsoleRecord()
    console: Console = record.console
    console.progress("Видео 1 из 2", ProgressStage.VIDEOS, StepCount(1, 2))
    console.progress("Видео 2 из 2", ProgressStage.VIDEOS, StepCount(2, 2))
    console.progress("Документ 1 из 1", ProgressStage.DOCS, StepCount(1, 1))
    console.say("Итог")
    assert record.lines == ["Видео 1 из 2", "Видео 2 из 2", "Документ 1 из 1", "Итог"]     # без полосы
    assert "\r" not in record.out.getvalue()


def test_the_last_step_of_a_stage_stays_and_the_next_stage_starts_on_a_new_line(monkeypatch: pytest.MonkeyPatch) -> None:
    """Шаг другого этапа сначала закрывает строку прежнего: её последний шаг остаётся на экране отдельной строкой,
    новый этап пишет поверх только себя (§14 решение 78)."""
    monkeypatch.setenv("COLUMNS", "20")
    stream: TerminalStream = TerminalStream()
    console: Console = Console(out=stream, err=stream)
    console.progress("Видео 1 из 2", ProgressStage.VIDEOS)
    console.progress("Видео 2 из 2", ProgressStage.VIDEOS)
    console.progress("Копия 1 из 2", ProgressStage.DRIVE_PREVIEWS)
    console.progress("Копия 2 из 2", ProgressStage.DRIVE_PREVIEWS)
    console.say("Итог")
    rows: list[str] = stream.getvalue().split("\n")
    assert rows == [
        "\rВидео 1 из 2       \rВидео 2 из 2       ",
        "\rКопия 1 из 2       \rКопия 2 из 2       ",
        "Итог",
        "",
    ]


def _bar_line(monkeypatch: pytest.MonkeyPatch, columns: int, text: str, step: StepCount) -> str:
    """Строка шага со счётом в терминале шириной `columns` — без возврата каретки."""
    monkeypatch.setenv("COLUMNS", str(columns))
    stream: TerminalStream = TerminalStream()
    Console(out=stream, err=stream).progress(text, ProgressStage.VIDEOS, step)
    return stream.getvalue().removeprefix("\r")


def test_the_bar_is_empty_on_the_first_step_and_full_on_the_last(monkeypatch: pytest.MonkeyPatch) -> None:
    """Полоса — остаток окна после текста: «[» + «=» на пройденную долю + пробелы + «]»; строка на знак уже окна."""
    first: str = _bar_line(monkeypatch, 40, "Видео 1 из 4", StepCount(1, 4))
    third: str = _bar_line(monkeypatch, 40, "Видео 3 из 4", StepCount(3, 4))
    last: str = _bar_line(monkeypatch, 40, "Видео 4 из 4", StepCount(4, 4))
    assert first == "Видео 1 из 4 [" + " " * 24 + "]"
    assert third == "Видео 3 из 4 [" + "=" * 16 + " " * 8 + "]"
    assert last == "Видео 4 из 4 [" + "=" * 24 + "]"
    assert len(last) == 39
    assert _bar_line(monkeypatch, 60, "Видео 1 из 1", StepCount(1, 1)) == "Видео 1 из 1 [" + "=" * 44 + "]"


def test_a_long_text_is_cut_and_the_bar_stays(monkeypatch: pytest.MonkeyPatch) -> None:
    """Текст длиннее окна укорачивается; полоса не уже 10 знаков и остаётся на месте."""
    line: str = _bar_line(monkeypatch, 30, "Чтение видео 2 из 3: https://youtu.be/dQw4w9WgXcQ", StepCount(2, 3))
    assert line == "Чтение видео 2 из  [====    ]"


def test_the_width_is_the_terminal_window_but_not_wider_than_120(monkeypatch: pytest.MonkeyPatch) -> None:
    console: Console = Console(out=TerminalStream(), err=None)
    monkeypatch.setenv("COLUMNS", "100")
    assert console.width == 100
    monkeypatch.setenv("COLUMNS", "300")
    assert console.width == 120
    assert ConsoleRecord().console.width == 80          # не терминал


def test_a_table_is_printed_at_the_width_of_the_console() -> None:
    record: ConsoleRecord = ConsoleRecord()
    record.console.say_table(ConsoleTable("Файлы", (("  отчёт  logs", "  лог    logs"),)))
    assert record.lines == [" Файлы ".center(80, "="), "  отчёт  logs", "  лог    logs", "=" * 80]
