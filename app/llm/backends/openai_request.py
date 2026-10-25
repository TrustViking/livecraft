"""Запрос к OpenAI Responses API: общий запрос разъёма плюс настройки OpenAI (CLAUDE.md §2 строки про llm\\).

`OpenAiRequest` — общий `LlmRequest`, модель OpenAI, уровень рассуждения и тариф из `LlmSettings`; сам строит аргументы
`responses.create` (`to_kwargs`) и новые запросы для откатов обмена: удвоенный предел ответа, тариф по умолчанию,
без температуры. `ResponseSchema` — схема ответа в формате `text.format` (json_schema, строгая): имя из схемы
запроса, а если схема своего не назвала — `response`.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Any, Final

from app.config.settings import LlmSettings, ReasoningEffort, ServiceTier
from app.llm.backend import LlmRequest
from app.llm.backends.openai_model import OpenAiModel, ServiceTierRule
from app.observability.log_event import LogEvent

BACKEND_NAME: Final[str] = "openai"              # имя реализации в логе и в отказах; название — msg.LLM_BACKEND_TITLE
MAX_OUTPUT_GROWTH: Final[int] = 2                # исчерпан max_output_tokens — один повтор с удвоенным пределом
DEFAULT_SCHEMA_NAME: Final[str] = "response"     # имя формата json_schema, если схема своего не назвала
USER_ROLE: Final[str] = "user"
INPUT_TEXT_TYPE: Final[str] = "input_text"
JSON_SCHEMA_TYPE: Final[str] = "json_schema"


class RequestKey(str, Enum):
    """Ключи аргументов `responses.create` и вложенных объектов запроса."""

    MODEL = "model"
    INPUT = "input"
    MAX_OUTPUT_TOKENS = "max_output_tokens"
    TIMEOUT = "timeout"
    REASONING = "reasoning"
    EFFORT = "effort"
    SERVICE_TIER = "service_tier"
    TEXT = "text"
    FORMAT = "format"
    TEMPERATURE = "temperature"
    ROLE = "role"
    CONTENT = "content"
    TYPE = "type"
    NAME = "name"
    STRICT = "strict"
    SCHEMA = "schema"


@dataclass(frozen=True)
class ResponseSchema:
    """Схема ответа запроса: имя формата и сама JSON-схема."""

    name: str
    body: object

    @classmethod
    def of(cls, schema: Mapping[str, object]) -> ResponseSchema:
        """Имя и тело из схемы запроса (`{"name": …, "schema": {…}}`); без имени — `response`."""
        return cls(name=str(schema.get(RequestKey.NAME.value, DEFAULT_SCHEMA_NAME)), body=schema[RequestKey.SCHEMA.value])

    @property
    def text_format(self) -> dict[str, Any]:
        """Значение аргумента `text`: строгий json_schema."""
        return {
            RequestKey.FORMAT.value: {
                RequestKey.TYPE.value: JSON_SCHEMA_TYPE,
                RequestKey.NAME.value: self.name,
                RequestKey.STRICT.value: True,
                RequestKey.SCHEMA.value: self.body,
            }
        }


@dataclass(frozen=True)
class OpenAiRequest:
    """Общий запрос плюс настройки OpenAI: модель, уровень рассуждения, тариф. Откаты строят новый, не правят этот."""

    request: LlmRequest
    model: OpenAiModel
    reasoning_effort: ReasoningEffort
    service_tier: ServiceTierRule

    @classmethod
    def of(cls, request: LlmRequest, settings: LlmSettings) -> OpenAiRequest:
        """Запрос с уровнем рассуждения и тарифом из настроек `llm` livecraft.json."""
        return cls(
            request=request,
            model=OpenAiModel(request.model_name),
            reasoning_effort=settings.reasoning_effort,
            service_tier=ServiceTierRule.of(settings.service_tier),
        )

    @classmethod
    def probe(cls, model_name: str, settings: LlmSettings) -> OpenAiRequest:
        """Проба доступа к модели: тот же уровень рассуждения, тариф по умолчанию."""
        return cls.of(LlmRequest.probe(model_name, float(settings.timeout_sec)), settings).on_default_tier()

    def to_kwargs(self) -> dict[str, Any]:
        """Аргументы `responses.create`: необязательные — только те, что модель и запрос поддерживают."""
        request: LlmRequest = self.request
        message: dict[str, Any] = {RequestKey.TYPE.value: INPUT_TEXT_TYPE, RequestKey.TEXT.value: request.prompt}
        kwargs: dict[str, Any] = {
            RequestKey.MODEL.value: self.model.name,
            RequestKey.INPUT.value: [{RequestKey.ROLE.value: USER_ROLE, RequestKey.CONTENT.value: [message]}],
            RequestKey.MAX_OUTPUT_TOKENS.value: request.max_output_tokens,
            RequestKey.TIMEOUT.value: request.timeout_sec,
        }
        return kwargs | self._optional_kwargs

    @property
    def _optional_kwargs(self) -> dict[str, Any]:
        """Рассуждение, тариф, схема ответа и температура — если модель их понимает и запрос их просит."""
        optional: dict[str, Any] = {}
        if self.model.supports_reasoning:
            optional[RequestKey.REASONING.value] = {RequestKey.EFFORT.value: self.reasoning_effort.value}
        if self.service_tier.request_value is not None:
            optional[RequestKey.SERVICE_TIER.value] = self.service_tier.request_value
        if self.request.schema is not None and self.model.supports_structured_output:
            optional[RequestKey.TEXT.value] = ResponseSchema.of(self.request.schema).text_format
        if self.sends_temperature and self.request.temperature is not None:
            optional[RequestKey.TEMPERATURE.value] = float(self.request.temperature)
        return optional

    def with_more_output(self) -> OpenAiRequest:
        grown: int = self.request.max_output_tokens * MAX_OUTPUT_GROWTH
        return dataclasses.replace(self, request=dataclasses.replace(self.request, max_output_tokens=grown))

    def on_default_tier(self) -> OpenAiRequest:
        return dataclasses.replace(self, service_tier=ServiceTierRule.of(ServiceTier.DEFAULT))

    def without_temperature(self) -> OpenAiRequest:
        return dataclasses.replace(self, request=dataclasses.replace(self.request, temperature=None))

    @property
    def sends_temperature(self) -> bool:
        return self.request.temperature is not None and self.model.supports_temperature

    @property
    def log_fields(self) -> Mapping[str, object]:
        """Что за запрос — без его текста: ярлык, модель, тариф, пределы, длина промта."""
        request: LlmRequest = self.request
        return dict(
            label=request.label,
            model=self.model.name,
            family=self.model.family,
            service_tier=self.service_tier.value,
            reasoning_effort=self.reasoning_effort,
            max_output_tokens=request.max_output_tokens,
            structured=request.is_structured,
            temperature=self.sends_temperature,
            prompt_chars=len(request.prompt),
            backend=BACKEND_NAME,
        )

    def event(self, name: Enum) -> LogEvent:
        """Строка лога `name` о запросе: его поля без текста промта."""
        return LogEvent.of(name, **self.log_fields)
