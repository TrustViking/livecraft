"""Прогон контура A (app\\slots\\intake.py): таблица → ряды → источники → слоты → пакет, коды выхода §10.

Сеть подменена целиком: читатель таблицы отдаёт `SheetPlan.from_values` из фиксированных значений, yt-dlp —
сохранённый ответ, загрузчик обложек — картинку из памяти; «сейчас» фиксировано.
"""
from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from app.config.loader import LivecraftSettings, load_settings
from app.core.retry import RetryPolicy
from app.paths import LivecraftPaths
from app.secretsafe.vault import Vault
from app.setup.run_mode import ExitCode
from app.sheets.client import SheetsReadError, SheetsReadReason
from app.sheets.plan import SheetPlan
from app.slots.builder import SlotBuilder
from app.slots.intake import IntakeRequest, IntakeResult, IntakeStage, PlanIntake
from app.sources.fetcher import SourceFailureReason, SourceFetch
from app.sources.language import LanguageResolver
from app.sources.metadata import SourceMetadata
from app.sources.preview import PreviewDownloader
from app.sources.video import SourceCatalog
from app.tests.conftest import FORM_URL, SHIPPED_SETTINGS, set_form_url
from app.ui import messages_ru as msg

DATA_DIR: Path = Path(__file__).resolve().parent / "data" / "ytdlp"
KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
NOW: datetime = datetime(2026, 10, 1, 12, 0, tzinfo=KYIV)
PACKAGE_ID: str = "0123456789abcdef0123456789abcdef"
HEADER: list[str] = ["Links", "Date", "Time"]
LINK: str = "https://youtu.be/dQw4w9WgXcQ"
OTHER_LINK: str = "https://youtu.be/aB3_-xYz012"
BROKEN_LINK: str = "https://youtu.be/Zx9_8yW7v6U"
FUTURE_ROW: list[str] = [LINK, "16.10.2026", "19:00"]
OTHER_ROW: list[str] = [OTHER_LINK, "17.10.2026", "20:00"]
PAST_ROW: list[str] = [LINK, "01.09.2026", "19:00"]
BROKEN_ROW: list[str] = [BROKEN_LINK, "18.10.2026", "19:00"]
RESOLVER: LanguageResolver = LanguageResolver.from_resources()


def _info() -> dict[str, Any]:
    info: Any = json.loads((DATA_DIR / "video_full.json").read_text(encoding="utf-8"))
    assert isinstance(info, dict)
    return info


def _ok_fetch(link: str) -> SourceFetch:
    return SourceFetch.from_metadata(link, SourceMetadata.from_ytdlp(link, _info()))


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

    def __init__(self, failures: dict[str, SourceFailureReason] | None = None) -> None:
        self.failures: dict[str, SourceFailureReason] = failures or {}
        self.calls: list[str] = []

    def fetch(self, url: str) -> SourceFetch:
        self.calls.append(url)
        if url in self.failures:
            return SourceFetch.failed(url, self.failures[url], "stub")
        return _ok_fetch(url)


@dataclass
class _Reader:
    """Читатель таблицы без Google: значения диапазона или сбой; сейф, с которым его позвали, запоминается."""

    values: list[list[str]] = field(default_factory=list)
    error: SheetsReadError | None = None
    vaults: list[Vault] = field(default_factory=list)

    def read_plan(self, vault: Vault) -> SheetPlan:
        self.vaults.append(vault)
        if self.error is not None:
            raise self.error
        return SheetPlan.from_values(self.values)


def _settings(paths: LivecraftPaths, form_url: str | None = FORM_URL) -> LivecraftSettings:
    SHIPPED_SETTINGS.install(paths.config_file)
    if form_url is not None:
        set_form_url(paths, form_url)
    return load_settings(paths.config_file)


