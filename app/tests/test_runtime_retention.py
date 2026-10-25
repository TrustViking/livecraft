"""Чистка старья по keep_days (app\\runtime\\retention.py, CLAUDE.md §3 шаг 12): старое своё удаляется, новое своё и
чужое остаются, сами папки ролей — всегда; строка лога по роли — всегда, строка «Запуск» — только при удалении.

Корень — временный, часы программы остановлены на 29.09.2026 12:00 по Киеву, срок — 30 дней: старьё — раньше 30.08.2026.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from app.observability.log_event import LogArea
from app.paths import DataDir, LivecraftPaths
from app.runtime.retention import Retention, RetentionResult
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

NOW: datetime = datetime(2026, 9, 29, 12, 0, tzinfo=ZoneInfo("Europe/Kyiv"))
KEEP_DAYS: int = 30
TEMPLATE: str = "{date}/{language}"
OLD_PACKAGE: str = "plan_01-08-2026_02-08-2026_gen01-08-2026-1200.bcast"
FUTURE_PACKAGE: str = "plan_01-08-2026_17-03-2027_gen01-08-2026-1200.bcast"


def _file(path: Path, age_days: int = 0) -> Path:
    """Файл с временем изменения `age_days` дней назад от «сейчас» теста."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x", encoding="utf-8")
    moment: float = (NOW - timedelta(days=age_days)).timestamp()
    os.utime(path, (moment, moment))
    return path


def _sweep(paths: LivecraftPaths, template: str = TEMPLATE) -> RetentionResult:
    return Retention(paths, KEEP_DAYS, template, StoppedClock.at(NOW)).sweep()


def test_old_logs_go_new_logs_and_nested_stay(livecraft_paths: LivecraftPaths) -> None:
    """Логи — как в planers: файлы самой папки по времени изменения; вложенное не трогается."""
    logs: Path = livecraft_paths.logs_dir
    old: Path = _file(logs / "01-08-2026_120000_livecraft.log", age_days=40)
    fresh: Path = _file(logs / "28-09-2026_120000_livecraft.log", age_days=1)
    nested: Path = _file(logs / "archive" / "old.log", age_days=400)
    result: RetentionResult = _sweep(livecraft_paths)
    assert not old.exists() and fresh.exists() and nested.exists()
    assert result.removed == 1


def test_packages_go_by_their_last_stream_date(livecraft_paths: LivecraftPaths) -> None:
    """Пакет с прошедшими эфирами — старьё; с будущими — нет, сколько бы дней ему ни было; чужое остаётся."""
    folder: Path = livecraft_paths.bcast_dir
    old: Path = _file(folder / OLD_PACKAGE)
    future: Path = _file(folder / FUTURE_PACKAGE, age_days=400)
    foreign: tuple[Path, ...] = (
        _file(folder / "notes.txt", age_days=400),
        _file(folder / "plan_old.bcast", age_days=400),
        _file(folder / "draft_01-08-2026_02-08-2026_gen01-08-2026-1200.bcast", age_days=400),
    )
    _sweep(livecraft_paths)
    assert not old.exists() and future.exists()
    assert all(path.exists() for path in foreign)
    assert folder.is_dir()


def test_preview_date_folders_go_whole(livecraft_paths: LivecraftPaths) -> None:
    images: Path = livecraft_paths.dir(DataDir.IMAGE)
    old: Path = _file(images / "01-08-2026" / "uk" / "1_UK_Title.jpg")
    fresh: Path = _file(images / "28-09-2026" / "uk" / "1_UK_Title.jpg", age_days=400)
    foreign: Path = _file(images / "my photos" / "01-08-2026.jpg", age_days=400)
    loose: Path = _file(images / "01-08-2026.jpg", age_days=400)
    _sweep(livecraft_paths)
    assert not old.parent.parent.exists()
    assert fresh.exists() and foreign.exists() and loose.exists() and images.is_dir()


