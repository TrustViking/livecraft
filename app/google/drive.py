"""Папка материалов на Google Диске: проверка папки, подпапки превью, загрузка копии превью (CLAUDE.md §9,
§14 решение 27).

`DriveClient` — клиент Drive v3 одного входа оператора (полный `drive`). Он проверяет папку, которую задал человек
(`folder`: название, папка ли это и может ли программа добавлять в неё файлы), находит или создаёт подпапки по частям
пути (`ensure_path`, кеш на запуск: одна подпапка — одно обращение) и кладёт файл (`upload`): файл с тем же именем и
размером в подпапке уже есть — берётся он, иначе файл загружается и открывается по ссылке всем, у кого она есть
(«читатель», `share`). Ссылка на файл — `DriveFile.download_url`: прямое скачивание, её пишут в таблицу плана.
Документ объявлений клиент создаёт пустым сразу в папке (`create_document`); ссылка на него —
`DriveFile.document_url`; готовый документ он выгружает в формате Word (`export_word`) для копии в docs\\. Каким
аккаунтом вошёл оператор, клиент узнаёт у Диска (`account_email`, about.get): скоуп `drive` у оператора уже есть.

Повторы — только через `RetryLoop` (§11): 429, 5xx и сбои ниже HTTP; кончились на «адрес сервера Google не найден» или
вход не обновился из-за сбоя сети — причина `DriveReason.NO_NETWORK`: у компьютера нет интернета. Создание документа — обращение создающее: после
5xx и обрыва исход неизвестен (`DriveReason.UNKNOWN`), и оно не повторяется — повтор задвоил бы документ; 429
повторяется. Успешное обращение — строкой `drive_call` с числом попыток (`CallLog`, §14 решение 38); отказ —
значением `DriveError` со строкой лога (`event`), её пишет вызывающий. Текст `HttpError` не выводится никуда (в нём
URL).
"""
from __future__ import annotations

import io
import random
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from http import HTTPStatus
from typing import Final, TypeVar

from googleapiclient.discovery import Resource
from googleapiclient.http import MediaIoBaseUpload

from app.core.retry import RETRYABLE_HTTP_STATUSES, AttemptFailure, RetryLoop, RetryPolicy
from app.google.auth import GoogleLogin
from app.google.call_failure import CallFailures, GoogleApi
from app.google.call_log import CallLog
from app.observability.log_event import LogEvent
from app.ui.messages import msg

T = TypeVar("T")

DRIVE_API: Final[GoogleApi] = GoogleApi(name="drive", version="v3")
FOLDER_MIME_TYPE: Final[str] = "application/vnd.google-apps.folder"
DOCUMENT_MIME_TYPE: Final[str] = "application/vnd.google-apps.document"
# Выгрузка документа Google Docs в формате Word (.docx); предел files.export — 10 МБ.
WORD_MIME_TYPE: Final[str] = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
# Прямая ссылка на скачивание файла: её понимают и браузер, и Google Docs (вставка картинки по адресу).
DOWNLOAD_URL_TEMPLATE: Final[str] = "https://drive.google.com/uc?export=download&id={file_id}"
DOCUMENT_URL_TEMPLATE: Final[str] = "https://docs.google.com/document/d/{file_id}/edit"
FOLDER_FIELDS: Final[str] = "id,name,mimeType,capabilities(canAddChildren)"
FOLDER_LIST_FIELDS: Final[str] = "files(id)"
FILE_LIST_FIELDS: Final[str] = "files(id,size)"
CREATED_FIELDS: Final[str] = "id"
ACCOUNT_FIELDS: Final[str] = "user(emailAddress)"
LIST_PAGE_SIZE: Final[int] = 20
SEARCH_SPACE: Final[str] = "drive"
# Запросы files.list: строки в них — в одинарных кавычках; обратная косая черта и кавычка внутри — с «\».
FOLDER_QUERY: Final[str] = "name = '{name}' and mimeType = '{mime}' and '{parent}' in parents and trashed = false"
FILE_QUERY: Final[str] = "name = '{name}' and '{parent}' in parents and trashed = false"
QUERY_ESCAPES: Final[tuple[tuple[str, str], ...]] = (("\\", "\\\\"), ("'", "\\'"))
# Доступ по ссылке: всем, у кого она есть; копия превью — только на чтение (как превью в restreamer).
ANYONE_TYPE: Final[str] = "anyone"
READER_ROLE: Final[str] = "reader"


