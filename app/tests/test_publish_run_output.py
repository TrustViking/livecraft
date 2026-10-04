"""Вывод запуска от слотов любого входа (app\\publish\\run_output.py, §14 решения 50, 51): пакет — по пакету на форму
из слотов для YouTube, строки части «Пакет» в консоли и отчёте, код; части, которые не идут, ничего не делают."""
from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

from app.config.settings import FormSettings, LivecraftSettings
from app.packages.package_slot import PackageSlot
from app.packages.run_slots import RunSlots
from app.paths import LivecraftPaths
from app.publish.run_output import RunOutput
from app.run.exit_code import ExitCode
from app.run.line_plan import RunScope
from app.run.mode import RunPart
from app.run.progress import StepCount
from app.run.run_report import RunJournal
from app.secretsafe.vault import Vault
from app.slots.slot import StreamSlot
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.tests.fixtures.announce import KYIV, stream_slot
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.packages import PACKAGE_FORM_URL, package_settings
from app.ui import messages_ru as msg

SETTINGS: LivecraftSettings = package_settings(PACKAGE_FORM_URL)
PACKAGE_ONLY: RunScope = RunScope(frozenset({RunPart.PLAN, RunPart.MERGE, RunPart.PACKAGE}))
YOUTUBE: StreamSlot = stream_slot(datetime(2026, 10, 16, 19, 0, tzinfo=KYIV))
NUMBERED: StreamSlot = stream_slot(
    datetime(2026, 10, 16, 20, 0, tzinfo=KYIV), "en", SlotTexts("1) Видео", "", SlotTextOrigin.NUMBERED)
)


def _output(paths: LivecraftPaths, record: ConsoleRecord, scope: RunScope = PACKAGE_ONLY) -> RunOutput:
    ids: list[str] = ["first-id", "second-id"]
    journal: RunJournal = RunJournal(record.console, dry_run=scope.dry_run)
    return RunOutput(paths, SETTINGS, Vault.empty(), scope, journal, new_id=lambda: ids.pop(0))


def _manifest(path: Path) -> dict[str, Any]:
    with zipfile.ZipFile(path) as archive:
        data: dict[str, Any] = json.loads(archive.read("manifest.json"))
    return data


def test_the_package_takes_only_the_slots_for_youtube(livecraft_paths: LivecraftPaths) -> None:
    """Слот «по номерам» — только для людей (§14 решение 32): в пакет идёт слот для YouTube, строка части — в консоль."""
    record: ConsoleRecord = ConsoleRecord()
    slots: RunSlots = RunSlots.of_table((YOUTUBE, NUMBERED), SETTINGS.form)
    assert _output(livecraft_paths, record).run(slots, None) is ExitCode.OK
    [package] = livecraft_paths.bcast_dir.glob("*.bcast")
    data: dict[str, Any] = _manifest(package)
    assert [slot["slot_id"] for slot in data["slots"]] == [YOUTUBE.slot_id] and data["package_id"] == "first-id"
    assert record.lines == [msg.PACKAGE_WRITTEN.format(path=package, slots=1, previews=1)]


def test_one_package_per_form_of_the_packages(livecraft_paths: LivecraftPaths) -> None:
    """Слоты пакетов двух форм — два пакета, у каждого своя форма и свой id; второй — с номером в имени."""
    record: ConsoleRecord = ConsoleRecord()
    other: FormSettings = package_settings("https://docs.google.com/forms/d/e/OTHER/viewform").form
    slots: RunSlots = RunSlots((PackageSlot(YOUTUBE, SETTINGS.form), PackageSlot(YOUTUBE, other)))
    scope: RunScope = RunScope(frozenset({RunPart.PACKAGES_IN, RunPart.PACKAGE}))
    assert _output(livecraft_paths, record, scope).run(slots, None) is ExitCode.OK
    first, second = sorted(livecraft_paths.bcast_dir.glob("*.bcast"), key=lambda path: len(path.name))
    assert second.name == first.name.replace(".bcast", "-2.bcast")
    assert [_manifest(path)["form"]["url"] for path in (first, second)] == [SETTINGS.form.url, other.url]
    assert len(record.lines) == 2


def test_no_slot_for_youtube_writes_no_package_and_says_so(livecraft_paths: LivecraftPaths) -> None:
    record: ConsoleRecord = ConsoleRecord()
    slots: RunSlots = RunSlots.of_table((NUMBERED,), SETTINGS.form)
    assert _output(livecraft_paths, record).run(slots, None) is ExitCode.OK
    assert list(livecraft_paths.bcast_dir.glob("*.bcast")) == [] and record.lines == [msg.PACKAGE_NO_YOUTUBE_SLOTS]


def test_a_package_without_the_form_is_not_written_and_the_code_is_1(livecraft_paths: LivecraftPaths) -> None:
    """Без ссылки на форму planers пакет не читает: пакета нет, причина — строкой, код 1."""
    record: ConsoleRecord = ConsoleRecord()
    slots: RunSlots = RunSlots.of_table((YOUTUBE,), package_settings("").form)
    assert _output(livecraft_paths, record).run(slots, None) is ExitCode.ERRORS
    assert list(livecraft_paths.bcast_dir.glob("*.bcast")) == []
    assert record.lines == [msg.PACKAGE_NOT_WRITTEN.format(reason=msg.PACKAGE_PROBLEMS["form_not_configured"])]


def test_parts_that_do_not_run_do_nothing(livecraft_paths: LivecraftPaths) -> None:
    """Линии вывода не идут — ни пакета, ни строк."""
    record: ConsoleRecord = ConsoleRecord()
    slots: RunSlots = RunSlots.of_table((YOUTUBE,), SETTINGS.form)
    assert _output(livecraft_paths, record, RunScope(frozenset({RunPart.PLAN}))).run(slots, None) is ExitCode.OK
    assert list(livecraft_paths.bcast_dir.glob("*.bcast")) == [] and record.lines == []


def test_the_progress_of_the_output_speaks_to_the_console_of_the_journal(livecraft_paths: LivecraftPaths) -> None:
    """Строки хода вывода (копии на Диск, документы, объявления, пакет в Telegram) идут на ту же консоль, что строки
    частей (CLAUDE.md §13 задача 9.5); в части отчёта журнала они не попадают."""
    record: ConsoleRecord = ConsoleRecord()
    output: RunOutput = _output(livecraft_paths, record)
    output.progress.doc_started(StepCount(1, 2), "16.10.2026")
    assert record.lines == [msg.PROGRESS_DOC.format(place=1, total=2, date="16.10.2026")]
    assert output.journal.parts == [] and output.journal.launch_lines == []
