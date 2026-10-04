"""Блок «Какой должна быть таблица» в окне настройщика (CLAUDE.md §8.2 п.2, §14 решение 26).

Проверка идёт в фоновом потоке; тест ждёт её итог, прокручивая события окна (`SetupWindowDriver.wait_for_table_check`).
К Google тесты не ходят: таблицу читает подделка. Непредвиденная ошибка потока уходит в лог запуска так, как в
программе: через `threading.excepthook`, который ставит `Launch.run`.
"""
from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from tkinter import ttk

import pytest

from app.core.text_format import NEWLINE
from app.main import Launch, LaunchEvent
from app.observability.logging_setup import RunLog
from app.paths import LivecraftPaths
from app.run.flag import CliFlag
from app.run.request import RunRequest
from app.secretsafe.field import SecretField
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.setup.tabs.check_line import RowState
from app.sheets.plan import PlanColumn, SheetPlan
from app.tests.conftest import FIXED_NOW, TOKEN_VALUES
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.setup_window import SetupWindowDriver
from app.tests.fixtures.sheets import OPERATOR_EMAIL, PLAN_SHEET, FakeSheetsReader
from app.ui import messages_ru as msg

OWN_SHEET_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table"
VALUES: list[list[str]] = [
    ["Ссылка", "Дата", "Время"],
    ["https://youtu.be/dQw4w9WgXcQ", "28.09.2026", "19:00"],
]
VERDICT: str = msg.SETUP_TABLE_OK_NEAREST.format(
    sheet=PLAN_SHEET, link="A", date="B", time="C", count=1, nearest="28.09.2026 19:00"
)
WAIT_SEC: float = 10.0
CRASH_TEXT: str = "reader broke unexpectedly"


@pytest.fixture
def driver(ready_paths: LivecraftPaths, pytestconfig: pytest.Config) -> Iterator[SetupWindowDriver]:
    yield from SetupWindowDriver.opened(ready_paths, pytestconfig)


class _WaitingReader(FakeSheetsReader):
    """Первый вход через браузер, который «ждёт человека»: чтение идёт, только когда тест отпустит `released`."""

    def __init__(self) -> None:
        super().__init__(values=VALUES, announce_login=True)
        self.released: threading.Event = threading.Event()

    def read_plan(self, vault: Vault) -> SheetPlan:
        assert self.released.wait(WAIT_SEC)
        return super().read_plan(vault)


class _BrokenReader(FakeSheetsReader):
    """Читатель, который падает ошибкой, не предусмотренной моделью проверки."""

    def read_plan(self, vault: Vault) -> SheetPlan:
        raise RuntimeError(CRASH_TEXT)


def _pump_until(driver: SetupWindowDriver, done: Callable[[], bool]) -> None:
    for _ in range(int(WAIT_SEC * 100)):
        if done():
            return
        driver.window.root.update()
        threading.Event().wait(0.01)
    raise AssertionError("окно не дождалось")


def test_the_tab_shows_the_sample_and_the_rules_with_the_timezone(driver: SetupWindowDriver) -> None:
    texts: list[str] = driver.visible_texts()
    assert msg.SETUP_TABLE_TITLE in texts and msg.SETUP_TABLE_TEXT_BEFORE in texts
    for column in PlanColumn:
        assert column.human in texts and msg.SETUP_TABLE_SAMPLE_ROW[column.value] in texts
    assert msg.SETUP_TABLE_TEXT_AFTER.format(timezone="Europe/Kyiv") in texts
    assert msg.SETUP_TABLE_BUTTON_CHECK in texts


def test_the_google_tab_has_no_range_row(driver: SetupWindowDriver) -> None:
    assert tuple(driver.tabs.plan.rows) == (SecretField.SHEETS_ID,)
    assert not any("B:H" in text for text in driver.visible_texts())


def test_the_window_opens_without_checking_the_table(driver: SetupWindowDriver) -> None:
    reader: FakeSheetsReader = FakeSheetsReader(values=VALUES)
    driver.read_table(reader)
    driver.window.root.update()
    assert driver.table.result_text == "" and not driver.table.is_running
    assert reader.vaults == []


