"""Google Диск без сети: подделка googleapiclient Drive v3 с теми же цепочками вызовов, что у клиента, — папки и файлы
лежат в памяти; запросы files.list разбираются так же, как их строит клиент. Исходы можно подменить очередью ошибок.
"""
from __future__ import annotations

import itertools
import random
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any

from googleapiclient.errors import HttpError

from app.core.retry import RetryPolicy
from app.google.drive import FOLDER_MIME_TYPE, DriveClient

ROOT_FOLDER_ID: str = "1AbCdEfGhIjKlMnOpQrStUvWxYz0123-_"
ROOT_FOLDER_NAME: str = "Материалы Livecraft"
ACCOUNT_EMAIL: str = "operator@example.com"
QUOTED: str = r"'((?:[^'\\]|\\.)*)'"
NAME_PATTERN: re.Pattern[str] = re.compile(rf"name = {QUOTED}")
MIME_PATTERN: re.Pattern[str] = re.compile(rf"mimeType = {QUOTED}")
PARENT_PATTERN: re.Pattern[str] = re.compile(rf"{QUOTED} in parents")
ESCAPE_PATTERN: re.Pattern[str] = re.compile(r"\\(.)")


@dataclass
class DriveItem:
    """Папка или файл в памяти подделки."""

    item_id: str
    name: str
    parent: str | None
    mime_type: str
    data: bytes = b""
    can_add: bool = True


def exported_bytes(name: str) -> bytes:
    """Байты, которые подделка отдаёт на выгрузку документа с этим именем в формате Word."""
    return f"docx:{name}".encode("utf-8")


@dataclass
class _Resp:
    """Ответ httplib2 в том объёме, который читает HttpError."""

    status: int
    reason: str = "error"


def drive_error(status: int) -> HttpError:
    """Настоящая HttpError: в её тексте — адрес запроса к Диску, как в бою."""
    content: bytes = b'{"error": {"message": "request failed"}}'
    uri: str = f"https://www.googleapis.com/drive/v3/files/{ROOT_FOLDER_ID}?alt=json"
    return HttpError(_Resp(status), content, uri=uri)  # type: ignore[arg-type]


class _Request:
    def __init__(self, drive: FakeDriveService, call: str, answer: Callable[[], Any]) -> None:
        self._drive: FakeDriveService = drive
        self._call: str = call
        self._answer: Callable[[], Any] = answer

    def execute(self) -> Any:
        self._drive.calls.append(self._call)
        failure: Exception | None = self._drive.fail_at.get(len(self._drive.calls))
        if failure is not None:
            raise failure
        if self._drive.failures:
            raise self._drive.failures.pop(0)
        return self._answer()


class _Files:
    def __init__(self, drive: FakeDriveService) -> None:
        self._drive: FakeDriveService = drive

    def get(self, *, fileId: str, fields: str, supportsAllDrives: bool) -> _Request:  # noqa: N803 — имена API
        return _Request(self._drive, "files.get", lambda: self._drive.describe(fileId))

    def list(self, *, q: str, fields: str, **options: Any) -> _Request:
        return _Request(self._drive, "files.list", lambda: {"files": self._drive.find(q)})

    def create(self, *, body: dict[str, Any], fields: str, media_body: Any = None, **options: Any) -> _Request:
        return _Request(self._drive, "files.create", lambda: {"id": self._drive.add(body, media_body)})

    def export(self, *, fileId: str, mimeType: str) -> _Request:  # noqa: N803 — имена API
        return _Request(self._drive, "files.export", lambda: self._drive.export(fileId, mimeType))


class _About:
    def __init__(self, drive: FakeDriveService) -> None:
        self._drive: FakeDriveService = drive

    def get(self, *, fields: str) -> _Request:
        return _Request(self._drive, "about.get", lambda: {"user": {"emailAddress": ACCOUNT_EMAIL}})


class _Permissions:
    def __init__(self, drive: FakeDriveService) -> None:
        self._drive: FakeDriveService = drive

    def create(self, *, fileId: str, body: dict[str, str], fields: str, **options: Any) -> _Request:  # noqa: N803
        return _Request(self._drive, "permissions.create", lambda: self._drive.share(fileId, body))


