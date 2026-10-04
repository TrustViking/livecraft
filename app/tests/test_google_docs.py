"""Клиент Google Docs (app\\google\\docs.py) на подделке Docs v1: устройство документа из сохранённого ответа
documents.get, правки пакетом и отказы Docs (CLAUDE.md §13 задача 4.4). К Google тесты не ходят."""
from __future__ import annotations

import pytest
from googleapiclient.errors import HttpError
from httplib2 import ServerNotFoundError

from app.google.auth import AuthError, AuthErrorReason, GoogleLogin
from app.core.retry import RetryPolicy
from app.google.docs import DOCS_FAILURES, DocsCall, DocsClient, DocsDocument, DocsError, DocsReason, DocsTable
from app.paths import LivecraftPaths
from app.observability.log_event import LogArea
from app.tests.fixtures.docs import (
    LAST_TABLE_CELL_STARTS, LAST_TABLE_START, FakeDocsService, docs_client, docs_error, saved_document,
)
from app.tests.fixtures.logs import LogCapture
from app.ui import messages_ru as msg

TEXT_REQUEST: dict[str, object] = {"insertText": {"location": {"index": 1}, "text": "Шапка"}}


def test_the_document_gives_its_tables_in_order_with_the_cell_starts() -> None:
    """Сохранённый ответ: таблица на 7 строк с индекса 39 и последняя — на 8 строк с индекса 62."""
    document: DocsDocument = docs_client(FakeDocsService()).document("doc-id")
    assert [table.start_index for table in document.tables] == [39, LAST_TABLE_START]
    assert document.last_table == DocsTable(start_index=LAST_TABLE_START, cell_starts=LAST_TABLE_CELL_STARTS)
    assert document.tables[0].cell_starts == (42, 45, 48, 51, 54, 57, 60)


def test_the_parsed_document_is_the_saved_answer() -> None:
    assert DocsDocument.of(saved_document()) == docs_client(FakeDocsService()).document("doc-id")


def test_an_update_sends_the_requests_as_one_batch_in_order() -> None:
    service: FakeDocsService = FakeDocsService()
    style: dict[str, object] = {"updateTextStyle": {"range": {"startIndex": 1, "endIndex": 6}}}
    docs_client(service).update("doc-id", [TEXT_REQUEST, style])
    assert service.updates == [[TEXT_REQUEST, style]] and service.calls == ["batchUpdate"]


def test_an_update_is_not_repeated_after_503_or_a_broken_connection() -> None:
    """Исход правки неизвестен: Google мог вставить текст — повтор задвоил бы его (DocsReason.UNKNOWN)."""
    for failure in (docs_error(503), ConnectionResetError(10054, "reset")):
        service: FakeDocsService = FakeDocsService(failures=[failure])
        sleeps: list[float] = []
        with pytest.raises(DocsError) as raised:
            docs_client(service, sleeps).update("doc-id", [TEXT_REQUEST])
        assert raised.value.reason is DocsReason.UNKNOWN and raised.value.call is DocsCall.UPDATE
        assert service.calls == ["batchUpdate"] and sleeps == [] and service.updates == []


def test_an_update_is_repeated_after_429() -> None:
    service: FakeDocsService = FakeDocsService(failures=[docs_error(429)])
    sleeps: list[float] = []
    docs_client(service, sleeps).update("doc-id", [TEXT_REQUEST])
    assert service.calls == ["batchUpdate", "batchUpdate"] and len(sleeps) == 1 and service.updates == [[TEXT_REQUEST]]


def test_reading_the_document_repeats_503() -> None:
    service: FakeDocsService = FakeDocsService(failures=[docs_error(503)])
    assert docs_client(service).document("doc-id").last_table.start_index == LAST_TABLE_START
    assert service.calls == ["get", "get"]


