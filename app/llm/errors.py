"""Отказы OpenAI: что случилось, повторять ли и виновата ли настройка модели (CLAUDE.md §2 строки про llm\\).

Правило классификации — `models\\model_compatibility.py::classify_openai_request_error` restreamer, порядок
проверок тот же: таймаут и обрыв связи → квота (429 с признаками оплаты) → прочий 429 → 5xx → 401 → 403 → 404 →
400/422 (неподдержанный параметр, форма ответа json_schema, прочее) → остальное.

Текст исключения — русская строка без ключа и без текста промта. `detail` — подробность ответа OpenAI для лога:
клиент вычёркивает из неё ключ (`SecretValue.scrub`) и обрезает её; исходная ошибка SDK — только `__cause__`.
"""
from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Any, Final

from app.ui import messages_ru as msg

DETAIL_MAX_CHARS: Final[int] = 300
QUOTA_SIGNALS: Final[tuple[str, ...]] = ("exceeded your current quota", "insufficient_quota", "billing", "quota", "balance", "credits")
REQUEST_SHAPE_SIGNALS: Final[tuple[str, ...]] = ("json_schema", "response format", "response_format", "text.format")
UNSUPPORTED_PARAMETER_CODE: Final[str] = "unsupported_parameter"
UNSUPPORTED_PARAMETER_TEXT: Final[str] = "unsupported parameter"
MODEL_NOT_FOUND_CODE: Final[str] = "model_not_found"
TEXT_PARAM_PREFIX: Final[str] = "text"
TEMPERATURE_PARAM: Final[str] = "temperature"
STATUS_TOO_MANY: Final[int] = 429
STATUS_UNAUTHORIZED: Final[int] = 401
STATUS_FORBIDDEN: Final[int] = 403
STATUS_NOT_FOUND: Final[int] = 404
STATUS_SERVER_MIN: Final[int] = 500
STATUSES_BAD_REQUEST: Final[frozenset[int]] = frozenset({400, 422})
# Имена классов openai: классификация по имени, как у донора, — так же ложатся и подделки SDK в тестах.
TIMEOUT_ERROR: Final[str] = "APITimeoutError"
CONNECTION_ERROR: Final[str] = "APIConnectionError"
RATE_LIMIT_ERROR: Final[str] = "RateLimitError"
SERVER_ERROR: Final[str] = "InternalServerError"
AUTH_ERROR: Final[str] = "AuthenticationError"
PERMISSION_ERROR: Final[str] = "PermissionDeniedError"
NOT_FOUND_ERROR: Final[str] = "NotFoundError"
BAD_REQUEST_ERRORS: Final[frozenset[str]] = frozenset({"BadRequestError", "UnprocessableEntityError"})
LOG_NONE: Final[str] = "-"


class LlmErrorKind(str, Enum):
    """Вид отказа; значения — `reason_code` донора, чтобы строки лога сравнивались с restreamer."""

    TIMEOUT = "openai_timeout"
    CONNECTION = "openai_connection_error"
    QUOTA = "openai_quota_exhausted"
    RATE_LIMIT = "openai_rate_limit"
    SERVER = "openai_server_error"
    AUTH = "openai_authentication_failed"
    ACCESS_DENIED = "openai_model_access_denied"
    MODEL_NOT_FOUND = "openai_model_not_found"
    REQUEST_SHAPE = "openai_incompatible_request_shape"
    UNSUPPORTED_PARAMETER = "openai_unsupported_parameter"
    BAD_REQUEST = "openai_bad_request"
    FAILED = "openai_request_failed"
    EMPTY_OUTPUT = "openai_empty_output"        # ответ пришёл, но текста в нём нет (RuntimeError у донора)
    NOT_CONFIGURED = "openai_not_configured"    # ключа OpenAI нет — к OpenAI не обращались

    @property
    def is_retryable(self) -> bool:
        """Сбой, который говорит о связи и нагрузке, а не о запросе: повтор может помочь."""
        return self in _RETRYABLE

    @property
    def is_model_configuration(self) -> bool:
        """Виновата настройка (ключ, модель, форма запроса): повтор того же не поможет, нужна правка."""
        return self in _MODEL_CONFIGURATION

    @property
    def is_fallback_reason(self) -> bool:
        """Этот проект не может пользоваться моделью — только это оправдывает переход на запасную (донор)."""
        return self in (LlmErrorKind.ACCESS_DENIED, LlmErrorKind.MODEL_NOT_FOUND)

    @property
    def human(self) -> str:
        return msg.LLM_ERROR_KIND_TEXT[self.value]


_RETRYABLE: Final[frozenset[LlmErrorKind]] = frozenset(
    {LlmErrorKind.TIMEOUT, LlmErrorKind.CONNECTION, LlmErrorKind.RATE_LIMIT, LlmErrorKind.SERVER}
)
_MODEL_CONFIGURATION: Final[frozenset[LlmErrorKind]] = frozenset(
    {
        LlmErrorKind.AUTH,
        LlmErrorKind.ACCESS_DENIED,
        LlmErrorKind.MODEL_NOT_FOUND,
        LlmErrorKind.REQUEST_SHAPE,
        LlmErrorKind.UNSUPPORTED_PARAMETER,
        LlmErrorKind.BAD_REQUEST,
        LlmErrorKind.NOT_CONFIGURED,
    }
)