class DriveKey(str, Enum):
    """Поля запросов и ответов Drive v3."""

    ID = "id"
    NAME = "name"
    SIZE = "size"
    FILES = "files"
    MIME_TYPE = "mimeType"
    PARENTS = "parents"
    CAPABILITIES = "capabilities"
    CAN_ADD_CHILDREN = "canAddChildren"
    TYPE = "type"
    ROLE = "role"
    USER = "user"
    EMAIL = "emailAddress"


class DriveReason(str, Enum):
    """Почему обращение к Google Диску не удалось."""

    AUTH = "auth"                       # вход оператора не удался или токен отозван по ходу запроса
    NO_ACCESS = "no_access"             # 401 / 403
    NOT_FOUND = "not_found"             # 404: папки нет или она не видна аккаунту
    BAD_REQUEST = "bad_request"         # 400
    REJECTED = "rejected"               # прочий неповторяемый код ответа
    UNAVAILABLE = "unavailable"         # повторы кончились на 429, 5xx или транспорте
    UNKNOWN = "unknown"                 # создающее обращение: 5xx или обрыв — выполнено ли, неизвестно
    NO_NETWORK = "no_network"           # адрес сервера Google не найден или вход не обновился из-за сбоя сети
    NOT_CONFIGURED = "not_configured"   # папка материалов не задана: к Диску не обращаемся (§14 решение 39)

    @classmethod
    def for_status(cls, status: int) -> DriveReason:
        if status in RETRYABLE_HTTP_STATUSES:
            return cls.UNAVAILABLE
        return _STATUS_REASONS.get(status, cls.REJECTED)

    @property
    def human(self) -> str:
        return msg.DRIVE_REASON_TEXT[self.value]


_STATUS_REASONS: Final[dict[int, DriveReason]] = {
    HTTPStatus.BAD_REQUEST: DriveReason.BAD_REQUEST,
    HTTPStatus.UNAUTHORIZED: DriveReason.NO_ACCESS,
    HTTPStatus.FORBIDDEN: DriveReason.NO_ACCESS,
    HTTPStatus.NOT_FOUND: DriveReason.NOT_FOUND,
}
DRIVE_FAILURES: Final[CallFailures] = CallFailures(
    DriveReason.for_status, DriveReason.AUTH, DriveReason.UNAVAILABLE, no_network=DriveReason.NO_NETWORK
)
DRIVE_CREATE_FAILURES: Final[CallFailures] = DRIVE_FAILURES.creating(DriveReason.UNKNOWN)


class DriveCall(str, Enum):
    """Какое обращение к Диску. Значение — идентификатор для лога."""

    FOLDER = "folder"                   # files.get: папка, которую задал человек
    OPEN = "open"                       # вход оператора
    FIND_FOLDER = "find_folder"         # files.list: подпапка по имени
    CREATE_FOLDER = "create_folder"     # files.create: новая подпапка
    FIND_FILE = "find_file"             # files.list: файл по имени
    UPLOAD = "upload"                   # files.create с содержимым
    SHARE = "share"                     # permissions.create: открыть по ссылке
    CREATE_DOCUMENT = "create_document"  # files.create: пустой документ Google Docs в папке
    EXPORT = "export"                   # files.export: документ Google Docs в формате Word
    ACCOUNT = "account"                 # about.get: почта аккаунта, под которым вошли


class DriveEvent(str, Enum):
    CALL = "drive_call"
    FAILED = "drive_failed"


class DriveError(Exception):
    """Обращение к Диску не удалось. Текст — строка для человека без адресов; `detail` — готовая для человека
    подробность без секретов (причина входа)."""

    def __init__(
        self, reason: DriveReason, call: DriveCall, failure: AttemptFailure | None = None, detail: str = ""
    ) -> None:
        self.reason: DriveReason = reason
        self.call: DriveCall = call
        self.failure: AttemptFailure | None = failure
        self.detail: str = detail
        super().__init__(self.human)

    @property
    def status(self) -> int | None:
        return None if self.failure is None else self.failure.status

    @property
    def human(self) -> str:
        reason: str = self.reason.human.format(detail=self.detail)
        if self.status is None:
            return msg.DRIVE_FAILED.format(reason=reason)
        return msg.DRIVE_FAILED_STATUS.format(reason=reason, status=self.status)

    @property
    def event(self) -> LogEvent:
        """Строка лога: причина, обращение, код ответа и имя исключения — без текста ошибки."""
        fields: Mapping[str, object] = {} if self.failure is None else self.failure.log_fields
        return LogEvent.of(DriveEvent.FAILED, reason=self.reason, call=self.call, **fields)

    def __str__(self) -> str:
        return self.human


