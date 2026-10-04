"""Этап «превью» прогона режима А (app\\intake\\preview_stage.py, CLAUDE.md §14 решение 27): копии превью в image\\
по шаблону, на Google Диске по шаблону подпапки и ссылки на копии — итогом этапа. Диск — подделка в памяти; к Google
тесты не ходят. Запись ссылок в таблицу — шаг «запись в таблицу» (test_intake_table_stage.py)."""
from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.config.files import ShippedSettings
from app.config.settings import LivecraftSettings
from app.google.drive import DriveCall, DriveClient, DriveError, DriveReason
from app.intake.preview_stage import DriveTarget, PreviewCopies, PreviewMode, PreviewResult, PreviewStage
from app.observability.log_event import LogArea
from app.run.line_plan import RunScope
from app.run.mode import RunPart
from app.run.progress import StageProgress
from app.secretsafe.vault import Vault
from app.slots.preview import Preview
from app.slots.slot import SlotKey, StreamSlot
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.sources.video import PreparedSources, SourceVideo
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.drive import ROOT_FOLDER_ID, FakeDriveService, drive_client, drive_error
from app.tests.fixtures.settings import drive_vault
from app.tests.fixtures.sources import admitted_row, ready_source
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
TEXTS: SlotTexts = SlotTexts("Эфир", "Опис", SlotTextOrigin.PACKAGE)
DAY: datetime = datetime(2026, 9, 28, 19, 0, tzinfo=KYIV)
NEXT_DAY: datetime = datetime(2026, 9, 29, 19, 0, tzinfo=KYIV)
LINKS: tuple[str, ...] = (
    "https://youtu.be/dQw4w9WgXcQ", "https://youtu.be/aB3_-xYz012", "https://youtu.be/Zx9_8yW7v6U",
    "https://youtu.be/Qq1_2wW3eE4", "https://youtu.be/Rr5_6tT7yY8",
)


def _preview(tag: bytes) -> Preview:
    return Preview(data=b"\xff\xd8" + tag + b"\xff\xd9", width=1280, height=720)


def _video(number: int, start: datetime, language: str, title: str, has_preview: bool = True) -> SourceVideo:
    """Готовое видео строки `number` (строки таблицы — с 2); превью у каждого своё."""
    preview: Preview | None = _preview(str(number).encode()) if has_preview else None
    return ready_source(admitted_row(number, LINKS[number - 2], start), title, "Описание", language, preview)


def _videos() -> tuple[SourceVideo, ...]:
    """Строки 2–6: украинское, русское, украинское без превью, украинское — на одну дату; украинское — на другую."""
    return (
        _video(2, DAY, "uk", "Привіт, світе"),
        _video(3, DAY, "ru", "Съешь ещё булок"),
        _video(4, DAY, "uk", "Без обкладинки", has_preview=False),
        _video(5, DAY, "uk", "Третій ефір"),
        _video(6, NEXT_DAY, "uk", "Наступний день"),
    )


def _settings() -> LivecraftSettings:
    return ShippedSettings().settings


def _stage(image_dir: Path, mode: PreviewMode, open_drive: Callable[[], DriveClient]) -> PreviewStage:
    return PreviewStage(image_dir, _settings(), drive_vault(ROOT_FOLDER_ID), mode, open_drive)


def _run(stage: PreviewStage) -> PreviewResult:
    return stage.run(PreviewCopies.of(_videos(), KYIV))


def _no_drive() -> DriveClient:
    raise AssertionError("к Диску в этом режиме не обращаются")


# --- имена и копии в image\


def test_the_number_is_the_place_among_videos_of_the_same_date_and_language() -> None:
    copies: PreviewCopies = PreviewCopies.of(_videos(), KYIV)
    assert [copy.file_name for copy in copies.items] == [
        "1_UK_pryvit_svite.jpg",
        "1_RU_sesh_eshchyo_bulok.jpg",
        "3_UK_tretii_efir.jpg",                 # строка 4 без превью: номер 2 она заняла, копии не дала
        "1_UK_nastupnyi_den.jpg",
    ]


def test_local_copies_lie_in_image_by_the_template(tmp_path: Path) -> None:
    result: PreviewResult = _run(_stage(tmp_path, PreviewMode.LOCAL, _no_drive))
    assert result.saved == 4 and not result.has_errors and result.links == ()
    assert (tmp_path / "28-09-2026" / "uk" / "1_UK_pryvit_svite.jpg").read_bytes() == _preview(b"2").data
    assert (tmp_path / "28-09-2026" / "ru" / "1_RU_sesh_eshchyo_bulok.jpg").is_file()
    assert (tmp_path / "29-09-2026" / "uk" / "1_UK_nastupnyi_den.jpg").is_file()
    assert result.console_lines == (msg.PREVIEWS_LOCAL_LINE.format(saved=4),)


