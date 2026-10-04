"""Клиент Google Диска (app\\google\\drive.py) на подделке Drive v3: папка материалов, подпапки превью, загрузка копии
и отказы Диска (CLAUDE.md §14 решение 27). К Google тесты не ходят."""
from __future__ import annotations

import pytest
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

from app.core.retry import RetryPolicy
from app.google.auth import AuthError, AuthErrorReason, GoogleLogin
from app.google.drive import (
    DOCUMENT_MIME_TYPE, DRIVE_FAILURES, FOLDER_MIME_TYPE, WORD_MIME_TYPE, DriveCall, DriveClient, DriveError, DriveFile, DriveFolder,
    DriveReason, DriveUpload,
)
from app.paths import LivecraftPaths
from app.observability.log_event import LogArea
from app.tests.fixtures.drive import (
    ACCOUNT_EMAIL, ROOT_FOLDER_ID, ROOT_FOLDER_NAME, DriveItem, FakeDriveService, drive_client, drive_error,
    exported_bytes,
)
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

JPEG: bytes = b"\xff\xd8\xff\xe0 fake jpeg \xff\xd9"
PARTS: tuple[str, ...] = ("preview", "28-09-2026", "uk")


def _upload(name: str = "1_UK_privit.jpg", data: bytes = JPEG) -> DriveUpload:
    return DriveUpload(name=name, data=data, mime_type="image/jpeg")


# --- папка, которую задал человек


def test_the_folder_names_itself_and_says_files_can_be_added() -> None:
    folder: DriveFolder = drive_client(FakeDriveService()).folder(ROOT_FOLDER_ID)
    assert folder == DriveFolder(folder_id=ROOT_FOLDER_ID, name=ROOT_FOLDER_NAME, is_folder=True, can_add_files=True)


def test_a_file_is_not_a_folder_and_a_shared_folder_may_be_read_only() -> None:
    service: FakeDriveService = FakeDriveService()
    service.items["doc"] = DriveItem("doc", "План.docx", ROOT_FOLDER_ID, "application/vnd.google-apps.document")
    service.items["ro"] = DriveItem("ro", "Чужая", None, FOLDER_MIME_TYPE, can_add=False)
    client: DriveClient = drive_client(service)
    assert not client.folder("doc").is_folder
    assert not client.folder("ro").can_add_files and client.folder("ro").is_folder


# --- аккаунт входа


def test_the_drive_names_the_account_of_the_login() -> None:
    """Каким аккаунтом вошёл оператор (§13 задача 9.6): одно обращение about.get, новый скоуп не нужен."""
    service: FakeDriveService = FakeDriveService()
    assert drive_client(service).account_email() == ACCOUNT_EMAIL
    assert service.calls == ["about.get"]


def test_an_account_that_is_not_named_is_a_drive_error_of_its_call() -> None:
    service: FakeDriveService = FakeDriveService(failures=[drive_error(403)])
    with pytest.raises(DriveError) as raised:
        drive_client(service).account_email()
    assert raised.value.call is DriveCall.ACCOUNT and raised.value.reason is DriveReason.NO_ACCESS


# --- подпапки превью


def test_subfolders_are_created_once_and_then_found() -> None:
    service: FakeDriveService = FakeDriveService()
    first: str = drive_client(service).ensure_path(ROOT_FOLDER_ID, PARTS)
    assert service.path_of(first) == PARTS
    assert all(item.mime_type == FOLDER_MIME_TYPE for item in service.items.values())
    service.calls.clear()
    again: str = drive_client(service).ensure_path(ROOT_FOLDER_ID, PARTS)      # новый запуск: находит, не создаёт
    assert again == first and service.calls == ["files.list"] * 3


def test_a_found_subfolder_is_not_asked_twice_in_one_run() -> None:
    service: FakeDriveService = FakeDriveService()
    client: DriveClient = drive_client(service)
    client.ensure_path(ROOT_FOLDER_ID, PARTS)
    service.calls.clear()
    client.ensure_path(ROOT_FOLDER_ID, PARTS)
    assert service.calls == []


