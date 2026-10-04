"""Копия документа объявлений в формате Word (app\\publish\\doc_copy.py, CLAUDE.md §14 решение 33): имя файла из имени
документа, запись в docs\\<дата>\\ временного корня, отказ Диска и сбой записи — значением. Диск — подделка в памяти."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.google.drive import DriveCall, DriveReason
from app.paths import LivecraftPaths
from app.publish.doc_copy import CopyProblem, DocCopy, DocCopyFailure, DocCopySaved
from app.tests.fixtures.drive import ROOT_FOLDER_ID, FakeDriveService, drive_client, drive_error, exported_bytes
from app.ui import messages_ru as msg

NAME: str = "17-03-2027_Ежедневные стримы - Everyday streams_15:24"


@pytest.mark.parametrize(
    ("name", "file_name"),
    [
        (NAME, "17-03-2027_Ежедневные_стримы_Everyday_streams_1524.docx"),
        ("  два   пробела\tи таб  ", "два_пробела_и_таб.docx"),
        ('a<b>c:d"e/f\\g|h?i*j', "a_b_c_d_e_f_g_h_i_j.docx"),
        ("x_-_y__z-_w", "x_y_z_w.docx"),
        ("-_.начало и конец._-", "начало_и_конец.docx"),
        ("?!", "document.docx"),
    ],
)
def test_the_file_name_comes_from_the_document_name(name: str, file_name: str) -> None:
    assert DocCopy("17-03-2027", name).file_name == file_name


def test_a_long_name_is_cut_like_a_preview_name() -> None:
    stem: str = DocCopy("17-03-2027", "а" * 300).stem
    assert stem == "а" * 120


def _document(drive: FakeDriveService) -> str:
    """id документа Google Docs с именем NAME в папке материалов."""
    return drive_client(drive).create_document(ROOT_FOLDER_ID, NAME).file_id


def test_the_copy_is_the_exported_word_file_in_the_folder_of_its_date(tmp_path: Path) -> None:
    drive: FakeDriveService = FakeDriveService()
    saved: DocCopySaved | DocCopyFailure = DocCopy("17-03-2027", NAME).save(
        drive_client(drive), _document(drive), LivecraftPaths(tmp_path)
    )
    assert isinstance(saved, DocCopySaved)
    assert saved.path == tmp_path / "docs" / "17-03-2027" / "17-03-2027_Ежедневные_стримы_Everyday_streams_1524.docx"
    assert saved.path.read_bytes() == exported_bytes(NAME)
    assert saved.shown == str(saved.path.relative_to(tmp_path))
    assert saved.console_part == msg.DOC_COPY_SAVED.format(path=saved.shown)
    assert [item.name for item in saved.path.parent.iterdir()] == [saved.path.name]   # временного файла нет


def test_a_refused_export_gives_the_drive_reason_and_no_file(tmp_path: Path) -> None:
    drive: FakeDriveService = FakeDriveService()
    file_id: str = _document(drive)
    drive.failures.append(drive_error(404))
    failed: DocCopySaved | DocCopyFailure = DocCopy("17-03-2027", NAME).save(
        drive_client(drive), file_id, LivecraftPaths(tmp_path)
    )
    assert isinstance(failed, DocCopyFailure)
    assert (failed.reason, failed.call, failed.status) == (DriveReason.NOT_FOUND, DriveCall.EXPORT, 404)
    assert failed.console_part == msg.DOC_COPY_NOT_SAVED.format(reason=failed.human)
    assert "404" in failed.human and "googleapis" not in failed.human
    assert not (tmp_path / "docs").exists()


def test_a_file_that_cannot_be_written_gives_the_reason_of_the_system(tmp_path: Path) -> None:
    drive: FakeDriveService = FakeDriveService()
    (tmp_path / "docs").write_text("не папка", encoding="utf-8")
    failed: DocCopySaved | DocCopyFailure = DocCopy("17-03-2027", NAME).save(
        drive_client(drive), _document(drive), LivecraftPaths(tmp_path)
    )
    assert isinstance(failed, DocCopyFailure)
    assert (failed.reason, failed.call, failed.status) == (CopyProblem.FILE_WRITE, None, None)
    assert failed.error is not None and failed.human.startswith("файл не записался: ")
    assert failed.event.text.startswith("doc_copy_failed date=17-03-2027 reason=file_write call=- status=- error=")