def _intake(
    paths: LivecraftPaths,
    reader: _Reader,
    fetcher: _Fetcher | None = None,
    form_url: str | None = FORM_URL,
) -> PlanIntake:
    settings: LivecraftSettings = _settings(paths, form_url)
    request: IntakeRequest = IntakeRequest(
        paths=paths, settings=settings, vault=Vault.empty(), now=NOW, package_id=PACKAGE_ID
    )
    get: Callable[[str, float], _Response] = lambda url, timeout: _Response(200, _png())
    catalog: SourceCatalog = SourceCatalog(
        fetcher=fetcher or _Fetcher(),
        downloader=PreviewDownloader(session_get=get, policy=RetryPolicy(), sleep=lambda _: None),
        resolver=RESOLVER,
    )
    return PlanIntake(
        request=request,
        reader_factory=lambda: reader,       # type: ignore[arg-type, return-value]
        catalog=catalog,
        builder=SlotBuilder(settings.zone),
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


def test_a_full_run_writes_a_package_that_zipfile_reads(livecraft_paths: LivecraftPaths) -> None:
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader).run()
    assert result.exit_code is ExitCode.OK
    assert result.stopped_at is None
    assert result.package is not None and result.package.is_written
    [package] = _packages(livecraft_paths)
    assert result.package.path == package
    with zipfile.ZipFile(package) as archive:
        manifest: dict[str, Any] = json.loads(archive.read("manifest.json").decode("utf-8"))
        assert manifest["package_id"] == PACKAGE_ID
        assert [slot["slot_id"] for slot in manifest["slots"]] == ["16-10-2026_1900_uk", "17-10-2026_2000_uk"]
        assert len([name for name in archive.namelist() if name.startswith("previews/")]) == 2
    assert reader.vaults == [Vault.empty()]


def test_the_console_lines_go_one_per_step_without_titles_or_the_form(livecraft_paths: LivecraftPaths) -> None:
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW])).run()
    lines: tuple[str, ...] = result.console_lines
    assert lines == (
        msg.INTAKE_TABLE_LINE.format(rows=2, admitted=2, skipped=0, reasons=""),
        msg.INTAKE_SOURCES_LINE.format(ready=2, total=2, no_preview=0, failures=""),
        msg.INTAKE_SLOTS_LINE.format(
            count=2, languages=msg.INTAKE_SLOTS_LANGUAGES.format(items="uk: 2"), refused=""
        ),
        result.package.console_line if result.package is not None else "",
    )
    _no_private_text(lines)
    _no_private_text((result.log_line,))


def test_past_rows_and_repeats_are_named_in_the_table_line(livecraft_paths: LivecraftPaths) -> None:
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, PAST_ROW, FUTURE_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader).run()
    assert result.exit_code is ExitCode.OK
    table: str = result.console_lines[0]
    assert "рядов 3, допущено 1, отсеяно 2" in table
    assert msg.INTAKE_COUNT_ITEM.format(name=msg.SHEET_ROW_SKIP_REASONS["in_past"], count=1) in table
    assert msg.INTAKE_COUNT_ITEM.format(name=msg.SHEET_ROW_SKIP_REASONS["duplicate"], count=1) in table


def test_one_link_in_two_rows_is_one_fetch(livecraft_paths: LivecraftPaths) -> None:
    fetcher: _Fetcher = _Fetcher()
    rows: list[list[str]] = [HEADER, FUTURE_ROW, [LINK, "17.10.2026", "20:00"]]
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=rows), fetcher).run()
    assert result.exit_code is ExitCode.OK
    assert fetcher.calls == [LINK]


# --- отказы и остановки


def test_a_refused_source_is_code_1_and_the_reason_is_in_the_sources_line(livecraft_paths: LivecraftPaths) -> None:
    fetcher: _Fetcher = _Fetcher({BROKEN_LINK: SourceFailureReason.UNAVAILABLE})
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW, BROKEN_ROW]), fetcher).run()
    assert result.exit_code is ExitCode.ERRORS
    assert result.package is not None and result.package.is_written      # годный слот всё равно в пакете
    sources: str = result.console_lines[1]
    assert "годных 1 из 2" in sources
    assert msg.INTAKE_COUNT_ITEM.format(name=SourceFailureReason.UNAVAILABLE.human, count=1) in sources


