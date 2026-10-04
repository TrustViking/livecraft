"""Часть «документ объявлений» (app\\publish\\doc_stage.py, CLAUDE.md §13 задача 4.4): документ на каждую дату слотов в
папке материалов, доступ по ссылке, порядок обращений, обложки с запасным адресом, остановка на сбое и пробный
запуск. Google Диск и Docs — подделки в памяти."""
from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from app.config.docs import DocAccess, DocsSettings
from app.google.drive import DOCUMENT_MIME_TYPE, WORD_MIME_TYPE
from app.observability.log_event import LogArea
from app.paths import DataFolders
from app.publish.doc_copy import DocCopyFailure
from app.publish.doc_stage import DocDocument, DocResult, DocStage
from app.run.exit_code import RunOutcome
from app.run.progress import StageProgress
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.docs import FakeDocsService, docs_error
from app.tests.fixtures.drive import ROOT_FOLDER_ID, DriveItem, FakeDriveService, drive_error, exported_bytes
from app.tests.fixtures.logs import LogCapture
from app.config.settings import FormSettings
from app.publish.day import PublishDay
from app.tests.fixtures.publish import KYIV, DocRun, doc_run, doc_settings, doc_stage, doc_video
from app.tests.fixtures.settings import with_docs
from app.ui import messages_ru as msg

LINKS: tuple[str, ...] = ("https://youtu.be/dQw4w9WgXcQ", "https://youtu.be/aB3_-xYz012", "https://youtu.be/Zx9_8yW7v6U")
THUMBNAIL: str = "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
# Копия документа даты относительно корня: имя документа «{дата}_Ежедневные стримы - Everyday streams_10:05».
COPY_SHOWN: str = str(Path("docs", "{date}", "{date}_Ежедневные_стримы_Everyday_streams_1005.docx"))
DAYS: tuple[datetime, ...] = (
    datetime(2026, 9, 28, 19, 0, tzinfo=KYIV), datetime(2026, 9, 29, 19, 0, tzinfo=KYIV),
    datetime(2026, 9, 30, 19, 0, tzinfo=KYIV),
)


def _one_day(tmp_path: Path, on_drive: bool = True) -> DocRun:
    """Одна дата, один слот из одного видео с превью."""
    return doc_run(tmp_path, [doc_video(2, LINKS[0], DAYS[0])], on_drive)


def _three_days(tmp_path: Path) -> DocRun:
    return doc_run(tmp_path, [doc_video(row + 2, LINKS[row], DAYS[row]) for row in range(3)])


def _documents(drive: FakeDriveService) -> list[DriveItem]:
    return [item for item in drive.items.values() if item.mime_type == DOCUMENT_MIME_TYPE]


def test_one_document_per_date_in_the_materials_folder_open_to_edit_by_link(tmp_path: Path) -> None:
    drive: FakeDriveService = FakeDriveService()
    run: DocRun = _three_days(tmp_path)
    result: DocResult = doc_stage(drive, FakeDocsService(), root=tmp_path).run(*run)
    documents: list[DriveItem] = _documents(drive)
    assert [item.name for item in documents] == [
        f"{date}_Ежедневные стримы - Everyday streams_10:05" for date in ("28-09-2026", "29-09-2026", "30-09-2026")
    ]
    assert all(item.parent == ROOT_FOLDER_ID for item in documents)
    assert all(drive.shared[item.item_id] == {"type": "anyone", "role": "writer"} for item in documents)
    assert result.outcome is RunOutcome.DONE and len(result.documents) == 3
    assert result.url_of(run.days[1]) == f"https://docs.google.com/document/d/{documents[1].item_id}/edit"
    other: PublishDay = PublishDay("01-10-2026", doc_settings().form, run.days[0].slots, 1)
    assert result.url_of(other) is None


def test_a_private_document_is_not_shared_by_link(tmp_path: Path) -> None:
    drive: FakeDriveService = FakeDriveService()
    settings = with_docs(doc_settings(), DocsSettings(access=DocAccess.PRIVATE, contacts=""))
    doc_stage(drive, FakeDocsService(), settings, root=tmp_path).run(*_one_day(tmp_path))
    assert drive.calls == ["files.create", "files.export"] and drive.shared == {}


