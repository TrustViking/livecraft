"""Чистка старья по keep_days (CLAUDE.md §3 шаг 12; перенос planers\\app\\core\\retention.py).

Единственное место, где программа удаляет свои файлы. Срок один на все роли — `keep_days` из настроек, «сейчас» —
часы программы (её пояс). Роли:

- логи (logs\\) — как в planers: файлы самой папки, изменённые раньше срока; вложенное не трогается; текущий лог и
  startup.log под срок не попадают — их пишет каждый запуск;
- пакеты (папка пакетов) — только пакеты программы `plan_<с>_<по>_gen<дата>-<время>.bcast`, у которых последняя дата
  эфиров (<по>) раньше срока: пакет с будущими эфирами не устаревает, сколько бы дней ему ни было;
- превью (папка превью) — папки дат, которые программа создаёт по шаблону `image_dir_template` ({date} — целой частью
  пути; дата — DD-MM-YYYY), дата раньше срока — папка целиком;
- копии документов (папка копий) — папки дат `<DD-MM-YYYY>`, дата раньше срока — папка целиком.

Чужие файлы и папки (имя не по правилу программы) и сами папки ролей, выбранные человеком (раздел folders), не
удаляются никогда. Не удалилось (файл занят) — строка лога, файл остаётся. Строка лога по каждой роли — всегда (удалено,
оставлено своего); итог — `RetentionResult`: строка «Запуск», когда удалено хоть что-то. Пробный запуск и служебные
режимы сюда не приходят: чистку зовёт только полный запуск по линиям (app\\main.py).
"""
from __future__ import annotations

import logging
import shutil
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from pathlib import Path, PureWindowsPath
from typing import Final

from app.core.clock import Clock
from app.core.dates import DATE_FORMAT
from app.core.errors import os_error_reason
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import DataDir, LivecraftPaths
from app.ui.messages import msg

LOGGER = get_logger(LogArea.RUNTIME)


class RetentionRole(str, Enum):
    """Роль папки, которую чистит программа. Значение — имя роли в логе."""

    LOGS = "logs"
    PACKAGES = "packages"
    PREVIEWS = "previews"
    DOC_COPIES = "doc_copies"


class RetentionEvent(str, Enum):
    """События чистки в логе."""

    SWEPT = "retention_swept"
    REMOVED = "retention_removed"
    REMOVE_FAILED = "retention_remove_failed"


class OwnName(str, Enum):
    """Части имён, по которым программа узнаёт свои пакеты и папки превью."""

    PACKAGE_PREFIX = "plan"
    PACKAGE_SUFFIX = ".bcast"
    PACKAGE_SEPARATOR = "_"
    DATE_PART = "{date}"             # подстановка даты шаблона папки превью
    LANGUAGE_PART = "{language}"     # подстановка языка шаблона папки превью
    ANY = "*"                        # любое имя в шаблоне поиска
    PATH_SEPARATOR = "/"


# Части имени пакета: plan, первая дата, последняя дата, отметка сборки.
PACKAGE_NAME_PARTS: Final[int] = 4
PACKAGE_LAST_DAY_PART: Final[int] = 2
PACKAGE_PATTERN: Final[str] = (
    OwnName.PACKAGE_PREFIX.value + OwnName.PACKAGE_SEPARATOR.value + OwnName.ANY.value + OwnName.PACKAGE_SUFFIX.value
)
# Правило своего имени роли: дата в имени; не по правилу — None (чужое).
DayRule = Callable[[Path], date | None]


@dataclass(frozen=True)
class RoleSweep:
    """Итог чистки одной роли: сколько своего удалено и сколько своего осталось (моложе срока или не удалилось)."""

    role: RetentionRole
    removed: int
    kept: int

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(RetentionEvent.SWEPT, role=self.role, removed=self.removed, kept=self.kept)


