"""Прогон контура A (app\\intake\\intake.py): таблица → ряды → источники → превью → запись в таблицу → merge → слоты,
исход по §10. Пакет, документ и Telegram — вывод запуска от слотов (test_publish_run_output.py).

Сеть подменена целиком: читатель таблицы отдаёт `SheetPlan.from_values` из фиксированных значений и запоминает
записи языков и ссылок, yt-dlp — сохранённый ответ, загрузчик обложек — картинку из памяти, Google Диск — подделка
в памяти, нейросеть — `QueueBackend`; «сейчас» фиксировано.
"""
from __future__ import annotations

import io
import json
import logging
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from app.config.files import SettingsFile
from app.config.settings import LivecraftSettings
from app.core.retry import RetryPolicy
from app.google.auth import GoogleLogin
from app.intake.builder import SlotBuilder
from app.intake.intake import IntakeRequest, IntakeResult, IntakeStage, PlanIntake
from app.intake.preview_stage import PreviewMode, PreviewStage
from app.intake.merge_stage import VideoTextReason
from app.intake.table_stage import TableStage
from app.llm.backends.openai import OpenAiClient
from app.llm.errors import LlmErrorKind
from app.observability.log_event import LogArea
from app.paths import DataDir, FileName, LivecraftPaths
from app.run.exit_code import RunOutcome
from app.run.line_plan import RunScope
from app.run.mode import RunPart
from app.run.progress import SILENT_PROGRESS, StageProgress
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.sheets.client import SheetsReadError, SheetsReadReason, SheetsWriteError
from app.sheets.operator import OperatorAccount, OperatorDoor, OperatorSheets
from app.sheets.plan import PlanProblem, SheetPlan
from app.sheets.preview import SheetOutput, SheetWrite
from app.sheets.rows import RowSkipReason
from app.slots.texts import SlotProblem, SlotTextOrigin
from app.sources.fetcher import SourceFetch
from app.sources.language import LanguageResolver
from app.sources.metadata import SourceFailureReason, SourceMetadata
from app.sources.preview import PreviewDownloader
from app.sources.video import SourceCatalog
from app.tests.conftest import FORM_URL
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.drive import ROOT_FOLDER_ID, FakeDriveService, drive_client, drive_error
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.merges import EXPANDED_SOURCES, STRONG_ANSWER, TITLE, QueueBackend, answer, error
from app.tests.fixtures.operator import FakeOperatorGoogle
from app.tests.fixtures.packages import manifest, slot_record, write_package
from app.tests.fixtures.settings import drive_vault, set_form_url
from app.tests.fixtures.sheets import OPERATOR_EMAIL
from app.tests.fixtures.sources import StubFetcher, video_metadata
from app.ui import messages_ru as msg

DATA_DIR: Path = Path(__file__).resolve().parent / "data" / "ytdlp"
KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
NOW: datetime = datetime(2026, 10, 1, 12, 0, tzinfo=KYIV)
HEADER: list[str] = ["Links", "Date", "Time"]
PLAN_SHEET: str = "План"
LINK: str = "https://youtu.be/dQw4w9WgXcQ"
OTHER_LINK: str = "https://youtu.be/aB3_-xYz012"
BROKEN_LINK: str = "https://youtu.be/Zx9_8yW7v6U"
FUTURE_ROW: list[str] = [LINK, "16.10.2026", "19:00"]
OTHER_ROW: list[str] = [OTHER_LINK, "17.10.2026", "20:00"]
PAST_ROW: list[str] = [LINK, "01.09.2026", "19:00"]
BROKEN_ROW: list[str] = [BROKEN_LINK, "18.10.2026", "19:00"]
RESOLVER: LanguageResolver = LanguageResolver.from_resources()
# Линии запуска с таблицей: таблица и превью в папке (§14 решение 37).
TABLE_SCOPE: RunScope = RunScope(parts=frozenset({RunPart.PLAN, RunPart.LOCAL_PREVIEWS}))


def _info() -> dict[str, Any]:
    info: Any = json.loads((DATA_DIR / "video_full.json").read_text(encoding="utf-8"))
    assert isinstance(info, dict)
    return info


def _ok_fetch(link: str, title: str | None = None) -> SourceFetch:
    info: dict[str, Any] = _info() if title is None else _info() | {"title": title}
    return SourceFetch.from_metadata(link, SourceMetadata.from_ytdlp(link, info))


def _png() -> bytes:
    output: io.BytesIO = io.BytesIO()
    Image.new("RGB", (64, 36), (200, 30, 30)).save(output, format="PNG")
    return output.getvalue()


class _Response:
    def __init__(self, status_code: int, content: bytes) -> None:
        self.status_code: int = status_code
        self.content: bytes = content


class _Fetcher:
    """Получатель без yt-dlp: по ссылке — сохранённый ответ или отказ."""

    def __init__(
        self, failures: dict[str, SourceFailureReason] | None = None, titles: dict[str, str] | None = None
    ) -> None:
        self.failures: dict[str, SourceFailureReason] = failures or {}
        self.titles: dict[str, str] = titles or {}
        self.calls: list[str] = []

    def fetch(self, url: str) -> SourceFetch:
        self.calls.append(url)
        if url in self.failures:
            return SourceFetch.failed(url, self.failures[url], "stub")
        return _ok_fetch(url, self.titles.get(url))