def test_a_document_is_written_header_table_cells_then_covers(tmp_path: Path) -> None:
    """Шапка одним пакетом с индекса 1; таблица в конец после пустого абзаца; тексты ячеек после чтения документа;
    обложка — после второго чтения, копия с Диска."""
    docs: FakeDocsService = FakeDocsService()
    doc_stage(FakeDriveService(), docs, root=tmp_path).run(*_one_day(tmp_path))
    assert docs.calls == ["batchUpdate", "batchUpdate", "get", "batchUpdate", "get", "batchUpdate"]
    assert docs.updates[0][0]["insertText"]["location"] == {"index": 1}
    assert docs.updates[0][0]["insertText"]["text"].startswith("Ежедневные стримы / Everyday streams\n")
    assert docs.kinds(1) == ["insertText", "insertTable"] and docs.updates[1][1]["insertTable"]["rows"] == 7
    assert docs.kinds(2)[:4] == ["updateTableCellStyle"] * 4 and "insertText" in docs.kinds(2)
    [image] = docs.images
    assert image["uri"].startswith("https://drive.google.com/uc?export=download&id=")


def test_every_table_but_the_first_starts_on_a_new_page(tmp_path: Path) -> None:
    docs: FakeDocsService = FakeDocsService()
    videos = [doc_video(2, LINKS[0], DAYS[0]), doc_video(3, LINKS[1], DAYS[0].replace(hour=20))]
    doc_stage(FakeDriveService(), docs, root=tmp_path).run(*doc_run(tmp_path, videos))
    tables: list[list[str]] = [kinds for kinds in map(docs.kinds, range(len(docs.updates))) if "insertTable" in kinds]
    assert tables == [["insertText", "insertTable"], ["insertPageBreak", "insertTable"]]


def test_a_refused_drive_copy_falls_back_to_the_youtube_thumbnail(tmp_path: Path) -> None:
    result: DocRun = _one_day(tmp_path)
    [copy] = result.covers.values()
    docs: FakeDocsService = FakeDocsService(refused_images={copy})
    done: DocResult = doc_stage(FakeDriveService(), docs, root=tmp_path).run(*result)
    assert [image["uri"] for image in docs.images] == [THUMBNAIL]
    assert (done.documents[0].covers_placed, done.documents[0].covers_missed) == (1, 0)


def test_a_cover_that_no_address_gives_is_counted_and_logged_not_an_error(tmp_path: Path) -> None:
    docs: FakeDocsService = FakeDocsService(refused_images={THUMBNAIL})
    with LogCapture.on(LogArea.PUBLISH) as log:
        done: DocResult = doc_stage(FakeDriveService(), docs, root=tmp_path).run(*_one_day(tmp_path, on_drive=False))
    document: DocDocument = done.documents[0]
    assert (document.covers_placed, document.covers_missed) == (0, 1) and done.outcome is RunOutcome.DONE
    assert (
        "doc_cover_missed slot=28-09-2026_1900_uk source=https://www.youtube.com/watch?v=dQw4w9WgXcQ tried=1"
        in log.messages(logging.WARNING)
    )
    assert done.console_lines == (
        msg.DOC_LINE.format(date="28.09.2026", url=document.url, placed=0, total=1)
        + msg.DOC_COPY_SAVED.format(path=COPY_SHOWN.format(date="28-09-2026")),
    )


def test_another_image_refusal_stops_the_part(tmp_path: Path) -> None:
    docs: FakeDocsService = FakeDocsService(fail_at={6: docs_error(403)})
    done: DocResult = doc_stage(FakeDriveService(), docs, root=tmp_path).run(*_one_day(tmp_path))
    assert done.outcome is RunOutcome.FAILED and done.documents == ()
    assert done.failure is not None and done.failure.date == "28-09-2026"


