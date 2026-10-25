from __future__ import annotations

from app.llm.errors import DETAIL_MAX_CHARS, LlmErrorKind, LlmFailure, LlmRequestError
from app.ui import messages_ru as msg

BACKEND: str = "fake"


def test_retryable_and_configuration_kinds() -> None:
    retryable: set[LlmErrorKind] = {kind for kind in LlmErrorKind if kind.is_retryable}
    assert retryable == {LlmErrorKind.TIMEOUT, LlmErrorKind.CONNECTION, LlmErrorKind.RATE_LIMIT, LlmErrorKind.SERVER}
    assert not LlmErrorKind.QUOTA.is_retryable and not LlmErrorKind.QUOTA.is_model_configuration
    assert LlmErrorKind.AUTH.is_model_configuration
    fallback: set[LlmErrorKind] = {kind for kind in LlmErrorKind if kind.is_fallback_reason}
    assert fallback == {LlmErrorKind.ACCESS_DENIED, LlmErrorKind.MODEL_NOT_FOUND}
    assert LlmFailure(LlmErrorKind.MODEL_NOT_FOUND, BACKEND).is_fallback_reason
    assert not LlmFailure(LlmErrorKind.TIMEOUT, BACKEND).is_fallback_reason


def test_kind_values_name_no_backend() -> None:
    assert all("openai" not in kind.value for kind in LlmErrorKind)


def test_every_kind_has_a_russian_text_and_the_message_is_it() -> None:
    assert set(msg.LLM_ERROR_KIND_TEXT) == {kind.value for kind in LlmErrorKind}
    plain: LlmFailure = LlmFailure(LlmErrorKind.NOT_CONFIGURED, "openai")
    assert plain.human == msg.LLM_REQUEST_FAILED.format(reason=LlmErrorKind.NOT_CONFIGURED.human("OpenAI"))
    assert "ключ OpenAI" in plain.human and plain.backend_title == "OpenAI"
    with_status: LlmFailure = LlmFailure(LlmErrorKind.AUTH, "openai", status_code=401)
    assert with_status.human == msg.LLM_REQUEST_FAILED_STATUS.format(reason=LlmErrorKind.AUTH.human("OpenAI"), status=401)


def test_the_exception_follows_the_error_contract() -> None:
    failure: LlmFailure = LlmFailure(LlmErrorKind.AUTH, "openai", status_code=401)
    error: LlmRequestError = LlmRequestError(failure)
    assert error.failure is failure and error.reason is LlmErrorKind.AUTH
    assert str(error) == error.human == failure.human and error.log_line == failure.log_line


def test_an_unknown_backend_is_named_as_is() -> None:
    failure: LlmFailure = LlmFailure(LlmErrorKind.TIMEOUT, BACKEND)
    assert failure.backend_title == BACKEND and failure.human_reason == f"{BACKEND} не ответил вовремя"
    assert failure.log_line == (
        f"llm_request_failed backend={BACKEND} reason_code=timeout status_code=- api_error_code=- api_error_param=- "
        "detail=-"
    )


def test_detail_is_scrubbed_by_the_given_rule_and_cut() -> None:
    long: LlmFailure = LlmFailure(LlmErrorKind.SERVER, BACKEND, detail="x" * 1000 + "SECRET").cleaned(lambda text: text)
    assert len(long.detail) == DETAIL_MAX_CHARS and "SECRET" not in long.detail
    scrubbed: LlmFailure = LlmFailure(LlmErrorKind.SERVER, BACKEND, status_code=500, detail="key SECRET here").cleaned(
        lambda text: text.replace("SECRET", "openai-key(abcd)")
    )
    assert "SECRET" not in scrubbed.detail and "openai-key(abcd)" in scrubbed.detail
    assert scrubbed.kind is LlmErrorKind.SERVER and scrubbed.status_code == 500 and scrubbed.backend == BACKEND
