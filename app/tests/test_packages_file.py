"""Чтение пакета plan_*.bcast — правила planers `reader.py` на объектах livecraft (режим Б, §14 решение 18)."""
from __future__ import annotations

import json
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.config.settings import LivecraftSettings
from app.packages.package import SlotPackage
from app.packages.package_file import PackageFailure, PackageFault, PackageFile, ReadPackage
from app.packages.package_line import PackageLine, PackageLineStatus
from app.packages.package_slot import FormSlots
from app.slots.preview import Preview
from app.slots.slot import StreamSlot
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.tests.fixtures.packages import (
    KYIV,
    PACKAGE_FORM_URL,
    PACKAGE_NOW,
    jpeg,
    manifest,
    package_settings,
    slot_record,
    write_package,
)
from app.tests.fixtures.pipeline import slot_of
from app.ui import messages_ru as msg

TOMORROW: datetime = datetime(2027, 3, 17, 19, 0, tzinfo=KYIV)
LATER: datetime = datetime(2027, 3, 18, 20, 0, tzinfo=KYIV)


def read(path: Path) -> ReadPackage | PackageFailure:
    return PackageFile(path, KYIV, PACKAGE_NOW).read()


def package_of(path: Path) -> ReadPackage:
    result: ReadPackage | PackageFailure = read(path)
    assert isinstance(result, ReadPackage), result
    return result


def failure_of(path: Path) -> PackageFailure:
    result: ReadPackage | PackageFailure = read(path)
    assert isinstance(result, PackageFailure), result
    return result


def preview(width: int, height: int) -> Preview:
    found: Preview | None = Preview.of_image(jpeg(width, height))
    assert found is not None
    return found


def as_read(slot: StreamSlot) -> StreamSlot:
    """Слот, каким его вернёт чтение пакета: те же ключ, тексты, обложки и источники; тексты — «из пакета»."""
    return StreamSlot(slot.key, SlotTexts(slot.title, slot.description, SlotTextOrigin.PACKAGE), slot.previews, slot.sources)


# --- годный пакет


def test_a_package_written_by_the_program_reads_back_into_the_same_slots_and_form(tmp_path: Path) -> None:
    """Пакет, который пишет режим А (`SlotPackage`), режим Б читает в те же слоты — с обложками — и ту же форму."""
    slots: tuple[StreamSlot, ...] = (
        slot_of(TOMORROW, "uk", previews=(preview(1280, 720), preview(640, 360))),
        slot_of(TOMORROW, "ru"),
        slot_of(LATER, "uk", previews=(preview(1920, 1080),)),
    )
    settings: LivecraftSettings = package_settings(PACKAGE_FORM_URL)
    group: FormSlots = FormSlots(settings.form, slots)
    written: Path | None = SlotPackage.of(group, settings, PACKAGE_NOW, "round-trip").write(tmp_path).path
    assert written is not None
    package: ReadPackage = package_of(written)
    assert [item.slot for item in package.future] == [as_read(slot) for slot in sorted(slots, key=lambda s: (s.start, s.language))]
    assert all(item.form == settings.form for item in package.future)
    assert package.past == () and package.package_id == "round-trip"
    assert package.generated_at == PACKAGE_NOW.replace(second=0, microsecond=0)


def test_a_past_slot_is_an_entry_without_previews_read(tmp_path: Path) -> None:
    """Прошедшему слоту обложки не нужны: их не читают — даже битая обложка пакет не ломает."""
    past: dict[str, Any] = slot_record("15-03-2027", previews=["previews/past.jpg"])
    path: Path = write_package(
        tmp_path, manifest(past, slot_record()), files={"previews/past.jpg": b"not an image"}
    )
    package: ReadPackage = package_of(path)
    [entry] = package.past
    assert entry.slot_id == "15-03-2027_1900_uk" and entry.preview_names == ("previews/past.jpg",)
    assert [item.slot.slot_id for item in package.future] == ["17-03-2027_1900_uk"]


def test_the_texts_of_a_package_are_for_youtube(tmp_path: Path) -> None:
    [item] = package_of(write_package(tmp_path)).future
    assert item.slot.text_origin is SlotTextOrigin.PACKAGE and item.slot.is_for_youtube
    assert item.slot.title == "Эфир из пакета" and item.slot.sources == ("https://www.youtube.com/watch?v=abcdefghijk",)


