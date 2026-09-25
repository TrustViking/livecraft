"""Отказ нейросети: что случилось, повторять ли, виновата ли настройка модели (CLAUDE.md §2 строки про llm\\).

Общий объект разъёма (`app\\llm\\backend.py`): только данные отказа и правила над ними — «повторяемо»,
«виновата настройка», «повод для запасной модели». Как исключение библиотеки конкретной нейросети становится
этим отказом, решает её реализация в `app\\llm\\backends\\`. Отказ знает, чья он (`backend`): имя
реализации идёт в лог, её название для человека — в текст.

Текст исключения — русская строка без ключа и без текста промта. `detail` — подробность ответа для лога:
реализация вычёркивает из неё ключ (`scrubbed`) и обрезает её; исходная ошибка библиотеки — только `__cause__`.
"""
from __future__ import annotations

from collections.abc import Callable
from enum import Enum
from typing import Final

from app.ui import messages_ru as msg

DETAIL_MAX_CHARS: Final[int] = 300
TEMPERATURE_PARAM: Final[str] = "temperature"
LOG_NONE: Final[str] = "-"


class LlmErrorKind(str, Enum):
    """Вид отказа. Значения — `reason_code` донора без приставки нейросети: чья она, говорит поле `backend`."""

    TIMEOUT = "timeout"
    CONNECTION = "connection_error"
    QUOTA = "quota_exhausted"
    RATE_LIMIT = "rate_limit"
    SERVER = "server_error"
    AUTH = "authentication_failed"
    ACCESS_DENIED = "model_access_denied"
    MODEL_NOT_FOUND = "model_not_found"
    REQUEST_SHAPE = "incompatible_request_shape"
    UNSUPPORTED_PARAMETER = "unsupported_parameter"
    BAD_REQUEST = "bad_request"
    FAILED = "request_failed"
    EMPTY_OUTPUT = "empty_output"        # ответ пришёл, но текста в нём нет (RuntimeError у донора)
    NOT_CONFIGURED = "not_configured"    # ключа нет — к нейросети не обращались

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

    def human(self, backend_title: str) -> str:
        """Причина для человека; `backend_title` — название нейросети в тексте («OpenAI»)."""
        return msg.LLM_ERROR_KIND_TEXT[self.value].format(provider=backend_title)


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


class LlmRequestError(Exception):
    """Запрос к нейросети не удался. Поля не меняются после создания; текст — русская строка без секретов.

    `backend` — имя реализации (`LlmBackend.name`); по нему текст берёт название нейросети для человека.
    """

    def __init__(
        self,
        kind: LlmErrorKind,
        *,
        backend: str,
        status_code: int | None = None,
        api_error_code: str = "",
        api_error_param: str = "",
        detail: str = "",
    ) -> None:
        self._kind: LlmErrorKind = kind
        self._backend: str = backend
        self._status_code: int | None = status_code
        self._api_error_code: str = api_error_code
        self._api_error_param: str = api_error_param
        self._detail: str = detail[:DETAIL_MAX_CHARS]
        super().__init__(self.human)

    def scrubbed(self, scrub: Callable[[str], str]) -> LlmRequestError:
        """Та же ошибка с подробностью, пропущенной через `scrub` (вычёркивание ключа владельцем ключа)."""
        return LlmRequestError(
            self._kind,
            backend=self._backend,
            status_code=self._status_code,
            api_error_code=self._api_error_code,
            api_error_param=self._api_error_param,
            detail=scrub(self._detail),
        )

    @property
    def kind(self) -> LlmErrorKind:
        return self._kind

    @property
    def backend(self) -> str:
        return self._backend

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
    def is_fallback_reason(self) -> bool:
        """Модель недоступна этому проекту — повод перейти на запасную (правило вида отказа)."""
        return self._kind.is_fallback_reason

    @property
    def is_temperature_unsupported(self) -> bool:
        """Модель не принимает температуру — запрос повторяется без неё (правило донора)."""
        if self._kind is not LlmErrorKind.UNSUPPORTED_PARAMETER:
            return False
        return self._api_error_param == TEMPERATURE_PARAM or TEMPERATURE_PARAM in self._detail.lower()

    @property
    def backend_title(self) -> str:
        """Название нейросети для человека; незнакомое имя реализации — как есть."""
        return msg.LLM_BACKEND_TITLE.get(self._backend, self._backend)

    @property
    def reason(self) -> str:
        """Причина для человека без обрамления «запрос не удался»."""
        return self._kind.human(self.backend_title)

    @property
    def human(self) -> str:
        if self._status_code is None:
            return msg.LLM_REQUEST_FAILED.format(reason=self.reason)
        return msg.LLM_REQUEST_FAILED_STATUS.format(reason=self.reason, status=self._status_code)

    @property
    def log_line(self) -> str:
        return (
            f"backend={self._backend} reason_code={self._kind.value} "
            f"status_code={self._status_code if self._status_code is not None else LOG_NONE} "
            f"api_error_code={self._api_error_code or LOG_NONE} api_error_param={self._api_error_param or LOG_NONE} "
            f"detail={self._detail or LOG_NONE}"
        )
