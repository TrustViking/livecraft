from __future__ import annotations

import dataclasses
import json
import logging
import zipfile
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.config.loader import FormSettings, LivecraftSettings
from app.core.dates import build_slot_id, parse_iso_start
from app.packages import package as package_module
from app.packages.package import (
    MANIFEST_NAME,
    SCHEMA_VERSION,
    PackageProblem,
    PackageResult,
    SlotPackage,
)
from app.paths import LivecraftPaths
from app.sheets.plan import SheetPlan
from app.sheets.rows import PlanRow
from app.slots.builder import SlotBuilder
from app.slots.slot import StreamSlot
from app.sources.preview import Preview
from app.sources.video import SourceVideo
from app.tests.conftest import SHIPPED_SETTINGS, LogCollector, ready_source
from app.ui import messages_ru as msg
from app.version import APP_VERSION

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
NOW: datetime = datetime(2026, 10, 1, 12, 0, tzinfo=KYIV)
GENERATED_AT: datetime = datetime(2026, 10, 1, 9, 5, tzinfo=timezone.utc)     # 12:05 по Киеву
PACKAGE_ID: str = "01-10-2026_120500"
FORM_URL: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-package-test/viewform"
HEADER: list[str] = ["Links", "Date", "Time"]
IDS: tuple[str, ...] = ("dQw4w9WgXcQ", "aB3_-xYz012", "Zx9_8yW7v6U", "Qw3_rTy8uI0")
# Верхний уровень манифеста — ровно схема донора (restreamer _build_manifest_payload), в том же порядке.
MANIFEST_KEYS: list[str] = [
    "schema_version", "package_id", "generated_at", "generator", "timezone", "period", "form", "slots",
]
PREVIEW_A: Preview = Preview(data=b"\xff\xd8jpeg-a", width=1280, height=720)
PREVIEW_B: Preview = Preview(data=b"\xff\xd8jpeg-b", width=640, height=360)
PREVIEW_C: Preview = Preview(data=b"\xff\xd8jpeg-c", width=1920, height=1080)


def link(index: int) -> str:
    return f"https://youtu.be/{IDS[index]}"


def settings(url: str = FORM_URL) -> LivecraftSettings:
    """Поставочные настройки, разобранные боевым загрузчиком, с заданной ссылкой на форму."""
    shipped: LivecraftSettings = SHIPPED_SETTINGS.settings
    return dataclasses.replace(shipped, form=dataclasses.replace(shipped.form, url=url))


def build_slots() -> tuple[StreamSlot, ...]:
    """Три слота настоящим путём 3.1 → 3.5: 16.10 19:00 uk (две обложки), 16.10 19:00 en (без обложки),
    18.10 20:00 uk (одна обложка)."""
    rows: tuple[PlanRow, ...] = SheetPlan.from_values(
        [
            HEADER,
            [link(0), "16.10.2026", "19:00"],
            [link(1), "16.10.2026", "19:00"],
            [link(2), "16.10.2026", "19:00"],
            [link(3), "18.10.2026", "20:00"],
        ]
    ).plan_rows(KYIV, NOW)
    first, second, third, fourth = rows
    videos: tuple[SourceVideo, ...] = (
        ready_source(first, "Эфир один", "Описание один", "uk", PREVIEW_A),
        ready_source(second, "Эфир два", "Описание два", "uk", PREVIEW_B),
        ready_source(third, "Stream three", "Description three", "en"),
        ready_source(fourth, "Эфир четыре", "", "uk", PREVIEW_C),
    )
    return SlotBuilder(zone=KYIV).build(videos).slots


def make_package(slots: tuple[StreamSlot, ...] | None = None, url: str = FORM_URL) -> SlotPackage:
    return SlotPackage.of(
        build_slots() if slots is None else slots, settings(url), GENERATED_AT, PACKAGE_ID
    )


def read_archive(path: Path) -> tuple[list[str], dict[str, Any], dict[str, bytes]]:
    with zipfile.ZipFile(path) as archive:
        names: list[str] = archive.namelist()
        manifest: dict[str, Any] = json.loads(archive.read(MANIFEST_NAME).decode("utf-8"))
        contents: dict[str, bytes] = {name: archive.read(name) for name in names}
    return names, manifest, contents


@pytest.fixture
def package_log() -> Iterator[LogCollector]:
    logger: logging.Logger = logging.getLogger("livecraft.packages")
    collector: LogCollector = LogCollector()
    level: int = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(collector)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(level)


@pytest.fixture
def written(livecraft_paths: LivecraftPaths) -> PackageResult:
    return make_package().write(livecraft_paths.bcast_dir)


# --- запись