def test_every_source_refused_is_code_1_without_a_package(livecraft_paths: LivecraftPaths) -> None:
    """Слотов нет из-за отказов — это ошибка (1), а не «нет будущих рядов» (3)."""
    fetcher: _Fetcher = _Fetcher({LINK: SourceFailureReason.TOOL_MISSING})
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW]), fetcher).run()
    assert result.exit_code is ExitCode.ERRORS
    assert result.stopped_at is IntakeStage.SOURCES
    assert result.build is None and result.package is None
    assert result.console_lines[-1] == msg.INTAKE_NO_SLOTS
    assert _packages(livecraft_paths) == []


def test_all_rows_in_the_past_is_code_3_without_sources_and_package(livecraft_paths: LivecraftPaths) -> None:
    fetcher: _Fetcher = _Fetcher()
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, PAST_ROW]), fetcher).run()
    assert result.exit_code is ExitCode.NO_FUTURE_SLOTS
    assert result.stopped_at is IntakeStage.TABLE
    assert fetcher.calls == []
    assert result.console_lines[-1] == msg.INTAKE_NO_FUTURE_ROWS
    assert _packages(livecraft_paths) == []


@pytest.mark.parametrize(
    ("reason", "code"),
    [
        (SheetsReadReason.AUTH, ExitCode.CONFIG),
        (SheetsReadReason.NOT_CONFIGURED, ExitCode.CONFIG),
        (SheetsReadReason.NO_ACCESS, ExitCode.ERRORS),
        (SheetsReadReason.UNAVAILABLE, ExitCode.ERRORS),
    ],
)
def test_a_table_that_does_not_read_is_a_result_not_an_exception(
    livecraft_paths: LivecraftPaths, reason: SheetsReadReason, code: ExitCode
) -> None:
    error: SheetsReadError = SheetsReadError(reason, "plan(9c2b)", status=403 if reason is SheetsReadReason.NO_ACCESS else None)
    fetcher: _Fetcher = _Fetcher()
    result: IntakeResult = _intake(livecraft_paths, _Reader(error=error), fetcher).run()
    assert result.exit_code is code
    assert result.sheets_error is error and result.stopped_at is IntakeStage.TABLE
    assert result.console_lines == (error.human,)
    assert fetcher.calls == [] and _packages(livecraft_paths) == []


def test_an_unknown_header_is_code_1(livecraft_paths: LivecraftPaths) -> None:
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[["Что-то", "Ещё"], FUTURE_ROW])).run()
    assert result.exit_code is ExitCode.ERRORS
    assert result.plan_problem is not None and result.console_lines == (result.plan_problem,)
    assert _packages(livecraft_paths) == []


def test_without_the_form_the_package_is_not_written_and_the_code_is_1(livecraft_paths: LivecraftPaths) -> None:
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW]), form_url=None).run()
    assert result.exit_code is ExitCode.ERRORS
    assert result.stopped_at is IntakeStage.PACKAGE
    assert result.package is not None and not result.package.is_written
    assert result.console_lines[-1] == result.package.console_line
    assert _packages(livecraft_paths) == []


def test_the_request_needs_an_aware_now(livecraft_paths: LivecraftPaths) -> None:
    with pytest.raises(ValueError):
        IntakeRequest(
            paths=livecraft_paths,
            settings=_settings(livecraft_paths),
            vault=Vault.empty(),
            now=datetime(2026, 10, 1, 12, 0),
            package_id=PACKAGE_ID,
        )


def test_of_wires_the_battle_dependencies_without_touching_google(livecraft_paths: LivecraftPaths) -> None:
    """Боевые зависимости собираются без входа в Google: читатель открывается только в run."""
    settings: LivecraftSettings = _settings(livecraft_paths)
    request: IntakeRequest = IntakeRequest(
        paths=livecraft_paths, settings=settings, vault=Vault.empty(), now=NOW, package_id=PACKAGE_ID
    )
    intake: PlanIntake = PlanIntake.of(request)
    assert intake.request is request
    assert intake.builder.zone == settings.zone
    assert not livecraft_paths.sheets_token_file.exists()