def _text_attr(error: Exception, name: str) -> str:
    return str(getattr(error, name, "") or "").strip().lower()


class LlmRequestError(Exception):
    """Запрос к нейросети не удался. Поля не меняются после создания; текст — русская строка без секретов."""

    def __init__(
        self,
        kind: LlmErrorKind,
        status_code: int | None = None,
        api_error_code: str = "",
        api_error_param: str = "",
        detail: str = "",
    ) -> None:
        self._kind: LlmErrorKind = kind
        self._status_code: int | None = status_code
        self._api_error_code: str = api_error_code
        self._api_error_param: str = api_error_param
        self._detail: str = detail[:DETAIL_MAX_CHARS]
        super().__init__(self.human)

    @classmethod
    def classify(cls, error: Exception) -> LlmRequestError:
        """Отказ SDK → вид отказа по правилу донора. `detail` ещё не вычищен: это делает клиент (`scrubbed`)."""
        status: Any = getattr(error, "status_code", None)
        status_code: int | None = status if isinstance(status, int) and not isinstance(status, bool) else None
        code: str = _text_attr(error, "code")
        param: str = _text_attr(error, "param")
        detail: str = str(error or "").strip() or type(error).__name__
        kind: LlmErrorKind = cls._kind_of(type(error).__name__, status_code, code, param, detail.lower())
        return cls(kind, status_code=status_code, api_error_code=code, api_error_param=param, detail=detail)

    @staticmethod
    def _kind_of(type_name: str, status: int | None, code: str, param: str, detail: str) -> LlmErrorKind:
        if type_name == TIMEOUT_ERROR:
            return LlmErrorKind.TIMEOUT
        if type_name == CONNECTION_ERROR:
            return LlmErrorKind.CONNECTION
        if status == STATUS_TOO_MANY and any(signal in detail for signal in QUOTA_SIGNALS):
            return LlmErrorKind.QUOTA
        if type_name == RATE_LIMIT_ERROR or status == STATUS_TOO_MANY:
            return LlmErrorKind.RATE_LIMIT
        if type_name == SERVER_ERROR or (status is not None and status >= STATUS_SERVER_MIN):
            return LlmErrorKind.SERVER
        if type_name == AUTH_ERROR or status == STATUS_UNAUTHORIZED:
            return LlmErrorKind.AUTH
        if type_name == PERMISSION_ERROR or status == STATUS_FORBIDDEN:
            return LlmErrorKind.ACCESS_DENIED
        if type_name == NOT_FOUND_ERROR or code == MODEL_NOT_FOUND_CODE or status == STATUS_NOT_FOUND:
            return LlmErrorKind.MODEL_NOT_FOUND
        if type_name in BAD_REQUEST_ERRORS or status in STATUSES_BAD_REQUEST:
            return LlmRequestError._bad_request_kind(code, param, detail)
        return LlmErrorKind.FAILED

    @staticmethod
    def _bad_request_kind(code: str, param: str, detail: str) -> LlmErrorKind:
        if code == UNSUPPORTED_PARAMETER_CODE or UNSUPPORTED_PARAMETER_TEXT in detail:
            return LlmErrorKind.REQUEST_SHAPE if param.startswith(TEXT_PARAM_PREFIX) else LlmErrorKind.UNSUPPORTED_PARAMETER
        if any(signal in detail for signal in REQUEST_SHAPE_SIGNALS) or param.startswith(TEXT_PARAM_PREFIX):
            return LlmErrorKind.REQUEST_SHAPE
        return LlmErrorKind.BAD_REQUEST

    def scrubbed(self, scrub: Callable[[str], str]) -> LlmRequestError:
        """Та же ошибка с подробностью, пропущенной через `scrub` (вычёркивание ключа владельцем ключа)."""
        return LlmRequestError(
            self._kind,
            status_code=self._status_code,
            api_error_code=self._api_error_code,
            api_error_param=self._api_error_param,
            detail=scrub(self._detail),
        )

    @property
    def kind(self) -> LlmErrorKind:
        return self._kind

    @property
    def status_code(self) -> int | None:
        return self._status_code

    @property
    def api_error_code(self) -> str:
        return self._api_error_code

    @property
    def api_error_param(self) -> str:
        return self._api_error_param

    @property
    def detail(self) -> str:
        return self._detail

    @property
    def retryable(self) -> bool:
        return self._kind.is_retryable

    @property
    def is_model_configuration(self) -> bool:
        return self._kind.is_model_configuration

    @property
    def is_temperature_unsupported(self) -> bool:
        """Модель не принимает температуру — запрос повторяется без неё (правило донора)."""
        if self._kind is not LlmErrorKind.UNSUPPORTED_PARAMETER:
            return False
        return self._api_error_param == TEMPERATURE_PARAM or TEMPERATURE_PARAM in self._detail.lower()

    @property
    def human(self) -> str:
        if self._status_code is None:
            return msg.LLM_REQUEST_FAILED.format(reason=self._kind.human)
        return msg.LLM_REQUEST_FAILED_STATUS.format(reason=self._kind.human, status=self._status_code)

    @property
    def log_line(self) -> str:
        return (
            f"reason_code={self._kind.value} status_code={self._status_code if self._status_code is not None else LOG_NONE} "
            f"api_error_code={self._api_error_code or LOG_NONE} api_error_param={self._api_error_param or LOG_NONE} "
            f"detail={self._detail or LOG_NONE}"
        )