def test_the_package_lands_in_bcast_under_the_template_name(
    livecraft_paths: LivecraftPaths, written: PackageResult
) -> None:
    assert written.problem is None and written.is_written
    assert written.path == livecraft_paths.bcast_dir / "plan_16-10-2026_18-10-2026_gen01-10-2026-1205.bcast"
    assert written.path.is_file()
    assert (written.slots, written.previews) == (3, 3)
    assert written.size_bytes == written.path.stat().st_size
    assert [item.name for item in livecraft_paths.bcast_dir.iterdir()] == [written.path.name]


def test_manifest_is_the_first_entry_and_follows_the_donor_schema(written: PackageResult) -> None:
    assert written.path is not None
    names, manifest, _ = read_archive(written.path)
    assert names[0] == MANIFEST_NAME
    assert list(manifest) == MANIFEST_KEYS
    assert type(manifest["schema_version"]) is int and manifest["schema_version"] == SCHEMA_VERSION == 1
    assert manifest["package_id"] == PACKAGE_ID
    assert manifest["generated_at"] == "01-10-2026 12:05"          # местное время, DD-MM-YYYY HH:MM
    assert manifest["generator"] == {"project": "livecraft", "version": APP_VERSION, "run_id": PACKAGE_ID}
    assert manifest["timezone"] == "Europe/Kyiv"
    assert manifest["period"] == {"from": "16-10-2026", "to": "18-10-2026"}


def test_form_carries_the_url_and_all_nine_questions(written: PackageResult) -> None:
    assert written.path is not None
    form: dict[str, Any] = read_archive(written.path)[1]["form"]
    expected: FormSettings = settings().form
    assert list(form) == ["url", "fields", "values", "date_format"]
    assert form["url"] == FORM_URL
    assert tuple(form["fields"]) == FormSettings.FIELD_KEYS
    assert form["fields"] == expected.fields
    assert form["values"] == expected.values
    assert form["date_format"] == expected.date_format


def test_slots_follow_start_then_language_and_pass_the_reader_rules(written: PackageResult) -> None:
    """Правила planers _ManifestParser._slot: slot_id по дате, времени и языку, start со смещением, title не пуст."""
    assert written.path is not None
    slots: list[dict[str, Any]] = read_archive(written.path)[1]["slots"]
    assert [slot["slot_id"] for slot in slots] == [
        "16-10-2026_1900_en", "16-10-2026_1900_uk", "18-10-2026_2000_uk",
    ]
    for slot in slots:
        assert slot["slot_id"] == build_slot_id(slot["date"], slot["time"], slot["language"])
        assert parse_iso_start(slot["start"]).utcoffset() is not None
        assert slot["title"].strip()
        assert slot["sources"] and all(isinstance(source, str) and source for source in slot["sources"])


def test_every_preview_name_is_in_the_archive_with_the_preview_bytes(written: PackageResult) -> None:
    assert written.path is not None
    names, manifest, contents = read_archive(written.path)
    by_id: dict[str, dict[str, Any]] = {slot["slot_id"]: slot for slot in manifest["slots"]}
    assert by_id["16-10-2026_1900_uk"]["previews"] == [
        "previews/16-10-2026_1900_uk_1.jpg", "previews/16-10-2026_1900_uk_2.jpg",
    ]
    assert by_id["18-10-2026_2000_uk"]["previews"] == ["previews/18-10-2026_2000_uk_1.jpg"]
    assert contents["previews/16-10-2026_1900_uk_1.jpg"] == PREVIEW_A.data
    assert contents["previews/16-10-2026_1900_uk_2.jpg"] == PREVIEW_B.data
    assert contents["previews/18-10-2026_2000_uk_1.jpg"] == PREVIEW_C.data
    listed: set[str] = {name for slot in manifest["slots"] for name in slot["previews"]}
    assert listed == set(names) - {MANIFEST_NAME}


def test_a_slot_without_previews_has_an_empty_list(written: PackageResult) -> None:
    assert written.path is not None
    slots: list[dict[str, Any]] = read_archive(written.path)[1]["slots"]
    (english,) = [slot for slot in slots if slot["language"] == "en"]
    assert english["previews"] == []


def test_preview_names_are_one_per_preview_numbered_from_one() -> None:
    package: SlotPackage = make_package()
    by_id: dict[str, StreamSlot] = {slot.slot_id: slot for slot in package.slots}
    assert package.preview_names(by_id["16-10-2026_1900_uk"]) == (
        "previews/16-10-2026_1900_uk_1.jpg", "previews/16-10-2026_1900_uk_2.jpg",
    )
    assert package.preview_names(by_id["16-10-2026_1900_en"]) == ()


def test_period_comes_from_the_earliest_and_latest_start() -> None:
    package: SlotPackage = make_package()
    assert (package.period_from, package.period_to) == ("16-10-2026", "18-10-2026")
    only_first: SlotPackage = make_package(package.slots[:1])
    assert (only_first.period_from, only_first.period_to) == ("16-10-2026", "16-10-2026")


