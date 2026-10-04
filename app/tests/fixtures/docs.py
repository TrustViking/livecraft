"""Google Docs без сети: подделка googleapiclient Docs v1 с теми же цепочками вызовов, что у клиента.

documents.get отдаёт сохранённый ответ (`app\\tests\\data\\docs\\`): документ с шапкой и двумя таблицами в одну
колонку — вторая (последняя) начинается с индекса 62, её абзацы ячеек — с 65 через каждые 3. documents.batchUpdate
запоминает запросы по порядку. Исходы можно подменить: очередь ошибок на следующие обращения, ошибка по номеру
обращения, отказ 400 на картинку по адресу — как у Docs, который не смог её скачать.
"""
from __future__ import annotations

import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from googleapiclient.errors import HttpError

from app.core.retry import RetryPolicy
from app.google.docs import DocsClient

DATA_DIR: Path = Path(__file__).resolve().parent.parent / "data" / "docs"
DOCUMENT_TWO_TABLES: str = "document_two_tables.json"
LAST_TABLE_START: int = 62
LAST_TABLE_CELL_STARTS: tuple[int, ...] = (65, 68, 71, 74, 77, 80, 83, 86)


@dataclass
class _Resp:
    """Ответ httplib2 в том объёме, который читает HttpError."""

    status: int
    reason: str = "error"


def docs_error(status: int) -> HttpError:
    """Настоящая HttpError: в её тексте — адрес запроса к Docs, как в бою."""
    content: bytes = b'{"error": {"message": "request failed"}}'
    return HttpError(_Resp(status), content, uri="https://docs.googleapis.com/v1/documents/doc-id:batchUpdate")  # type: ignore[arg-type]


def saved_document(name: str = DOCUMENT_TWO_TABLES) -> dict[str, Any]:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


class _Request:
    def __init__(self, docs: FakeDocsService, call: str, answer: Any, images: tuple[str, ...] = ()) -> None:
        self._docs: FakeDocsService = docs
        self._call: str = call
        self._answer: Any = answer
        self._images: tuple[str, ...] = images

    def execute(self) -> Any:
        self._docs.calls.append(self._call)
        failure: Exception | None = self._docs.fail_at.get(len(self._docs.calls))
        if failure is not None:
            raise failure
        if self._docs.failures:
            raise self._docs.failures.pop(0)
        if any(uri in self._docs.refused_images for uri in self._images):
            raise docs_error(400)
        if self._call == "batchUpdate":
            self._docs.updates.append(self._answer)
            return {"replies": []}
        return self._answer


class _Documents:
    def __init__(self, docs: FakeDocsService) -> None:
        self._docs: FakeDocsService = docs

    def get(self, *, documentId: str) -> _Request:  # noqa: N803 — имена API
        return _Request(self._docs, "get", self._docs.document)

    def batchUpdate(self, *, documentId: str, body: dict[str, Any]) -> _Request:  # noqa: N802, N803 — имена API
        requests: list[dict[str, Any]] = body["requests"]
        images: tuple[str, ...] = tuple(
            request["insertInlineImage"]["uri"] for request in requests if "insertInlineImage" in request
        )
        return _Request(self._docs, "batchUpdate", requests, images)


@dataclass
class FakeDocsService:
    """Docs в памяти: ответ documents.get (`document`), обращения по порядку (`calls`), принятые пакеты правок
    (`updates`), очередь ошибок (`failures`), ошибки по номеру обращения с 1 (`fail_at`) и адреса картинок, которые
    Docs не скачает (`refused_images`, отказ 400)."""

    document: dict[str, Any] = field(default_factory=saved_document)
    calls: list[str] = field(default_factory=list)
    updates: list[list[dict[str, Any]]] = field(default_factory=list)
    failures: list[Exception] = field(default_factory=list)
    fail_at: dict[int, Exception] = field(default_factory=dict)
    refused_images: set[str] = field(default_factory=set)

    def documents(self) -> _Documents:
        return _Documents(self)

    @property
    def requests(self) -> list[dict[str, Any]]:
        """Все принятые запросы по порядку."""
        return [request for update in self.updates for request in update]

    def kinds(self, update: int) -> list[str]:
        """Виды запросов пакета правок по порядку: insertText, updateTextStyle, …"""
        return [next(iter(request)) for request in self.updates[update]]

    @property
    def images(self) -> list[dict[str, Any]]:
        """Вставленные картинки по порядку."""
        return [request["insertInlineImage"] for request in self.requests if "insertInlineImage" in request]


class _NoRandom(random.Random):
    def uniform(self, a: float, b: float) -> float:
        return a


def docs_client(service: FakeDocsService, sleeps: list[float] | None = None) -> DocsClient:
    """Клиент Docs на подделке: паузы повторов — в список, без ожидания."""
    return DocsClient(
        service=service,  # type: ignore[arg-type]
        policy=RetryPolicy(),
        rng=_NoRandom(0),
        sleep=(sleeps if sleeps is not None else []).append,
    )
