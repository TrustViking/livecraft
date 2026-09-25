"""Отказ SDK openai → общий отказ разъёма `LlmRequestError` (CLAUDE.md §2 строки про llm\\). Только для OpenAI.

Правило классификации — `models\\model_compatibility.py::classify_openai_request_error` restreamer, порядок
проверок тот же: таймаут и обрыв связи → квота (429 с признаками оплаты) → прочий 429 → 5xx → 401 → 403 → 404 →
400/422 (неподдержанный параметр, форма ответа json_schema, прочее) → остальное.
Классификация идёт по имени класса исключения, как у донора, — так же ложатся и подделки SDK в тестах.
Подробность `detail` здесь ещё не вычищена от ключа: это делает владелец ключа (`OpenAiClient`).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

from app.llm.errors import LlmErrorKind, LlmRequestError

QUOTA_SIGNALS: Final[tuple[str, ...]] = ("exceeded your current quota", "insufficient_quota", "billing", "quota", "balance", "credits")
REQUEST_SHAPE_SIGNALS: Final[tuple[str, ...]] = ("json_schema", "response format", "response_format", "text.format")
UNSUPPORTED_PARAMETER_CODE: Final[str] = "unsupported_parameter"
UNSUPPORTED_PARAMETER_TEXT: Final[str] = "unsupported parameter"
MODEL_NOT_FOUND_CODE: Final[str] = "model_not_found"
TEXT_PARAM_PREFIX: Final[str] = "text"
STATUS_TOO_MANY: Final[int] = 429
STATUS_UNAUTHORIZED: Final[int] = 401
STATUS_FORBIDDEN: Final[int] = 403
STATUS_NOT_FOUND: Final[int] = 404
STATUS_SERVER_MIN: Final[int] = 500
STATUSES_BAD_REQUEST: Final[frozenset[int]] = frozenset({400, 422})
TIMEOUT_ERROR: Final[str] = "APITimeoutError"
CONNECTION_ERROR: Final[str] = "APIConnectionError"
RATE_LIMIT_ERROR: Final[str] = "RateLimitError"
SERVER_ERROR: Final[str] = "InternalServerError"
AUTH_ERROR: Final[str] = "AuthenticationError"
PERMISSION_ERROR: Final[str] = "PermissionDeniedError"
NOT_FOUND_ERROR: Final[str] = "NotFoundError"
BAD_REQUEST_ERRORS: Final[frozenset[str]] = frozenset({"BadRequestError", "UnprocessableEntityError"})


def _text_attr(error: Exception, name: str) -> str:
    return str(getattr(error, name, "") or "").strip().lower()


@dataclass(frozen=True)
class OpenAiFailure:
    """Что сказал отказ SDK: имя класса, код ответа, код и параметр ошибки OpenAI, текст. Сам решает вид отказа."""

    type_name: str
    status_code: int | None
    code: str
    param: str
    detail: str

    @classmethod
    def of(cls, error: Exception) -> OpenAiFailure:
        status: Any = getattr(error, "status_code", None)
        return cls(
            type_name=type(error).__name__,
            status_code=status if isinstance(status, int) and not isinstance(status, bool) else None,
            code=_text_attr(error, "code"),
            param=_text_attr(error, "param"),
            detail=str(error or "").strip() or type(error).__name__,
        )

    @property
    def kind(self) -> LlmErrorKind:
        status: int | None = self.status_code
        detail: str = self.detail.lower()
        if self.type_name == TIMEOUT_ERROR:
            return LlmErrorKind.TIMEOUT
        if self.type_name == CONNECTION_ERROR:
            return LlmErrorKind.CONNECTION
        if status == STATUS_TOO_MANY and any(signal in detail for signal in QUOTA_SIGNALS):
            return LlmErrorKind.QUOTA
        if self.type_name == RATE_LIMIT_ERROR or status == STATUS_TOO_MANY:
            return LlmErrorKind.RATE_LIMIT
        if self.type_name == SERVER_ERROR or (status is not None and status >= STATUS_SERVER_MIN):
            return LlmErrorKind.SERVER
        if self.type_name == AUTH_ERROR or status == STATUS_UNAUTHORIZED:
            return LlmErrorKind.AUTH
        if self.type_name == PERMISSION_ERROR or status == STATUS_FORBIDDEN:
            return LlmErrorKind.ACCESS_DENIED
        if self.type_name == NOT_FOUND_ERROR or self.code == MODEL_NOT_FOUND_CODE or status == STATUS_NOT_FOUND:
            return LlmErrorKind.MODEL_NOT_FOUND
        if self.type_name in BAD_REQUEST_ERRORS or status in STATUSES_BAD_REQUEST:
            return self._bad_request_kind(detail)
        return LlmErrorKind.FAILED

    def _bad_request_kind(self, detail: str) -> LlmErrorKind:
        if self.code == UNSUPPORTED_PARAMETER_CODE or UNSUPPORTED_PARAMETER_TEXT in detail:
            return LlmErrorKind.REQUEST_SHAPE if self.param.startswith(TEXT_PARAM_PREFIX) else LlmErrorKind.UNSUPPORTED_PARAMETER
        if any(signal in detail for signal in REQUEST_SHAPE_SIGNALS) or self.param.startswith(TEXT_PARAM_PREFIX):
            return LlmErrorKind.REQUEST_SHAPE
        return LlmErrorKind.BAD_REQUEST

    def to_error(self, backend: str) -> LlmRequestError:
        """Общий отказ разъёма от имени реализации `backend`; подробность ещё не вычищена."""
        return LlmRequestError(
            self.kind,
            backend=backend,
            status_code=self.status_code,
            api_error_code=self.code,
            api_error_param=self.param,
            detail=self.detail,
        )
