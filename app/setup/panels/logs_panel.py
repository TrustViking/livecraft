"""Вкладка «Логи» без окна: «Сохранить архив логов» (CLAUDE.md §8.2 п.11, §14 решения 20, 46, 62).

Одно действие — `run`: архив папки логов (`LogArchive`: новые файлы первыми, до 45 МБ, без прежних архивов) с
`diagnostics.txt` (`Diagnostics`, значений сейфа нет) под именем `livecraft_logs_<DD-MM-YYYY_HHMMSS>.zip` по поясу
программы ложится в саму папку logs\\ — там его найти, как и остальные логи (старые архивы чистит срок хранения, как
весь logs\\). Отправляет архив человек сам, кому нужно: бота и чата поддержки нет (§14 решение 62). Итог — строками со
знаками для строки проверки окна и путь архива (`LogsVerdict`): по нему окно открывает папку с выделенным архивом.
Архив не записался — строка с причиной ОС, пути нет. Лог — область `setup`, без значений: сколько файлов и байтов,
путь архива, причина отказа.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path

from app.config.files import SettingsFile
from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.core.dates import FILE_STAMP_FORMAT
from app.core.errors import os_error_reason
from app.core.text_format import NEWLINE
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.paths import AtomicFile, DataDir, LivecraftPaths
from app.runtime.log_archive import LOG_ARCHIVE_LIMIT_BYTES, LOG_ARCHIVE_LIMIT_MEGABYTES, LogArchive, PackedLogs
from app.setup.diagnostics import Diagnostics
from app.setup.readiness import Readiness
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SETUP)


class LogsEvent(str, Enum):
    """События вкладки «Логи» в логе."""

    SAVED = "logs_saved"
    NOT_SAVED = "logs_not_saved"


@dataclass(frozen=True)
class LogsVerdict:
    """Итог «Сохранить архив логов»: удалось ли, строки для окна и путь архива (не записался — None)."""

    is_ok: bool
    lines: tuple[str, ...]
    archive: Path | None = None

    @classmethod
    def problem(cls, text: str) -> LogsVerdict:
        """Не удалось: причина словами — строкой со знаком «✗»."""
        return cls(is_ok=False, lines=(msg.CHECK_PROBLEM_LINE.format(line=text),))

    @property
    def text(self) -> str:
        return NEWLINE.join(self.lines)


@dataclass(frozen=True)
class LogsPanel:
    """Вкладка «Логи»: установка `paths` и часы `clock` (момент архива — по поясу программы из livecraft.json)."""

    paths: LivecraftPaths
    clock: Clock

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> LogsPanel:
        return cls(paths=paths, clock=Clock.utc())

    def run(self) -> LogsVerdict:
        """Архив логов с diagnostics.txt — в logs\\; итог — строки и путь архива. OSError чтения логов — наружу."""
        settings: LivecraftSettings = SettingsFile.of(self.paths).latest
        moment: datetime = self.clock.now().astimezone(settings.zone)
        diagnostics: str = Diagnostics(Readiness.check(self.paths), moment).text
        folder: Path = self.paths.dir(DataDir.LOGS)
        packed: PackedLogs = LogArchive(folder, LOG_ARCHIVE_LIMIT_BYTES).pack(
            diagnostics, moment.strftime(FILE_STAMP_FORMAT)
        )
        return self._saved(packed, folder / packed.name)

    def _saved(self, packed: PackedLogs, target: Path) -> LogsVerdict:
        """Архив — в logs\\ целиком или никак; не записался — строка с причиной ОС."""
        try:
            AtomicFile.at(target).write(lambda path: path.write_bytes(packed.data))
        except OSError as error:
            LogEvent.of(LogsEvent.NOT_SAVED, path=Quoted(str(target)), error=Quoted(str(error))).emit(
                LOGGER, logging.WARNING
            )
            return LogsVerdict.problem(msg.SETUP_LOGS_NOT_SAVED.format(reason=os_error_reason(error)))
        LogEvent.of(LogsEvent.SAVED, path=Quoted(str(target)), files=packed.files, bytes=packed.size).emit(LOGGER)
        saved_line: str = msg.SETUP_LOGS_SAVED.format(
            path=self.paths.shown(target), files=packed.files, megabytes=packed.megabytes
        )
        lines: tuple[str, ...] = (msg.CHECK_OK_LINE.format(line=saved_line), *self._skipped(packed))
        return LogsVerdict(is_ok=True, lines=lines, archive=target)

    def _skipped(self, packed: PackedLogs) -> tuple[str, ...]:
        """Старые файлы за пределом архива — строкой справки; все вошли — ничего."""
        if not packed.skipped:
            return ()
        return (msg.SETUP_LOGS_SKIPPED.format(count=packed.skipped, limit=LOG_ARCHIVE_LIMIT_MEGABYTES),)