@dataclass
class _Reader:
    """Читатель таблицы без Google: значения диапазона или сбой чтения, сбой записи; сейф, с которым его позвали, и
    записи языков и ссылок на превью запоминаются."""

    values: list[list[str]] = field(default_factory=list)
    error: SheetsReadError | None = None
    write_error: SheetsWriteError | None = None
    vaults: list[Vault] = field(default_factory=list)
    writes: list[SheetWrite] = field(default_factory=list)
    open_error: SheetsReadError | None = None
    relogin: _Reader | None = None
    account_email: str = OPERATOR_EMAIL
    entered: _Reader | None = None

    def read_plan(self, vault: Vault) -> SheetPlan:
        self.vaults.append(vault)
        if self.error is not None:
            raise self.error
        return SheetPlan.from_values(PLAN_SHEET, 0, self.values)

    def reader(self, on_login: Callable[[], None], again: bool = False) -> _Reader:
        """Он же — вход оператора прогона: вход не удался (`open_error`) или читатель входа; повторный вход (`again`)
        открывает «браузер» и отдаёт читателя `relogin` (None — этого же)."""
        if self.open_error is not None:
            raise self.open_error
        if again:
            on_login()
        self.entered = self.relogin if again and self.relogin is not None else self
        return self.entered

    def account(self) -> OperatorAccount:
        """Аккаунт читателя, которого вход отдал последним."""
        return OperatorAccount((self.entered or self).account_email)

    def write_outputs(self, vault: Vault, write: SheetWrite) -> None:
        self.writes.append(write)
        if self.write_error is not None:
            raise self.write_error


def _settings(paths: LivecraftPaths, form_url: str | None = FORM_URL) -> LivecraftSettings:
    SettingsFile(paths.file(FileName.CONFIG)).install_shipped()
    if form_url is not None:
        set_form_url(paths, form_url)
    return SettingsFile(paths.file(FileName.CONFIG)).load()


def _intake(
    paths: LivecraftPaths,
    reader: _Reader,
    fetcher: _Fetcher | StubFetcher | None = None,
    form_url: str | None = FORM_URL,
    backend: QueueBackend | None = None,
    drive: FakeDriveService | None = None,
    dry_run: bool = False,
    without: tuple[RunPart, ...] = (),
    progress: StageProgress = SILENT_PROGRESS,
) -> PlanIntake:
    """Прогон на подменённой сети; `backend` — нейросеть прогона (None — merge нет, как без ключа OpenAI); `drive` — Google
    Диск прогона (None — линия «превью на Диске» не идёт: копии превью только в папке превью); `dry_run` — пробный
    запуск: к записи в таблицу прогон не обращается; `without` — линии, которые в запуске не идут; `progress` — строки
    хода прогона (по умолчанию молчит)."""
    settings: LivecraftSettings = _settings(paths, form_url)
    parts: set[RunPart] = {RunPart.PLAN, RunPart.LOCAL_PREVIEWS}
    parts |= {RunPart.MERGE} if backend is not None else set()
    parts |= {RunPart.DRIVE_PREVIEWS} if drive is not None else set()
    request: IntakeRequest = IntakeRequest(
        paths=paths,
        settings=settings,
        vault=Vault.empty() if drive is None else drive_vault(ROOT_FOLDER_ID),
        now=NOW,
        scope=RunScope(parts=frozenset(parts - set(without)), dry_run=dry_run),
        progress=progress,
    )
    get: Callable[[str, float], _Response] = lambda url, timeout: _Response(200, _png())
    catalog: SourceCatalog = SourceCatalog(
        fetcher=fetcher or _Fetcher(),
        downloader=PreviewDownloader(session_get=get, policy=RetryPolicy(), sleep=lambda _: None),
        resolver=RESOLVER,
    )
    mode: PreviewMode | None = PreviewMode.of(request.scope)
    previews: PreviewStage | None = None if mode is None else PreviewStage(
        paths.dir(DataDir.IMAGE), settings, request.vault, mode, lambda: drive_client(drive or FakeDriveService())
    )
    return PlanIntake(
        request=request,
        sheets=OperatorSheets.for_console(reader, progress.operator_note),       # type: ignore[arg-type]
        catalog=catalog,
        previews=previews,
        table=TableStage(Vault.empty(), dry_run),
        builder=SlotBuilder(settings.zone),
        merge_backend=backend,
    )


def _packages(paths: LivecraftPaths) -> list[Path]:
    return sorted(paths.bcast_dir.glob("*.bcast"))


def _no_private_text(lines: tuple[str, ...]) -> None:
    """Строки консоли: ни названий и описаний видео, ни ссылки на форму."""
    text: str = "\n".join(lines)
    info: dict[str, Any] = _info()
    assert str(info["title"]) not in text
    assert str(info["description"])[:40] not in text
    assert FORM_URL not in text


# --- полный прогон


def test_a_full_run_builds_the_slots_with_their_previews(livecraft_paths: LivecraftPaths) -> None:
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader).run()
    assert result.outcome is RunOutcome.DONE
    assert result.stopped_at is None
    assert [slot.slot_id for slot in result.slots] == ["16-10-2026_1900_uk", "17-10-2026_2000_uk"]
    assert [len(slot.previews) for slot in result.slots] == [1, 1]
    assert _packages(livecraft_paths) == []                 # пакет пишет вывод запуска, а не прогон таблицы
    assert reader.vaults == [Vault.empty()]


def test_the_console_lines_go_one_per_step_without_titles_or_the_form(livecraft_paths: LivecraftPaths) -> None:
    with LogCapture.on(LogArea.INTAKE) as intake_log:
        result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW])).run()
    lines: tuple[str, ...] = result.console_lines
    assert lines == (
        msg.INTAKE_TABLE_LINE.format(rows=2, admitted=2, skipped=0, reasons=""),
        msg.INTAKE_SOURCES_LINE.format(ready=2, total=2, no_preview=0, failures=""),
        msg.PREVIEWS_LOCAL_LINE.format(saved=2),
        msg.INTAKE_SHEET_WRITE_LANGUAGES_LINE.format(languages=2, languages_kept=0),
        msg.INTAKE_SLOTS_LINE.format(
            count=2, languages=msg.INTAKE_SLOTS_LANGUAGES.format(items="uk: 2"), refused=""
        ),
    )
    _no_private_text(lines)
    _no_private_text(tuple(intake_log.messages()))