@dataclass(frozen=True)
class DriveFolder:
    """Папка по id: название, папка ли это вообще и может ли программа добавлять в неё файлы."""

    folder_id: str
    name: str
    is_folder: bool
    can_add_files: bool

    @classmethod
    def of(cls, folder_id: str, response: Mapping[str, str | Mapping[str, bool]]) -> DriveFolder:
        """Папка из ответа files.get с полями FOLDER_FIELDS."""
        capabilities: str | Mapping[str, bool] = response[DriveKey.CAPABILITIES]
        can_add: bool = isinstance(capabilities, Mapping) and bool(capabilities[DriveKey.CAN_ADD_CHILDREN])
        return cls(
            folder_id=folder_id,
            name=str(response[DriveKey.NAME]),
            is_folder=response[DriveKey.MIME_TYPE] == FOLDER_MIME_TYPE,
            can_add_files=can_add,
        )


@dataclass(frozen=True)
class DriveUpload:
    """Что положить на Диск: имя файла, содержимое и его вид."""

    name: str
    data: bytes
    mime_type: str

    @property
    def size(self) -> int:
        return len(self.data)


@dataclass(frozen=True)
class DriveFile:
    """Файл на Диске: id и загружен ли он этим обращением (или такой уже был)."""

    file_id: str
    is_new: bool

    @property
    def download_url(self) -> str:
        return DOWNLOAD_URL_TEMPLATE.format(file_id=self.file_id)

    @property
    def document_url(self) -> str:
        """Ссылка на документ Google Docs для людей: открывает его в редакторе."""
        return DOCUMENT_URL_TEMPLATE.format(file_id=self.file_id)