def test_generated_at_is_taken_in_the_program_zone() -> None:
    package: SlotPackage = make_package()
    assert package.generated_at.utcoffset() == timedelta(hours=3)
    assert package.generated_at == GENERATED_AT


def test_naive_generated_at_is_a_programming_error() -> None:
    with pytest.raises(ValueError):
        SlotPackage.of(build_slots(), settings(), datetime(2026, 10, 1, 12, 5), PACKAGE_ID)


# --- пакет не пишется


def test_no_slots_writes_nothing(livecraft_paths: LivecraftPaths, package_log: LogCollector) -> None:
    result: PackageResult = make_package(()).write(livecraft_paths.bcast_dir)
    assert result.problem is PackageProblem.NO_SLOTS and result.path is None and not result.is_written
    assert list(livecraft_paths.bcast_dir.iterdir()) == []
    assert package_log.messages(logging.WARNING) == ["package_skipped problem=no_slots slots=0"]


def test_form_not_configured_writes_nothing(livecraft_paths: LivecraftPaths) -> None:
    result: PackageResult = make_package(url="").write(livecraft_paths.bcast_dir)
    assert result.problem is PackageProblem.FORM_NOT_CONFIGURED and result.path is None
    assert list(livecraft_paths.bcast_dir.iterdir()) == []
    assert "Настройки запуска" in result.console_line


def test_no_slots_is_named_before_the_form() -> None:
    assert make_package((), url="").problem is PackageProblem.NO_SLOTS


def test_every_problem_has_a_text() -> None:
    for problem in PackageProblem:
        assert problem.human == msg.PACKAGE_PROBLEMS[problem.value]


def test_a_slot_with_a_problem_does_not_get_into_the_package(package_log: LogCollector) -> None:
    good, *_ = build_slots()
    empty: StreamSlot = dataclasses.replace(good, slot_id="17-10-2026_1900_uk", title="  ")
    package: SlotPackage = make_package((good, empty))
    assert package.slots == (good,)
    assert any(line.startswith("package_slot_refused ") for line in package_log.messages(logging.WARNING))


def test_a_repeated_slot_id_keeps_the_later_slot(package_log: LogCollector) -> None:
    good, *_ = build_slots()
    later: StreamSlot = dataclasses.replace(good, title="Позднее название")
    package: SlotPackage = make_package((good, later))
    assert package.slots == (later,)
    assert package_log.messages(logging.WARNING) == [
        f"package_slot_duplicate slot={good.slot_id} resolution=later_wins"
    ]


# --- сбой записи и замена


def test_bcast_being_a_file_is_an_os_error_and_leaves_no_temp_file(livecraft_paths: LivecraftPaths) -> None:
    blocker: Path = livecraft_paths.root / "blocked"
    blocker.write_text("not a folder", encoding="utf-8")
    with pytest.raises(OSError):
        make_package().write(blocker)
    assert [item.name for item in livecraft_paths.root.iterdir() if item.name.startswith(".plan_")] == []


def test_failed_replace_removes_the_temp_file(
    livecraft_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(source: object, target: object) -> None:
        raise PermissionError("target is locked")

    monkeypatch.setattr(package_module.os, "replace", refuse)
    with pytest.raises(OSError):
        make_package().write(livecraft_paths.bcast_dir)
    assert list(livecraft_paths.bcast_dir.iterdir()) == []


def test_writing_the_same_name_again_replaces_the_package(livecraft_paths: LivecraftPaths) -> None:
    first: PackageResult = make_package().write(livecraft_paths.bcast_dir)
    again: SlotPackage = dataclasses.replace(make_package(), package_id="another-run")
    second: PackageResult = again.write(livecraft_paths.bcast_dir)
    assert first.path == second.path and second.path is not None
    assert read_archive(second.path)[1]["package_id"] == "another-run"
    assert [item.name for item in livecraft_paths.bcast_dir.iterdir()] == [second.path.name]


# --- что видят лог и консоль


def test_log_line_has_no_form_url_and_no_slot_texts(written: PackageResult) -> None:
    assert written.path is not None
    assert written.log_line == (
        f"path={written.path} slots=3 previews=3 size_bytes={written.size_bytes}"
    )
    for text in (written.log_line, written.console_line):
        assert FORM_URL not in text
        assert "Эфир" not in text and "Описание" not in text


def test_writing_logs_one_line_without_the_form_url(
    livecraft_paths: LivecraftPaths, package_log: LogCollector
) -> None:
    result: PackageResult = make_package().write(livecraft_paths.bcast_dir)
    (line,) = package_log.messages(logging.INFO)
    assert line == f"package_written package_id={PACKAGE_ID} {result.log_line}"
    assert FORM_URL not in line


def test_console_line_names_the_path_and_counts(written: PackageResult) -> None:
    assert written.console_line == msg.PACKAGE_WRITTEN.format(path=written.path, slots=3, previews=3)
