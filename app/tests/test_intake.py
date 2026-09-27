"""Прогон контура A (app\\intake\\intake.py): таблица → ряды → источники → merge → слоты → пакет, исход по §10.

Сеть подменена целиком: читатель таблицы отдаёт `SheetPlan.from_values` из фиксированных значений, yt-dlp —
сохранённый ответ, загрузчик обложек — картинку из памяти, нейросеть — `QueueBackend`; «сейчас» фиксировано.
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
from app.intake.builder import SlotBuilder
from app.intake.intake import IntakeRequest, IntakeResult, IntakeStage, PlanIntake
from app.intake.merge_stage import VideoTextReason
from app.llm.backends.openai import OpenAiClient
from app.llm.errors import LlmErrorKind
from app.observability.log_event import LogArea
from app.paths import LivecraftPaths
from app.run.exit_code import RunOutcome
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.sheets.client import SheetsReadError, SheetsReadReason
from app.sheets.plan import PlanProblem, SheetPlan
from app.sheets.rows import RowSkipReason
from app.slots.texts import SlotProblem, SlotTextOrigin
from app.sources.fetcher import SourceFetch
from app.sources.language import LanguageResolver
from app.sources.metadata import SourceFailureReason, SourceMetadata
from app.sources.preview import PreviewDownloader
from app.sources.video import SourceCatalog
from app.tests.conftest import FORM_URL
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.merges import EXPANDED_SOURCES, STRONG_ANSWER, TITLE, QueueBackend, answer, error
from app.tests.fixtures.settings import set_form_url
from app.tests.fixtures.sources import StubFetcher, video_metadata
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
    SettingsFile(paths.config_file).install_shipped()
    if form_url is not None:
        set_form_url(paths, form_url)
    return SettingsFile(paths.config_file).load()


def _intake(
    paths: LivecraftPaths,
    reader: _Reader,
    fetcher: _Fetcher | StubFetcher | None = None,
    form_url: str | None = FORM_URL,
    backend: QueueBackend | None = None,
) -> PlanIntake:
    """Прогон на подменённой сети; `backend` — нейросеть прогона (None — merge нет, как с --no-llm)."""
    settings: LivecraftSettings = _settings(paths, form_url)
    request: IntakeRequest = IntakeRequest(
        paths=paths,
        settings=settings,
        vault=Vault.empty(),
        now=NOW,
        package_id=PACKAGE_ID,
        with_merge=backend is not None,
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


def test_a_full_run_writes_a_package_that_zipfile_reads(livecraft_paths: LivecraftPaths) -> None:
    reader: _Reader = _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader).run()
    assert result.outcome is RunOutcome.DONE
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
    with LogCapture.on(LogArea.INTAKE) as intake_log:
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
    assert result.package is not None and result.package.is_written      # годный слот всё равно в пакете
    sources: str = result.console_lines[1]
    assert "годных 1 из 2" in sources
    assert msg.INTAKE_COUNT_ITEM.format(name=SourceFailureReason.UNAVAILABLE.human, count=1) in sources


def test_every_source_refused_is_code_1_without_a_package(livecraft_paths: LivecraftPaths) -> None:
    """Слотов нет из-за отказов — это ошибка (1), а не «нет будущих рядов» (3)."""
    fetcher: _Fetcher = _Fetcher({LINK: SourceFailureReason.TOOL_MISSING})
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW]), fetcher).run()
    assert result.outcome is RunOutcome.FAILED
    assert result.stopped_at is IntakeStage.SOURCES
    assert result.build is None and result.package is None
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
        (SheetsReadReason.NO_ACCESS, RunOutcome.FAILED),
        (SheetsReadReason.UNAVAILABLE, RunOutcome.FAILED),
    ],
)
def test_a_table_that_does_not_read_is_a_result_not_an_exception(
    livecraft_paths: LivecraftPaths, reason: SheetsReadReason, outcome: RunOutcome
) -> None:
    error: SheetsReadError = SheetsReadError(reason, "plan(9c2b)", status=403 if reason is SheetsReadReason.NO_ACCESS else None)
    fetcher: _Fetcher = _Fetcher()
    result: IntakeResult = _intake(livecraft_paths, _Reader(error=error), fetcher).run()
    assert result.outcome is outcome
    assert result.sheets_error is error and result.stopped_at is IntakeStage.TABLE
    assert result.console_lines == (error.human,)
    assert fetcher.calls == [] and _packages(livecraft_paths) == []


def test_an_unknown_header_is_code_1(livecraft_paths: LivecraftPaths) -> None:
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[["Что-то", "Ещё"], FUTURE_ROW])).run()
    assert result.outcome is RunOutcome.FAILED
    assert result.plan_problem is PlanProblem.HEADER_UNKNOWN and result.stopped_at is IntakeStage.TABLE
    assert result.plan is not None and result.console_lines == (result.plan.problem_text,)
    assert "«Что-то», «Ещё»" in result.console_lines[0]
    assert result.rows is None and _packages(livecraft_paths) == []


def test_an_empty_range_is_code_1_and_names_the_empty_table(livecraft_paths: LivecraftPaths) -> None:
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[])).run()
    assert result.outcome is RunOutcome.FAILED
    assert result.plan_problem is PlanProblem.EMPTY and result.console_lines == (msg.SHEET_PLAN_EMPTY,)


def test_a_slot_with_an_empty_title_is_refused_and_does_not_get_into_the_package(
    livecraft_paths: LivecraftPaths,
) -> None:
    """Название без границы слова не влезает в 100 символов: слот уходит в отказ, пакет — без него, код 1."""
    fetcher: _Fetcher = _Fetcher(titles={OTHER_LINK: "x" * 150})
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW, OTHER_ROW]), fetcher).run()
    assert result.outcome is RunOutcome.FAILED
    assert result.build is not None
    (refused,) = result.build.refused
    assert (refused.slot_id, refused.problem) == ("17-10-2026_2000_uk", SlotProblem.EMPTY_TITLE)
    assert [slot.slot_id for slot in result.build.slots] == ["16-10-2026_1900_uk"]
    assert result.package is not None and result.package.is_written and result.package.slots == 1
    [package] = _packages(livecraft_paths)
    with zipfile.ZipFile(package) as archive:
        manifest: dict[str, Any] = json.loads(archive.read("manifest.json").decode("utf-8"))
    assert [slot["slot_id"] for slot in manifest["slots"]] == ["16-10-2026_1900_uk"]
    assert result.console_lines[2] == msg.INTAKE_SLOTS_LINE.format(
        count=1,
        languages=msg.INTAKE_SLOTS_LANGUAGES.format(items="uk: 1"),
        refused=msg.INTAKE_SLOTS_REFUSED.format(count=1),
    )


def test_without_the_form_the_package_is_not_written_and_the_code_is_1(livecraft_paths: LivecraftPaths) -> None:
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=[HEADER, FUTURE_ROW]), form_url=None).run()
    assert result.outcome is RunOutcome.FAILED
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
            with_merge=False,
        )


def test_of_wires_the_battle_dependencies_without_touching_google(livecraft_paths: LivecraftPaths) -> None:
    """Боевые зависимости собираются без входа в Google: читатель открывается только в run."""
    settings: LivecraftSettings = _settings(livecraft_paths)
    request: IntakeRequest = IntakeRequest(
        paths=livecraft_paths, settings=settings, vault=Vault.empty(), now=NOW, package_id=PACKAGE_ID, with_merge=False
    )
    intake: PlanIntake = PlanIntake.of(request)
    assert intake.request is request
    assert intake.builder.zone == settings.zone
    assert intake.merge_backend is None                 # merge не идёт — нейросети у прогона нет
    assert not livecraft_paths.sheets_token_file.exists()


def test_of_gives_the_run_openai_when_merge_goes(livecraft_paths: LivecraftPaths) -> None:
    """Merge идёт (ключ в сейфе) — у прогона клиент OpenAI; к OpenAI он не обращается, пока его не спросят."""
    key: SecretValue = SecretValue(field=SecretField.OPENAI_API_KEY, value="sk-test-key-for-intake")
    vault: Vault = Vault.empty().with_field(SecretField.OPENAI_API_KEY, key, VaultOrigin.OWN)
    request: IntakeRequest = IntakeRequest(
        paths=livecraft_paths,
        settings=_settings(livecraft_paths),
        vault=vault,
        now=NOW,
        package_id=PACKAGE_ID,
        with_merge=True,
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
        f"intake_finished package_id={PACKAGE_ID} stopped_at=table sheets_error=- plan_problem=- rows=1 admitted=0 "
        "sources=- ready=- merged=- slots=- refused=- package=- outcome=nothing_planned"
    )


def test_a_failed_table_is_logged_with_its_label_reason_and_status(livecraft_paths: LivecraftPaths) -> None:
    error: SheetsReadError = SheetsReadError(SheetsReadReason.NO_ACCESS, "plan(9c2b)", status=403)
    with LogCapture.on(LogArea.INTAKE) as intake_log:
        _intake(livecraft_paths, _Reader(error=error)).run()
    assert intake_log.messages(logging.ERROR) == [
        f"intake_table_failed package_id={PACKAGE_ID} reason=no_access sheet=plan(9c2b) status=403"
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


def _manifest_slots(paths: LivecraftPaths) -> list[dict[str, Any]]:
    [package] = _packages(paths)
    with zipfile.ZipFile(package) as archive:
        manifest: dict[str, Any] = json.loads(archive.read("manifest.json").decode("utf-8"))
    slots: list[dict[str, Any]] = manifest["slots"]
    return slots


def test_a_merge_run_puts_the_model_texts_into_the_package(livecraft_paths: LivecraftPaths) -> None:
    """Слот из трёх источников получает тексты модели, слот из одного — тексты видео без обращения к нейросети;
    пакет несёт тексты, которые получили слоты."""
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
    slots: list[dict[str, Any]] = _manifest_slots(livecraft_paths)
    assert [(slot["title"], slot["description"]) for slot in slots] == [
        (merged.title, merged.description),
        (single.title, single.description),
    ]


def test_the_merge_lines_stand_between_the_videos_and_the_slots(livecraft_paths: LivecraftPaths) -> None:
    """Порядок строк: таблица, видео, модель, итог merge, расход, слоты, пакет; ни названий, ни описаний видео."""
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=None)
    reader: _Reader = _Reader(values=[*MERGE_ROWS, SINGLE_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    assert result.sources is not None and result.merge is not None
    assert result.build is not None and result.package is not None
    lines: tuple[str, ...] = result.console_lines
    assert lines[1] == result.sources.console_line
    assert lines[2:5] == result.merge.console_lines and len(result.merge.console_lines) == 3
    assert lines[5:] == (result.build.console_line, result.package.console_line)
    text: str = "\n".join(lines)
    for title, body in EXPANDED_SOURCES:
        assert title not in text and body[:40] not in text
    assert SINGLE_TITLE not in text and TITLE not in text and FORM_URL not in text


def test_without_a_chosen_model_the_package_is_written_with_the_video_texts_and_the_code_is_1(
    livecraft_paths: LivecraftPaths,
) -> None:
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=LlmErrorKind.AUTH)
    reader: _Reader = _Reader(values=MERGE_ROWS)
    result: IntakeResult = _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    assert result.outcome is RunOutcome.FAILED and backend.requests == []
    assert result.package is not None and result.package.is_written
    assert result.build is not None and result.build.slots[0].texts.origin is SlotTextOrigin.SOURCE_COMPOSED
    assert result.merge is not None and result.merge.choice is not None
    assert result.merge.choice.human in result.console_lines


def test_quota_on_the_first_slot_leaves_the_next_slot_without_requests(livecraft_paths: LivecraftPaths) -> None:
    """Квота на первом слоте — merge остановлен: следующий слот без обращений, пакет записан, код 1."""
    backend: QueueBackend = QueueBackend(replies=[error(LlmErrorKind.QUOTA), answer(STRONG_ANSWER)], probe_kind=None)
    second: list[list[str]] = [[link, "17.10.2026", "20:00"] for link in (MERGE_LINKS[0], SINGLE_LINK)]
    reader: _Reader = _Reader(values=[*MERGE_ROWS, *second])
    result: IntakeResult = _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    assert result.outcome is RunOutcome.FAILED and len(backend.requests) == 1
    assert result.merge is not None
    assert [slot.video_reason for slot in result.merge.slots] == [VideoTextReason.STOPPED, VideoTextReason.STOPPED]
    assert result.package is not None and result.package.is_written and result.package.slots == 2
    stopped: str = msg.INTAKE_MERGE_STOPPED.format(failure=error(LlmErrorKind.QUOTA).failure.human)
    assert stopped in result.console_lines


def test_a_run_of_single_source_slots_asks_the_model_nothing(livecraft_paths: LivecraftPaths) -> None:
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=None)
    reader: _Reader = _Reader(values=[HEADER, SINGLE_ROW])
    result: IntakeResult = _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    assert result.outcome is RunOutcome.DONE
    assert backend.probes == [] and backend.requests == []
    assert result.merge is not None and result.merge.choice is None
    assert result.console_lines[2] == result.merge.console_lines[0]


def test_without_merge_there_is_no_merge_stage(livecraft_paths: LivecraftPaths) -> None:
    """--no-llm или нет ключа: стадии merge нет, тексты слотов — из видео, строк нейросети нет."""
    result: IntakeResult = _intake(livecraft_paths, _Reader(values=MERGE_ROWS), _merge_fetcher()).run()
    assert result.outcome is RunOutcome.DONE and result.merge is None
    assert result.build is not None and result.build.slots[0].texts.origin is SlotTextOrigin.SOURCE_COMPOSED
    assert len(result.console_lines) == 4


def test_the_finished_line_counts_the_slots_with_model_texts(livecraft_paths: LivecraftPaths) -> None:
    backend: QueueBackend = QueueBackend(replies=[answer(STRONG_ANSWER)], probe_kind=None)
    with LogCapture.on(LogArea.INTAKE) as intake_log:
        reader: _Reader = _Reader(values=[*MERGE_ROWS, SINGLE_ROW])
        _intake(livecraft_paths, reader, _merge_fetcher(), backend=backend).run()
    [finished] = [line for line in intake_log.messages(logging.INFO) if line.startswith("intake_finished ")]
    assert " sources=4 ready=4 merged=1 slots=2 " in finished