def test_a_failure_on_the_second_date_leaves_the_third_uncreated(tmp_path: Path) -> None:
    """Второй files.create упал (403): первый документ готов, третий не создаётся, код — ошибка."""
    drive: FakeDriveService = FakeDriveService(fail_at={4: drive_error(403)})
    with LogCapture.on(LogArea.PUBLISH) as log:
        done: DocResult = doc_stage(drive, FakeDocsService(), root=tmp_path).run(*_three_days(tmp_path))
    assert len(_documents(drive)) == 1
    assert drive.calls == ["files.create", "permissions.create", "files.export", "files.create"]
    assert done.outcome is RunOutcome.FAILED and [document.date for document in done.documents] == ["28-09-2026"]
    assert done.failure is not None and done.skipped == 1
    assert done.console_lines == (
        done.documents[0].console_line,
        msg.DOC_FAILED_LINE.format(date="29.09.2026", reason=done.failure.error.human),
        msg.DOC_SKIPPED_LINE.format(count=1),
    )
    assert "doc_failed date=29-09-2026 reason=no_access call=create_document status=403" in log.messages(logging.ERROR)


def test_a_dry_run_touches_no_google_service_and_writes_no_copy(tmp_path: Path) -> None:
    drive: FakeDriveService = FakeDriveService()
    docs: FakeDocsService = FakeDocsService()
    done: DocResult = doc_stage(drive, docs, dry_run=True, root=tmp_path).run(*_one_day(tmp_path))
    assert drive.calls == [] and docs.calls == [] and drive.exports == []
    assert not (tmp_path / "docs").exists()
    assert done.console_lines == (msg.DOC_DRY_RUN_LINE,) and done.outcome is RunOutcome.DONE


def test_the_log_carries_dates_counts_links_and_the_copy_path_only(tmp_path: Path) -> None:
    with LogCapture.on(LogArea.PUBLISH) as log:
        done: DocResult = doc_stage(FakeDriveService(), FakeDocsService(), root=tmp_path).run(*_one_day(tmp_path))
    url: str = done.documents[0].url
    shown: str = COPY_SHOWN.format(date="28-09-2026")
    assert f"doc_created date=28-09-2026 url={url} covers=1 covers_missed=0 copy={shown}" in log.messages()
    assert (
        "docs_finished dry_run=no dates=1 documents=1 covers=1 covers_missed=0 copies=1 copies_failed=0 failed_date=-"
        in log.messages()
    )


# --- копия .docx в docs\<дата>\ (§14 решение 33)


def test_every_document_is_copied_as_word_into_the_folder_of_its_date(tmp_path: Path) -> None:
    drive: FakeDriveService = FakeDriveService()
    done: DocResult = doc_stage(drive, FakeDocsService(), root=tmp_path).run(*_three_days(tmp_path))
    assert done.outcome is RunOutcome.DONE
    for date, document in zip(("28-09-2026", "29-09-2026", "30-09-2026"), _documents(drive)):
        copy: Path = tmp_path / COPY_SHOWN.format(date=date)
        assert copy.read_bytes() == exported_bytes(document.name)
    assert [mime for _, mime in drive.exports] == [WORD_MIME_TYPE] * 3
    assert [item_id for item_id, _ in drive.exports] == [item.item_id for item in _documents(drive)]
    assert done.console_lines[0] == (
        msg.DOC_LINE.format(date="28.09.2026", url=done.documents[0].url, placed=1, total=1)
        + msg.DOC_COPY_SAVED.format(path=COPY_SHOWN.format(date="28-09-2026"))
    )


def test_without_the_copy_line_the_document_is_made_without_a_copy(tmp_path: Path) -> None:
    """Линия «Копия документа» не идёт (§14 решение 37): документ есть, выгрузки нет, строка — без пути копии, код 0."""
    drive: FakeDriveService = FakeDriveService()
    done: DocResult = doc_stage(drive, FakeDocsService(), root=tmp_path, with_copy=False).run(*_one_day(tmp_path))
    assert done.outcome is RunOutcome.DONE and len(_documents(drive)) == 1
    assert drive.exports == [] and not (tmp_path / "docs").exists()
    assert done.console_lines == (msg.DOC_LINE.format(date="28.09.2026", url=done.documents[0].url, placed=1, total=1),)
    assert (done.log_fields["copies"], done.log_fields["copies_failed"]) == (0, 0)