def test_a_dry_run_saves_copies_only_and_says_so(tmp_path: Path) -> None:
    result: PreviewResult = _run(_stage(tmp_path, PreviewMode.DRY_RUN, _no_drive))
    assert result.saved == 4 and result.links == ()
    assert result.console_lines == (msg.PREVIEWS_DRY_RUN_LINE.format(saved=4),)


def _scope(*parts: RunPart, dry_run: bool = False) -> RunScope:
    return RunScope(parts=frozenset(parts), dry_run=dry_run)


def test_the_mode_follows_the_lines_and_the_dry_run() -> None:
    """Линии превью (§14 решение 37): обе — копии в папке и на Диске; одна — только её копии; пробный запуск на Диск
    не пишет; нечего делать — этапа нет."""
    local, drive = RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS
    assert PreviewMode.of(_scope(local, drive)) is PreviewMode.FULL
    assert PreviewMode.of(_scope(local, drive, dry_run=True)) is PreviewMode.DRY_RUN
    assert PreviewMode.of(_scope(local)) is PreviewMode.LOCAL
    assert PreviewMode.of(_scope(local, dry_run=True)) is PreviewMode.LOCAL
    assert PreviewMode.of(_scope(drive)) is PreviewMode.DRIVE
    assert PreviewMode.of(_scope(drive, dry_run=True)) is None
    assert PreviewMode.of(_scope()) is None and PreviewMode.of(_scope(RunPart.PLAN)) is None


def test_the_drive_mode_uploads_without_local_copies(tmp_path: Path) -> None:
    """Линия «Превью на диске» выключена: папка превью пуста, копии — на Диске, строка — только о Диске."""
    service: FakeDriveService = FakeDriveService()
    result: PreviewResult = _run(_stage(tmp_path, PreviewMode.DRIVE, lambda: drive_client(service)))
    assert result.saved == 0 and not any(path.is_file() for path in tmp_path.rglob("*"))
    assert len(result.links) == 4
    assert result.console_lines == (msg.PREVIEWS_DRIVE_LINE.format(uploaded=4, kept=0),)


# --- Диск


def test_copies_go_to_the_drive_subfolders_and_their_links_to_the_rows(tmp_path: Path) -> None:
    service: FakeDriveService = FakeDriveService()
    result: PreviewResult = _run(_stage(tmp_path, PreviewMode.FULL, lambda: drive_client(service)))
    assert not result.has_errors
    [first] = service.named("1_UK_pryvit_svite.jpg")
    assert service.path_of(first.item_id) == ("preview", "28-09-2026", "uk", "1_UK_pryvit_svite.jpg")
    assert first.data == _preview(b"2").data
    assert [link.row_number for link in result.links] == [2, 3, 5, 6]      # строка 4 без превью
    assert result.links[0].text == f"https://drive.google.com/uc?export=download&id={first.item_id}"
    assert result.console_lines == (msg.PREVIEWS_LINE.format(saved=4, uploaded=4, kept=0),)


def test_a_second_run_uploads_nothing_and_gives_the_same_links(tmp_path: Path) -> None:
    service: FakeDriveService = FakeDriveService()
    first: PreviewResult = _run(_stage(tmp_path, PreviewMode.FULL, lambda: drive_client(service)))
    again: PreviewResult = _run(_stage(tmp_path, PreviewMode.FULL, lambda: drive_client(service)))
    assert again.links == first.links
    assert again.console_lines == (msg.PREVIEWS_LINE.format(saved=4, uploaded=0, kept=4),)


def test_a_drive_that_does_not_open_is_an_error_line_without_links(tmp_path: Path) -> None:
    def _refused() -> DriveClient:
        raise DriveError(DriveReason.AUTH, DriveCall.OPEN, detail="вход не удался")

    result: PreviewResult = _run(_stage(tmp_path, PreviewMode.FULL, _refused))
    assert result.has_errors and result.saved == 4 and result.links == ()
    assert result.drive.error is not None
    assert result.console_lines == (
        msg.PREVIEWS_LINE.format(saved=4, uploaded=0, kept=0),
        result.drive.error.human,
    )


