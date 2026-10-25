from __future__ import annotations

import logging
from pathlib import Path

import pytest

from app.observability.log_event import LogArea, get_logger
from app.paths import ROOT_ENV_VAR, DataDir, LivecraftPaths
from app.run.exit_code import ExitCode
from app.tests.fixtures.console import ConsoleRecord
from app.tools.probe import ProbeConsole, ProbeLauncher, ProbeSession
from app.ui import messages_ru as msg


def test_a_refusal_names_the_problem_then_the_action_and_is_code_2() -> None:
    record: ConsoleRecord = ConsoleRecord()
    code: int = ProbeConsole(record.console).refuse("сейф не прочитан")
    assert code == ExitCode.CONFIG == 2
    assert record.lines == ["сейф не прочитан", msg.SETUP_REQUIRED]


def test_the_probe_console_prints_lines_in_order() -> None:
    record: ConsoleRecord = ConsoleRecord()
    console: ProbeConsole = ProbeConsole(record.console)
    console.say("заголовок")
    console.say_lines(("один", "два"))
    assert record.lines == ["заголовок", "один", "два"]


def test_the_launcher_gives_the_probe_a_ready_root_and_a_log_for_the_run(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Корень — из LIVECRAFT_ROOT, папки созданы, лог открыт на время пробника и закрыт после; код — код пробника."""
    root: Path = tmp_path / "root"
    monkeypatch.setenv(ROOT_ENV_VAR, str(root))
    record: ConsoleRecord = ConsoleRecord()
    sessions: list[ProbeSession] = []

    def probe(session: ProbeSession) -> int:
        sessions.append(session)
        get_logger(LogArea.SHEETS_PROBE).info("probe_ran")
        session.console.say("пробник работает")
        return int(ExitCode.NO_FUTURE_SLOTS)

    assert ProbeLauncher(console=ProbeConsole(record.console)).run(probe) == ExitCode.NO_FUTURE_SLOTS
    (session,) = sessions
    assert session.paths == LivecraftPaths(root.resolve())
    assert all(session.paths.dir(folder).is_dir() for folder in DataDir)
    assert session.log.path.parent == session.paths.logs_dir
    assert "probe_ran" in session.log.path.read_text(encoding="utf-8")
    assert not any(handler in logging.getLogger().handlers for handler in session.log.handlers)
    assert session.started.utcoffset() is not None
    assert record.lines == ["пробник работает"]


def test_the_log_is_closed_even_when_the_probe_fails(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(ROOT_ENV_VAR, str(tmp_path / "root"))
    sessions: list[ProbeSession] = []

    def probe(session: ProbeSession) -> int:
        sessions.append(session)
        raise OSError("disk full")

    with pytest.raises(OSError):
        ProbeLauncher(console=ProbeConsole(ConsoleRecord().console)).run(probe)
    assert not any(handler in logging.getLogger().handlers for handler in sessions[0].log.handlers)
