"""Разъём нейросети (решение Артура 25-09-2026): что merge и прогон знают о модели — и ничего сверх этого.

`LlmBackend` — протокол: запрос → ответ, проба доступа к модели, расход запуска. Реализации живут в
`app\\llm\\backends\\` — у каждой свои тарифы, цены, параметры модели и откаты; здесь их нет. Запрос и ответ —
общие объекты: в запросе только то, что имеет смысл для любой нейросети, в ответе — текст, разобранный JSON и модель,
которая ответила. Расход реализация сама складывает в `run_usage`, свои откаты сама пишет в лог.

Выбор реализации по настройке появится вместе со второй реализацией; до тех пор единственную создаёт вызывающий.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Final, Protocol, runtime_checkable

from app.config.loader import LlmSettings
from app.llm.errors import LlmRequestError
from app.llm.usage import RunUsage

DEFAULT_TEMPERATURE: Final[float] = 0.0          # детерминированный ответ; модель, которая её не берёт, — без неё
# Проба доступа к модели (правило пробы restreamer): самый дешёвый настоящий запрос. Любой ответ,
# даже обрезанный, доказывает, что модель доступна.
PROBE_PROMPT: Final[str] = "Reply with OK."
PROBE_MAX_OUTPUT_TOKENS: Final[int] = 16
PROBE_TIMEOUT_SEC: Final[float] = 30.0
PROBE_LABEL: Final[str] = "model_probe"


@dataclass(frozen=True)
class LlmRequest:
    """Один запрос к модели — без настроек конкретной реализации. `prompt` и `schema` в `repr` не печатаются.

    `schema` — JSON-схема ответа (`{"name": …, "schema": {…}}`); None — ответ свободным текстом.
    `temperature` None — не слать.
    """

    prompt: str = field(repr=False)
    model_name: str
    max_output_tokens: int
    label: str
    timeout_sec: float
    schema: dict[str, Any] | None = field(default=None, repr=False, compare=False)
    temperature: float | None = DEFAULT_TEMPERATURE

    @classmethod
    def from_settings(
        cls, settings: LlmSettings, model_name: str, prompt: str, label: str, schema: dict[str, Any] | None = None
    ) -> LlmRequest:
        """Запрос с пределом ответа и ожиданием из настроек `llm` livecraft.json."""
        return cls(
            prompt=prompt,
            model_name=model_name,
            max_output_tokens=settings.max_output_tokens,
            label=label,
            timeout_sec=float(settings.timeout_sec),
            schema=schema,
        )

    @classmethod
    def probe(cls, model_name: str, timeout_sec: float) -> LlmRequest:
        """Проба доступа к модели: 16 токенов, не дольше 30 с и не дольше настроенного ожидания."""
        return cls(
            prompt=PROBE_PROMPT,
            model_name=model_name,
            max_output_tokens=PROBE_MAX_OUTPUT_TOKENS,
            label=PROBE_LABEL,
            timeout_sec=min(PROBE_TIMEOUT_SEC, float(timeout_sec)),
        )

    @property
    def is_structured(self) -> bool:
        return self.schema is not None


@dataclass(frozen=True)
class LlmResponse:
    """Ответ модели: текст, JSON (если просили схему) и модель, которая ответила. Текст и JSON в `repr` не печатаются."""

    text: str = field(repr=False)
    structured: dict[str, Any] | None = field(repr=False)
    model: str


@runtime_checkable
class LlmBackend(Protocol):
    """Нейросеть за разъёмом. Сбой запроса — `LlmRequestError`; проба отказ возвращает, а не бросает."""

    @property
    def name(self) -> str:
        """Идентификатор реализации для лога."""
        ...

    @property
    def run_usage(self) -> RunUsage:
        """Расход этого запуска: реализация добавляет в него каждый полученный ответ."""
        ...

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Запрос со всеми откатами реализации; ответ без текста — `LlmRequestError`."""
        ...

    def probe(self, model_name: str) -> LlmResponse | LlmRequestError:
        """Одно дешёвое обращение: доступна ли модель."""
        ...
