from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from app.paths import LivecraftPaths
from app.runtime.single_instance import (
    EVENT_ACQUIRED,
    EVENT_REJECTED,
    EVENT_RELEASED,
    UNKNOWN_PID,
    AnotherInstanceRunning,
    InstanceLock,
    LockOwner,
)

STARTED_AT: str = "20-09-2026 15:30"


@pytest.fixture
def lock(livecraft_paths: LivecraftPaths) -> InstanceLock:
    """Замок в корне из tmp_path: папки state\\ и logs\\ создал ensure_dirs, как в боевом запуске."""
    return InstanceLock(path=livecraft_paths.lock_file, startup_log=livecraft_paths.startup_log_file)


@pytest.fixture
def dead_pid() -> int:
    """Честный номер мёртвого процесса: запускаем python с пустой командой и дожидаемся его конца."""
    child: subprocess.Popen[bytes] = subprocess.Popen([sys.executable, "-c", ""])
    child.wait()
    return child.pid


@pytest.fixture
def live_foreign_process() -> Iterator[subprocess.Popen[bytes]]:
    """Живой посторонний процесс: его номером заняты замки в проверках «чужой владелец жив»."""
    child: subprocess.Popen[bytes] = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield child
    finally:
        child.kill()
        child.wait()


def _lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _owner_of(lock: InstanceLock) -> LockOwner:
    """Владелец, записанный в файле замка; записи нет — тест падает здесь, а не строкой ниже."""
    owner: LockOwner | None = LockOwner.parse(lock.path.read_text(encoding="utf-8"))
    assert owner is not None, lock.path.read_text(encoding="utf-8")
    return owner


# --- LockOwner: запись о владельце


def test_owner_round_trip() -> None:
    owner: LockOwner = LockOwner(pid=4321, started_at=STARTED_AT)
    assert owner.render() == f"4321 {STARTED_AT}\n"
    assert LockOwner.parse(owner.render()) == owner


def test_owner_parse_keeps_the_time_as_written() -> None:
    """Время в файле не разбирается: показываем оператору ровно то, что там лежит."""
    assert LockOwner.parse("4321 2026-09-20T12:00:00") == LockOwner(pid=4321, started_at="2026-09-20T12:00:00")


@pytest.mark.parametrize(
    "text",
    ["", "   ", "\n", "мусор", "abc 20-09-2026 15:30", "12.5 20-09-2026", "4321", "4321   ", "-"],
)
def test_owner_parse_refuses_anything_but_a_full_record(text: str) -> None:
    """Пусто, мусор, нечисловой pid и неполная запись — владелец не опознан (инвариант 12: нечитаемая запись)."""
    assert LockOwner.parse(text) is None


def test_own_process_is_alive() -> None:
    assert LockOwner(pid=os.getpid(), started_at=STARTED_AT).is_alive


def test_finished_process_is_not_alive(dead_pid: int) -> None:
    assert not LockOwner(pid=dead_pid, started_at=STARTED_AT).is_alive


@pytest.mark.parametrize("pid", [0, -1, UNKNOWN_PID])
def test_a_process_number_that_cannot_exist_is_not_alive(pid: int) -> None:
    assert not LockOwner(pid=pid, started_at=STARTED_AT).is_alive


def test_unknown_owner_is_not_known() -> None:
    assert not LockOwner.unknown().is_known
    assert LockOwner(pid=4321, started_at=STARTED_AT).is_known
    assert not LockOwner(pid=4321, started_at="").is_known


# --- InstanceLock: захват


def test_acquire_writes_one_line_with_our_process_number(lock: InstanceLock) -> None:
    lock.acquire()
    assert len(_lines(lock.path)) == 1
    owner: LockOwner = _owner_of(lock)
    assert owner.pid == os.getpid() and owner.is_alive
    assert lock.path.read_text(encoding="utf-8") == owner.render()


def test_a_live_foreign_owner_is_not_pushed_out(
    lock: InstanceLock,
    live_foreign_process: subprocess.Popen[bytes],
) -> None:
    """Живой чужой замок — отказ с этим владельцем, файл остаётся его (инвариант 12)."""
    foreign: InstanceLock = InstanceLock(
        path=lock.path, startup_log=lock.startup_log, pid=live_foreign_process.pid
    )
    foreign.acquire()
    before: bytes = lock.path.read_bytes()
    with pytest.raises(AnotherInstanceRunning) as raised:
        lock.acquire()
    assert raised.value.owner.pid == live_foreign_process.pid
    assert raised.value.owner.is_known
    assert lock.path.read_bytes() == before