def test_past_rows_and_repeats_are_named_in_the_table_line(livecraft_paths: LivecraftPaths) -> None:
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, PAST_ROW, FUTURE_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader).run()
    assert result.outcome is RunOutcome.DONE
    table: str = result.console_lines[0]
    assert "рядов 3, допущено 1, отсеяно 2" in table
    assert msg.INTAKE_COUNT_ITEM.format(name=msg.SHEET_ROW_SKIP_REASONS["in_past"], count=1) in table
    assert msg.INTAKE_COUNT_ITEM.format(name=msg.SHEET_ROW_SKIP_REASONS["duplicate"], count=1) in table


def test_one_link_in_two_rows_is_one_fetch(livecraft_paths: LivecraftPaths) -> None:
    fetcher: _Fetcher = _Fetcher()
    rows: list[list[str]] = [HEADER, FUTURE_ROW, [LINK, "17.10.2026", "20:00"]]
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=rows), fetcher).run()
    assert result.outcome is RunOutcome.DONE
    assert fetcher.calls == [LINK]


# --- отказы и остановки


def test_a_refused_source_is_code_1_and_the_reason_is_in_the_sources_line(livecraft_paths: LivecraftPaths) -> None:
    fetcher: _Fetcher = _Fetcher({BROKEN_LINK: SourceFailureReason.UNAVAILABLE})
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW, BROKEN_ROW]), fetcher).run()
    assert result.outcome is RunOutcome.FAILED
    assert len(result.slots) == 1                                          # годный слот идёт дальше
    sources: str = result.console_lines[1]
    assert "годных 1 из 2" in sources
    assert msg.INTAKE_COUNT_ITEM.format(name=SourceFailureReason.UNAVAILABLE.human, count=1) in sources


def test_every_source_refused_is_code_1_without_a_package(livecraft_paths: LivecraftPaths) -> None:
    """Слотов нет из-за отказов — это ошибка (1), а не «нет будущих рядов» (3)."""
    fetcher: _Fetcher = _Fetcher({LINK: SourceFailureReason.TOOL_MISSING})
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW]), fetcher).run()
    assert result.outcome is RunOutcome.FAILED
    assert result.stopped_at is IntakeStage.SOURCES
    assert result.build is None and result.slots == ()
    assert result.console_lines[-1] == msg.INTAKE_NO_SLOTS
    assert _packages(livecraft_paths) == []


def test_all_rows_in_the_past_is_code_3_without_sources_and_package(livecraft_paths: LivecraftPaths) -> None:
    fetcher: _Fetcher = _Fetcher()
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, PAST_ROW]), fetcher).run()
    assert result.outcome is RunOutcome.NOTHING_PLANNED
    assert result.stopped_at is IntakeStage.TABLE
    assert fetcher.calls == []
    assert result.console_lines[-1] == msg.INTAKE_NO_FUTURE_ROWS
    assert _packages(livecraft_paths) == []


@pytest.mark.parametrize(
    ("reason", "outcome"),
    [
        (SheetsReadReason.AUTH, RunOutcome.NOT_CONFIGURED),
        (SheetsReadReason.NOT_CONFIGURED, RunOutcome.NOT_CONFIGURED),
        (SheetsReadReason.ACCOUNT_REFUSED, RunOutcome.FAILED),
        (SheetsReadReason.UNAVAILABLE, RunOutcome.FAILED),
        (SheetsReadReason.NO_NETWORK, RunOutcome.FAILED),
    ],
)
def test_a_table_that_does_not_read_is_a_result_not_an_exception(
    livecraft_paths: LivecraftPaths, reason: SheetsReadReason, outcome: RunOutcome
) -> None:
    error: SheetsReadError = SheetsReadError(reason, "plan(9c2b)", detail=OPERATOR_EMAIL)
    fetcher: _Fetcher = _Fetcher()
    result: IntakeResult = _intake(livecraft_paths, _Reader(error=error), fetcher).run()
    assert result.outcome is outcome
    assert result.sheets_error is error and result.stopped_at is IntakeStage.TABLE
    assert result.console_lines == (error.human,)
    assert fetcher.calls == [] and _packages(livecraft_paths) == []


def test_a_login_that_fails_is_a_result_not_an_exception(livecraft_paths: LivecraftPaths) -> None:
    """Вход оператора не удался (браузер закрыт, нет client_secret.json) — итог с причиной и код 2, а не падение
    запуска."""
    error: SheetsReadError = SheetsReadError(SheetsReadReason.AUTH, "plan(9c2b)", detail="вход не завершён")
    result: IntakeResult = _intake(livecraft_paths, _Reader(open_error=error)).run()
    assert result.outcome is RunOutcome.NOT_CONFIGURED
    assert result.sheets_error is error and result.console_lines == (error.human,)


def test_an_account_without_access_logs_in_again_and_the_run_goes_on(livecraft_paths: LivecraftPaths) -> None:
    """Аккаунту входа таблица не открыта (§13 задача 9.6): строка с почтой, повторный вход в том же запуске, прогон
    идёт дальше — и язык видео в таблицу пишет читатель нового входа."""
    record: ConsoleRecord = ConsoleRecord()
    table: _Reader = _Reader(values=[HEADER, FUTURE_ROW], account_email="table@example.com")
    refused: SheetsReadError = SheetsReadError(SheetsReadReason.NO_ACCESS, "plan(9c2b)", status=403)
    door: _Reader = _Reader(error=refused, relogin=table)
    result: IntakeResult = _intake(livecraft_paths, door, progress=StageProgress(record.console)).run()
    assert result.outcome is RunOutcome.DONE and len(result.slots) == 1
    assert record.lines[:3] == [
        msg.OPERATOR_ACCESS_REFUSED.format(account=OPERATOR_EMAIL),
        msg.SHEETS_LOGIN_BROWSER,
        msg.OPERATOR_LOGGED_IN.format(account="table@example.com"),
    ]
    assert len(table.writes) == 1 and door.writes == []


