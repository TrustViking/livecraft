"""Копия документа объявлений в формате Word: <папка копий>\\<DD-MM-YYYY>\\<имя файла>.docx (CLAUDE.md §14 решения 33,
37).

Когда идёт линия «Копия документа», после каждого документа даты программа выгружает его с Диска
(`DriveClient.export_word`) и кладёт копию в папку даты внутри папки копий из настроек: оператор открывает документ без
браузера. Имя файла — из имени документа: пробелы — «_», знаки,
которых нет в именах файлов Windows, и управляющие — «_», «_» вместе с соседними «-» и «_» — один «_», по краям — без
«._-»; двоеточие времени убирается («15:24» → «1524»). Основа имени — не длиннее, чем у превью.

Итог — значение: сохранённая копия (`DocCopySaved`) или отказ (`DocCopyFailure`) с причиной для человека — отказ Диска
или сбой записи файла. Отказ копии — не сбой документа: документы следующих дат создаются, а часть «документ
объявлений» кончается кодом 1.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.core.errors import os_error_reason
from app.core.text_format import WHITESPACE_RUN_PATTERN
from app.google.drive import DriveCall, DriveClient, DriveError
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import AtomicFile, LivecraftPaths
from app.sources.preview_name import MAX_STEM_CHARS, REPEATED_SEPARATOR_PATTERN, NameMark
from app.ui.messages import msg

LOGGER = get_logger(LogArea.PUBLISH)

WORD_FILE_EXTENSION: Final[str] = ".docx"
# Двоеточие между цифрами — время создания в имени документа («15:24»): убирается, а не меняется на «_».
TIME_COLON_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?<=\d):(?=\d)")
# Знаки, которых нет в именах файлов Windows, и управляющие — подряд одним «_».
UNSAFE_CHARS_PATTERN: Final[re.Pattern[str]] = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
# «_» с соседними «-» и «_» слева или справа: «стримы_-_Everyday» → «стримы_Everyday».
SEPARATOR_LEFT_PATTERN: Final[re.Pattern[str]] = re.compile(r"_(?:[-_]+)")
SEPARATOR_RIGHT_PATTERN: Final[re.Pattern[str]] = re.compile(r"(?:[-_]+)_")
EDGE_JUNK_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\W+|\W+$")


class CopyName(str, Enum):
    """Основа имени копии, когда от имени документа ничего не осталось."""

    FALLBACK = "document"


class CopyProblem(str, Enum):
    """Почему копия не сохранилась, если Диск ни при чём."""

    FILE_WRITE = "file_write"       # файл в docs\\ не записался


class CopyEvent(str, Enum):
    """События копии документа в логе."""

    FAILED = "doc_copy_failed"


@dataclass(frozen=True)
class DocCopySaved:
    """Сохранённая копия: путь файла и он же относительно корня программы — для людей."""

    path: Path
    shown: str

    @property
    def console_part(self) -> str:
        return msg.DOC_COPY_SAVED.format(path=self.shown)

    def extend(self, event: LogEvent) -> LogEvent:
        return event.extended(copy=self.shown)


@dataclass(frozen=True)
class DocCopyFailure:
    """Копия не сохранилась: дата, причина для людей и для лога, обращение к Диску, код ответа, имя исключения."""

    date: str
    human: str
    reason: Enum                    # DriveReason или CopyProblem
    call: DriveCall | None = None   # обращение к Диску; сбой записи файла — None
    status: int | None = None
    error: str | None = None        # имя исключения записи файла

    @classmethod
    def of_drive(cls, date: str, error: DriveError) -> DocCopyFailure:
        return cls(date=date, human=error.human, reason=error.reason, call=error.call, status=error.status)

    @classmethod
    def of_file(cls, date: str, error: OSError) -> DocCopyFailure:
        human: str = msg.DOC_COPY_WRITE_FAILED.format(reason=os_error_reason(error))
        return cls(date=date, human=human, reason=CopyProblem.FILE_WRITE, error=type(error).__name__)

    @property
    def console_part(self) -> str:
        return msg.DOC_COPY_NOT_SAVED.format(reason=self.human)

    @property
    def event(self) -> LogEvent:
        """Строка `doc_copy_failed`: дата, причина, обращение, код ответа — без текста ошибки."""
        failed: LogEvent = LogEvent.of(CopyEvent.FAILED, date=self.date, reason=self.reason, call=self.call)
        return failed.extended(status=self.status, error=self.error)

    def extend(self, event: LogEvent) -> LogEvent:
        return event.extended(copy_failed=self.reason)


@dataclass(frozen=True)
class DocCopy:
    """Копия документа даты: дата DD-MM-YYYY (папка копии) и имя документа (имя файла)."""

    date: str
    name: str

    @property
    def file_name(self) -> str:
        return self.stem + WORD_FILE_EXTENSION

    @property
    def stem(self) -> str:
        """Основа имени файла из имени документа по правилу выше; не длиннее MAX_STEM_CHARS."""
        separator: str = NameMark.SEPARATOR.value
        text: str = WHITESPACE_RUN_PATTERN.sub(separator, self.name.strip())
        text = UNSAFE_CHARS_PATTERN.sub(separator, TIME_COLON_PATTERN.sub("", text))
        text = SEPARATOR_RIGHT_PATTERN.sub(separator, SEPARATOR_LEFT_PATTERN.sub(separator, text))
        text = EDGE_JUNK_PATTERN.sub("", REPEATED_SEPARATOR_PATTERN.sub(separator, text))
        edges: str = NameMark.EDGES.value
        return text.strip(edges)[:MAX_STEM_CHARS].rstrip(edges) or CopyName.FALLBACK.value

    def save(self, drive: DriveClient, file_id: str, paths: LivecraftPaths) -> DocCopySaved | DocCopyFailure:
        """Выгрузить документ в формате Word и записать файл целиком в папку даты; отказ — значением и строкой лога."""
        try:
            data: bytes = drive.export_word(file_id)
        except DriveError as error:
            return self._failed(DocCopyFailure.of_drive(self.date, error))
        path: Path = paths.doc_copy_file(self.date, self.file_name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            AtomicFile.at(path).write(lambda target: target.write_bytes(data))
        except OSError as error:
            return self._failed(DocCopyFailure.of_file(self.date, error))
        return DocCopySaved(path=path, shown=paths.shown(path))

    def _failed(self, failure: DocCopyFailure) -> DocCopyFailure:
        failure.event.emit(LOGGER, logging.WARNING)
        return failure