def test_an_empty_description_and_empty_lists_are_valid(tmp_path: Path) -> None:
    record: dict[str, Any] = slot_record()
    record["description"] = ""
    record["sources"] = []
    [item] = package_of(write_package(tmp_path, manifest(record))).future
    assert item.slot.description == "" and item.slot.sources == () and item.slot.previews == ()


def test_the_line_of_a_package_counts_the_slots_of_the_channel_languages(tmp_path: Path) -> None:
    path: Path = write_package(tmp_path, manifest(slot_record(), slot_record(language="en"), slot_record("15-03-2027")))
    line: PackageLine = package_of(path).line(("uk",))
    assert line == PackageLine(path.name, PackageLineStatus.ACCEPTED, slots_total=3, slots_mine=2)
    assert line.text == f"{path.name} — принят, слотов 3, из них языков каналов 2"


def test_a_package_of_past_slots_only_plans_nothing(tmp_path: Path) -> None:
    path: Path = write_package(tmp_path, manifest(slot_record("14-03-2027"), slot_record("15-03-2027")))
    line: PackageLine = package_of(path).line(("uk",))
    assert line.status is PackageLineStatus.ALL_PAST
    assert line.text == msg.PACKAGE_LINE_TEMPLATES["all_past"].format(file=path.name)


# --- пакет не читается: причина и подробность


def test_not_a_zip(tmp_path: Path) -> None:
    path: Path = tmp_path / "broken.bcast"
    path.write_bytes(b"not a zip")
    failure: PackageFailure = failure_of(path)
    assert failure.fault is PackageFault.NOT_ZIP and path.read_bytes() == b"not a zip"
    assert failure.line.status is PackageLineStatus.DAMAGED
    assert failure.line.text.startswith(f"{path.name} — пакет повреждён: не ZIP-архив (")


def test_no_manifest(tmp_path: Path) -> None:
    path: Path = tmp_path / "empty.bcast"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("previews/a.jpg", jpeg())
    failure: PackageFailure = failure_of(path)
    assert (failure.fault, failure.detail) == (PackageFault.NO_MANIFEST, "manifest.json")


@pytest.mark.parametrize("raw", [b"{not json", b"\xff\xfe", b"[1, 2]"])
def test_a_manifest_that_is_not_a_json_object(tmp_path: Path, raw: bytes) -> None:
    path: Path = tmp_path / "bad.bcast"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", raw)
    assert failure_of(path).fault is PackageFault.BAD_JSON


@pytest.mark.parametrize("version", [2, "1", True, 1.0])
def test_an_unsupported_schema_version(tmp_path: Path, version: object) -> None:
    content: dict[str, Any] = manifest(slot_record())
    content["schema_version"] = version
    failure: PackageFailure = failure_of(write_package(tmp_path, content))
    assert (failure.fault, failure.detail) == (PackageFault.UNSUPPORTED_SCHEMA, str(version))
    assert failure.line.status is PackageLineStatus.UNSUPPORTED_SCHEMA
    assert failure.line.text == f"plan_test.bcast — версия пакета {version} не поддерживается (нужна 1); файл не тронут"


def test_a_missing_schema_version(tmp_path: Path) -> None:
    content: dict[str, Any] = manifest(slot_record())
    del content["schema_version"]
    failure: PackageFailure = failure_of(write_package(tmp_path, content))
    assert (failure.fault, failure.detail) == (PackageFault.MISSING_KEY, "schema_version")


def test_a_missing_form_field_slot_id(tmp_path: Path) -> None:
    content: dict[str, Any] = manifest(slot_record())
    del content["form"]["fields"]["slot_id"]
    failure: PackageFailure = failure_of(write_package(tmp_path, content))
    assert (failure.fault, failure.detail) == (PackageFault.MISSING_KEY, "form.fields.slot_id")


def test_an_unknown_form_field(tmp_path: Path) -> None:
    content: dict[str, Any] = manifest(slot_record())
    content["form"]["fields"]["extra"] = "Лишний вопрос"
    failure: PackageFailure = failure_of(write_package(tmp_path, content))
    assert (failure.fault, failure.detail) == (PackageFault.BAD_VALUE, "form.fields.extra")


