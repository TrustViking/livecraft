"""Образец и проверка таблицы плана на вкладке «Таблица плана» без окна (CLAUDE.md §8.2 п.2, §14 решение 26)."""
from __future__ import annotations

from types import ModuleType
from zoneinfo import ZoneInfo

import pytest

from app.core.sheet_text import SheetCell
from app.google.auth import GoogleLogin
from app.paths import LivecraftPaths
from app.secretsafe.field import SecretField
from app.secretsafe.store import VaultStore
from app.secretsafe.vault import Vault
from app.setup.panels import table_check
from app.setup.panels.table_check import TableCheck, TableSample, TableVerdict
from app.sheets.client import SheetsReadError, SheetsReadReason
from app.sheets.plan import PlanColumn, PlanProblem, SheetColumns, SheetHeader, SheetPlan
from app.sheets.preview import LANGUAGE_HEADER, PREVIEW_HEADER, OutputColumn, SheetOutput
from app.sheets.rows import PlannedRows
from app.tests.conftest import FIXED_NOW, TOKEN_VALUES, write_token_vault
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.operator import SHEET_TITLE, FakeOperatorGoogle
from app.tests.fixtures.sheets import OPERATOR_EMAIL, PLAN_SHEET, FakeSheetsReader
from app.ui import messages_ru as msg
from app.ui.messages import CATALOGS

HEADER: list[str] = ["№", "Заметки", "Ссылка", "Дата", "Время"]
LINK: str = "https://youtu.be/dQw4w9WgXcQ"
OTHER_LINK: str = "https://youtu.be/aB3_-xYz012"
CLOCK: StoppedClock = StoppedClock.at(FIXED_NOW)          # 20-09-2026 12:00 по Киеву
TABLE_ACCOUNT: str = "table@example.com"
CHANNEL_ACCOUNT: str = "channel@example.com"


def check_of(paths: LivecraftPaths, reader: FakeSheetsReader) -> TableCheck:
    return TableCheck(paths=paths, door=reader, clock=CLOCK)


def ok_line(**values: object) -> str:
    return msg.SETUP_TABLE_OK_NEAREST.format(sheet=PLAN_SHEET, link="C", date="D", time="E", **values)


# --- образец


def test_the_sample_is_the_plan_table_sample() -> None:
    """Образец таблицы плана: язык «Lang», чип видео, ссылка, дата, время, превью; язык и превью пишет
    программа."""
    sample: TableSample = TableSample("Europe/Kyiv")
    assert sample.header == (
        LANGUAGE_HEADER, msg.SETUP_TABLE_SAMPLE_CHIP_HEADER, *(column.human for column in PlanColumn), PREVIEW_HEADER
    )
    assert sample.header[0] == "Lang"
    assert sample.row[0] == sample.row[-1] == msg.SETUP_TABLE_SAMPLE_BY_PROGRAM
    assert sample.row[1] == msg.SETUP_TABLE_SAMPLE_CHIP


