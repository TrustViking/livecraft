from __future__ import annotations

import pytest

from app.llm.backends.openai_errors import OpenAiFailure
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
    assert OpenAiFailure.of(error).kind is kind
    assert OpenAiFailure.of(error).to_error("openai").kind is kind


def test_fields_of_a_classified_error() -> None:
    error: LlmRequestError = OpenAiFailure.of(
        api_error(400, "Unsupported parameter: 'temperature'", code="unsupported_parameter", param="temperature")
    ).to_error("openai")
    assert (error.status_code, error.api_error_code, error.api_error_param) == (400, "unsupported_parameter", "temperature")
    assert error.is_temperature_unsupported and error.is_model_configuration and not error.retryable
    assert "backend=openai reason_code=unsupported_parameter status_code=400" in error.log_line


def test_the_message_names_openai_and_hides_the_key() -> None:
    error: LlmRequestError = OpenAiFailure.of(api_error(401, "Incorrect API key provided: sk-proj-****abcd")).to_error("openai")
    assert str(error) == msg.LLM_REQUEST_FAILED_STATUS.format(reason=error.reason, status=401)
    assert "OpenAI не принял ключ" in str(error) and "sk-" not in str(error)


def test_the_detail_is_cut_to_the_limit() -> None:
    error: LlmRequestError = OpenAiFailure.of(api_error(500, "x" * 1000 + "SECRET")).to_error("openai")
    assert len(error.detail) == DETAIL_MAX_CHARS and "SECRET" not in error.detail