def test_the_same_process_may_take_its_own_lock_again(lock: InstanceLock) -> None:
    lock.acquire()
    before: bytes = lock.path.read_bytes()
    lock.acquire()
    assert lock.path.read_bytes() == before      # в существующий файл замка не пишем никогда


def test_a_stale_lock_of_a_dead_owner_is_taken_over(lock: InstanceLock, dead_pid: int) -> None:
    """Мёртвый владелец — застарелый замок: снимается и перезаписывается одной повторной попыткой."""
    stale: InstanceLock = InstanceLock(path=lock.path, startup_log=lock.startup_log, pid=dead_pid)
    stale.acquire()
    assert _owner_of(lock).pid == dead_pid and not _owner_of(lock).is_alive
    lock.acquire()
    assert len(_lines(lock.path)) == 1 and _owner_of(lock).pid == os.getpid()


def test_an_unreadable_record_is_treated_as_stale(lock: InstanceLock) -> None:
    """Файл есть, а записи владельца в нём нет: инвариант 12 велит снимать такой замок."""
    lock.path.write_text("мусор без номера процесса\n", encoding="utf-8")
    lock.acquire()
    owner: LockOwner | None = LockOwner.parse(lock.path.read_text(encoding="utf-8"))
    assert owner is not None and owner.pid == os.getpid() and len(_lines(lock.path)) == 1


def test_losing_the_single_retry_is_a_refusal_not_an_overwrite(
    lock: InstanceLock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Застарелый замок не снялся (его тут же занял другой процесс) — уступаем, а не пишем поверх."""
    lock.path.write_text("мусор без номера процесса\n", encoding="utf-8")
    before: bytes = lock.path.read_bytes()
    monkeypatch.setattr(Path, "unlink", lambda self, missing_ok=False: None)
    with pytest.raises(AnotherInstanceRunning) as raised:
        lock.acquire()
    assert raised.value.owner == LockOwner.unknown()
    assert lock.path.read_bytes() == before


def test_a_lock_that_cannot_be_removed_is_a_refusal(lock: InstanceLock) -> None:
    """Путь замка занят папкой: прочитать нельзя, снять нельзя, создать нельзя — fail-closed."""
    lock.path.mkdir()
    with pytest.raises(AnotherInstanceRunning) as raised:
        lock.acquire()
    assert not raised.value.owner.is_known
    assert lock.path.is_dir()


# --- InstanceLock: освобождение


def test_release_removes_our_own_lock(lock: InstanceLock) -> None:
    lock.acquire()
    lock.release()
    assert not lock.path.exists()


def test_release_does_not_touch_a_foreign_lock(
    lock: InstanceLock,
    live_foreign_process: subprocess.Popen[bytes],
) -> None:
    foreign: InstanceLock = InstanceLock(
        path=lock.path, startup_log=lock.startup_log, pid=live_foreign_process.pid
    )
    foreign.acquire()
    lock.release()
    assert lock.path.is_file()
    assert _owner_of(lock).pid == live_foreign_process.pid


def test_release_without_a_lock_is_quiet(lock: InstanceLock) -> None:
    lock.release()
    assert not lock.path.exists()


def test_release_after_release_is_quiet(lock: InstanceLock) -> None:
    lock.acquire()
    lock.release()
    lock.release()
    assert not lock.path.exists()


# --- след в logs\startup.log: на момент захвата логи ещё не настроены


def test_startup_log_gets_the_acquire_and_release_events(lock: InstanceLock) -> None:
    lock.acquire()
    lock.release()
    text: str = lock.startup_log.read_text(encoding="utf-8")
    assert f"{EVENT_ACQUIRED} path={lock.path}" in text
    assert f"{EVENT_RELEASED} path={lock.path}" in text
    assert f"pid={os.getpid()}" in text


def test_startup_log_gets_the_rejection(
    lock: InstanceLock,
    live_foreign_process: subprocess.Popen[bytes],
) -> None:
    InstanceLock(path=lock.path, startup_log=lock.startup_log, pid=live_foreign_process.pid).acquire()
    with pytest.raises(AnotherInstanceRunning):
        lock.acquire()
    assert EVENT_REJECTED in lock.startup_log.read_text(encoding="utf-8")


def test_startup_log_line_carries_a_readable_stamp(lock: InstanceLock) -> None:
    """Формат события машинный, но отметка времени — DD-MM-YYYY HH:MM, как во всех файлах (инвариант 4)."""
    lock.acquire()
    [line] = _lines(lock.startup_log)
    stamp, pid_part, event_part = (part.strip() for part in line.split("|", maxsplit=2))
    assert len(stamp.split()) == 2 and stamp.count("-") == 2 and ":" in stamp
    assert pid_part == f"pid={os.getpid()}"
    assert event_part.startswith(EVENT_ACQUIRED)