def test_a_form_without_a_link_is_a_bad_value(tmp_path: Path) -> None:
    """Без ссылки ключ отправлять некуда: пакет повреждён."""
    failure: PackageFailure = failure_of(write_package(tmp_path, manifest(slot_record(), form_url="")))
    assert (failure.fault, failure.detail) == (PackageFault.BAD_VALUE, "form.url=''")


@pytest.mark.parametrize(
    ("key", "value", "detail"),
    [
        ("package_id", "", "package_id=''"),
        ("timezone", 5, "timezone=5"),
        ("generator", "Livecraft", "generator='Livecraft'"),
        ("generated_at", "2027-03-15 10:00", "generated_at='2027-03-15 10:00'"),
        ("period", {"from": "15.03.2027", "to": "17-03-2027"}, "period.from='15.03.2027'"),
        ("slots", {}, "slots={}"),
    ],
)
def test_a_bad_head_value_names_its_path(tmp_path: Path, key: str, value: object, detail: str) -> None:
    content: dict[str, Any] = manifest(slot_record())
    content[key] = value
    failure: PackageFailure = failure_of(write_package(tmp_path, content))
    assert (failure.fault, failure.detail) == (PackageFault.BAD_VALUE, detail)


@pytest.mark.parametrize(
    "key", ["slot_id", "date", "time", "start", "language", "title", "description", "previews", "sources"]
)
def test_a_missing_slot_field_names_its_path(tmp_path: Path, key: str) -> None:
    record: dict[str, Any] = slot_record()
    del record[key]
    failure: PackageFailure = failure_of(write_package(tmp_path, manifest(slot_record("18-03-2027"), record)))
    assert (failure.fault, failure.detail) == (PackageFault.MISSING_KEY, f"slots[1].{key}")


@pytest.mark.parametrize(
    ("key", "value"),
    [("slot_id", "17-03-2027_1900_ru"), ("date", "18-03-2027"), ("time", "20:00"), ("language", "ru")],
)
def test_the_slot_id_must_match_the_date_the_time_and_the_language(tmp_path: Path, key: str, value: str) -> None:
    record: dict[str, Any] = slot_record()
    record[key] = value
    failure: PackageFailure = failure_of(write_package(tmp_path, manifest(record)))
    assert failure.fault is PackageFault.BAD_VALUE and failure.detail.startswith("slots[0].")


def test_a_naive_start_is_rejected(tmp_path: Path) -> None:
    record: dict[str, Any] = slot_record()
    record["start"] = "2027-03-17T19:00:00"
    failure: PackageFailure = failure_of(write_package(tmp_path, manifest(record)))
    assert (failure.fault, failure.detail) == (PackageFault.BAD_VALUE, "slots[0].start='2027-03-17T19:00:00'")


def test_an_empty_title_is_rejected(tmp_path: Path) -> None:
    failure: PackageFailure = failure_of(write_package(tmp_path, manifest(slot_record(title=" "))))
    assert (failure.fault, failure.detail) == (PackageFault.BAD_VALUE, "slots[0].title=' '")


def test_a_duplicate_slot_id(tmp_path: Path) -> None:
    failure: PackageFailure = failure_of(write_package(tmp_path, manifest(slot_record(), slot_record(title="Второй"))))
    assert (failure.fault, failure.detail) == (PackageFault.DUPLICATE_SLOT, "17-03-2027_1900_uk")


def test_a_preview_missing_in_the_archive(tmp_path: Path) -> None:
    path: Path = tmp_path / "plan.bcast"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(manifest(slot_record(previews=["previews/a.jpg"]))))
    failure: PackageFailure = failure_of(path)
    assert (failure.fault, failure.detail) == (PackageFault.PREVIEW_MISSING, "slots[0]: previews/a.jpg")


def test_a_preview_of_a_future_slot_that_is_not_an_image(tmp_path: Path) -> None:
    content: dict[str, Any] = manifest(slot_record(previews=["previews/a.jpg"]))
    failure: PackageFailure = failure_of(write_package(tmp_path, content, files={"previews/a.jpg": b"text"}))
    assert (failure.fault, failure.detail) == (PackageFault.PREVIEW_NOT_IMAGE, "previews/a.jpg")
    assert failure.line.text == "plan_test.bcast — пакет повреждён: файл превью в архиве — не картинка (previews/a.jpg); файл не тронут"


def test_every_fault_has_a_reason_text() -> None:
    assert set(msg.PACKAGE_REASON_TEXT) == {fault.value for fault in PackageFault}
