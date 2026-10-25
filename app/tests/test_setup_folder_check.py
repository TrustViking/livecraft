"""Проверка папки Google Диска без окна (app\\setup\\panels\\folder_check.py, CLAUDE.md §8.2 пп. 4, 5, §14 решения 27,
39, 60): папка — из сейфа, у проверки — своё поле (папка превью или папка документов), Диск — подделка; к Google тесты
не ходят. Подделка знает папку только по id: годный итог — это id из сейфа, дошедший до Диска через точку раскрытия
`DriveTarget`."""
from __future__ import annotations

from app.google.drive import FOLDER_MIME_TYPE, DriveReason
from app.paths import FileName, LivecraftPaths
from app.secretsafe.field import SecretField
from app.setup.panels.folder_check import FolderCheck, FolderVerdict
from app.tests.fixtures.drive import ROOT_FOLDER_ID, ROOT_FOLDER_NAME, DriveItem, FakeDriveService, drive_client, drive_error
from app.tests.fixtures.settings import DRIVE_FOLDER_URL, set_drive_folder
from app.ui import messages_ru as msg


def _check(
    paths: LivecraftPaths, service: FakeDriveService, field: SecretField = SecretField.DRIVE_PREVIEWS_FOLDER
) -> FolderVerdict:
    check: FolderCheck = FolderCheck(paths=paths, field=field, open_drive=lambda on_login: drive_client(service))
    return check.run(lambda: None)


def test_a_folder_the_program_can_fill_is_named(ready_paths: LivecraftPaths) -> None:
    set_drive_folder(ready_paths, ROOT_FOLDER_ID)
    verdict: FolderVerdict = _check(ready_paths, FakeDriveService())
    assert verdict == FolderVerdict(is_ok=True, text=msg.SETUP_FOLDER_OK.format(name=ROOT_FOLDER_NAME))


def test_the_folder_id_is_taken_from_the_link(ready_paths: LivecraftPaths) -> None:
    """В ссылке id папки — «1AbC…»; подделка знает папку только по нему."""
    set_drive_folder(ready_paths, DRIVE_FOLDER_URL)
    assert _check(ready_paths, FakeDriveService()).is_ok


def test_a_file_is_not_a_folder(ready_paths: LivecraftPaths) -> None:
    service: FakeDriveService = FakeDriveService()
    service.items["doc"] = DriveItem("doc", "План", None, "application/vnd.google-apps.document")
    set_drive_folder(ready_paths, "doc")
    verdict: FolderVerdict = _check(ready_paths, service)
    assert verdict == FolderVerdict.failed(msg.SETUP_FOLDER_NOT_FOLDER.format(name="План"))
    assert not verdict.is_ok


def test_a_folder_without_the_right_to_add_says_what_to_give(ready_paths: LivecraftPaths) -> None:
    service: FakeDriveService = FakeDriveService()
    service.items["ro"] = DriveItem("ro", "Чужая", None, FOLDER_MIME_TYPE, can_add=False)
    set_drive_folder(ready_paths, "ro")
    assert _check(ready_paths, service) == FolderVerdict.failed(msg.SETUP_FOLDER_READ_ONLY.format(name="Чужая"))


def test_a_folder_that_is_not_there_names_the_reason(ready_paths: LivecraftPaths) -> None:
    set_drive_folder(ready_paths, "missing")
    verdict: FolderVerdict = _check(ready_paths, FakeDriveService())
    reason: str = DriveReason.NOT_FOUND.human.format(detail="")
    assert verdict == FolderVerdict.failed(msg.DRIVE_FAILED_STATUS.format(reason=reason, status=404))


def test_no_access_is_a_line_without_the_address(ready_paths: LivecraftPaths) -> None:
    set_drive_folder(ready_paths, ROOT_FOLDER_ID)
    verdict: FolderVerdict = _check(ready_paths, FakeDriveService(failures=[drive_error(403)]))
    assert not verdict.is_ok and ROOT_FOLDER_ID not in verdict.text


def test_without_a_folder_the_drive_is_not_asked(ready_paths: LivecraftPaths) -> None:
    service: FakeDriveService = FakeDriveService()
    reason: str = DriveReason.NOT_CONFIGURED.human.format(detail="")
    assert _check(ready_paths, service) == FolderVerdict.failed(msg.DRIVE_FAILED.format(reason=reason))
    assert service.calls == []


def test_an_unreadable_vault_file_is_named(ready_paths: LivecraftPaths) -> None:
    ready_paths.file(FileName.VAULT_TOKEN).write_text("{", encoding="utf-8")
    service: FakeDriveService = FakeDriveService()
    verdict: FolderVerdict = _check(ready_paths, service)
    assert not verdict.is_ok and verdict.text.startswith(msg.SETUP_FOLDER_FAILED.format(problem=""))
    assert service.calls == []


def test_each_check_asks_the_drive_about_its_own_folder(ready_paths: LivecraftPaths) -> None:
    """Папка превью и папка документов — разные: проверка каждой спрашивает Диск о своей (§14 решение 60)."""
    service: FakeDriveService = FakeDriveService()
    service.items["doc"] = DriveItem("doc", "План", None, "application/vnd.google-apps.document")
    set_drive_folder(ready_paths, ROOT_FOLDER_ID, (SecretField.DRIVE_PREVIEWS_FOLDER,))
    set_drive_folder(ready_paths, "doc", (SecretField.DRIVE_DOCS_FOLDER,))
    assert _check(ready_paths, service).is_ok
    docs: FolderVerdict = _check(ready_paths, service, SecretField.DRIVE_DOCS_FOLDER)
    assert docs == FolderVerdict.failed(msg.SETUP_FOLDER_NOT_FOLDER.format(name="План"))
