from __future__ import annotations

import logging

import pytest

from app.texts.source_title import LOGGER, sanitize_source_video_title

# Случаи донора restreamer (app\tests\test_video_title_cleanup.py) — поведение переносится как есть.
DONOR_CASES: list[tuple[str, str]] = [
    ("33 серия: Проверка на прочность  #эксперимент #ии #тест", "33 серия: Проверка на прочность"),
    ("The Most Terrible Title | #12", "The Most Terrible Title | #12"),
    ("Название | #14 #эксперимент #ии", "Название | #14"),
    ("Серия #15. Середина названия. Хвост", "Серия #15. Середина названия. Хвост"),
    ("Название #2026", "Название #2026"),
    ("Название #AI", "Название"),
    ("Название | #эксперимент", "Название"),
    ("Название - #cult #AI", "Название"),
    ("Название — #тег", "Название"),
    ("Название – #тег", "Название"),
    ("A clean title without tags", "A clean title without tags"),
    ("#cult #AI #ии", ""),
    ("Series | #1 #2 #3", "Series | #1 #2 #3"),
    ("Title #abc123", "Title"),
    ("Title #123", "Title #123"),
    ("Title #!", "Title #!"),
    ("Хештег #внутри названия остаётся", "Хештег #внутри названия остаётся"),
    ("  Края обрезаются  ", "Края обрезаются"),
]


@pytest.mark.parametrize(("source", "expected"), DONOR_CASES)
def test_title_is_cleaned_like_the_donor(source: str, expected: str) -> None:
    assert sanitize_source_video_title(source) == expected


@pytest.mark.parametrize("source", ["", "   \t  "])
def test_empty_title_stays_empty(source: str) -> None:
    assert sanitize_source_video_title(source) == ""


def test_the_separator_is_trimmed_only_after_removal() -> None:
    """Висящий разделитель без хвоста хештегов — часть названия: донор его не трогает."""
    assert sanitize_source_video_title("Название |") == "Название |"


class _Collector(logging.Handler):
    """Свой обработчик прямо на логгере livecraft.texts: не зависит от propagate после других тестов."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def test_removal_is_logged_only_at_debug() -> None:
    collector: _Collector = _Collector()
    level: int = LOGGER.level
    LOGGER.setLevel(logging.DEBUG)
    LOGGER.addHandler(collector)
    try:
        sanitize_source_video_title("Название #тег")
        sanitize_source_video_title("Название без хвоста")
    finally:
        LOGGER.removeHandler(collector)
        LOGGER.setLevel(level)
    records: list[logging.LogRecord] = collector.records
    assert len(records) == 1
    assert records[0].levelno == logging.DEBUG
    assert "count=1" in records[0].getMessage()