def test_saving_the_table_link_checks_the_table_and_shows_the_verdict(driver: SetupWindowDriver) -> None:
    reader: FakeSheetsReader = FakeSheetsReader(values=VALUES)
    driver.read_table(reader, StoppedClock.at(FIXED_NOW))
    driver.accept_key(SecretField.SHEETS_ID, OWN_SHEET_ID)
    assert driver.table.is_running
    driver.wait_for_table_check()
    assert driver.table.result_text == VERDICT
    assert len(reader.vaults) == 1
    own: SecretValue | None = reader.vaults[0].get(SecretField.SHEETS_ID)
    assert own is not None and own.reveal() == OWN_SHEET_ID
    assert str(driver.table.button.cget("state")) == "normal"


def test_saving_another_field_does_not_check_the_table(driver: SetupWindowDriver) -> None:
    reader: FakeSheetsReader = FakeSheetsReader(values=VALUES)
    driver.read_table(reader)
    driver.accept_key(SecretField.OPENAI_API_KEY, "sk-proj-own-Zy9xWvUtSrQpOnMlKjIhGfEdCbA9876543210")
    assert not driver.table.is_running and reader.vaults == []


def test_the_button_checks_and_is_disabled_until_the_verdict_with_the_browser_line_meanwhile(
    driver: SetupWindowDriver,
) -> None:
    reader: _WaitingReader = _WaitingReader()
    driver.read_table(reader, StoppedClock.at(FIXED_NOW))
    button: ttk.Button = driver.table.button
    button.invoke()
    assert str(button.cget("state")) == "disabled"
    _pump_until(driver, lambda: driver.table.result_text == msg.SETUP_TABLE_LOGIN)
    button.invoke()                                              # недоступна: второй проверки нет
    reader.released.set()
    driver.wait_for_table_check()
    logged_in: str = msg.OPERATOR_LOGGED_IN.format(account=OPERATOR_EMAIL)
    assert driver.table.result_text == NEWLINE.join((logged_in, VERDICT))     # каким аккаунтом вошли — в итоге
    assert [row.state for row in driver.table.line.shown] == [RowState.NOTE, RowState.OK]
    assert reader.login_announced == 1 and len(reader.vaults) == 1


def test_a_failed_check_is_a_red_line_without_vault_values(driver: SetupWindowDriver) -> None:
    driver.read_table(FakeSheetsReader(values=[["Ссылка", "Время"]]))
    driver.table.button.invoke()
    driver.wait_for_table_check()
    text: str = driver.table.result_text
    assert text.startswith("✗ ") and "«Ссылка», «Время»" in text
    for value in TOKEN_VALUES.values():
        assert value not in text


def test_a_new_timezone_in_the_settings_changes_the_rules(driver: SetupWindowDriver) -> None:
    driver.table.show_rules("Europe/Warsaw")
    assert msg.SETUP_TABLE_TEXT_AFTER.format(timezone="Europe/Warsaw") in driver.visible_texts()


def test_an_unexpected_error_ends_the_check_and_the_launch_logs_the_traceback(
    driver: SetupWindowDriver, ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Итог «проверка прервалась», кнопка снова доступна, трассировка — в логе запуска, а не в пустоте."""
    log: RunLog = RunLog.open(ready_paths.logs_dir, debug=False, started=FIXED_NOW)
    launch: Launch = Launch(RunRequest.from_argv([CliFlag.SETUP.value]), ready_paths, ConsoleRecord().console, log)
    monkeypatch.setattr(threading, "excepthook", launch.log_thread_crash)
    driver.read_table(_BrokenReader(values=VALUES))
    try:
        driver.table.button.invoke()
        driver.wait_for_table_check()
        _pump_until(driver, lambda: CRASH_TEXT in log.path.read_text(encoding="utf-8"))
    finally:
        log.close()
    assert driver.table.result_text == msg.SETUP_TABLE_FAILED.format(problem=msg.SETUP_TABLE_INTERRUPTED)
    assert str(driver.table.button.cget("state")) == "normal"
    logged: str = log.path.read_text(encoding="utf-8")
    assert f"{LaunchEvent.THREAD_CRASHED.value} error=RuntimeError" in logged
    assert "Traceback" in logged and f"RuntimeError: {CRASH_TEXT}" in logged