def test_no_access_after_the_second_login_is_code_1_with_the_account(livecraft_paths: LivecraftPaths) -> None:
    refused: SheetsReadError = SheetsReadError(SheetsReadReason.NO_ACCESS, "plan(9c2b)", status=403)
    fetcher: _Fetcher = _Fetcher()
    result: IntakeResult = _intake(livecraft_paths, _Reader(error=refused), fetcher).run()
    assert result.outcome is RunOutcome.FAILED and result.stopped_at is IntakeStage.TABLE
    assert result.sheets_error is not None and result.sheets_error.reason is SheetsReadReason.ACCOUNT_REFUSED
    assert OPERATOR_EMAIL in result.console_lines[0] and fetcher.calls == []


def test_an_unknown_header_is_code_1(livecraft_paths: LivecraftPaths) -> None:
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[["Что-то", "Ещё"], FUTURE_ROW])).run()
    assert result.outcome is RunOutcome.FAILED
    assert result.plan_problem is PlanProblem.HEADER_UNKNOWN and result.stopped_at is IntakeStage.TABLE
    assert result.plan is not None and result.console_lines == (result.plan.problem_text,)
    assert "«Что-то», «Ещё»" in result.console_lines[0]
    assert result.rows is None and _packages(livecraft_paths) == []


def test_a_sheet_without_rows_is_code_1_and_names_the_empty_sheet(livecraft_paths: LivecraftPaths) -> None:
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER])).run()
    assert result.outcome is RunOutcome.FAILED
    assert result.plan_problem is PlanProblem.EMPTY
    assert result.console_lines == (msg.SHEET_PLAN_EMPTY.format(sheet=PLAN_SHEET),)


def test_a_slot_with_an_empty_title_is_refused_and_goes_no_further(livecraft_paths: LivecraftPaths) -> None:
    """Нейросеть идёт, merge не нужен — тексты видео по правилам YouTube: название без границы слова не влезает в 100
    символов, слот уходит в отказ, дальше идёт только годный, код 1."""
    fetcher: _Fetcher = _Fetcher(titles={OTHER_LINK: "x" * 150})
    backend: QueueBackend = QueueBackend(replies=[], probe_kind=None)
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, fetcher, backend=backend).run()
    assert result.outcome is RunOutcome.FAILED
    assert result.build is not None
    (refused,) = result.build.refused
    assert (refused.slot_id, refused.problem) == ("17-10-2026_2000_uk", SlotProblem.EMPTY_TITLE)
    assert [slot.slot_id for slot in result.slots] == ["16-10-2026_1900_uk"]
    assert result.console_lines[-1] == msg.INTAKE_SLOTS_LINE.format(
        count=1,
        languages=msg.INTAKE_SLOTS_LANGUAGES.format(items="uk: 1"),
        refused=msg.INTAKE_SLOTS_REFUSED.format(count=1),
    )


def test_the_request_needs_an_aware_now(livecraft_paths: LivecraftPaths) -> None:
    with pytest.raises(ValueError):
        IntakeRequest(
            paths=livecraft_paths,
            settings=_settings(livecraft_paths),
            vault=Vault.empty(),
            now=datetime(2026, 10, 1, 12, 0),
            scope=TABLE_SCOPE,
        )


def test_of_wires_the_battle_dependencies_without_touching_google(livecraft_paths: LivecraftPaths) -> None:
    """Боевые зависимости собираются без входа в Google: читатель открывается только в run."""
    settings: LivecraftSettings = _settings(livecraft_paths)
    request: IntakeRequest = IntakeRequest(
        paths=livecraft_paths, settings=settings, vault=Vault.empty(), now=NOW, scope=TABLE_SCOPE
    )
    intake: PlanIntake = PlanIntake.of(request)
    assert intake.request is request
    assert intake.table == TableStage(request.vault, dry_run=False)
    assert intake.builder.zone == settings.zone
    assert intake.merge_backend is None                 # merge не идёт — нейросети у прогона нет
    assert not livecraft_paths.file(FileName.SHEETS_TOKEN).exists()
    assert intake.previews is not None
    assert intake.previews.mode is PreviewMode.LOCAL     # линия «превью на Google Диске» не идёт
    assert intake.previews.image_dir == livecraft_paths.dir(DataDir.IMAGE)
    assert intake.sheets.door == OperatorDoor(GoogleLogin.operator(livecraft_paths), request.progress)


