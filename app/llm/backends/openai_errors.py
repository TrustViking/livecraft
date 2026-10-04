"""Отказ SDK openai → общий отказ разъёма `LlmFailure` (CLAUDE.md §2 строки про llm\\). Только для OpenAI.

Порядок проверок классификации: таймаут и обрыв связи → квота (429 с признаками оплаты) → прочий 429 → 5xx → 401 →
403 → 404 → 400/422 (неподдержанный параметр, форма ответа json_schema, прочее) → остальное. Классификация идёт по
имени класса исключения — так же ложатся и подделки SDK в тестах. Подробность `detail` здесь ещё не вычищена от
ключа: это делает владелец ключа (`OpenAiClient`). Здесь же правило «модель не берёт параметр» — оно знает имена
параметров запроса OpenAI (`OpenAiParam.is_refused_in`).
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from http import HTTPStatus
from typing import Any, Final

from app.llm.errors import LlmErrorKind, LlmFailure

QUOTA_SIGNALS: Final[tuple[str, ...]] = ("exceeded your current quota", "insufficient_quota", "billing", "quota", "balance", "credits")
REQUEST_SHAPE_SIGNALS: Final[tuple[str, ...]] = ("json_schema", "response format", "response_format", "text.format")
UNSUPPORTED_PARAMETER_CODE: Final[str] = "unsupported_parameter"
UNSUPPORTED_PARAMETER_TEXT: Final[str] = "unsupported parameter"
MODEL_NOT_FOUND_CODE: Final[str] = "model_not_found"
STATUSES_BAD_REQUEST: Final[frozenset[int]] = frozenset({HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY})
TIMEOUT_ERROR: Final[str] = "APITimeoutError"
CONNECTION_ERROR: Final[str] = "APIConnectionError"
RATE_LIMIT_ERROR: Final[str] = "RateLimitError"
SERVER_ERROR: Final[str] = "InternalServerError"
AUTH_ERROR: Final[str] = "AuthenticationError"
PERMISSION_ERROR: Final[str] = "PermissionDeniedError"
NOT_FOUND_ERROR: Final[str] = "NotFoundError"
BAD_REQUEST_ERRORS: Final[frozenset[str]] = frozenset({"BadRequestError", "UnprocessableEntityError"})


class OpenAiParam(str, Enum):
    """Параметры запроса Responses API, которые OpenAI называет в поле `param` отказа."""

    TEXT = "text"                  # формат ответа (`text.format`): отказ по нему — ошибка формы запроса
    TEMPERATURE = "temperature"    # температура: модель её не берёт — запрос повторяется без неё

    def is_refused_in(self, failure: LlmFailure) -> bool:
        """Отказ «неподдержанный параметр» называет этот параметр — в поле `param` или в тексте подробности."""
        if failure.kind is not LlmErrorKind.UNSUPPORTED_PARAMETER:
            return False
        return failure.api_error_param == self.value or self.value in failure.detail.lower()


class ErrorAttr(str, Enum):
    """Атрибуты исключения SDK, которые читает классификация."""

    STATUS = "status_code"
    CODE = "code"
    PARAM = "param"

    def text_of(self, error: Exception) -> str:
        """Значение атрибута строкой без краёв в нижнем регистре; нет — пусто."""
        return str(getattr(error, self.value, "") or "").strip().lower()


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
        status: Any = getattr(error, ErrorAttr.STATUS.value, None)
        return cls(
            type_name=type(error).__name__,
            status_code=status if isinstance(status, int) and not isinstance(status, bool) else None,
            code=ErrorAttr.CODE.text_of(error),
            param=ErrorAttr.PARAM.text_of(error),
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
        if status == HTTPStatus.TOO_MANY_REQUESTS and any(signal in detail for signal in QUOTA_SIGNALS):
            return LlmErrorKind.QUOTA
        if self.type_name == RATE_LIMIT_ERROR or status == HTTPStatus.TOO_MANY_REQUESTS:
            return LlmErrorKind.RATE_LIMIT
        if self.type_name == SERVER_ERROR or (status is not None and status >= HTTPStatus.INTERNAL_SERVER_ERROR):
            return LlmErrorKind.SERVER
        if self.type_name == AUTH_ERROR or status == HTTPStatus.UNAUTHORIZED:
            return LlmErrorKind.AUTH
        if self.type_name == PERMISSION_ERROR or status == HTTPStatus.FORBIDDEN:
            return LlmErrorKind.ACCESS_DENIED
        if self.type_name == NOT_FOUND_ERROR or self.code == MODEL_NOT_FOUND_CODE or status == HTTPStatus.NOT_FOUND:
            return LlmErrorKind.MODEL_NOT_FOUND
        if self.type_name in BAD_REQUEST_ERRORS or status in STATUSES_BAD_REQUEST:
            return self._bad_request_kind(detail)
        return LlmErrorKind.FAILED

    def _bad_request_kind(self, detail: str) -> LlmErrorKind:
        if self.code == UNSUPPORTED_PARAMETER_CODE or UNSUPPORTED_PARAMETER_TEXT in detail:
            return LlmErrorKind.REQUEST_SHAPE if self.param.startswith(OpenAiParam.TEXT) else LlmErrorKind.UNSUPPORTED_PARAMETER
        if any(signal in detail for signal in REQUEST_SHAPE_SIGNALS) or self.param.startswith(OpenAiParam.TEXT):
            return LlmErrorKind.REQUEST_SHAPE
        return LlmErrorKind.BAD_REQUEST

    def to_failure(self, backend: str) -> LlmFailure:
        """Общий отказ разъёма от имени реализации `backend`; подробность ещё не вычищена."""
        return LlmFailure(
            kind=self.kind,
            backend=backend,
            status_code=self.status_code,
            api_error_code=self.code,
            api_error_param=self.param,
            detail=self.detail,
        )