def test_a_drive_failure_midway_keeps_the_links_of_what_was_uploaded(tmp_path: Path) -> None:
    """Первая копия: три подпапки (найти и создать) и файл (найти, загрузить, открыть) — 9 обращений; десятое —
    подпапка «ru» второй копии — Диск отвергает, дальше его не спрашивают."""
    service: FakeDriveService = FakeDriveService(fail_at={10: drive_error(403)})
    result: PreviewResult = _run(_stage(tmp_path, PreviewMode.FULL, lambda: drive_client(service)))
    assert len(service.calls) == 10
    assert result.drive.uploaded == 1 and result.drive.error is not None
    assert result.drive.error.reason is DriveReason.NO_ACCESS and result.has_errors
    assert [link.row_number for link in result.links] == [2]


def test_the_log_carries_rows_and_counts_but_no_titles(tmp_path: Path) -> None:
    with LogCapture.on(LogArea.INTAKE) as log:
        _run(_stage(tmp_path, PreviewMode.FULL, lambda: drive_client(FakeDriveService())))
    lines: list[str] = log.messages()
    assert any(line.startswith("preview_copy row=2 ") for line in lines)
    assert "previews_finished mode=full saved=4 uploaded=4 kept=0 drive_error=-" in lines
    assert not any("Привіт" in line or "булок" in line for line in lines)


# --- папка материалов — поле сейфа (§14 решение 39): её id отдаёт Диску одна точка раскрытия, DriveTarget


def test_the_drive_target_masks_the_folder_and_without_it_the_drive_is_not_asked(tmp_path: Path) -> None:
    target: DriveTarget = DriveTarget.from_vault(drive_vault(ROOT_FOLDER_ID))
    assert ROOT_FOLDER_ID not in repr(target) and ROOT_FOLDER_ID not in f"{target}"
    with pytest.raises(DriveError) as raised:
        DriveTarget.from_vault(Vault.empty())
    assert (raised.value.reason, raised.value.call) == (DriveReason.NOT_CONFIGURED, DriveCall.FOLDER)
    service: FakeDriveService = FakeDriveService()
    stage: PreviewStage = PreviewStage(
        tmp_path, _settings(), Vault.empty(), PreviewMode.DRIVE, lambda: drive_client(service)
    )
    result: PreviewResult = _run(stage)
    assert result.drive.error is not None and result.drive.error.reason is DriveReason.NOT_CONFIGURED
    assert service.calls == [] and result.links == ()


def test_the_subfolders_are_made_in_the_folder_of_the_vault(tmp_path: Path) -> None:
    """Подделка Диска знает только папку с этим id: подпапки превью легли в неё — id дошёл из сейфа."""
    service: FakeDriveService = FakeDriveService()
    stage: PreviewStage = PreviewStage(
        tmp_path, _settings(), drive_vault(ROOT_FOLDER_ID), PreviewMode.DRIVE, lambda: drive_client(service)
    )
    _run(stage)
    top: set[str] = {item.name for item in service.items.values() if item.parent == ROOT_FOLDER_ID}
    assert top == {"preview"}


# --- превью слотов пакетов (вход «Пакеты», §14 решение 51)


def test_the_previews_of_package_slots_take_the_names_of_the_slot_covers() -> None:
    """Превью слота пакета — под именами обложек слота; чьё оно — по месту среди видео, когда превью столько же, сколько
    видео; строки таблицы у них нет."""
    cover: Preview = Preview(data=b"\xff\xd8a\xff\xd9", width=1280, height=720)
    sources: tuple[str, ...] = (
        "https://www.youtube.com/watch?v=aaaaaaaaaaa", "https://www.youtube.com/watch?v=bbbbbbbbbbb"
    )
    whole: StreamSlot = StreamSlot(SlotKey(datetime(2026, 10, 16, 19, 0, tzinfo=KYIV), "uk"), TEXTS, (cover, cover), sources)
    partial: StreamSlot = StreamSlot(SlotKey(datetime(2026, 10, 16, 20, 0, tzinfo=KYIV), "en"), TEXTS, (cover,), sources)
    copies: PreviewCopies = PreviewCopies.of_slots((whole, partial))
    assert [copy.file_name for copy in copies.items] == [
        "16-10-2026_1900_uk_1.jpg", "16-10-2026_1900_uk_2.jpg", "16-10-2026_2000_en_1.jpg"
    ]
    assert [copy.source for copy in copies.items] == [*whole.sources, None]
    assert all(copy.row_number is None for copy in copies.items)


