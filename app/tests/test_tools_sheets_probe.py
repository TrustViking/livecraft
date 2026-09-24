from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest

from app.google.auth import GoogleLogin
from app.paths import LivecraftPaths, ROOT_ENV_VAR
from app.secretsafe.value import SecretField
from app.secretsafe.vault import Vault
from app.sheets.client import SheetsReader, SheetsReadError, SheetsReadReason
from app.sheets.plan import SheetPlan
from app.sheets.rows import RowSkipReason
from app.tests.conftest import FIXED_NOW, REPO_SETTINGS_FILE, SUPPLIED_VALUES
from app.tools import sheets_probe
from app.tools.sheets_probe import ProbeExit, SheetsProbe
from app.ui import messages_ru as msg

LINK: str = "https://youtu.be/dQw4w9WgXcQ"
OTHER_LINK: str = "https://www.youtube.com/watch?v=aB3_-xYz012"
VALUES: list[list[str]] = [
    ["№", "Ссылка на видео", "Дата", "Время"],
    ["1", LINK, "16.10.2026", "19:00"],
    ["2", OTHER_LINK, "17.10.2026", "20:00"],
    ["3", LINK, "01.09.2026", "19:00"],
    ["4", "", "16.10.2026", "19:00"],
    ["5", LINK, "16.10.2026", "19:00"],
]


class _FakeReader:
    """Читатель без сети: отдаёт план из заданных значений или падает заданной ошибкой."""

    def __init__(self, values: list[list[str]] | None = None, error: SheetsReadError | None = None) -> None:
        self.values: list[list[str]] | None = values
        self.error: SheetsReadError | None = error
        self.vaults: list[Vault] = []

    def read_plan(self, vault: Vault) -> SheetPlan:
        self.vaults.append(vault)
        if self.error is not None:
            raise self.error
        return SheetPlan.from_values(self.values or [])


def patch_open(monkeypatch: pytest.MonkeyPatch, reader: _FakeReader) -> list[GoogleLogin]:
    logins: list[GoogleLogin] = []

    def _open(cls: Any, login: GoogleLogin, allow_login: bool = True, on_login: Any = None) -> _FakeReader:
        logins.append(login)
        return reader

    monkeypatch.setattr(SheetsReader, "open", classmethod(_open))
    return logins


def run_probe(paths: LivecraftPaths, now: datetime = FIXED_NOW) -> tuple[int, list[str]]:
    lines: list[str] = []
    code: int = SheetsProbe(paths=paths, now=now, say=lines.append).run()
    return code, lines


def assert_no_vault_values(lines: list[str]) -> None:
    text: str = "\n".join(lines)
    for value in SUPPLIED_VALUES.values():
        assert value not in text


def test_probe_prints_columns_and_counters_only(
    ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    reader: _FakeReader = _FakeReader(values=VALUES)
    logins: list[GoogleLogin] = patch_open(monkeypatch, reader)
    code, lines = run_probe(ready_paths)
    assert code == ProbeExit.OK == 0
    assert logins == [GoogleLogin.operator(ready_paths)]
    assert reader.vaults[0].get(SecretField.SHEETS_ID) is not None
    assert lines[0] == msg.SHEETS_PROBE_TITLE
    assert msg.SHEETS_PROBE_COLUMNS.format(
        link=msg.SHEETS_PROBE_COLUMN.format(name="Ссылка на видео", number=2),
        date=msg.SHEETS_PROBE_COLUMN.format(name="Дата", number=3),
        time=msg.SHEETS_PROBE_COLUMN.format(name="Время", number=4),
    ) in lines
    assert msg.SHEETS_PROBE_ROWS.format(rows=5, admitted=2, skipped=3) in lines
    for reason in (RowSkipReason.IN_PAST, RowSkipReason.EMPTY_LINK, RowSkipReason.DUPLICATE):
        assert msg.SHEETS_PROBE_SKIP_LINE.format(reason=reason.human, count=1) in lines
    assert_no_vault_values(lines)
    assert not any(LINK in line or "aB3_-xYz012" in line for line in lines)


def test_probe_prints_the_plan_problem(ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    patch_open(monkeypatch, _FakeReader(values=[["Links", "Time"]]))
    code, lines = run_probe(ready_paths)
    assert code == ProbeExit.OK
    assert lines[1:] == [SheetPlan.from_values([["Links", "Time"]]).problem]


def test_probe_without_vault_is_code_2_and_does_not_open_google(
    livecraft_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    livecraft_paths.config_file.write_bytes(REPO_SETTINGS_FILE.read_bytes())
    logins: list[GoogleLogin] = patch_open(monkeypatch, _FakeReader(values=VALUES))
    code, lines = run_probe(livecraft_paths)
    assert code == ProbeExit.CONFIG == 2
    assert logins == []
    assert lines[-1] == msg.SETUP_REQUIRED
    assert SecretField.SHEETS_ID.human_label in "\n".join(lines)


def test_probe_without_settings_is_code_2(ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    ready_paths.config_file.unlink()
    logins: list[GoogleLogin] = patch_open(monkeypatch, _FakeReader(values=VALUES))
    code, lines = run_probe(ready_paths)
    assert code == ProbeExit.CONFIG
    assert logins == []
    assert lines[-1] == msg.SETUP_REQUIRED


def test_probe_read_error_is_code_1(ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch) -> None:
    error: SheetsReadError = SheetsReadError(SheetsReadReason.NO_ACCESS, "sheets-plan(abcd)", status=403)
    patch_open(monkeypatch, _FakeReader(error=error))
    code, lines = run_probe(ready_paths)
    assert code == ProbeExit.ERRORS == 1
    assert lines[-1] == error.human
    assert_no_vault_values(lines)


def test_probe_main_runs_on_the_root_from_the_environment(
    ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ROOT_ENV_VAR, str(ready_paths.root))
    patch_open(monkeypatch, _FakeReader(values=VALUES))
    assert sheets_probe.main() == ProbeExit.OK
    out: str = capsys.readouterr().out
    assert msg.SHEETS_PROBE_TITLE in out
    assert_no_vault_values([out])
    log_text: str = "\n".join(path.read_text(encoding="utf-8") for path in ready_paths.logs_dir.glob("*_livecraft.log"))
    assert_no_vault_values([log_text])
