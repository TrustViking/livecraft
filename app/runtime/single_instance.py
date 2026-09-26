"""Один экземпляр livecraft на машину: файл-замок `state\\livecraft.lock` (CLAUDE.md §6, инвариант 12).

Зачем: два одновременных запуска создадут по эфиру на один слот. Сверка с YouTube у второго процесса
пройдёт до того, как первый успеет создать эфир, — и оба увидят «эфира нет» (инвариант 1: истина об
эфирах на YouTube, а не в памяти).

Замок берётся в `main.run_cli` **до** настройки логов и снимается **после** их закрытия, поэтому пишет он
только свой журнал `logs\\startup.log`: захват, освобождение, отказ и каждый сбой файловой системы. Логгеров
программы он не зовёт — без настроенных логов их запись ушла бы английской строкой в консоль оператора.
Отметки журнала и время владельца в файле замка — по часам программы (`Clock`), то есть по её поясу.

Захват атомарный: `os.open(..., O_CREAT | O_EXCL | O_WRONLY)` — гонку создания выигрывает ровно один
процесс. Проигравший читает запись владельца и либо уступает (владелец жив), либо снимает застарелый
замок ровно одной повторной попыткой. Проигрыш повтора — отказ, а не перезапись: перезапись вернула бы
ту самую гонку, от которой замок и защищает. В существующий файл замка не пишем никогда.

Живость процесса-владельца: на Windows — `OpenProcess` + `GetExitCodeProcess` через `ctypes` с явными
`argtypes` и `restype` (на 64-битной Windows это обязательно, иначе HANDLE обрезается до 32 бит и
`GetExitCodeProcess` врёт); на остальных системах — `os.kill(pid, 0)`. Новых зависимостей нет.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Final, NoReturn

from app.core.clock import Clock
from app.core.dates import format_datetime_text, format_timestamp
from app.core.errors import os_error_reason
from app.core.system import WINDOWS_PLATFORM
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogEvent
from app.ui import messages_ru as msg

LOCK_FILE_MODE: Final[int] = 0o644
APPEND_MODE: Final[str] = "a"
OWNER_TOKENS: Final[int] = 2          # запись владельца — «<pid> <время запуска>», ровно два токена
UNKNOWN_PID: Final[int] = -1          # владельца опознать не удалось: файл занят, но запись не наша
OWNER_LINE_TEMPLATE: Final[str] = "{pid} {started_at}\n"
STARTUP_LOG_LINE: Final[str] = "{stamp} | pid={pid} | {event}\n"
PROCESS_QUERY_LIMITED_INFORMATION: Final[int] = 0x1000   # право OpenProcess: только спросить о состоянии
STILL_ACTIVE: Final[int] = 259                           # код выхода процесса, который ещё работает


class LockEvent(str, Enum):
    """События замка в журнале startup.log."""

    ACQUIRED = "lock_acquired"
    RELEASED = "lock_released"
    REJECTED = "lock_rejected"
    STALE = "lock_stale"
    UNREADABLE = "lock_unreadable"
    CREATE_DENIED = "lock_create_denied"
    STALE_KEPT = "lock_stale_not_removed"
    RELEASE_FAILED = "lock_release_failed"
    FOREIGN = "lock_foreign_not_released"
    READ_FAILED = "lock_read_failed"


class LockRejection(str, Enum):
    """Почему запуск уступил: владелец замка опознан или нет."""

    OWNER_KNOWN = "owner_known"
    OWNER_UNKNOWN = "owner_unknown"


@dataclass(frozen=True)
class LockOwner:
    """Запись о владельце замка: одна строка файла «<pid> <время запуска>».

    Время — текст как есть: его пишет и читает только эта запись, разбирать его незачем, а показывать
    оператору надо ровно тем, что лежит в файле.
    """

    pid: int
    started_at: str

    @classmethod
    def parse(cls, text: str) -> LockOwner | None:
        """Строка файла → владелец; пусто, мусор, нечисловой pid или неполная запись дают None."""
        parts: list[str] = text.strip().split(maxsplit=1)
        if len(parts) != OWNER_TOKENS:
            return None
        try:
            pid: int = int(parts[0])
        except ValueError:
            return None
        started_at: str = parts[1].strip()
        if not started_at:
            return None
        return cls(pid=pid, started_at=started_at)

    @classmethod
    def unknown(cls) -> LockOwner:
        """Файл замка занят, а чья это запись — неизвестно: уступаем, но назвать владельца не можем."""
        return cls(pid=UNKNOWN_PID, started_at="")

    @property
    def is_known(self) -> bool:
        """Опознанный владелец: есть и номер процесса, и время его запуска."""
        return self.pid > 0 and bool(self.started_at)

    @property
    def is_alive(self) -> bool:
        """Жив ли процесс-владелец. Мёртвый владелец — застарелый замок, его можно снять."""
        if self.pid <= 0:
            return False
        if sys.platform == WINDOWS_PLATFORM:
            return self._is_alive_on_windows()
        try:
            os.kill(self.pid, 0)
        except ProcessLookupError:
            return False
        except PermissionError:
            return True       # процесс есть, но сигнал ему не наш — считаем живым
        except OSError:
            return False
        return True

    def render(self) -> str:
        """Содержимое файла замка: ровно одна строка."""
        return OWNER_LINE_TEMPLATE.format(pid=self.pid, started_at=self.started_at)

    def _is_alive_on_windows(self) -> bool:
        """ctypes напрямую: argtypes и restype заданы явно — иначе на Win64 HANDLE теряет старшие 32 бита."""
        import ctypes
        from ctypes import wintypes

        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, self.pid)
        if not handle:
            return False
        try:
            exit_code: wintypes.DWORD = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == STILL_ACTIVE
        finally:
            kernel32.CloseHandle(handle)


class AnotherInstanceRunning(RuntimeError):
    """Замок держит другой процесс: запуск уступает. `str(error)` — русская строка оператору (контракт ошибок)."""

    def __init__(self, owner: LockOwner) -> None:
        self.owner: LockOwner = owner
        self.reason: LockRejection = LockRejection.OWNER_KNOWN if owner.is_known else LockRejection.OWNER_UNKNOWN
        super().__init__(self.human)

    @property
    def human(self) -> str:
        """Называем владельца, если его удалось опознать."""
        if self.reason is LockRejection.OWNER_UNKNOWN:
            return msg.LOCK_REJECTED_UNKNOWN_OWNER
        return msg.LOCK_REJECTED.format(pid=self.owner.pid, started_at=self.owner.started_at)

    @property
    def event(self) -> LogEvent:
        return LogEvent.of(LockEvent.REJECTED, owner_pid=self.owner.pid)

    @property
    def log_line(self) -> str:
        return self.event.text


@dataclass(frozen=True)
class InstanceLock:
    """Замок одного экземпляра: сам себя берёт, сам снимает и сам пишет свой след в startup.log.

    `pid` — отдельное поле, а не `os.getpid()` по месту: так объект можно построить от имени другого
    процесса — это нужно и тестам, и чтению застарелого замка. `clock` — часы программы.
    """

    path: Path
    startup_log: Path
    clock: Clock
    pid: int = field(default_factory=os.getpid)

    def acquire(self) -> None:
        """Инвариант 12: одна попытка O_EXCL; живой чужой владелец — отказ; застарелый — unlink и ровно
        одна повторная попытка; проигрыш повтора — тоже отказ (fail-closed), а не перезапись."""
        if self._create_exclusively():
            self._note(LogEvent.of(LockEvent.ACQUIRED))
            return
        owner: LockOwner | None = LockOwner.parse(self._read())
        if owner is not None:
            if owner.pid == self.pid:
                self._note(LogEvent.of(LockEvent.ACQUIRED))       # свой же замок: перезахват тем же процессом
                return
            if owner.is_alive:
                self._reject(owner)
            self._note(LogEvent.of(LockEvent.STALE, owner_pid=owner.pid))
        else:
            self._note(LogEvent.of(LockEvent.UNREADABLE))   # нечитаемую запись инвариант 12 велит снимать как застарелую
        self._discard_stale()
        if not self._create_exclusively():
            self._reject(LockOwner.parse(self._read()) or LockOwner.unknown())
        self._note(LogEvent.of(LockEvent.ACQUIRED))

    def release(self) -> None:
        """Снимает только свой замок: чужой не трогает, отсутствующий не ищет."""
        owner: LockOwner | None = LockOwner.parse(self._read())
        if owner is None:
            return
        if owner.pid != self.pid:
            self._note(LogEvent.of(LockEvent.FOREIGN, owner_pid=owner.pid))
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            self._note(LogEvent.of(LockEvent.RELEASE_FAILED, error=os_error_reason(error)))
            return
        self._note(LogEvent.of(LockEvent.RELEASED))

    def _reject(self, owner: LockOwner) -> NoReturn:
        """Уступить владельцу: след в startup.log и исключение — решение о выводе и коде принимает main."""
        rejection: AnotherInstanceRunning = AnotherInstanceRunning(owner)
        self._note(rejection.event)
        raise rejection

    def _create_exclusively(self) -> bool:
        """Ровно одна атомарная попытка: True — файл создан нами, False — путь замка занят.

        PermissionError — тоже «занят»: так Windows отвечает, когда именем замка занята папка или файл
        держит другой процесс. Ответ «не создали» ведёт к отказу запуска (fail-closed), а не к перезаписи;
        сама причина уходит в startup.log, иначе её негде было бы увидеть. Нет папки под замок
        (FileNotFoundError) — это уже не занятость, а сломанное окружение: ошибка идёт наружу.
        """
        owner: LockOwner = LockOwner(pid=self.pid, started_at=format_datetime_text(self.clock.now()))
        try:
            handle: int = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, LOCK_FILE_MODE)
        except FileExistsError:
            return False
        except PermissionError as error:
            self._note(LogEvent.of(LockEvent.CREATE_DENIED, error=os_error_reason(error)))
            return False
        try:
            os.write(handle, owner.render().encode(TEXT_ENCODING))
        finally:
            os.close(handle)
        return True

    def _discard_stale(self) -> None:
        """Снять застарелый замок. Не снялся — не беда: повторная попытка создания сама решит исход."""
        try:
            self.path.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            self._note(LogEvent.of(LockEvent.STALE_KEPT, error=os_error_reason(error)))

    def _read(self) -> str:
        """Содержимое файла замка; нет файла или не читается — пустая строка (владелец неопознан)."""
        try:
            return self.path.read_text(encoding=TEXT_ENCODING)
        except FileNotFoundError:
            return ""
        except OSError as error:
            self._note(LogEvent.of(LockEvent.READ_FAILED, error=os_error_reason(error)))
            return ""

    def _note(self, event: LogEvent) -> None:
        """Событие в logs\\startup.log с отметкой до секунды и путём замка.

        Журнал не пишется (нет прав, диск полон) — событие теряется, а замок работает дальше: сообщить о
        сбое журнала некуда, логов программы в этот момент нет, а отказ запуска из-за журнала хуже потери строки.
        """
        line: str = STARTUP_LOG_LINE.format(
            stamp=format_timestamp(self.clock.now()), pid=self.pid, event=event.extended(path=self.path).text
        )
        try:
            with self.startup_log.open(APPEND_MODE, encoding=TEXT_ENCODING) as stream:
                stream.write(line)
        except OSError:
            return