@dataclass(frozen=True)
class RetentionResult:
    """Итог чистки всех ролей и срок, по которому она шла."""

    keep_days: int
    sweeps: tuple[RoleSweep, ...]

    @property
    def removed(self) -> int:
        return sum(sweep.removed for sweep in self.sweeps)

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Строка «Запуск», только когда удалено хоть что-то."""
        if not self.removed:
            return ()
        return (msg.RETENTION_REMOVED.format(days=self.keep_days, count=self.removed),)


@dataclass(frozen=True)
class Retention:
    """Чистка папок ролей этой установки (`paths` — с папками из настроек) по сроку `keep_days`; шаблон папки превью
    `image_template` говорит, где в папке превью стоят папки дат; «сейчас» — часы программы."""

    paths: LivecraftPaths
    keep_days: int
    image_template: str
    clock: Clock

    @property
    def border(self) -> datetime:
        """Момент, раньше которого своё — старьё."""
        return self.clock.now() - timedelta(days=self.keep_days)

    def sweep(self) -> RetentionResult:
        """Каждая роль: старое своё удаляется, строка лога роли — всегда."""
        owned: dict[RetentionRole, dict[Path, bool]] = {
            RetentionRole.LOGS: self._logs(),
            RetentionRole.PACKAGES: self._dated(self.paths.bcast_dir.glob(PACKAGE_PATTERN), self._package_day),
            RetentionRole.PREVIEWS: self._dated(self._preview_folders(), self._folder_day),
            RetentionRole.DOC_COPIES: self._dated(self.paths.dir(DataDir.DOCS).iterdir(), self._folder_day),
        }
        sweeps: tuple[RoleSweep, ...] = tuple(self._swept(role, items) for role, items in owned.items())
        for sweep in sweeps:
            sweep.event.emit(LOGGER)
        return RetentionResult(keep_days=self.keep_days, sweeps=sweeps)

    def _logs(self) -> dict[Path, bool]:
        """Логи — как в planers: все файлы самой папки; старьё — изменённые раньше срока."""
        files: list[Path] = [path for path in sorted(self.paths.logs_dir.iterdir()) if path.is_file()]
        return {path: datetime.fromtimestamp(path.stat().st_mtime, tz=self.clock.zone) < self.border for path in files}

    def _dated(self, entries: Iterable[Path], day_of: DayRule) -> dict[Path, bool]:
        """Своё по правилу имени `day_of` (дата в имени; не по правилу — чужое, не берётся); старьё — дата раньше
        срока."""
        border_day: date = self.border.date()
        days: dict[Path, date | None] = {path: day_of(path) for path in sorted(entries)}
        return {path: day < border_day for path, day in days.items() if day is not None}

    def _package_day(self, path: Path) -> date | None:
        """Последняя дата эфиров пакета из имени plan_<с>_<по>_gen…; имя не по правилу — None."""
        parts: list[str] = path.stem.split(OwnName.PACKAGE_SEPARATOR.value)
        if not path.is_file() or len(parts) != PACKAGE_NAME_PARTS or parts[0] != OwnName.PACKAGE_PREFIX.value:
            return None
        return self._day_in(parts[PACKAGE_LAST_DAY_PART])

    def _preview_folders(self) -> list[Path]:
        """Папки на месте {date} шаблона папки превью; {date} — не целая часть пути: своих папок дат не узнать."""
        parts: tuple[str, ...] = PureWindowsPath(self.image_template).parts
        if OwnName.DATE_PART.value not in parts:
            return []
        parents: list[str] = [part.replace(OwnName.LANGUAGE_PART.value, OwnName.ANY.value) for part in parts]
        pattern: str = OwnName.PATH_SEPARATOR.value.join(
            [*parents[: parts.index(OwnName.DATE_PART.value)], OwnName.ANY.value]
        )
        return list(self.paths.dir(DataDir.IMAGE).glob(pattern))

    def _folder_day(self, path: Path) -> date | None:
        """Дата папки даты <DD-MM-YYYY>; не папка или имя не дата — None."""
        return self._day_in(path.name) if path.is_dir() else None

    def _day_in(self, text: str) -> date | None:
        """Дата DD-MM-YYYY (как в slot_id и именах файлов); не дата — None."""
        try:
            return datetime.strptime(text, DATE_FORMAT).date()
        except ValueError:
            return None

    def _swept(self, role: RetentionRole, owned: dict[Path, bool]) -> RoleSweep:
        """Удалить старьё роли; не удалилось — остаётся."""
        removed: int = sum(1 for path, is_old in owned.items() if is_old and self._removed(path))
        return RoleSweep(role=role, removed=removed, kept=len(owned) - removed)

    def _removed(self, path: Path) -> bool:
        """Папка — целиком, файл — сам; сбой — строка лога и False."""
        try:
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
        except OSError as error:
            failed: LogEvent = LogEvent.of(RetentionEvent.REMOVE_FAILED, path=path, reason=os_error_reason(error))
            failed.emit(LOGGER, logging.WARNING)
            return False
        LogEvent.of(RetentionEvent.REMOVED, path=path).emit(LOGGER)
        return True
