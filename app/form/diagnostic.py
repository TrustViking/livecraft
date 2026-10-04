"""Страница формы в logs\\ для разбора: форма не прочиталась или не подтвердила запись ответа (CLAUDE.md §6).

Имя — `{отметка}_form_{вид}_{хеш ссылки}.html`: отметка по часам программы, хеш — первые 8 hex sha1 ссылки на форму
(ссылка не секрет, но имя файла короче). Страница отказа повторяет введённые ответы, а logs\\ уходят в архив
«Отправить логи» (§14 решение 20): ключ потока в теле до записи заменяется маской (инвариант 6).
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.core.clock import Clock
from app.core.dates import FILE_STAMP_FORMAT
from app.core.text_format import TEXT_ENCODING
from app.form.failure import FormEvent
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.observability.logging_setup import mask_stream_key
from app.paths import write_text_atomically

LOGGER = get_logger(LogArea.FORM)

DIAGNOSTIC_TEMPLATE: Final[str] = "{stamp}_form_{kind}_{digest}.html"
URL_HASH_CHARS: Final[int] = 8


class DiagnosticKind(str, Enum):
    """Какая страница сохранена: страница формы или страница ответа."""

    PAGE = "page"
    RESPONSE = "response"


@dataclass(frozen=True)
class DiagnosticPage:
    """Что сохранить: вид страницы, ссылка на форму, текст страницы и ключ потока, который в ней не должен остаться."""

    kind: DiagnosticKind
    form_url: str
    body: str
    stream_key: str | None = None

    @property
    def masked_body(self) -> str:
        """Текст страницы, где ключ потока заменён маской."""
        if not self.stream_key:
            return self.body
        return self.body.replace(self.stream_key, mask_stream_key(self.stream_key))

    @property
    def digest(self) -> str:
        return hashlib.sha1(self.form_url.encode(TEXT_ENCODING)).hexdigest()[:URL_HASH_CHARS]


@dataclass(frozen=True)
class FormDiagnostic:
    """Папка logs\\ и часы программы: куда и под какой отметкой сохранять страницы формы."""

    logs_dir: Path
    clock: Clock

    def save(self, page: DiagnosticPage) -> Path | None:
        """Путь сохранённой страницы; не записалась — строка в лог и None: разбор не главнее запуска."""
        stamp: str = self.clock.now().strftime(FILE_STAMP_FORMAT)
        path: Path = self.logs_dir / DIAGNOSTIC_TEMPLATE.format(stamp=stamp, kind=page.kind.value, digest=page.digest)
        try:
            self.logs_dir.mkdir(parents=True, exist_ok=True)
            write_text_atomically(path, page.masked_body, TEXT_ENCODING)
        except OSError as error:
            not_saved: LogEvent = LogEvent.of(FormEvent.DIAGNOSTIC_NOT_SAVED, path=path, error=type(error).__name__)
            not_saved.emit(LOGGER, logging.WARNING)
            return None
        LogEvent.of(FormEvent.DIAGNOSTIC_SAVED, path=path).emit(LOGGER)
        return path