def test_a_quote_in_a_subfolder_name_is_escaped_in_the_query() -> None:
    service: FakeDriveService = FakeDriveService()
    folder_id: str = drive_client(service).ensure_path(ROOT_FOLDER_ID, ("it's",))
    assert service.path_of(folder_id) == ("it's",)
    assert drive_client(service).ensure_path(ROOT_FOLDER_ID, ("it's",)) == folder_id


# --- загрузка


def test_a_new_file_is_uploaded_and_opened_by_link_for_reading() -> None:
    service: FakeDriveService = FakeDriveService()
    client: DriveClient = drive_client(service)
    folder_id: str = client.ensure_path(ROOT_FOLDER_ID, PARTS)
    file: DriveFile = client.upload(folder_id, _upload())
    assert file.is_new
    assert service.items[file.file_id].data == JPEG and service.items[file.file_id].parent == folder_id
    assert service.shared[file.file_id] == {"type": "anyone", "role": "reader"}
    assert file.download_url == f"https://drive.google.com/uc?export=download&id={file.file_id}"


def test_a_file_with_the_same_name_and_size_is_not_uploaded_again() -> None:
    service: FakeDriveService = FakeDriveService()
    folder_id: str = drive_client(service).ensure_path(ROOT_FOLDER_ID, PARTS)
    first: DriveFile = drive_client(service).upload(folder_id, _upload())
    service.calls.clear()
    again: DriveFile = drive_client(service).upload(folder_id, _upload())
    assert again == DriveFile(file_id=first.file_id, is_new=False)
    assert service.calls == ["files.list"]


def test_the_same_name_with_another_size_is_a_new_upload() -> None:
    service: FakeDriveService = FakeDriveService()
    client: DriveClient = drive_client(service)
    folder_id: str = client.ensure_path(ROOT_FOLDER_ID, PARTS)
    first: DriveFile = client.upload(folder_id, _upload())
    second: DriveFile = client.upload(folder_id, _upload(data=JPEG + b"more"))
    assert second.is_new and second.file_id != first.file_id


# --- отказы Диска


@pytest.mark.parametrize(
    ("status", "reason"),
    [(403, DriveReason.NO_ACCESS), (401, DriveReason.NO_ACCESS), (404, DriveReason.NOT_FOUND),
     (400, DriveReason.BAD_REQUEST), (409, DriveReason.REJECTED)],
)
def test_other_statuses_fail_at_once_without_the_address(status: int, reason: DriveReason) -> None:
    service: FakeDriveService = FakeDriveService(failures=[drive_error(status)])
    sleeps: list[float] = []
    with pytest.raises(DriveError) as raised:
        drive_client(service, sleeps).folder(ROOT_FOLDER_ID)
    assert raised.value.reason is reason and raised.value.status == status
    assert sleeps == [] and len(service.calls) == 1
    assert ROOT_FOLDER_ID in str(drive_error(status))                 # подделка честная: адрес с id в тексте ошибки
    assert ROOT_FOLDER_ID not in str(raised.value) and ROOT_FOLDER_ID not in raised.value.event.text
    assert str(raised.value) == msg.DRIVE_FAILED_STATUS.format(reason=reason.human.format(detail=""), status=status)
    assert isinstance(raised.value.__cause__, HttpError)


def test_503_and_transport_errors_are_retried_by_the_policy() -> None:
    sleeps: list[float] = []
    service: FakeDriveService = FakeDriveService(failures=[drive_error(503), ConnectionResetError(10054, "reset")])
    assert drive_client(service, sleeps).folder(ROOT_FOLDER_ID).name == ROOT_FOLDER_NAME
    assert len(sleeps) == 2 and len(service.calls) == 3


