"""Перехват строк лога одной области за время теста (CLAUDE.md §11: логгер — только через LogArea)."""
from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager

from app.observability.log_event import LogArea, get_logger


class LogCapture(logging.Handler):
    """Свой обработчик прямо на логгере области: не зависит от propagate и обработчиков после других тестов."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    @classmethod
    @contextmanager
    def on(cls, area: LogArea, level: int = logging.DEBUG) -> Iterator[LogCapture]:
        """Записи логгера области от `level` за время блока; после блока логгер — как был."""
        logger: logging.Logger = get_logger(area)
        capture: LogCapture = cls()
        previous: int = logger.level
        logger.setLevel(level)
        logger.addHandler(capture)
        try:
            yield capture
        finally:
            logger.removeHandler(capture)
            logger.setLevel(previous)

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self, level: int | None = None) -> list[str]:
        return [record.getMessage() for record in self.records if level is None or record.levelno == level]
