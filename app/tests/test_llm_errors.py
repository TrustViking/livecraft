from __future__ import annotations

import pytest

from app.llm.errors import DETAIL_MAX_CHARS, LlmErrorKind, LlmRequestError
from app.tests.conftest import api_error, connection_error, timeout_error
from app.ui import messages_ru as msg


@pytest.mark.parametrize(
    ("error", "kind"),
    [
        (timeout_error(), LlmErrorKind.TIMEOUT),
        (connection_error(), LlmErrorKind.CONNECTION),
        (api_error(429, "You exceeded your current quota", code="insufficient_quota"), LlmErrorKind.QUOTA),
        (api_error(429, "Resource unavailable", code="resource_unavailable"), LlmErrorKind.RATE_LIMIT),
        (api_error(500, "boom"), LlmErrorKind.SERVER),
        (api_error(503, "overloaded"), LlmErrorKind.SERVER),
        (api_error(401, "Incorrect API key provided"), LlmErrorKind.AUTH),
        (api_error(403, "Project does not have access to model"), LlmErrorKind.ACCESS_DENIED),
        (api_error(404, "The model does not exist", code="model_not_found"), LlmErrorKind.MODEL_NOT_FOUND),
        (api_error(400, "The model does not exist", code="model_not_found"), LlmErrorKind.MODEL_NOT_FOUND),
        (
            api_error(400, "Unsupported parameter: 'temperature'", code="unsupported_parameter", param="temperature"),
            LlmErrorKind.UNSUPPORTED_PARAMETER,
        ),
        (
            api_error(400, "Unsupported parameter: 'text.format'", code="unsupported_parameter", param="text.format"),
            LlmErrorKind.REQUEST_SHAPE,
        ),
        (api_error(400, "Invalid schema for response_format 'merge_v1'"), LlmErrorKind.REQUEST_SHAPE),
        (api_error(422, "bad input"), LlmErrorKind.BAD_REQUEST),
        (api_error(409, "conflict"), LlmErrorKind.FAILED),
        (ValueError("что-то иное"), LlmErrorKind.FAILED),
    ],
)
def test_classification_follows_the_donor(error: Exception, kind: LlmErrorKind) -> None:
    assert LlmRequestError.classify(error).kind is kind


def test_fields_of_a_classified_error() -> None:
    error: LlmRequestError = LlmRequestError.classify(
        api_error(400, "Unsupported parameter: 'temperature'", code="unsupported_parameter", param="temperature")
    )
    assert (error.status_code, error.api_error_code, error.api_error_param) == (400, "unsupported_parameter", "temperature")
    assert error.is_temperature_unsupported and error.is_model_configuration and not error.retryable
    assert "reason_code=openai_unsupported_parameter status_code=400" in error.log_line


def test_retryable_and_configuration_kinds() -> None:
    retryable: set[LlmErrorKind] = {kind for kind in LlmErrorKind if kind.is_retryable}
    assert retryable == {LlmErrorKind.TIMEOUT, LlmErrorKind.CONNECTION, LlmErrorKind.RATE_LIMIT, LlmErrorKind.SERVER}
    assert not LlmErrorKind.QUOTA.is_retryable and not LlmErrorKind.QUOTA.is_model_configuration
    assert LlmErrorKind.AUTH.is_model_configuration
    fallback: set[LlmErrorKind] = {kind for kind in LlmErrorKind if kind.is_fallback_reason}
    assert fallback == {LlmErrorKind.ACCESS_DENIED, LlmErrorKind.MODEL_NOT_FOUND}


def test_every_kind_has_a_russian_text_and_the_message_is_it() -> None:
    assert set(msg.LLM_ERROR_KIND_TEXT) == {kind.value for kind in LlmErrorKind}
    error: LlmRequestError = LlmRequestError.classify(api_error(401, "Incorrect API key provided: sk-proj-****abcd"))
    assert str(error) == msg.LLM_REQUEST_FAILED_STATUS.format(reason=LlmErrorKind.AUTH.human, status=401)
    assert "sk-" not in str(error)
    plain: LlmRequestError = LlmRequestError(LlmErrorKind.NOT_CONFIGURED)
    assert str(plain) == msg.LLM_REQUEST_FAILED.format(reason=LlmErrorKind.NOT_CONFIGURED.human)


def test_detail_is_cut_and_scrubbed_by_the_given_rule() -> None:
    error: LlmRequestError = LlmRequestError.classify(api_error(500, "x" * 1000 + "SECRET"))
    assert len(error.detail) == DETAIL_MAX_CHARS
    scrubbed: LlmRequestError = LlmRequestError.classify(api_error(500, "key SECRET here")).scrubbed(
        lambda text: text.replace("SECRET", "openai-key(abcd)")
    )
    assert "SECRET" not in scrubbed.detail and "openai-key(abcd)" in scrubbed.detail
    assert scrubbed.kind is LlmErrorKind.SERVER and scrubbed.status_code == 500
