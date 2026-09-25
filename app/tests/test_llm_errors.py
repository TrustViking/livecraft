from __future__ import annotations

from app.llm.errors import DETAIL_MAX_CHARS, LlmErrorKind, LlmRequestError
from app.ui import messages_ru as msg

BACKEND: str = "fake"


def test_retryable_and_configuration_kinds() -> None:
    retryable: set[LlmErrorKind] = {kind for kind in LlmErrorKind if kind.is_retryable}
    assert retryable == {LlmErrorKind.TIMEOUT, LlmErrorKind.CONNECTION, LlmErrorKind.RATE_LIMIT, LlmErrorKind.SERVER}
    assert not LlmErrorKind.QUOTA.is_retryable and not LlmErrorKind.QUOTA.is_model_configuration
    assert LlmErrorKind.AUTH.is_model_configuration
    fallback: set[LlmErrorKind] = {kind for kind in LlmErrorKind if kind.is_fallback_reason}
    assert fallback == {LlmErrorKind.ACCESS_DENIED, LlmErrorKind.MODEL_NOT_FOUND}
    assert LlmRequestError(LlmErrorKind.MODEL_NOT_FOUND, backend=BACKEND).is_fallback_reason
    assert not LlmRequestError(LlmErrorKind.TIMEOUT, backend=BACKEND).is_fallback_reason


def test_kind_values_name_no_backend() -> None:
    assert all("openai" not in kind.value for kind in LlmErrorKind)


def test_every_kind_has_a_russian_text_and_the_message_is_it() -> None:
    assert set(msg.LLM_ERROR_KIND_TEXT) == {kind.value for kind in LlmErrorKind}
    plain: LlmRequestError = LlmRequestError(LlmErrorKind.NOT_CONFIGURED, backend="openai")
    assert str(plain) == msg.LLM_REQUEST_FAILED.format(reason=LlmErrorKind.NOT_CONFIGURED.human("OpenAI"))
    assert "ключ OpenAI" in str(plain) and plain.backend_title == "OpenAI"
    with_status: LlmRequestError = LlmRequestError(LlmErrorKind.AUTH, backend="openai", status_code=401)
    assert str(with_status) == msg.LLM_REQUEST_FAILED_STATUS.format(reason=LlmErrorKind.AUTH.human("OpenAI"), status=401)


def test_an_unknown_backend_is_named_as_is() -> None:
    error: LlmRequestError = LlmRequestError(LlmErrorKind.TIMEOUT, backend=BACKEND)
    assert error.backend_title == BACKEND and error.reason == f"{BACKEND} не ответил вовремя"
    assert error.log_line.startswith(f"backend={BACKEND} reason_code=timeout status_code=-")


def test_temperature_refusal_is_recognised_by_param_or_text() -> None:
    by_param: LlmRequestError = LlmRequestError(
        LlmErrorKind.UNSUPPORTED_PARAMETER, backend=BACKEND, api_error_param="temperature"
    )
    by_text: LlmRequestError = LlmRequestError(
        LlmErrorKind.UNSUPPORTED_PARAMETER, backend=BACKEND, detail="Unsupported parameter: 'Temperature'"
    )
    other: LlmRequestError = LlmRequestError(LlmErrorKind.BAD_REQUEST, backend=BACKEND, api_error_param="temperature")
    assert by_param.is_temperature_unsupported and by_text.is_temperature_unsupported
    assert not other.is_temperature_unsupported


def test_detail_is_cut_and_scrubbed_by_the_given_rule() -> None:
    error: LlmRequestError = LlmRequestError(LlmErrorKind.SERVER, backend=BACKEND, detail="x" * 1000 + "SECRET")
    assert len(error.detail) == DETAIL_MAX_CHARS
    scrubbed: LlmRequestError = LlmRequestError(
        LlmErrorKind.SERVER, backend=BACKEND, status_code=500, detail="key SECRET here"
    ).scrubbed(lambda text: text.replace("SECRET", "openai-key(abcd)"))
    assert "SECRET" not in scrubbed.detail and "openai-key(abcd)" in scrubbed.detail
    assert scrubbed.kind is LlmErrorKind.SERVER and scrubbed.status_code == 500 and scrubbed.backend == BACKEND