def test_package_previews_go_to_the_drive_without_table_links_but_with_covers(tmp_path: Path) -> None:
    """Копии превью слотов пакетов — в папке превью по шаблону и на Диске; ссылок в таблицу нет, обложки документа — по
    ссылкам видео."""
    cover: Preview = Preview(data=b"\xff\xd8a\xff\xd9", width=1280, height=720)
    key: SlotKey = SlotKey(datetime(2026, 10, 16, 19, 0, tzinfo=KYIV), "uk")
    slot: StreamSlot = StreamSlot(key, TEXTS, (cover,), ("https://www.youtube.com/watch?v=aaaaaaaaaaa",))
    service: FakeDriveService = FakeDriveService()
    result: PreviewResult = _stage(tmp_path, PreviewMode.FULL, lambda: drive_client(service)).run(
        PreviewCopies.of_slots((slot,))
    )
    assert (tmp_path / "16-10-2026" / "uk" / "16-10-2026_1900_uk_1.jpg").read_bytes() == cover.data
    assert result.links == () and list(result.covers) == list(slot.sources)
    assert result.covers[slot.sources[0]].startswith("https://drive.google.com/uc?export=download&id=")


# --- строки хода в консоли (CLAUDE.md §13 задача 9.5)


def _drive_lines(total: int, upto: int | None = None) -> list[str]:
    last: int = total if upto is None else upto
    return [msg.PROGRESS_DRIVE_PREVIEW.format(place=place, total=total) for place in range(1, last + 1)]


@pytest.mark.parametrize("mode", [PreviewMode.FULL, PreviewMode.DRIVE])
def test_a_progress_line_goes_before_each_copy_to_the_drive(tmp_path: Path, mode: PreviewMode) -> None:
    """Четыре превью — четыре строки хода по порядку загрузок; копии в папке превью строк не дают: они быстрые."""
    record: ConsoleRecord = ConsoleRecord()
    service: FakeDriveService = FakeDriveService()
    stage: PreviewStage = _stage(tmp_path, mode, lambda: drive_client(service))
    result: PreviewResult = stage.run(PreviewCopies.of(_videos(), KYIV), StageProgress(record.console))
    assert len(result.links) == 4
    assert record.lines == _drive_lines(4) and record.lines[0] == "Копия превью на Google Диск: 1 из 4."


def test_a_copy_that_is_already_on_the_drive_has_its_line_too(tmp_path: Path) -> None:
    """Счёт — по превью запуска: и для копии, которая на Диске уже лежит, Диск спрашивается."""
    record: ConsoleRecord = ConsoleRecord()
    service: FakeDriveService = FakeDriveService()
    _run(_stage(tmp_path, PreviewMode.FULL, lambda: drive_client(service)))
    again: PreviewStage = _stage(tmp_path, PreviewMode.FULL, lambda: drive_client(service))
    result: PreviewResult = again.run(PreviewCopies.of(_videos(), KYIV), StageProgress(record.console))
    assert result.drive.uploaded == 0 and record.lines == _drive_lines(4)


def test_after_a_drive_failure_no_more_progress_lines_follow(tmp_path: Path) -> None:
    """Сбой Диска на второй копии (десятое обращение) останавливает загрузку: строки хода — до неё включительно."""
    record: ConsoleRecord = ConsoleRecord()
    service: FakeDriveService = FakeDriveService(fail_at={10: drive_error(403)})
    stage: PreviewStage = _stage(tmp_path, PreviewMode.FULL, lambda: drive_client(service))
    result: PreviewResult = stage.run(PreviewCopies.of(_videos(), KYIV), StageProgress(record.console))
    assert result.has_errors and len(result.drive.copies) == 1
    assert record.lines == _drive_lines(4, upto=2)


@pytest.mark.parametrize("mode", [PreviewMode.LOCAL, PreviewMode.DRY_RUN])
def test_without_uploads_there_are_no_progress_lines(tmp_path: Path, mode: PreviewMode) -> None:
    """Пробный запуск и линия без Диска: загрузок нет — строк хода нет."""
    record: ConsoleRecord = ConsoleRecord()
    result: PreviewResult = _stage(tmp_path, mode, _no_drive).run(
        PreviewCopies.of(_videos(), KYIV), StageProgress(record.console)
    )
    assert result.saved == 4 and record.lines == []


def test_without_a_console_the_uploads_say_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    service: FakeDriveService = FakeDriveService()
    _run(_stage(tmp_path, PreviewMode.FULL, lambda: drive_client(service)))
    assert capsys.readouterr().out == ""