def test_preview_date_folders_are_found_where_the_template_puts_them(livecraft_paths: LivecraftPaths) -> None:
    images: Path = livecraft_paths.dir(DataDir.IMAGE)
    old: Path = _file(images / "preview" / "01-08-2026" / "uk" / "a.jpg")
    elsewhere: Path = _file(images / "01-08-2026" / "uk" / "a.jpg")
    _sweep(livecraft_paths, "preview/{date}/{language}")
    assert not old.exists() and elsewhere.exists()
    by_language: Path = _file(images / "en" / "01-08-2026" / "a.jpg")
    _sweep(livecraft_paths, "{language}\\{date}")
    assert not by_language.exists()


def test_a_template_with_the_date_inside_a_name_cleans_no_previews(livecraft_paths: LivecraftPaths) -> None:
    """{date} не целой частью пути: своих папок дат не узнать — превью не трогаются."""
    folder: Path = _file(livecraft_paths.dir(DataDir.IMAGE) / "day_01-08-2026" / "uk" / "a.jpg")
    _sweep(livecraft_paths, "day_{date}/{language}")
    assert folder.exists()


def test_doc_copy_date_folders_go_whole(livecraft_paths: LivecraftPaths) -> None:
    docs: Path = livecraft_paths.dir(DataDir.DOCS)
    old: Path = _file(docs / "01-08-2026" / "01-08-2026_Ежедневные стримы - Everyday streams_1524.docx")
    fresh: Path = _file(docs / "29-09-2026" / "a.docx", age_days=400)
    foreign: Path = _file(docs / "archive" / "a.docx", age_days=400)
    _sweep(livecraft_paths)
    assert not old.parent.exists() and fresh.exists() and foreign.exists() and docs.is_dir()


def test_the_border_is_keep_days_back_from_now(livecraft_paths: LivecraftPaths) -> None:
    """30.08.2026 — ровно срок: остаётся; 29.08.2026 — раньше срока: удаляется."""
    docs: Path = livecraft_paths.dir(DataDir.DOCS)
    kept: Path = _file(docs / "30-08-2026" / "a.docx")
    gone: Path = _file(docs / "29-08-2026" / "a.docx")
    _sweep(livecraft_paths)
    assert kept.exists() and not gone.exists()


def test_every_role_logs_a_line_and_the_launch_line_comes_only_with_removal(livecraft_paths: LivecraftPaths) -> None:
    with LogCapture.on(LogArea.RUNTIME) as capture:
        quiet: RetentionResult = _sweep(livecraft_paths)
    assert quiet.console_lines == ()
    assert capture.messages(logging.INFO) == [
        f"retention_swept role={role} removed=0 kept=0" for role in ("logs", "packages", "previews", "doc_copies")
    ]
    _file(livecraft_paths.bcast_dir / OLD_PACKAGE)
    _file(livecraft_paths.dir(DataDir.DOCS) / "01-08-2026" / "a.docx")
    _file(livecraft_paths.dir(DataDir.DOCS) / "28-09-2026" / "a.docx")
    result: RetentionResult = _sweep(livecraft_paths)
    assert result.console_lines == (msg.RETENTION_REMOVED.format(days=KEEP_DAYS, count=2),)
    assert [sweep.kept for sweep in result.sweeps] == [0, 0, 0, 1]


def test_a_file_that_cannot_be_removed_stays_with_a_log_line(livecraft_paths: LivecraftPaths) -> None:
    """Файл занят (открыт) — остаётся, строка лога с причиной; остальное чистится."""
    busy: Path = _file(livecraft_paths.logs_dir / "busy.log", age_days=40)
    gone: Path = _file(livecraft_paths.logs_dir / "gone.log", age_days=40)
    with busy.open(encoding="utf-8"), LogCapture.on(LogArea.RUNTIME) as capture:
        result: RetentionResult = _sweep(livecraft_paths)
    assert busy.exists() and not gone.exists()
    assert result.removed == 1 and result.sweeps[0].kept == 1
    assert any(line.startswith("retention_remove_failed") for line in capture.messages(logging.WARNING))
