"""Шаг «запись в таблицу» прогона режима А (app\\intake\\table_stage.py, CLAUDE.md §6 инвариант 3, §14 решения 27,
29): язык годного видео и ссылка на копию превью — в строку видео одной записью. Диск — подделка в памяти, таблица —
читатель, который запоминает записи; к Google тесты не ходят."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from app.config.files import ShippedSettings
from app.config.settings import LivecraftSettings
from app.intake.preview_stage import PreviewCopies, PreviewMode, PreviewResult, PreviewStage
from app.intake.table_stage import TableResult, TableStage
from app.observability.log_event import LogArea
from app.secretsafe.vault import Vault
from app.sheets.client import SheetsReader, SheetsReadReason, SheetsWriteError
from app.sheets.plan import SheetPlan
from app.sheets.preview import LANGUAGE_HEADER, PREVIEW_HEADER, SheetOutput, SheetWrite
from app.slots.preview import Preview
from app.sources.metadata import SourceFailureReason
from app.sources.video import PreparedSources
from app.tests.fixtures.drive import ROOT_FOLDER_ID, FakeDriveService, drive_client
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.settings import drive_vault
from app.tests.fixtures.sources import admitted_row, failed_source, ready_source
from app.ui import messages_ru as msg

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
DAY: datetime = datetime(2026, 9, 28, 19, 0, tzinfo=KYIV)
LINKS: tuple[str, ...] = (
    "https://youtu.be/dQw4w9WgXcQ", "https://youtu.be/aB3_-xYz012", "https://youtu.be/Zx9_8yW7v6U",
)
PREVIEW: Preview = Preview(data=b"\xff\xd8preview\xff\xd9", width=1280, height=720)


def _sources() -> PreparedSources:
    """Строки 2–4: украинское и русское видео с превью, строка 4 — видео, за которым yt-dlp отказал."""
    return PreparedSources((
        ready_source(admitted_row(2, LINKS[0], DAY), "Привіт, світе", "Опис", "uk", PREVIEW),
        ready_source(admitted_row(3, LINKS[1], DAY), "Съешь ещё булок", "Описание", "ru", PREVIEW),
        failed_source(admitted_row(4, LINKS[2], DAY), SourceFailureReason.UNAVAILABLE),
    ))


def _plan(languages: tuple[str, ...] | None = None) -> SheetPlan:
    """Лист плана со строками 2–4; колонка языка «Lang» перед ссылкой, датой и временем — если заданы её ячейки."""
    header: list[str] = ["Links", "Date", "Time"] if languages is None else [LANGUAGE_HEADER, "Links", "Date", "Time"]
    rows: list[list[str]] = [
        [*(() if languages is None else (languages[index],)), link, "28.09.2026", "19:00"]
        for index, link in enumerate(LINKS)
    ]
    return SheetPlan.from_values("План", 7, [header, *rows])


@dataclass
class _Table:
    """Читатель таблицы без Google: записи запоминаются; сбой записи — если задан."""

    error: SheetsWriteError | None = None
    writes: list[SheetWrite] = field(default_factory=list)

    def write_outputs(self, vault: Vault, write: SheetWrite) -> None:
        self.writes.append(write)
        if self.error is not None:
            raise self.error


class _Untouchable:
    """Читатель, к которому шаг не должен обращаться вовсе."""

    def write_outputs(self, vault: Vault, write: SheetWrite) -> None:
        raise AssertionError("пробный запуск к таблице не обращается")


def _previews(tmp_path: Path, mode: PreviewMode) -> PreviewResult:
    """Итог этапа превью на тех же видео: в полном режиме — копии на поддельном Диске и ссылки на них."""
    settings: LivecraftSettings = ShippedSettings().settings
    stage: PreviewStage = PreviewStage(
        tmp_path, settings, drive_vault(ROOT_FOLDER_ID), mode, lambda: drive_client(FakeDriveService())
    )
    return stage.run(PreviewCopies.of(_sources().videos, KYIV))


def _run(reader: object, previews: PreviewResult, plan: SheetPlan, dry_run: bool = False) -> TableResult:
    table: SheetsReader = reader  # type: ignore[assignment]
    return TableStage(Vault.empty(), dry_run).run(plan, _sources(), previews, table)


def test_without_the_drive_folder_the_languages_are_written_and_no_links(tmp_path: Path) -> None:
    """Часть «превью на Диске» не идёт (LOCAL): ссылок нет, языки годных видео пишутся, «обрезать» — нечего; строка
    итога — только о языках (о ссылках, которых программа не пишет, «записано 0» было бы неправдой)."""
    table: _Table = _Table()
    result: TableResult = _run(table, _previews(tmp_path, PreviewMode.LOCAL), _plan(("", "", "")))
    [write] = table.writes
    assert write.values_body["data"] == [
        {"range": "'План'!A2", "values": [["uk"]]},
        {"range": "'План'!A3", "values": [["ru"]]},
    ]
    assert not write.has_clip and not result.has_errors
    assert result.console_lines == (msg.INTAKE_SHEET_WRITE_LANGUAGES_LINE.format(languages=2, languages_kept=0),)


def test_full_mode_writes_languages_and_links_in_one_body_and_clips_only_the_links(tmp_path: Path) -> None:
    table: _Table = _Table()
    previews: PreviewResult = _previews(tmp_path, PreviewMode.FULL)
    result: TableResult = _run(table, previews, _plan(("", "", "")))
    [write] = table.writes
    first, second = previews.links
    assert write.values_body["data"] == [
        {"range": "'План'!E1", "values": [[PREVIEW_HEADER]]},
        {"range": "'План'!E2", "values": [[first.text]]},
        {"range": "'План'!E3", "values": [[second.text]]},
        {"range": "'План'!A2", "values": [["uk"]]},
        {"range": "'План'!A3", "values": [["ru"]]},
    ]
    requests: list[dict[str, dict[str, dict[str, int]]]] = write.clip_body["requests"]  # type: ignore[assignment]
    assert [request["repeatCell"]["range"]["startColumnIndex"] for request in requests] == [4, 4]
    assert result.console_lines == (
        msg.INTAKE_SHEET_WRITE_LINE.format(languages=2, languages_kept=0, links=2, links_kept=0),
    )


def test_a_plan_without_a_language_column_gets_the_added_lang_column() -> None:
    """Колонки языка на листе нет: программа добавляет «Lang» справа от последнего заголовка и пишет языки туда."""
    table: _Table = _Table()
    _run(table, PreviewResult(mode=PreviewMode.LOCAL, saved=0), _plan())
    [write] = table.writes
    assert write.values_body["data"] == [
        {"range": "'План'!D1", "values": [["Lang"]]},
        {"range": "'План'!D2", "values": [["uk"]]},
        {"range": "'План'!D3", "values": [["ru"]]},
    ]


def test_only_the_ready_videos_give_their_language() -> None:
    """Строка 4 — видео, за которым yt-dlp отказал: языка у него нет, в его строку ничего не пишется."""
    table: _Table = _Table()
    _run(table, PreviewResult(mode=PreviewMode.LOCAL, saved=0), _plan(("", "", "")))
    [write] = table.writes
    assert [cell.row_number for change in write.changes for cell in change.changed] == [2, 3]


def test_languages_already_in_place_are_not_written_and_the_table_is_not_asked() -> None:
    """«UK» и «ru» уже стоят: писать нечего — к таблице не обращаются, в строке — сколько уже стояли."""
    table: _Table = _Table()
    result: TableResult = _run(table, PreviewResult(mode=PreviewMode.LOCAL, saved=0), _plan(("UK", " ru ", "")))
    assert table.writes == []
    assert result.console_lines == (msg.INTAKE_SHEET_WRITE_LANGUAGES_LINE.format(languages=0, languages_kept=2),)


def test_a_dry_run_does_not_touch_the_table(tmp_path: Path) -> None:
    result: TableResult = _run(_Untouchable(), _previews(tmp_path, PreviewMode.DRY_RUN), _plan(), dry_run=True)
    assert result.console_lines == (msg.INTAKE_SHEET_WRITE_DRY_RUN_LINE,) and not result.has_errors


def test_a_table_that_does_not_take_the_write_is_an_error_line_and_nothing_counts_as_written() -> None:
    error: SheetsWriteError = SheetsWriteError(SheetsReadReason.NO_ACCESS, "таблица плана (ab12)", 403)
    result: TableResult = _run(_Table(error=error), PreviewResult(mode=PreviewMode.LOCAL, saved=0), _plan())
    assert result.has_errors and result.error is error
    assert result.written(SheetOutput.LANGUAGE) == 0
    assert result.console_lines == (
        msg.INTAKE_SHEET_WRITE_LANGUAGES_LINE.format(languages=0, languages_kept=0),
        error.human,
    )
    assert "язык видео и ссылки на превью не записались" in error.human


def test_the_log_carries_counts_and_the_reason_without_values(tmp_path: Path) -> None:
    error: SheetsWriteError = SheetsWriteError(SheetsReadReason.NO_ACCESS, "plan(9c2b)", 403)
    with LogCapture.on(LogArea.INTAKE) as log:
        _run(_Table(), _previews(tmp_path, PreviewMode.FULL), _plan(("", "", "")))
        _run(_Table(error=error), PreviewResult(mode=PreviewMode.LOCAL, saved=0), _plan())
    lines: list[str] = log.messages()
    assert "sheet_write_finished dry_run=no languages=2 languages_kept=0 links=2 links_kept=0 error=-" in lines
    assert "sheet_write_failed reason=no_access sheet=plan(9c2b)" in lines
    assert not any("drive.google.com" in line for line in lines)