def test_the_copy_goes_into_the_docs_folder_of_the_settings(tmp_path: Path) -> None:
    """Папка копий из настроек: абсолютная — как есть; путь копии в строке — целиком."""
    chosen: Path = tmp_path / "chosen" / "copies"
    drive: FakeDriveService = FakeDriveService()
    stage: DocStage = doc_stage(drive, FakeDocsService(), root=tmp_path / "root", folders=DataFolders(docs=chosen))
    done: DocResult = stage.run(*_one_day(tmp_path))
    copy: Path = chosen / "28-09-2026" / Path(COPY_SHOWN.format(date="28-09-2026")).name
    assert copy.read_bytes() == exported_bytes(_documents(drive)[0].name)
    assert done.console_lines[0].endswith(msg.DOC_COPY_SAVED.format(path=copy))


def test_a_refused_export_is_named_in_the_line_and_the_next_date_is_still_copied(tmp_path: Path) -> None:
    """files.export первого документа — 403: копии нет, причина в строке, код 1; документ второй даты создан и
    скопирован — отказ копии не сбой документа."""
    drive: FakeDriveService = FakeDriveService(fail_at={3: drive_error(403)})
    with LogCapture.on(LogArea.PUBLISH) as log:
        done: DocResult = doc_stage(drive, FakeDocsService(), root=tmp_path).run(*_three_days(tmp_path))
    assert done.outcome is RunOutcome.FAILED and done.failure is None and len(done.documents) == 3
    first: DocDocument = done.documents[0]
    assert isinstance(first.copy, DocCopyFailure) and not first.is_copied
    assert first.console_line.endswith(msg.DOC_COPY_NOT_SAVED.format(reason=first.copy.human))
    assert not (tmp_path / "docs" / "28-09-2026").exists()
    assert (tmp_path / COPY_SHOWN.format(date="29-09-2026")).is_file()
    assert "doc_copy_failed date=28-09-2026 reason=no_access call=export status=403 error=-" in log.messages(
        logging.WARNING
    )
    assert "copies=2 copies_failed=1 failed_date=-" in log.messages()[-1]
    assert any(message.startswith("doc_created date=28-09-2026 ") and message.endswith(" copy_failed=no_access")
               for message in log.messages())


def test_a_server_error_on_export_is_retried(tmp_path: Path) -> None:
    drive: FakeDriveService = FakeDriveService(fail_at={3: drive_error(503)})
    done: DocResult = doc_stage(drive, FakeDocsService(), root=tmp_path).run(*_one_day(tmp_path))
    assert drive.calls == ["files.create", "permissions.create", "files.export", "files.export"]
    assert done.outcome is RunOutcome.DONE and done.documents[0].is_copied


def test_a_copy_that_cannot_be_written_names_the_reason(tmp_path: Path) -> None:
    """Папка даты занята файлом: копия не записалась — причина в строке документа, код 1."""
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "28-09-2026").write_text("не папка", encoding="utf-8")
    with LogCapture.on(LogArea.PUBLISH) as log:
        done: DocResult = doc_stage(FakeDriveService(), FakeDocsService(), root=tmp_path).run(*_one_day(tmp_path))
    document: DocDocument = done.documents[0]
    assert isinstance(document.copy, DocCopyFailure) and done.outcome is RunOutcome.FAILED
    assert document.copy.human.startswith("файл не записался: ")
    assert document.console_line.endswith(msg.DOC_COPY_NOT_SAVED.format(reason=document.copy.human))
    [line] = [message for message in log.messages(logging.WARNING) if message.startswith("doc_copy_failed ")]
    assert line.startswith("doc_copy_failed date=28-09-2026 reason=file_write call=- status=- error=")


# --- дни по дате и форме (§14 решение 51)


