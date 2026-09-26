"""Отказ нейросети: что случилось, повторять ли, виновата ли настройка модели (CLAUDE.md §2 строки про llm\\).

Общие объекты разъёма (`app\\llm\\backend.py`). `LlmFailure` — значение отказа: вид, чья нейросеть, код ответа,
код и параметр ошибки, подробность — и правила над ними: «повторяемо», «виновата настройка», «повод для запасной
модели». `LlmRequestError` — исключение с этим значением: так разъём сообщает о сбое `complete`; попытка merge и
выбор модели дальше работают со значением. Как исключение библиотеки конкретной нейросети становится отказом, решает
её реализация в `app\\llm\\backends\\` — там же правила, которые знают параметры запроса этой нейросети.

Текст отказа — русская строка без ключа и без текста промта. `detail` — подробность ответа для лога: реализация
вычёркивает из неё ключ и обрезает её (`cleaned`); исходная ошибка библиотеки — только `__cause__` исключения.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import Enum
from typing import Final

from app.observability.log_event import LogEvent
from app.ui import messages_ru as msg

DETAIL_MAX_CHARS: Final[int] = 300


class LlmErrorKind(str, Enum):
    """Вид отказа. Значение — код причины в логе, без имени нейросети: чья она, говорит поле `backend`."""

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
    EMPTY_OUTPUT = "empty_output"        # ответ пришёл, но текста в нём нет
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
        """Этот проект не может пользоваться моделью — только это оправдывает переход на запасную."""
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


class LlmEvent(str, Enum):
    """События отказа нейросети в логе."""

    REQUEST_FAILED = "llm_request_failed"


@dataclass(frozen=True)
class LlmFailure:
    """Отказ нейросети — значение. `backend` — имя реализации (`LlmBackend.name`): по нему текст берёт название
    нейросети для человека; `status_code` — код ответа, если он был; `detail` — подробность для лога."""

    kind: LlmErrorKind
    backend: str
    status_code: int | None = None
    api_error_code: str = ""
    api_error_param: str = ""
    detail: str = ""

    def cleaned(self, scrub: Callable[[str], str]) -> LlmFailure:
        """Тот же отказ с подробностью, пропущенной через `scrub` (вычёркивание ключа владельцем ключа) и обрезанной."""
        return replace(self, detail=scrub(self.detail)[:DETAIL_MAX_CHARS])

    @property
    def retryable(self) -> bool:
        return self.kind.is_retryable

    @property
    def is_model_configuration(self) -> bool:
        return self.kind.is_model_configuration

    @property
    def is_fallback_reason(self) -> bool:
        """Модель недоступна этому проекту — повод перейти на запасную (правило вида отказа)."""
        return self.kind.is_fallback_reason

    @property
    def backend_title(self) -> str:
        """Название нейросети для человека; незнакомое имя реализации — как есть."""
        return msg.LLM_BACKEND_TITLE.get(self.backend, self.backend)

    @property
    def human_reason(self) -> str:
        """Причина для человека без обрамления «запрос не удался»."""
        return self.kind.human(self.backend_title)

    @property
    def human(self) -> str:
        if self.status_code is None:
            return msg.LLM_REQUEST_FAILED.format(reason=self.human_reason)
        return msg.LLM_REQUEST_FAILED_STATUS.format(reason=self.human_reason, status=self.status_code)

    def extend(self, event: LogEvent) -> LogEvent:
        """Строка лога `event` с полями отказа: чей, вид, код ответа, код и параметр ошибки, подробность."""
        return event.extended(
            backend=self.backend,
            reason_code=self.kind,
            status_code=self.status_code,
            api_error_code=self.api_error_code,
            api_error_param=self.api_error_param,
            detail=self.detail,
        )

    @property
    def log_line(self) -> str:
        return self.extend(LogEvent.of(LlmEvent.REQUEST_FAILED)).text


class LlmRequestError(Exception):
    """Запрос к нейросети не удался: исключение разъёма со значением отказа `failure`.

    Контракт ошибок (CLAUDE.md §11): `reason` — вид отказа, `human` — русская строка без секретов (она же текст
    исключения), `log_line` — строка лога.
    """

    def __init__(self, failure: LlmFailure) -> None:
        self.failure: LlmFailure = failure
        super().__init__(failure.human)

    @property
    def reason(self) -> LlmErrorKind:
        return self.failure.kind

    @property
    def human(self) -> str:
        return self.failure.human

    @property
    def log_line(self) -> str:
        return self.failure.log_line