@dataclass
class DriveClient:
    """Клиент Drive v3 одного входа оператора. `service` — клиент googleapiclient или подделка с теми же цепочками
    `files().get/list/create/export(...)`, `permissions().create(...)` и `about().get(...)`; `folders` — подпапки,
    найденные в этом запуске: (id родителя, имя) → id подпапки."""

    service: Resource
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random)
    sleep: Callable[[float], None] = time.sleep
    folders: dict[tuple[str, str], str] = field(default_factory=dict)

    @classmethod
    def open(cls, login: GoogleLogin, on_login: Callable[[], None] | None = None) -> DriveClient:
        """Вход оператора и клиент Drive v3; вход не удался — DriveError(AUTH), а действующий вход не обновился из-за
        сбоя сети — DriveError(NO_NETWORK)."""
        return cls(
            service=DRIVE_API.open(
                login,
                on_login,
                DRIVE_FAILURES,
                lambda reason, error: DriveError(DriveReason(reason), DriveCall.OPEN, detail=error.human),
            )
        )

    def account_email(self) -> str:
        """Почта аккаунта Google, под которым открыт клиент (about.get): каким аккаунтом вошёл оператор."""
        response: Mapping[str, Mapping[str, str]] = self._call(
            DriveCall.ACCOUNT, lambda: self.service.about().get(fields=ACCOUNT_FIELDS).execute()
        )
        return response[DriveKey.USER][DriveKey.EMAIL]

    def folder(self, folder_id: str) -> DriveFolder:
        """Папка, которую задал человек: название, папка ли это и можно ли в неё добавлять файлы."""
        response: Mapping[str, str | Mapping[str, bool]] = self._call(
            DriveCall.FOLDER,
            lambda: self.service.files().get(fileId=folder_id, fields=FOLDER_FIELDS, supportsAllDrives=True).execute(),
        )
        return DriveFolder.of(folder_id, response)

    def ensure_path(self, parent_id: str, parts: Sequence[str]) -> str:
        """id подпапки по частям пути внутри `parent_id`: каждая часть — найти или создать."""
        folder_id: str = parent_id
        for part in parts:
            folder_id = self._subfolder(folder_id, part)
        return folder_id

    def upload(self, folder_id: str, upload: DriveUpload) -> DriveFile:
        """Файл в папке: тот же имя и размер уже есть — он; иначе загрузить и открыть по ссылке на чтение."""
        query: str = FILE_QUERY.format(name=self._quoted(upload.name), parent=self._quoted(folder_id))
        found: list[dict[str, str]] = self._list(DriveCall.FIND_FILE, query, FILE_LIST_FIELDS)
        same: list[str] = [item[DriveKey.ID] for item in found if int(item[DriveKey.SIZE]) == upload.size]
        if same:
            return DriveFile(file_id=same[0], is_new=False)
        body: dict[str, object] = {DriveKey.NAME.value: upload.name, DriveKey.PARENTS.value: [folder_id]}
        created: dict[str, str] = self._call(
            DriveCall.UPLOAD,
            lambda: self.service.files().create(
                body=body, media_body=self._media(upload), fields=CREATED_FIELDS, supportsAllDrives=True
            ).execute(),
        )
        file_id: str = created[DriveKey.ID]
        self.share(file_id, READER_ROLE)
        return DriveFile(file_id=file_id, is_new=True)

    def create_document(self, folder_id: str, name: str) -> DriveFile:
        """Пустой документ Google Docs с этим именем сразу в папке. Обращение создающее: 5xx и обрыв не
        повторяются (`DriveReason.UNKNOWN`) — повтор задвоил бы документ."""
        body: dict[str, object] = {
            DriveKey.NAME.value: name, DriveKey.MIME_TYPE.value: DOCUMENT_MIME_TYPE, DriveKey.PARENTS.value: [folder_id]
        }
        created: dict[str, str] = self._call(
            DriveCall.CREATE_DOCUMENT,
            lambda: self.service.files().create(body=body, fields=CREATED_FIELDS, supportsAllDrives=True).execute(),
            DRIVE_CREATE_FAILURES,
        )
        return DriveFile(file_id=created[DriveKey.ID], is_new=True)

    def export_word(self, file_id: str) -> bytes:
        """Документ Google Docs в формате Word (.docx) байтами. Обращение читающее: повтор ничего не задваивает."""
        return self._call(
            DriveCall.EXPORT, lambda: self.service.files().export(fileId=file_id, mimeType=WORD_MIME_TYPE).execute()
        )

    def share(self, file_id: str, role: str) -> None:
        """Открыть файл по ссылке всем, у кого она есть, с этой ролью Диска (reader, commenter, writer)."""
        body: dict[str, str] = {DriveKey.TYPE.value: ANYONE_TYPE, DriveKey.ROLE.value: role}
        self._call(
            DriveCall.SHARE,
            lambda: self.service.permissions().create(
                fileId=file_id, body=body, fields=CREATED_FIELDS, supportsAllDrives=True
            ).execute(),
        )

    def _subfolder(self, parent_id: str, name: str) -> str:
        """Подпапка `name` в `parent_id`: из кеша, найденная или созданная."""
        cached: str | None = self.folders.get((parent_id, name))
        if cached is not None:
            return cached
        query: str = FOLDER_QUERY.format(name=self._quoted(name), mime=FOLDER_MIME_TYPE, parent=self._quoted(parent_id))
        found: list[dict[str, str]] = self._list(DriveCall.FIND_FOLDER, query, FOLDER_LIST_FIELDS)
        folder_id: str = found[0][DriveKey.ID] if found else self._create_folder(parent_id, name)
        self.folders[(parent_id, name)] = folder_id
        return folder_id

    def _create_folder(self, parent_id: str, name: str) -> str:
        body: dict[str, object] = {
            DriveKey.NAME.value: name, DriveKey.MIME_TYPE.value: FOLDER_MIME_TYPE, DriveKey.PARENTS.value: [parent_id]
        }
        created: dict[str, str] = self._call(
            DriveCall.CREATE_FOLDER,
            lambda: self.service.files().create(body=body, fields=CREATED_FIELDS, supportsAllDrives=True).execute(),
        )
        return created[DriveKey.ID]

    def _list(self, call: DriveCall, query: str, fields: str) -> list[dict[str, str]]:
        """Файлы по запросу files.list: во всех дисках, без корзины."""
        response: dict[str, list[dict[str, str]]] = self._call(
            call,
            lambda: self.service.files().list(
                q=query, spaces=SEARCH_SPACE, fields=fields, pageSize=LIST_PAGE_SIZE,
                includeItemsFromAllDrives=True, supportsAllDrives=True,
            ).execute(),
        )
        return response[DriveKey.FILES]

    def _media(self, upload: DriveUpload) -> MediaIoBaseUpload:
        """Содержимое для files.create — новое на каждую попытку: повтор читает поток с начала."""
        return MediaIoBaseUpload(io.BytesIO(upload.data), mimetype=upload.mime_type, resumable=False)

    def _quoted(self, text: str) -> str:
        """Строка для запроса files.list: обратная косая черта и кавычка — с «\\»."""
        for raw, escaped in QUERY_ESCAPES:
            text = text.replace(raw, escaped)
        return text

    def _call(self, call: DriveCall, request: Callable[[], T], failures: CallFailures = DRIVE_FAILURES) -> T:
        """Одно обращение с повторами по `policy`: ответ и строка `drive_call`; повторы кончились или сбой
        неповторяемый — DriveError."""
        return CallLog(DriveEvent.CALL, call).run(
            failures,
            RetryLoop(self.policy, self.rng, self.sleep),
            request,
            lambda failure: DriveError(DriveReason(failure.reason), call, failure),
        )
