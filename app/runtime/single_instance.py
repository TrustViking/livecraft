"""Один экземпляр livecraft на машину: файл-замок `state\\livecraft.lock` (CLAUDE.md §6, инвариант 12).

Зачем: два одновременных запуска создадут по эфиру на один слот. Сверка с YouTube у второго процесса
пройдёт до того, как первый успеет создать эфир, — и оба увидят «эфира нет» (инвариант 1: истина об
эфирах на YouTube, а не в памяти).

Замок берётся в `main.run_cli` **до** настройки логов, поэтому единственный надёжный след событий —
`logs\\startup.log`: записи `lock_acquired`, `lock_released`, `lock_rejected` пишет сам объект-замок.
Записи в LOGGER на момент захвата и освобождения обработчиков ещё (уже) не имеют — они остаются на
случай, когда замок держит живой пайплайн, и потому не поднимаются выше INFO: WARNING без настроенных
логов ушёл бы английской строкой в консоль оператора через `logging.lastResort`.

Захват атомарный: `os.open(..., O_CREAT | O_EXCL | O_WRONLY)` — гонку создания выигрывает ровно один
процесс. Проигравший читает запись владельца и либо уступает (владелец жив), либо снимает застарелый
замок ровно одной повторной попыткой. Проигрыш повтора — отказ, а не перезапись: перезапись вернула бы
ту самую гонку, от которой замок и защищает. В существующий файл замка не пишем никогда.

Живость процесса-владельца: на Windows — `OpenProcess` + `GetExitCodeProcess` через `ctypes` с явными
`argtypes` и `restype` (на 64-битной Windows это обязательно, иначе HANDLE обрезается до 32 бит и
`GetExitCodeProcess` врёт); на остальных системах — `os.kill(pid, 0)`. Поведение перенесено из
`restreamer\\app\\runtime\\single_instance.py` без упрощений. Новых зависимостей нет: ни psutil, ни pywin32.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Final, NoReturn

from app.core.dates import format_datetime_text
from app.observability.logging_setup import get_logger

LOGGER = get_logger("runtime")

LOCK_ENCODING: Final[str] = "utf-8"
LOCK_FILE_MODE: Final[int] = 0o644
OWNER_TOKENS: Final[int] = 2          # запись владельца — «<pid> <время запуска>», ровно два токена
UNKNOWN_PID: Final[int] = -1          # владельца опознать не удалось: файл занят, но запись не наша

EVENT_ACQUIRED: Final[str] = "lock_acquired"
EVENT_RELEASED: Final[str] = "lock_released"
EVENT_REJECTED: Final[str] = "lock_rejected"
EVENT_STALE: Final[str] = "lock_stale"
EVENT_CREATE_DENIED: Final[str] = "lock_create_denied"
EVENT_STALE_KEPT: Final[str] = "lock_stale_not_removed"
EVENT_RELEASE_FAILED: Final[str] = "lock_release_failed"
EVENT_FOREIGN: Final[str] = "lock_foreign_not_released"
EVENT_UNREADABLE: Final[str] = "lock_unreadable"
STARTUP_LOG_LINE: Final[str] = "{stamp} | pid={pid} | {event} path={path}\n"


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
        if sys.platform == "win32":
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
        return f"{self.pid} {self.started_at}\n"

    def _is_alive_on_windows(self) -> bool:
        """ctypes напрямую: argtypes и restype заданы явно — иначе на Win64 HANDLE теряет старшие 32 бита."""
        import ctypes
        from ctypes import wintypes

        process_query_limited_information: int = 0x1000
        still_active: int = 259
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
        kernel32.GetExitCodeProcess.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        handle = kernel32.OpenProcess(process_query_limited_information, False, self.pid)
        if not handle:
            return False
        try:
            exit_code: wintypes.DWORD = wintypes.DWORD()
            if not kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return False
            return exit_code.value == still_active
        finally:
            kernel32.CloseHandle(handle)


class AnotherInstanceRunning(RuntimeError):
    """Замок держит другой процесс. Русскую строку оператору печатает main, здесь — след для лога."""

    def __init__(self, owner: LockOwner) -> None:
        super().__init__(
            f"another livecraft instance holds the lock (pid={owner.pid}, started_at={owner.started_at!r})"
        )
        self.owner: LockOwner = owner


@dataclass(frozen=True)
class InstanceLock:
    """Замок одного экземпляра: сам себя берёт, сам снимает и сам пишет свой след в startup.log.

    `pid` — отдельное поле, а не `os.getpid()` по месту: так объект можно построить от имени другого
    процесса — это нужно и тестам, и чтению застарелого замка.
    """

    path: Path
    startup_log: Path
    pid: int = field(default_factory=os.getpid)

    def acquire(self) -> None:
        """Инвариант 12: одна попытка O_EXCL; живой чужой владелец — отказ; застарелый — unlink и ровно
        одна повторная попытка; проигрыш повтора — тоже отказ (fail-closed), а не перезапись."""
        if self._create_exclusively():
            self._note(EVENT_ACQUIRED)
            LOGGER.info("lock_acquired pid=%d path=%s", self.pid, self.path)
            return
        owner: LockOwner | None = LockOwner.parse(self._read())
        if owner is not None:
            if owner.pid == self.pid:
                self._note(EVENT_ACQUIRED)       # свой же замок: перезахват тем же процессом
                return
            if owner.is_alive:
                self._reject(owner)
            self._note(f"{EVENT_STALE} owner_pid={owner.pid}")
        else:
            self._note(EVENT_UNREADABLE)         # запись нечитаема — инвариант 12 велит снимать как застарелую
        self._discard_stale()
        if not self._create_exclusively():
            self._reject(LockOwner.parse(self._read()) or LockOwner.unknown())
        self._note(EVENT_ACQUIRED)
        LOGGER.info("lock_acquired pid=%d path=%s stale=1", self.pid, self.path)

    def release(self) -> None:
        """Снимает только свой замок: чужой не трогает, отсутствующий не ищет."""
        owner: LockOwner | None = LockOwner.parse(self._read())
        if owner is None:
            return
        if owner.pid != self.pid:
            self._note(f"{EVENT_FOREIGN} owner_pid={owner.pid}")
            LOGGER.warning("lock_foreign_not_released owner_pid=%d pid=%d", owner.pid, self.pid)
            return
        try:
            self.path.unlink()
        except FileNotFoundError:
            return
        except OSError as error:
            self._note(f"{EVENT_RELEASE_FAILED} error={error.strerror}")
            LOGGER.warning("lock_release_failed path=%s error=%s", self.path, error)
            return
        self._note(EVENT_RELEASED)
        LOGGER.info("lock_released pid=%d path=%s", self.pid, self.path)

    def _reject(self, owner: LockOwner) -> NoReturn:
        """Уступить владельцу: след в startup.log и исключение — решение о выводе и коде принимает main."""
        self._note(f"{EVENT_REJECTED} owner_pid={owner.pid}")
        raise AnotherInstanceRunning(owner)

    def _create_exclusively(self) -> bool:
        """Ровно одна атомарная попытка: True — файл создан нами, False — путь замка занят.

        PermissionError — тоже «занят»: так Windows отвечает, когда именем замка занята папка или файл
        держит другой процесс. Ответ «не создали» ведёт к отказу запуска (fail-closed), а не к перезаписи;
        сама причина уходит в startup.log, иначе её негде было бы увидеть. Нет папки под замок
        (FileNotFoundError) — это уже не занятость, а сломанное окружение: ошибка идёт наружу.
        """
        owner: LockOwner = LockOwner(pid=self.pid, started_at=format_datetime_text(datetime.now().astimezone()))
        try:
            handle: int = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, LOCK_FILE_MODE)
        except FileExistsError:
            return False
        except PermissionError as error:
            self._note(f"{EVENT_CREATE_DENIED} error={error.strerror}")
            LOGGER.warning("lock_create_denied path=%s error=%s", self.path, error)
            return False
        try:
            os.write(handle, owner.render().encode(LOCK_ENCODING))
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
            self._note(f"{EVENT_STALE_KEPT} error={error.strerror}")
            LOGGER.warning("lock_stale_not_removed path=%s error=%s", self.path, error)

    def _read(self) -> str:
        """Содержимое файла замка; нет файла или не читается — пустая строка (владелец неопознан)."""
        try:
            return self.path.read_text(encoding=LOCK_ENCODING)
        except FileNotFoundError:
            return ""
        except OSError as error:
            LOGGER.warning("lock_read_failed path=%s error=%s", self.path, error)
            return ""

    def _note(self, event: str) -> None:
        """Событие в logs\\startup.log: на момент захвата и освобождения обработчиков логов нет."""
        line: str = STARTUP_LOG_LINE.format(
            stamp=format_datetime_text(datetime.now().astimezone()),
            pid=self.pid,
            event=event,
            path=self.path,
        )
        try:
            with self.startup_log.open("a", encoding=LOCK_ENCODING) as stream:
                stream.write(line)
        except OSError as error:
            LOGGER.warning("startup_log_write_failed path=%s error=%s", self.startup_log, error)