@dataclass
class FakeDriveService:
    """Диск в памяти: корневая папка материалов, обращения по порядку (`calls`), открытые по ссылке файлы (`shared`),
    выгрузки документов (`exports`: id и вид), очередь ошибок на следующие обращения (`failures`) и ошибки по номеру
    обращения с 1 (`fail_at`)."""

    items: dict[str, DriveItem] = field(default_factory=dict)
    calls: list[str] = field(default_factory=list)
    shared: dict[str, dict[str, str]] = field(default_factory=dict)
    failures: list[Exception] = field(default_factory=list)
    fail_at: dict[int, Exception] = field(default_factory=dict)
    exports: list[tuple[str, str]] = field(default_factory=list)
    ids: Iterator[int] = field(default_factory=lambda: itertools.count(1))

    def __post_init__(self) -> None:
        self.items.setdefault(ROOT_FOLDER_ID, DriveItem(ROOT_FOLDER_ID, ROOT_FOLDER_NAME, None, FOLDER_MIME_TYPE))

    def files(self) -> _Files:
        return _Files(self)

    def permissions(self) -> _Permissions:
        return _Permissions(self)

    def about(self) -> _About:
        return _About(self)

    def describe(self, item_id: str) -> dict[str, Any]:
        item: DriveItem | None = self.items.get(item_id)
        if item is None:
            raise drive_error(404)
        return {
            "id": item.item_id, "name": item.name, "mimeType": item.mime_type,
            "capabilities": {"canAddChildren": item.can_add},
        }

    def find(self, query: str) -> list[dict[str, str]]:
        """Файлы по запросу клиента: имя, родитель и, если задан, вид."""
        name: str = self._value(NAME_PATTERN, query)
        parent: str = self._value(PARENT_PATTERN, query)
        mime: re.Match[str] | None = MIME_PATTERN.search(query)
        return [
            {"id": item.item_id, "size": str(len(item.data))}
            for item in self.items.values()
            if item.name == name and item.parent == parent and (mime is None or item.mime_type == mime.group(1))
        ]

    def add(self, body: dict[str, Any], media: Any) -> str:
        item_id: str = f"id{next(self.ids)}"
        data: bytes = b"" if media is None else media.getbytes(0, media.size())
        mime: str = body.get("mimeType", "" if media is None else media.mimetype())
        self.items[item_id] = DriveItem(item_id, body["name"], body["parents"][0], mime, data)
        return item_id

    def export(self, item_id: str, mime_type: str) -> bytes:
        """Выгрузка документа: байты — вид и имя документа, чтобы тест видел, что это именно он."""
        item: DriveItem | None = self.items.get(item_id)
        if item is None:
            raise drive_error(404)
        self.exports.append((item_id, mime_type))
        return exported_bytes(item.name)

    def share(self, item_id: str, body: dict[str, str]) -> dict[str, str]:
        self.shared[item_id] = body
        return {"id": f"perm-{item_id}"}

    def path_of(self, item_id: str) -> tuple[str, ...]:
        """Путь элемента от корня материалов по именам: («preview», «28-09-2026», «uk», «1_UK_x.jpg»)."""
        item: DriveItem = self.items[item_id]
        if item.parent is None:
            return ()
        return (*self.path_of(item.parent), item.name)

    def named(self, name: str) -> list[DriveItem]:
        return [item for item in self.items.values() if item.name == name]

    def _value(self, pattern: re.Pattern[str], query: str) -> str:
        found: re.Match[str] | None = pattern.search(query)
        assert found is not None, query
        return ESCAPE_PATTERN.sub(r"\1", found.group(1))


class _NoRandom(random.Random):
    def uniform(self, a: float, b: float) -> float:
        return a


def drive_client(service: FakeDriveService, sleeps: list[float] | None = None) -> DriveClient:
    """Клиент Диска на подделке: паузы повторов — в список, без ожидания."""
    return DriveClient(
        service=service,  # type: ignore[arg-type]
        policy=RetryPolicy(),
        rng=_NoRandom(0),
        sleep=(sleeps if sleeps is not None else []).append,
    )