@pytest.mark.parametrize("catalog", CATALOGS.values())
def test_every_sample_column_name_is_recognized_by_the_plan_and_the_writes(
    catalog: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Образец рисуется из тех же названий, что узнаёт план, на любом языке окна: ссылка — на месте «ссылки», а не
    «видео (чип)»; колонки языка и превью узнаёт запись в таблицу (§14 решения 27, 29)."""
    monkeypatch.setattr(table_check, "msg", catalog)
    sample: TableSample = TableSample("Europe/Kyiv")
    assert SheetColumns.from_header(SheetHeader(sample.header)) == SheetColumns(link=2, date=3, time=4)
    plan: SheetPlan = SheetPlan.from_values(PLAN_SHEET, 0, [list(sample.header), list(sample.row)])
    assert plan.columns is not None
    language: OutputColumn = OutputColumn.of(plan, SheetOutput.LANGUAGE, plan.columns.indexes)
    preview: OutputColumn = OutputColumn.of(plan, SheetOutput.PREVIEW, plan.columns.indexes | {language.index})
    assert (language.index, language.has_header, preview.index, preview.has_header) == (0, True, 5, True)


def test_the_sample_date_and_time_are_read_by_the_table_rules() -> None:
    sample: TableSample = TableSample("Europe/Kyiv")
    row: dict[PlanColumn, str] = dict(zip(PlanColumn, sample.row[2: 2 + len(PlanColumn)], strict=True))
    assert SheetCell.DATE.parse(row[PlanColumn.DATE]).date().isoformat() == "2026-09-28"
    assert SheetCell.TIME.parse(row[PlanColumn.TIME]).strftime("%H:%M") == "19:00"


def test_the_rules_name_the_program_timezone() -> None:
    assert "Europe/Kyiv" in TableSample("Europe/Kyiv").rules


# --- итог проверки


def test_a_good_table_names_the_sheet_letters_count_and_the_nearest_stream(ready_paths: LivecraftPaths) -> None:
    reader: FakeSheetsReader = FakeSheetsReader(values=[
        HEADER,
        ["1", "", OTHER_LINK, "30.09.2026", "20:00"],
        ["2", "", LINK, "28-09-2026", "19:00"],
    ])
    verdict: TableVerdict = check_of(ready_paths, reader).run(lambda: None)
    assert verdict.is_ok
    assert verdict.lines == (ok_line(count=2, nearest="28.09.2026 19:00"),)
    assert reader.vaults[0].get(SecretField.SHEETS_ID) is not None


def test_a_table_without_future_streams_says_so(ready_paths: LivecraftPaths) -> None:
    reader: FakeSheetsReader = FakeSheetsReader(values=[HEADER, ["1", "", LINK, "10.09.2026", "19:00"]])
    verdict: TableVerdict = check_of(ready_paths, reader).run(lambda: None)
    assert verdict.is_ok
    none: str = msg.SETUP_TABLE_OK_NONE.format(sheet=PLAN_SHEET, link="C", date="D", time="E")
    assert verdict.lines[0] == none


def test_skipped_rows_add_the_line_of_the_launch(ready_paths: LivecraftPaths) -> None:
    values: list[list[str]] = [HEADER, ["1", "", LINK, "28.09.2026", "19:00"], ["2", "", "", "28.09.2026", "20:00"]]
    verdict: TableVerdict = check_of(ready_paths, FakeSheetsReader(values=values)).run(lambda: None)
    plan: SheetPlan = SheetPlan.from_values(PLAN_SHEET, 0, values)
    rows: PlannedRows = PlannedRows.of(plan.rows, ZoneInfo("Europe/Kyiv"), FIXED_NOW)
    assert verdict.lines == (ok_line(count=1, nearest="28.09.2026 19:00"), rows.console_line)


def test_a_read_failure_is_its_human_text(ready_paths: LivecraftPaths) -> None:
    error: SheetsReadError = SheetsReadError(SheetsReadReason.NOT_FOUND, "sheets-plan(ab12)", status=404)
    verdict: TableVerdict = check_of(ready_paths, FakeSheetsReader(error=error)).run(lambda: None)
    assert not verdict.is_ok
    assert verdict.lines == (msg.SETUP_TABLE_FAILED.format(problem=error.human),)


# --- вход оператора: то же правило, что в запуске (§13 задача 9.6)


def test_a_new_login_is_named_in_the_first_line_of_the_verdict(ready_paths: LivecraftPaths) -> None:
    values: list[list[str]] = [HEADER, ["1", "", LINK, "28.09.2026", "19:00"]]
    reader: FakeSheetsReader = FakeSheetsReader(values=values, announce_login=True)
    verdict: TableVerdict = check_of(ready_paths, reader).run(lambda: None)
    assert verdict.is_ok
    assert verdict.lines == (
        msg.OPERATOR_LOGGED_IN.format(account=OPERATOR_EMAIL), ok_line(count=1, nearest="28.09.2026 19:00"),
    )


def test_an_account_without_access_logs_in_again_in_the_same_check(ready_paths: LivecraftPaths) -> None:
    said: list[str] = []
    values: list[list[str]] = [HEADER, ["1", "", LINK, "28.09.2026", "19:00"]]
    table: FakeSheetsReader = FakeSheetsReader(values=values, account_email=TABLE_ACCOUNT)
    refused: SheetsReadError = SheetsReadError(SheetsReadReason.NO_ACCESS, "sheets-plan(ab12)", status=403)
    door: FakeSheetsReader = FakeSheetsReader(error=refused, account_email=CHANNEL_ACCOUNT, relogin=table)
    verdict: TableVerdict = check_of(ready_paths, door).run(lambda: said.append("login"))
    assert verdict.is_ok and said == ["login"]               # «открылся браузер» — окну, как при первом входе
    assert verdict.lines == (
        msg.OPERATOR_ACCESS_REFUSED.format(account=CHANNEL_ACCOUNT),
        msg.OPERATOR_LOGGED_IN.format(account=TABLE_ACCOUNT),
        ok_line(count=1, nearest="28.09.2026 19:00"),
    )


def test_no_access_twice_is_the_problem_line_with_the_account(ready_paths: LivecraftPaths) -> None:
    refused: SheetsReadError = SheetsReadError(SheetsReadReason.NO_ACCESS, "sheets-plan(ab12)", status=403)
    other: FakeSheetsReader = FakeSheetsReader(error=refused, account_email=TABLE_ACCOUNT)
    door: FakeSheetsReader = FakeSheetsReader(error=refused, account_email=CHANNEL_ACCOUNT, relogin=other)
    verdict: TableVerdict = check_of(ready_paths, door).run(lambda: None)
    stop: SheetsReadError = SheetsReadError(
        SheetsReadReason.ACCOUNT_REFUSED, "sheets-plan(ab12)", status=403, detail=TABLE_ACCOUNT
    )
    assert not verdict.is_ok
    assert verdict.lines == (
        msg.OPERATOR_ACCESS_REFUSED.format(account=CHANNEL_ACCOUNT),
        msg.OPERATOR_LOGGED_IN.format(account=TABLE_ACCOUNT),
        msg.SETUP_TABLE_FAILED.format(problem=stop.human),
    )


def test_the_real_login_of_the_check_follows_the_operator_rule(
    ready_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Боевая проверка окна на подменённом браузере: токен аккаунта без доступа — повторный вход и чтение; прежний
    токен цел до удачного входа."""
    login: GoogleLogin = GoogleLogin.operator(ready_paths)
    values: list[list[str]] = [HEADER, ["1", "", LINK, "28.09.2026", "19:00"]]
    google: FakeOperatorGoogle = FakeOperatorGoogle(login, [TABLE_ACCOUNT], {TABLE_ACCOUNT}, values).install(monkeypatch)
    old_token: str = google.write_token(CHANNEL_ACCOUNT)
    said: list[str] = []
    check: TableCheck = TableCheck(paths=ready_paths, door=TableCheck.of(ready_paths).door, clock=CLOCK)
    verdict: TableVerdict = check.run(lambda: said.append("login"))
    assert verdict.is_ok and said == ["login"] and google.tokens_at_login == [old_token]
    assert verdict.lines == (
        msg.OPERATOR_ACCESS_REFUSED.format(account=CHANNEL_ACCOUNT),
        msg.OPERATOR_LOGGED_IN.format(account=TABLE_ACCOUNT),
        msg.SETUP_TABLE_OK_NEAREST.format(
            sheet=SHEET_TITLE, link="C", date="D", time="E", count=1, nearest="28.09.2026 19:00"
        ),
    )


def test_the_plan_is_read_by_the_operator_rule_for_the_form_check(ready_paths: LivecraftPaths) -> None:
    """Проверка формы читает план тем же правилом входа оператора: строки правила — тому, кого назвали."""
    refused: SheetsReadError = SheetsReadError(SheetsReadReason.NO_ACCESS, "sheets-plan(ab12)", status=403)
    table: FakeSheetsReader = FakeSheetsReader(values=[HEADER], account_email=TABLE_ACCOUNT)
    reader: FakeSheetsReader = FakeSheetsReader(error=refused, account_email=CHANNEL_ACCOUNT, relogin=table)
    said: list[str] = []
    vault: Vault = VaultStore.open(ready_paths).load().vault
    plan: SheetPlan = check_of(ready_paths, reader).read_plan(vault, lambda: None, said.append)
    assert plan.sheet_title == PLAN_SHEET and table.vaults != []
    assert said == [
        msg.OPERATOR_ACCESS_REFUSED.format(account=CHANNEL_ACCOUNT), msg.OPERATOR_LOGGED_IN.format(account=TABLE_ACCOUNT)
    ]


def test_the_browser_text_of_the_window_names_the_account_to_use() -> None:
    assert "которому открыта таблица плана" in msg.SETUP_TABLE_LOGIN
    assert "не аккаунт канала YouTube" in msg.SETUP_TABLE_LOGIN


def test_a_header_problem_is_the_plan_problem(ready_paths: LivecraftPaths) -> None:
    values: list[list[str]] = [["Ссылка", "Время"], [LINK, "19:00"]]
    verdict: TableVerdict = check_of(ready_paths, FakeSheetsReader(values=values)).run(lambda: None)
    plan: SheetPlan = SheetPlan.from_values(PLAN_SHEET, 0, values)
    assert plan.problem is PlanProblem.HEADER_UNKNOWN
    assert verdict.lines == (msg.SETUP_TABLE_FAILED.format(problem=plan.problem_text),)


def test_an_empty_sheet_is_a_problem(ready_paths: LivecraftPaths) -> None:
    verdict: TableVerdict = check_of(ready_paths, FakeSheetsReader(values=[HEADER])).run(lambda: None)
    assert verdict.lines == (msg.SETUP_TABLE_FAILED.format(problem=msg.SHEET_PLAN_EMPTY.format(sheet=PLAN_SHEET)),)


def test_no_table_in_the_vault_is_said_before_any_login(ready_paths: LivecraftPaths) -> None:
    write_token_vault(ready_paths, {SecretField.OPENAI_API_KEY: TOKEN_VALUES[SecretField.OPENAI_API_KEY]})
    reader: FakeSheetsReader = FakeSheetsReader(values=[HEADER], announce_login=True)
    verdict: TableVerdict = check_of(ready_paths, reader).run(lambda: None)
    assert not verdict.is_ok and SheetsReadReason.NOT_CONFIGURED.human in verdict.text
    assert reader.login_announced == 0 and reader.vaults == []


def test_the_browser_line_goes_to_the_caller(ready_paths: LivecraftPaths) -> None:
    said: list[str] = []
    values: list[list[str]] = [HEADER, ["1", "", LINK, "28.09.2026", "19:00"]]
    reader: FakeSheetsReader = FakeSheetsReader(values=values, announce_login=True)
    check_of(ready_paths, reader).run(lambda: said.append("login"))
    assert said == ["login"]


def test_no_vault_value_is_in_the_verdict(ready_paths: LivecraftPaths) -> None:
    values: list[list[str]] = [HEADER, ["1", "", LINK, "28.09.2026", "19:00"]]
    texts: list[str] = [
        check_of(ready_paths, FakeSheetsReader(values=values)).run(lambda: None).text,
        check_of(ready_paths, FakeSheetsReader(values=[["x"]])).run(lambda: None).text,
    ]
    for text in texts:
        for value in TOKEN_VALUES.values():
            assert value not in text