@pytest.mark.parametrize(
    ("status", "reason"),
    [(400, DocsReason.BAD_REQUEST), (403, DocsReason.NO_ACCESS), (404, DocsReason.NOT_FOUND), (409, DocsReason.REJECTED)],
)
def test_other_statuses_fail_at_once_without_the_address(status: int, reason: DocsReason) -> None:
    service: FakeDocsService = FakeDocsService(failures=[docs_error(status)])
    with pytest.raises(DocsError) as raised:
        docs_client(service).update("doc-id", [TEXT_REQUEST])
    assert raised.value.reason is reason and raised.value.status == status
    assert "docs.googleapis.com" in str(docs_error(status))          # подделка честная: адрес в тексте ошибки
    assert "googleapis" not in str(raised.value) and "googleapis" not in raised.value.event.text
    status_text: str = msg.DOCS_FAILED_STATUS.format(status=status)
    assert str(raised.value) == msg.DOCS_FAILED.format(reason=reason.human.format(detail=""), status=status_text)
    assert raised.value.event.text == f"docs_failed reason={reason.value} call=update status={status} error=HttpError"
    assert isinstance(raised.value.__cause__, HttpError)


def test_a_login_that_fails_is_a_docs_error_with_the_reason(
    livecraft_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(self: GoogleLogin, **options: object) -> None:
        raise AuthError(AuthErrorReason.SCOPES_NOT_GRANTED)

    monkeypatch.setattr(GoogleLogin, "credentials", _fail)
    with pytest.raises(DocsError) as raised:
        DocsClient.open(GoogleLogin.operator(livecraft_paths))
    assert raised.value.reason is DocsReason.AUTH and raised.value.call is DocsCall.OPEN
    assert AuthErrorReason.SCOPES_NOT_GRANTED.human in str(raised.value)
    assert str(raised.value) == msg.DOCS_FAILED.format(reason=raised.value.reason.human.format(
        detail=AuthErrorReason.SCOPES_NOT_GRANTED.human), status="")


def test_an_update_without_network_is_no_network_not_unknown() -> None:
    """Адрес сервера Google не найден: правка до Google не дошла — исход известен, она повторяется, а после повторов —
    «нет интернета» теми же словами, что у таблицы плана, а не «исход неизвестен»."""
    policy: RetryPolicy = RetryPolicy()
    service: FakeDocsService = FakeDocsService(failures=[ServerNotFoundError("x")] * policy.max_attempts)
    with pytest.raises(DocsError) as raised:
        docs_client(service).update("doc-id", [TEXT_REQUEST])
    assert raised.value.reason is DocsReason.NO_NETWORK and raised.value.call is DocsCall.UPDATE
    assert len(service.calls) == policy.max_attempts and service.updates == []
    assert DocsReason.NO_NETWORK.human == msg.GOOGLE_NO_NETWORK_TEXT
    assert str(raised.value) == msg.DOCS_FAILED.format(reason=msg.GOOGLE_NO_NETWORK_TEXT, status="")


def test_reading_without_network_is_no_network() -> None:
    policy: RetryPolicy = RetryPolicy()
    service: FakeDocsService = FakeDocsService(failures=[ServerNotFoundError("x")] * policy.max_attempts)
    with pytest.raises(DocsError) as raised:
        docs_client(service).document("doc-id")
    assert raised.value.reason is DocsReason.NO_NETWORK and raised.value.call is DocsCall.DOCUMENT


def test_a_login_that_is_not_refreshed_without_network_is_no_network(
    livecraft_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    def _fail(self: GoogleLogin, **options: object) -> None:
        raise AuthError(AuthErrorReason.REFRESH_FAILED, "sheets.token.json: TransportError")

    monkeypatch.setattr(GoogleLogin, "credentials", _fail)
    with pytest.raises(DocsError) as raised:
        DocsClient.open(GoogleLogin.operator(livecraft_paths))
    assert raised.value.reason is DocsReason.NO_NETWORK and raised.value.call is DocsCall.OPEN
    others: list[AuthErrorReason] = [reason for reason in AuthErrorReason if reason is not AuthErrorReason.REFRESH_FAILED]
    assert {DOCS_FAILURES.login_reason(reason) for reason in others} == {DocsReason.AUTH}


def test_every_reason_has_a_text() -> None:
    assert set(msg.DOCS_REASON_TEXT) == {reason.value for reason in DocsReason}


def test_a_successful_call_is_a_log_line_with_its_attempts() -> None:
    """Решение 38: строка `docs_call` — обращение и число попыток, без адресов и id документа."""
    with LogCapture.on(LogArea.PUBLISH) as capture:
        docs_client(FakeDocsService()).update("doc-id", [TEXT_REQUEST])
    assert capture.messages() == ["docs_call call=update attempts=1"]