def test_retries_that_run_out_are_unavailable() -> None:
    policy: RetryPolicy = RetryPolicy()
    service: FakeDriveService = FakeDriveService(failures=[drive_error(429)] * policy.max_attempts)
    with pytest.raises(DriveError) as raised:
        drive_client(service).upload(ROOT_FOLDER_ID, _upload())
    assert raised.value.reason is DriveReason.UNAVAILABLE and len(service.calls) == policy.max_attempts
    assert raised.value.event.text.startswith("drive_failed reason=unavailable call=find_file status=429")


def test_a_login_that_fails_is_a_drive_error_with_the_reason(
    livecraft_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(self: GoogleLogin, **options: object) -> None:
        raise AuthError(AuthErrorReason.SCOPES_NOT_GRANTED)

    monkeypatch.setattr(GoogleLogin, "credentials", _fail)
    with pytest.raises(DriveError) as raised:
        DriveClient.open(GoogleLogin.operator(livecraft_paths))
    assert raised.value.reason is DriveReason.AUTH
    assert AuthErrorReason.SCOPES_NOT_GRANTED.human in str(raised.value)


def test_a_server_that_is_not_found_to_the_end_is_no_network() -> None:
    """Адрес сервера Google не найден и после повторов — у компьютера нет интернета, а не «Google не ответил»; слова —
    те же, что у таблицы плана."""
    policy: RetryPolicy = RetryPolicy()
    service: FakeDriveService = FakeDriveService(failures=[ServerNotFoundError("x")] * policy.max_attempts)
    with pytest.raises(DriveError) as raised:
        drive_client(service).folder(ROOT_FOLDER_ID)
    assert raised.value.reason is DriveReason.NO_NETWORK and len(service.calls) == policy.max_attempts
    assert DriveReason.NO_NETWORK.human == msg.SHEETS_READ_REASON_TEXT["no_network"] == msg.GOOGLE_NO_NETWORK_TEXT
    assert str(raised.value) == msg.DRIVE_FAILED.format(reason=msg.GOOGLE_NO_NETWORK_TEXT)
    assert raised.value.event.text.startswith("drive_failed reason=no_network call=folder")


def test_creating_a_document_without_network_is_no_network_not_unknown() -> None:
    """Создающее обращение без интернета: до Google запрос не дошёл — исход известен, повтор ничего не задвоит."""
    policy: RetryPolicy = RetryPolicy()
    service: FakeDriveService = FakeDriveService(failures=[ServerNotFoundError("x")] * policy.max_attempts)
    with pytest.raises(DriveError) as raised:
        drive_client(service).create_document(ROOT_FOLDER_ID, "doc")
    assert raised.value.reason is DriveReason.NO_NETWORK and raised.value.call is DriveCall.CREATE_DOCUMENT
    assert len(service.calls) == policy.max_attempts and service.named("doc") == []


def test_a_login_that_is_not_refreshed_without_network_is_no_network(
    livecraft_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(self: GoogleLogin, **options: object) -> None:
        raise AuthError(AuthErrorReason.REFRESH_FAILED, "sheets.token.json: TransportError")

    monkeypatch.setattr(GoogleLogin, "credentials", _fail)
    with pytest.raises(DriveError) as raised:
        DriveClient.open(GoogleLogin.operator(livecraft_paths))
    assert raised.value.reason is DriveReason.NO_NETWORK and raised.value.call is DriveCall.OPEN
    assert str(raised.value) == msg.DRIVE_FAILED.format(reason=msg.GOOGLE_NO_NETWORK_TEXT)
    others: list[AuthErrorReason] = [reason for reason in AuthErrorReason if reason is not AuthErrorReason.REFRESH_FAILED]
    assert {DRIVE_FAILURES.login_reason(reason) for reason in others} == {DriveReason.AUTH}


def test_every_reason_has_a_text() -> None:
    assert set(msg.DRIVE_REASON_TEXT) == {reason.value for reason in DriveReason}


# --- документ объявлений: создание в папке и доступ по ссылке (§13 задача 4.4)


def test_a_document_is_created_empty_right_in_the_folder() -> None:
    service: FakeDriveService = FakeDriveService()
    created: DriveFile = drive_client(service).create_document(ROOT_FOLDER_ID, "28-09-2026_Ежедневные стримы")
    item: DriveItem = service.items[created.file_id]
    assert (item.name, item.parent, item.mime_type) == ("28-09-2026_Ежедневные стримы", ROOT_FOLDER_ID, DOCUMENT_MIME_TYPE)
    assert created.document_url == f"https://docs.google.com/document/d/{created.file_id}/edit"
    assert service.calls == ["files.create"] and service.shared == {}


def test_creating_a_document_is_not_repeated_after_503_or_a_broken_connection() -> None:
    """Исход неизвестен: Google мог создать документ — повтор задвоил бы его (DriveReason.UNKNOWN)."""
    for failure in (drive_error(503), ConnectionResetError(10054, "reset")):
        service: FakeDriveService = FakeDriveService(failures=[failure])
        sleeps: list[float] = []
        with pytest.raises(DriveError) as raised:
            drive_client(service, sleeps).create_document(ROOT_FOLDER_ID, "doc")
        assert raised.value.reason is DriveReason.UNKNOWN and raised.value.call is DriveCall.CREATE_DOCUMENT
        assert len(service.calls) == 1 and sleeps == []


def test_creating_a_document_is_repeated_after_429() -> None:
    """429 — отказ до выполнения: повтор не задвоит документ."""
    service: FakeDriveService = FakeDriveService(failures=[drive_error(429)])
    sleeps: list[float] = []
    drive_client(service, sleeps).create_document(ROOT_FOLDER_ID, "doc")
    assert len(service.calls) == 2 and len(sleeps) == 1 and len(service.named("doc")) == 1


def test_reading_still_repeats_503() -> None:
    service: FakeDriveService = FakeDriveService(failures=[drive_error(503)])
    assert drive_client(service).folder(ROOT_FOLDER_ID).name == ROOT_FOLDER_NAME
    assert len(service.calls) == 2


def test_a_document_is_exported_as_word() -> None:
    service: FakeDriveService = FakeDriveService()
    client: DriveClient = drive_client(service)
    file_id: str = client.create_document(ROOT_FOLDER_ID, "doc").file_id
    assert client.export_word(file_id) == exported_bytes("doc")
    assert service.exports == [(file_id, WORD_MIME_TYPE)]
    assert WORD_MIME_TYPE == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


def test_export_repeats_503_and_a_client_error_is_a_drive_error_of_the_export() -> None:
    """Выгрузка только читает: повтор на 503 ничего не задваивает; 403 — отказ сразу."""
    service: FakeDriveService = FakeDriveService()
    sleeps: list[float] = []
    client: DriveClient = drive_client(service, sleeps)
    file_id: str = client.create_document(ROOT_FOLDER_ID, "doc").file_id
    service.failures.append(drive_error(503))
    assert client.export_word(file_id) == exported_bytes("doc") and len(sleeps) == 1
    service.failures.append(drive_error(403))
    with pytest.raises(DriveError) as raised:
        client.export_word(file_id)
    error: DriveError = raised.value
    assert (error.reason, error.call, error.status) == (DriveReason.NO_ACCESS, DriveCall.EXPORT, 403)
    assert len(sleeps) == 1


def test_share_opens_the_file_by_link_with_the_given_role() -> None:
    service: FakeDriveService = FakeDriveService()
    drive_client(service).share("doc-id", "writer")
    assert service.shared == {"doc-id": {"type": "anyone", "role": "writer"}}


def test_a_successful_call_is_a_log_line_with_its_attempts() -> None:
    """Решение 38: строка `drive_call` — обращение и число попыток, без адресов и id."""
    service: FakeDriveService = FakeDriveService(failures=[drive_error(503)])
    with LogCapture.on(LogArea.PUBLISH) as capture:
        drive_client(service).folder(ROOT_FOLDER_ID)
    assert capture.messages() == ["drive_call call=folder attempts=2"]