def test_the_battle_run_says_the_operator_login_on_the_console_of_the_run(
    livecraft_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Боевые зависимости на подменённом браузере (§13 задача 9.6): перед браузером — каким аккаунтом входить, после
    входа — каким вошли; обе строки — на консоль запуска."""
    livecraft_paths.file(FileName.CLIENT_SECRET).write_text("{}", encoding="utf-8")
    login: GoogleLogin = GoogleLogin.operator(livecraft_paths)
    FakeOperatorGoogle(login, [OPERATOR_EMAIL], {OPERATOR_EMAIL}, [HEADER, PAST_ROW]).install(monkeypatch)
    record: ConsoleRecord = ConsoleRecord()
    sheet_id: SecretValue = SecretValue(field=SecretField.SHEETS_ID, value="1AbCdEfGhIjKlMnOpQrStUvWxYz0123456789-_abcd")
    request: IntakeRequest = IntakeRequest(
        paths=livecraft_paths, settings=_settings(livecraft_paths), now=NOW, scope=TABLE_SCOPE,
        vault=Vault.empty().with_field(SecretField.SHEETS_ID, sheet_id, VaultOrigin.OWN),
        progress=StageProgress(record.console),
    )
    result: IntakeResult = PlanIntake.of(request).run()
    assert result.outcome is RunOutcome.NOTHING_PLANNED       # таблица прочитана: будущих рядов нет
    assert record.lines == [msg.SHEETS_LOGIN_BROWSER, msg.OPERATOR_LOGGED_IN.format(account=OPERATOR_EMAIL)]


@pytest.mark.parametrize(
    ("parts", "dry_run", "mode"),
    [
        ((RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS), False, PreviewMode.FULL),
        ((RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS), True, PreviewMode.DRY_RUN),
        ((RunPart.LOCAL_PREVIEWS,), False, PreviewMode.LOCAL),
        ((RunPart.DRIVE_PREVIEWS,), False, PreviewMode.DRIVE),
        ((), False, None),
    ],
)
def test_of_takes_the_preview_mode_from_the_lines(
    livecraft_paths: LivecraftPaths, parts: tuple[RunPart, ...], dry_run: bool, mode: PreviewMode | None
) -> None:
    request: IntakeRequest = IntakeRequest(
        paths=livecraft_paths, settings=_settings(livecraft_paths), vault=Vault.empty(), now=NOW,
        scope=RunScope(parts=frozenset({RunPart.PLAN, *parts}), dry_run=dry_run),
    )
    intake: PlanIntake = PlanIntake.of(request)
    assert (None if intake.previews is None else intake.previews.mode) is mode and intake.table.dry_run is dry_run


def test_without_the_ai_the_texts_are_for_people_and_that_is_no_error(livecraft_paths: LivecraftPaths) -> None:
    """Нейросеть не идёт (§14 решение 50): слот из одного видео — его тексты целиком, из нескольких — «по номерам»;
    это настройка, а не отказ merge: код 0, строк о слотах не для YouTube нет."""
    reader: _Reader = _Reader(values=[*MERGE_ROWS, SINGLE_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, _merge_fetcher()).run()
    assert result.outcome is RunOutcome.DONE and result.merge is None
    numbered, single = result.slots
    assert numbered.texts.origin is SlotTextOrigin.NUMBERED and not numbered.is_for_youtube
    assert single.texts.origin is SlotTextOrigin.SOURCE_SINGLE and single.title == SINGLE_TITLE
    assert result.build is not None and result.build.merge_refused == () and result.build.refused == ()
    assert result.console_lines[-1] == result.build.console_lines[0]


def test_a_full_run_puts_copies_on_the_drive_and_languages_and_links_into_the_table(
    livecraft_paths: LivecraftPaths,
) -> None:
    """§14 решения 27, 29: превью — в image\\ и на Диске; язык видео и ссылка на копию — в строку видео одной
    записью; обложки документа — копии на Диске по ссылкам видео."""
    SettingsFile(livecraft_paths.file(FileName.CONFIG)).install_shipped()
    drive: FakeDriveService = FakeDriveService()
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, drive=drive).run()
    assert result.outcome is RunOutcome.DONE and len(result.slots) == 2
    [write] = reader.writes
    assert (write.written(SheetOutput.PREVIEW), write.written(SheetOutput.LANGUAGE)) == (2, 2)
    assert len(list(livecraft_paths.dir(DataDir.IMAGE).rglob("*.jpg"))) == 2
    assert result.console_lines[2:4] == (
        msg.PREVIEWS_LINE.format(saved=2, uploaded=2, kept=0),
        msg.INTAKE_SHEET_WRITE_LINE.format(languages=2, languages_kept=0, links=2, links_kept=0),
    )
    assert result.previews is not None
    assert sorted(result.previews.covers) == sorted(source for slot in result.slots for source in slot.sources)


def test_without_the_drive_previews_nothing_goes_to_the_drive_and_only_languages_to_the_table(
    livecraft_paths: LivecraftPaths,
) -> None:
    """Линия «Превью на Google Диске» не идёт: ни загрузок, ни ссылок в таблицу; язык видео пишется, копии — в папке."""
    SettingsFile(livecraft_paths.file(FileName.CONFIG)).install_shipped()
    drive: FakeDriveService = FakeDriveService()
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, drive=drive, without=(RunPart.DRIVE_PREVIEWS,)).run()
    assert result.outcome is RunOutcome.DONE and result.previews is not None and result.previews.links == ()
    assert drive.calls == [] and drive.items.keys() == {ROOT_FOLDER_ID}
    [write] = reader.writes
    assert (write.written(SheetOutput.PREVIEW), write.written(SheetOutput.LANGUAGE)) == (0, 2)
    assert len(list(livecraft_paths.dir(DataDir.IMAGE).rglob("*.jpg"))) == 2


def test_without_the_local_previews_the_preview_folder_stays_empty(livecraft_paths: LivecraftPaths) -> None:
    """Линия «Превью на диске» не идёт: папка превью пуста, копии и ссылки — на Диске; превью слота — в памяти."""
    SettingsFile(livecraft_paths.file(FileName.CONFIG)).install_shipped()
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW])
    result: IntakeResult = _intake(
        livecraft_paths, reader, drive=FakeDriveService(), without=(RunPart.LOCAL_PREVIEWS,)
    ).run()
    assert result.outcome is RunOutcome.DONE
    assert list(livecraft_paths.dir(DataDir.IMAGE).rglob("*.*")) == []
    assert result.previews is not None and len(result.previews.links) == 1
    assert msg.PREVIEWS_DRIVE_LINE.format(uploaded=1, kept=0) in result.console_lines
    assert len(result.slots[0].previews) == 1


def test_without_any_preview_line_there_is_no_preview_stage_and_the_languages_are_written(
    livecraft_paths: LivecraftPaths,
) -> None:
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, without=(RunPart.LOCAL_PREVIEWS,)).run()
    assert result.outcome is RunOutcome.DONE and result.previews is None
    assert list(livecraft_paths.dir(DataDir.IMAGE).rglob("*.*")) == []
    [write] = reader.writes
    assert (write.written(SheetOutput.PREVIEW), write.written(SheetOutput.LANGUAGE)) == (0, 1)
    assert len(result.slots[0].previews) == 1


def test_a_drive_failure_is_code_1_the_languages_are_written_and_the_slots_go_on(
    livecraft_paths: LivecraftPaths,
) -> None:
    SettingsFile(livecraft_paths.file(FileName.CONFIG)).install_shipped()
    drive: FakeDriveService = FakeDriveService(failures=[drive_error(403)])
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, drive=drive).run()
    assert result.outcome is RunOutcome.FAILED and result.stopped_at is None and len(result.slots) == 1
    [write] = reader.writes
    assert (write.written(SheetOutput.PREVIEW), write.written(SheetOutput.LANGUAGE)) == (0, 1)
    assert result.previews is not None and result.previews.drive.error is not None
    assert result.previews.drive.error.human in result.console_lines


def test_a_table_that_does_not_take_the_write_is_code_1_and_merge_goes_on(
    livecraft_paths: LivecraftPaths,
) -> None:
    error: SheetsWriteError = SheetsWriteError(SheetsReadReason.NO_ACCESS, "plan(9c2b)", status=403)
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=None)
    reader: _Reader = _Reader(values=MERGE_ROWS, write_error=error)
    result: IntakeResult = _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    assert result.outcome is RunOutcome.FAILED and result.stopped_at is None
    assert result.merge is not None and result.merge.merged == 1 and len(result.slots) == 1
    assert result.table is not None and result.table.error is error
    assert error.human in result.console_lines


def test_a_dry_run_does_not_touch_the_table_write(livecraft_paths: LivecraftPaths) -> None:
    SettingsFile(livecraft_paths.file(FileName.CONFIG)).install_shipped()
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, drive=FakeDriveService(), dry_run=True).run()
    assert result.outcome is RunOutcome.DONE and reader.writes == []
    assert msg.INTAKE_SHEET_WRITE_DRY_RUN_LINE in result.console_lines


def test_of_gives_the_run_openai_when_merge_goes(livecraft_paths: LivecraftPaths) -> None:
    """Merge идёт (ключ в сейфе) — у прогона клиент OpenAI; к OpenAI он не обращается, пока его не спросят."""
    key: SecretValue = SecretValue(field=SecretField.OPENAI_API_KEY, value="sk-test-key-for-intake")
    vault: Vault = Vault.empty().with_field(SecretField.OPENAI_API_KEY, key, VaultOrigin.OWN)
    request: IntakeRequest = IntakeRequest(
        paths=livecraft_paths,
        settings=_settings(livecraft_paths),
        vault=vault,
        now=NOW,
        scope=RunScope(parts=TABLE_SCOPE.parts | {RunPart.MERGE}),
    )
    backend: object = PlanIntake.of(request).merge_backend
    assert isinstance(backend, OpenAiClient) and backend.run_usage.requests == 0


# --- строки лога и повтор ссылки


def test_the_finished_line_names_the_outcome_instead_of_a_code(livecraft_paths: LivecraftPaths) -> None:
    """Строка `intake_finished` пишет исход прогона; число кода решает запуск (app\\run)."""
    with LogCapture.on(LogArea.INTAKE) as intake_log:
        _intake(livecraft_paths, _Reader(values=[HEADER, PAST_ROW])).run()
    [finished] = [line for line in intake_log.messages(logging.INFO) if line.startswith("intake_finished ")]
    assert finished == (
        "intake_finished stopped_at=table sheets_error=- plan_problem=- rows=1 admitted=0 "
        "sources=- ready=- previews=- table_error=- merged=- slots=- refused=- outcome=nothing_planned"
    )


def test_a_failed_table_is_logged_with_its_label_reason_and_status(livecraft_paths: LivecraftPaths) -> None:
    error: SheetsReadError = SheetsReadError(SheetsReadReason.NOT_FOUND, "plan(9c2b)", status=404)
    with LogCapture.on(LogArea.INTAKE) as intake_log:
        _intake(livecraft_paths, _Reader(error=error)).run()
    assert intake_log.messages(logging.ERROR) == [
        "intake_table_failed reason=not_found sheet=plan(9c2b) status=404"
    ]


def test_the_same_link_at_the_same_moment_twice_is_one_source_of_the_slot(livecraft_paths: LivecraftPaths) -> None:
    """Повтор ссылки в тот же момент снимают ряды таблицы (причина — «повтор»): в слоте один источник."""
    fetcher: _Fetcher = _Fetcher()
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW, FUTURE_ROW]), fetcher).run()
    assert result.outcome is RunOutcome.DONE
    assert result.rows is not None and [row.row_number for row in result.rows.admitted] == [2]
    assert [(row.reason, row.duplicate_of) for row in result.rows.skipped] == [(RowSkipReason.DUPLICATE, 2)]
    assert fetcher.calls == [LINK]
    assert result.build is not None
    (slot,) = result.build.slots
    assert slot.sources == ("https://www.youtube.com/watch?v=dQw4w9WgXcQ",)


# --- merge в прогоне (нейросеть — QueueBackend, видео — yt-dlp без сети)

MERGE_LINKS: tuple[str, ...] = tuple(f"https://youtu.be/mergeSrc00{index}" for index in (1, 2, 3))
SINGLE_LINK: str = "https://youtu.be/singleSrc01"
SINGLE_TITLE: str = "Single evening stream about the grid"
MERGE_ROWS: list[list[str]] = [HEADER, *([link, "16.10.2026", "19:00"] for link in MERGE_LINKS)]
SINGLE_ROW: list[str] = [SINGLE_LINK, "17.10.2026", "20:00"]


def _merge_fetcher() -> StubFetcher:
    """Три видео одного вечера с разными описаниями и одно видео другого вечера — все на английском."""
    videos: list[tuple[str, str, str]] = [
        (link, title, body) for link, (title, body) in zip(MERGE_LINKS, EXPANDED_SOURCES)
    ]
    videos.append((SINGLE_LINK, SINGLE_TITLE, "One source only: the grid repair schedule."))
    return StubFetcher({link: video_metadata(link, title, body, "en") for link, title, body in videos})


def test_a_merge_run_gives_the_model_texts_to_the_slot_that_needs_them(livecraft_paths: LivecraftPaths) -> None:
    """Слот из трёх источников получает тексты модели, слот из одного — тексты видео без обращения к нейросети."""
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=None)
    reader: _Reader = _Reader(values=[*MERGE_ROWS, SINGLE_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    assert result.outcome is RunOutcome.DONE and len(backend.requests) == 1
    assert result.merge is not None and result.merge.merged == 1
    assert result.build is not None
    merged, single = result.build.slots
    assert (merged.slot_id, single.slot_id) == ("16-10-2026_1900_en", "17-10-2026_2000_en")
    assert merged.texts.origin is SlotTextOrigin.MERGED and merged.title == TITLE
    assert single.texts.origin is SlotTextOrigin.SOURCE_SINGLE and single.title == SINGLE_TITLE
    assert merged.is_for_youtube and single.is_for_youtube


def test_the_merge_lines_stand_between_the_videos_and_the_slots(livecraft_paths: LivecraftPaths) -> None:
    """Порядок строк: таблица, видео, превью, запись в таблицу, модель, итог merge, расход, слоты; ни названий, ни
    описаний видео."""
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=None)
    reader: _Reader = _Reader(values=[*MERGE_ROWS, SINGLE_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    assert result.sources is not None and result.merge is not None
    assert result.build is not None
    lines: tuple[str, ...] = result.console_lines
    assert result.previews is not None and result.table is not None
    assert lines[1] == result.sources.console_line and lines[2:3] == result.previews.console_lines
    assert lines[3:4] == result.table.console_lines
    assert lines[4:7] == result.merge.console_lines and len(result.merge.console_lines) == 3
    assert lines[7:] == result.build.console_lines
    text: str = "\n".join(lines)
    for title, body in EXPANDED_SOURCES:
        assert title not in text and body[:40] not in text
    assert SINGLE_TITLE not in text and TITLE not in text and FORM_URL not in text


def test_without_a_chosen_model_the_slot_is_numbered_and_not_for_youtube(livecraft_paths: LivecraftPaths) -> None:
    """Модель не выбрана, а merge нужен — тексты «по номерам» (§14 решение 32): слот не для YouTube, строка консоли о
    нём, код 1."""
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=LlmErrorKind.AUTH)
    reader: _Reader = _Reader(values=MERGE_ROWS)
    result: IntakeResult = _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    assert result.outcome is RunOutcome.FAILED and backend.requests == [] and result.stopped_at is None
    assert result.build is not None and result.build.slots[0].texts.origin is SlotTextOrigin.NUMBERED
    assert not result.build.slots[0].is_for_youtube
    assert result.merge is not None and result.merge.choice is not None
    assert result.merge.choice.human in result.console_lines
    numbered: str = msg.INTAKE_SLOT_NOT_FOR_YOUTUBE.format(language="EN", time="19:00", date="16.10.2026")
    assert result.console_lines[-1] == numbered


def test_quota_on_the_first_slot_leaves_the_next_slot_without_requests(livecraft_paths: LivecraftPaths) -> None:
    """Квота на первом слоте — merge остановлен: следующий слот без обращений; оба слота, которым merge нужен, —
    «по номерам» и не для YouTube; слот без нужды в merge — для YouTube (§14 решение 32); код 1."""
    backend: QueueBackend = QueueBackend(replies=[error(LlmErrorKind.QUOTA), answer(STRONG_ANSWER)], probe_kind=None)
    second: list[list[str]] = [[link, "17.10.2026", "20:00"] for link in (MERGE_LINKS[0], SINGLE_LINK)]
    reader: _Reader = _Reader(values=[*MERGE_ROWS, *second, [SINGLE_LINK, "18.10.2026", "21:00"]])
    result: IntakeResult = _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    assert result.outcome is RunOutcome.FAILED and len(backend.requests) == 1
    assert result.merge is not None
    assert [slot.video_reason for slot in result.merge.slots] == [
        VideoTextReason.STOPPED, VideoTextReason.STOPPED, VideoTextReason.FEW_DESCRIPTIONS,
    ]
    assert result.build is not None and len(result.build.not_for_youtube) == 2
    assert [slot.slot_id for slot in result.build.for_youtube] == ["18-10-2026_2100_en"]
    stopped: str = msg.INTAKE_MERGE_STOPPED.format(failure=error(LlmErrorKind.QUOTA).failure.human)
    assert stopped in result.console_lines


def test_a_run_of_single_source_slots_asks_the_model_nothing(livecraft_paths: LivecraftPaths) -> None:
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=None)
    reader: _Reader = _Reader(values=[HEADER, SINGLE_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    assert result.outcome is RunOutcome.DONE
    assert backend.probes == [] and backend.requests == []
    assert result.merge is not None and result.merge.choice is None
    assert result.console_lines[4] == result.merge.console_lines[0]


def test_without_merge_there_is_no_merge_stage(livecraft_paths: LivecraftPaths) -> None:
    """Нейросеть не идёт: стадии merge нет, строк нейросети нет; слот из нескольких видео — «по номерам», только для
    людей (§14 решение 50), и это не ошибка."""
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=MERGE_ROWS), _merge_fetcher()).run()
    assert result.outcome is RunOutcome.DONE and result.merge is None
    assert result.build is not None and result.build.slots[0].texts.origin is SlotTextOrigin.NUMBERED
    # таблица, видео, превью, запись в таблицу, слоты
    assert len(result.console_lines) == 5 and result.console_lines[-1] == result.build.console_lines[0]


def test_the_slots_of_the_run_are_every_good_slot_numbered_ones_too(livecraft_paths: LivecraftPaths) -> None:
    """Годные слоты прогона — те, по которым идут вывод и эфиры: слот «по номерам» среди них, хоть на YouTube он и не
    идёт (§14 решение 32); прогон, остановленный до слотов, слотов не даёт."""
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=MERGE_ROWS), _merge_fetcher()).run()
    assert result.build is not None and result.slots == result.build.slots and len(result.slots) == 1
    assert result.slots[0].texts.origin is SlotTextOrigin.NUMBERED and not result.slots[0].is_for_youtube
    assert IntakeResult(stopped_at=IntakeStage.TABLE).slots == ()


def test_the_finished_line_counts_the_slots_with_model_texts(livecraft_paths: LivecraftPaths) -> None:
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=None)
    with LogCapture.on(LogArea.INTAKE) as intake_log:
        reader: _Reader = _Reader(values=[*MERGE_ROWS, SINGLE_ROW])
        _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    [finished] = [line for line in intake_log.messages(logging.INFO) if line.startswith("intake_finished ")]
    assert " sources=4 ready=4 previews=local table_error=- merged=1 slots=2 refused=0 outcome=done" in finished


# --- полка пакетов прогону таблицы не указ (§14 решение 50)


def test_a_slot_already_in_a_package_goes_to_merge_all_the_same(livecraft_paths: LivecraftPaths) -> None:
    """Тексты из пакетов при входе «Таблица» ушли (§14 решение 50): слот с тем же slot_id и теми же видео в пакете
    полки всё равно получает тексты нейросети."""
    record: dict[str, Any] = slot_record("16-10-2026", "19:00", "en", "Evening stream from the package")
    record["sources"] = [f"https://www.youtube.com/watch?v={link.rsplit('/', 1)[-1]}" for link in MERGE_LINKS]
    write_package(livecraft_paths.bcast_dir, manifest(record, generated_at="30-09-2026 10:00"))
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=None)
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=MERGE_ROWS), _merge_fetcher(), backend=backend).run()
    assert len(backend.requests) == 1 and result.merge is not None and result.merge.merged == 1
    assert result.build is not None and result.build.slots[0].title == TITLE


def test_every_admitted_row_is_a_log_line(livecraft_paths: LivecraftPaths) -> None:
    """Решение 38: допущенный ряд — строкой лога с ссылкой, ячейками и моментом старта; отсеянный — своей строкой."""
    with LogCapture.on(LogArea.INTAKE) as intake_log:
        _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW, PAST_ROW])).run()
    admitted: list[str] = [line for line in intake_log.messages() if line.startswith("sheet_row_admitted")]
    assert admitted == [
        f"sheet_row_admitted row=2 link={LINK} date=16.10.2026 time=19:00 start=2026-10-16T19:00:00+03:00"
    ]


# --- строки хода в консоли (CLAUDE.md §13 задача 9.5)


def test_the_run_says_each_video_and_each_drive_copy_as_it_goes(livecraft_paths: LivecraftPaths) -> None:
    """Три ряда с превью и Google Диск: строки хода — три видео по рядам, затем три копии на Диск; в итоговых строках
    прогона (они идут в отчёт) строк хода нет."""
    SettingsFile(livecraft_paths.file(FileName.CONFIG)).install_shipped()
    record: ConsoleRecord = ConsoleRecord()
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW, BROKEN_ROW])
    result: IntakeResult = _intake(
        livecraft_paths, reader, drive=FakeDriveService(), progress=StageProgress(record.console)
    ).run()
    assert result.outcome is RunOutcome.DONE
    assert record.lines == [
        f"Чтение видео 1 из 3: {LINK}", f"Чтение видео 2 из 3: {OTHER_LINK}", f"Чтение видео 3 из 3: {BROKEN_LINK}",
        *(msg.PROGRESS_DRIVE_PREVIEW.format(place=place, total=3) for place in (1, 2, 3)),
    ]
    assert not set(record.lines) & set(result.console_lines)


def test_the_run_says_each_slot_that_goes_to_the_model(livecraft_paths: LivecraftPaths) -> None:
    """Три группы, merge нужен двум: после строк видео — две строки нейросети; слот из одного видео строки не даёт."""
    record: ConsoleRecord = ConsoleRecord()
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER), answer(STRONG_ANSWER)], probe_kind=None)
    second: list[list[str]] = [[link, "17.10.2026", "20:00"] for link in MERGE_LINKS]
    reader: _Reader = _Reader(values=[*MERGE_ROWS, *second, [SINGLE_LINK, "18.10.2026", "21:00"]])
    result: IntakeResult = _intake(
        livecraft_paths, reader, _merge_fetcher(), backend=backend, progress=StageProgress(record.console)
    ).run()
    assert len(result.slots) == 3 and len(backend.requests) == 2
    videos: list[str] = [line for line in record.lines if line.startswith("Чтение видео")]
    assert len(videos) == 7 and record.lines[:7] == videos and videos[-1].startswith("Чтение видео 7 из 7: ")
    assert record.lines[7:] == [
        "Нейросеть: слот 1 из 2 — 16.10.2026 19:00 en.", "Нейросеть: слот 2 из 2 — 17.10.2026 20:00 en.",
    ]


def test_a_dry_run_says_the_videos_but_no_drive_copy(livecraft_paths: LivecraftPaths) -> None:
    """Пробный запуск: видео читаются — их строки есть; на Диск ничего не идёт — строк копий нет."""
    SettingsFile(livecraft_paths.file(FileName.CONFIG)).install_shipped()
    record: ConsoleRecord = ConsoleRecord()
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW])
    _intake(
        livecraft_paths, reader, drive=FakeDriveService(), dry_run=True, progress=StageProgress(record.console)
    ).run()
    assert record.lines == [f"Чтение видео 1 из 2: {LINK}", f"Чтение видео 2 из 2: {OTHER_LINK}"]


def test_without_a_console_the_run_says_nothing(livecraft_paths: LivecraftPaths, capsys: pytest.CaptureFixture[str]) -> None:
    SettingsFile(livecraft_paths.file(FileName.CONFIG)).install_shipped()
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW])
    assert _intake(livecraft_paths, reader, drive=FakeDriveService()).run().outcome is RunOutcome.DONE
    assert capsys.readouterr().out == ""