def test_two_forms_on_one_date_make_two_documents_with_their_own_forms_and_names(tmp_path: Path) -> None:
    """Слоты одной даты из пакетов двух форм: два документа, у второго имя с номером, в шапке — форма своих слотов;
    копии .docx не затирают друг друга."""
    run: DocRun = doc_run(tmp_path, [doc_video(2, LINKS[0], DAYS[0]), doc_video(3, LINKS[1], DAYS[0].replace(hour=20))])
    other: FormSettings = FormSettings(
        url="https://docs.google.com/forms/d/e/OTHER/viewform", fields=run.days[0].form.fields,
        values=run.days[0].form.values, date_format=run.days[0].form.date_format,
    )
    [day] = run.days
    first, second = day.slots
    days: tuple[PublishDay, ...] = (
        PublishDay(day.date, day.form, (first,), 1), PublishDay(day.date, other, (second,), 2)
    )
    drive: FakeDriveService = FakeDriveService()
    docs: FakeDocsService = FakeDocsService()
    done: DocResult = doc_stage(drive, docs, root=tmp_path).run(days, run.covers)
    assert done.outcome is RunOutcome.DONE and [item.name for item in _documents(drive)] == [
        "28-09-2026_Ежедневные стримы - Everyday streams_10:05",
        "28-09-2026_Ежедневные стримы - Everyday streams_10:05_2",
    ]
    headers: list[str] = [
        update[0]["insertText"]["text"] for update in docs.updates
        if "insertText" in update[0] and update[0]["insertText"].get("location") == {"index": 1}
    ]
    assert day.form.url in headers[0] and other.url not in headers[0] and other.url in headers[1]
    assert (tmp_path / COPY_SHOWN.format(date="28-09-2026")).is_file()
    assert (tmp_path / "docs" / "28-09-2026" / "28-09-2026_Ежедневные_стримы_Everyday_streams_1005_2.docx").is_file()
    assert done.url_of(days[1]) == done.documents[1].url != done.url_of(days[0])


# --- строки хода в консоли (CLAUDE.md §13 задача 9.5)


def _two_days(tmp_path: Path) -> DocRun:
    return doc_run(tmp_path, [doc_video(row + 2, LINKS[row], DAYS[row]) for row in range(2)])


def test_a_progress_line_names_each_date_before_its_document_is_created(tmp_path: Path) -> None:
    """Две даты — две строки хода с местом документа и датой для людей; строка даты на консоли раньше, чем её
    документ создан на Диске."""
    record: ConsoleRecord = ConsoleRecord()
    seen: list[int] = []

    class _Watching(FakeDriveService):
        def add(self, body: dict[str, Any], media: Any) -> str:
            seen.append(len(record.lines))
            return super().add(body, media)

    result: DocResult = doc_stage(_Watching(), FakeDocsService(), root=tmp_path).run(
        *_two_days(tmp_path), StageProgress(record.console)
    )
    assert len(result.documents) == 2
    assert record.lines == [
        "Создание документа объявлений 1 из 2: 28.09.2026.", "Создание документа объявлений 2 из 2: 29.09.2026.",
    ]
    assert seen == [1, 2]


def test_after_a_failed_document_no_more_progress_lines_follow(tmp_path: Path) -> None:
    """Создание документа второй даты из трёх упало: строки хода — первой и второй дат, третьей нет."""
    record: ConsoleRecord = ConsoleRecord()
    drive: FakeDriveService = FakeDriveService(fail_at={4: drive_error(403)})
    result: DocResult = doc_stage(drive, FakeDocsService(), root=tmp_path).run(
        *_three_days(tmp_path), StageProgress(record.console)
    )
    assert result.failure is not None and result.skipped == 1
    assert record.lines == [
        msg.PROGRESS_DOC.format(place=place, total=3, date=date) for place, date in ((1, "28.09.2026"), (2, "29.09.2026"))
    ]


def test_a_dry_run_has_no_document_progress_lines(tmp_path: Path) -> None:
    record: ConsoleRecord = ConsoleRecord()
    stage: DocStage = doc_stage(FakeDriveService(), FakeDocsService(), dry_run=True, root=tmp_path)
    assert stage.run(*_two_days(tmp_path), StageProgress(record.console)).dry_run and record.lines == []


def test_without_a_console_the_documents_say_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc_stage(FakeDriveService(), FakeDocsService(), root=tmp_path).run(*_two_days(tmp_path))
    assert capsys.readouterr().out == ""
