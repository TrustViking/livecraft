"""Строки хода таблицы и вывода (app\\run\\progress.py, CLAUDE.md §13 задача 9.5): строка на каждый долгий шаг — сразу
на консоль оператора; без консоли прогресс молчит."""
from __future__ import annotations

from app.run.progress import SILENT_PROGRESS, StageProgress, StepCount
from app.tests.fixtures.console import ConsoleRecord

LINK: str = "https://youtu.be/dQw4w9WgXcQ"
PACKAGE_NAME: str = "plan_17-03-2027_18-03-2027_gen.bcast"
OPERATOR_LINE: str = "Вход в Google: operator@example.com"


def _every_step(progress: StageProgress) -> None:
    progress.video_started(StepCount(2, 15), LINK)
    progress.drive_copy_started(StepCount(3, 13))
    progress.merge_started(StepCount(1, 6), "17.03.2027", "19:00", "uk")
    progress.doc_started(StepCount(1, 4), "17.03.2027")
    progress.announce_started(StepCount(4, 4), "20.03.2027")
    progress.package_send_started(PACKAGE_NAME)
    progress.sheets_retry(StepCount(2, 4))
    progress.operator_note(OPERATOR_LINE)


def test_every_step_is_one_line_that_says_what_goes_and_which_of_how_many() -> None:
    record: ConsoleRecord = ConsoleRecord()
    _every_step(StageProgress(record.console))
    assert record.lines == [
        f"Чтение видео 2 из 15: {LINK}",
        "Копия превью на Google Диск: 3 из 13.",
        "Нейросеть: слот 1 из 6 — 17.03.2027 19:00 uk.",
        "Создание документа объявлений 1 из 4: 17.03.2027.",
        "Отправка объявлений в Telegram 4 из 4: 20.03.2027.",
        f"Отправка пакета в Telegram: {PACKAGE_NAME}.",
        "Google не ответил — повтор 2 из 4.",
        OPERATOR_LINE,
    ]
    assert record.error_lines == []


def test_a_line_is_on_the_console_before_the_next_step_is_called() -> None:
    """Строка уходит сразу, а не пачкой: после каждого шага на консоли ровно на строку больше."""
    record: ConsoleRecord = ConsoleRecord()
    progress: StageProgress = StageProgress(record.console)
    progress.video_started(StepCount(1, 2), LINK)
    assert len(record.lines) == 1
    progress.video_started(StepCount(2, 2), LINK)
    assert len(record.lines) == 2


def test_without_a_console_the_progress_is_silent() -> None:
    _every_step(StageProgress())
    _every_step(SILENT_PROGRESS)
    assert SILENT_PROGRESS.console is None and StageProgress() == SILENT_PROGRESS
