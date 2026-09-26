"""Ответ OpenAI Responses API: текст, причина обрыва и расход (CLAUDE.md §2 строки про llm\\). Только для OpenAI.

Текст — `output_text`, иначе куски `output[].content[]` типов output_text/text. Расход — поля `ResponseUsage` openai:
input_tokens, input_tokens_details.{cached_tokens, cache_write_tokens}, output_tokens,
output_tokens_details.reasoning_tokens, total_tokens. Ответ SDK бывает объектом или словарём — `SdkObject` читает поля
одинаково. Здесь ответ SDK становится общими объектами разъёма — `RequestUsage` со стоимостью по ценам OpenAI и
`LlmResponse`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Final

from app.core.text_format import NEWLINE
from app.llm.backend import LlmResponse
from app.llm.backends.openai_model import OpenAiModel, OpenAiTariffs, ServiceTierRule
from app.llm.backends.openai_request import OpenAiRequest
from app.llm.json_text import ParsedJson
from app.llm.usage import RequestUsage, TokenCounts

INT_PATTERN: Final[re.Pattern[str]] = re.compile(r"-?\d+")
THOUSANDS_SEPARATOR: Final[str] = ","
INCOMPLETE_MAX_OUTPUT: Final[str] = "max_output_tokens"
OUTPUT_TEXT_TYPES: Final[frozenset[str]] = frozenset({"output_text", "text"})


class ResponseField(str, Enum):
    """Поля ответа Responses API, которые читает программа."""

    ID = "id"
    MODEL = "model"
    SERVICE_TIER = "service_tier"
    USAGE = "usage"
    OUTPUT = "output"
    OUTPUT_TEXT = "output_text"
    CONTENT = "content"
    TEXT = "text"
    TYPE = "type"
    INCOMPLETE_DETAILS = "incomplete_details"
    REASON = "reason"
    INPUT_TOKENS = "input_tokens"
    INPUT_DETAILS = "input_tokens_details"
    CACHED_TOKENS = "cached_tokens"
    CACHE_WRITE_TOKENS = "cache_write_tokens"
    OUTPUT_TOKENS = "output_tokens"
    OUTPUT_DETAILS = "output_tokens_details"
    REASONING_TOKENS = "reasoning_tokens"
    TOTAL_TOKENS = "total_tokens"


def parse_int(raw: Any) -> int | None:
    """Целое из числа или строки «1,234»; логическое, дробная строка и мусор — None."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    text: str = str(raw or "").strip().replace(THOUSANDS_SEPARATOR, "")
    return int(text) if INT_PATTERN.fullmatch(text) else None


@dataclass(frozen=True)
class SdkObject:
    """Объект ответа SDK или его часть: поле читается у объекта атрибутом, у словаря ключом; нет — None."""

    value: Any

    def get(self, name: ResponseField) -> Any:
        if isinstance(self.value, dict):
            return self.value.get(name.value)
        return getattr(self.value, name.value, None)

    def part(self, name: ResponseField) -> SdkObject:
        return SdkObject(self.get(name))

    def integer(self, name: ResponseField) -> int | None:
        return parse_int(self.get(name))

    def count(self, name: ResponseField) -> int:
        """Число токенов поля; нет или не число — 0."""
        return self.integer(name) or 0

    def text(self, name: ResponseField) -> str:
        """Строка поля без краёв; нет — пусто."""
        return str(self.get(name) or "").strip()

    def items(self, name: ResponseField) -> tuple[SdkObject, ...]:
        """Элементы поля-списка; не список — пусто."""
        found: Any = self.get(name)
        return tuple(SdkObject(item) for item in found) if isinstance(found, list) else ()

    @property
    def output_text(self) -> str:
        """Текст ответа: `output_text`, иначе куски `output[].content[]` типов output_text/text."""
        direct: str = self.text(ResponseField.OUTPUT_TEXT)
        if direct:
            return direct
        chunks: list[str] = [
            content.text(ResponseField.TEXT)
            for item in self.items(ResponseField.OUTPUT)
            for content in item.items(ResponseField.CONTENT)
            if content.text(ResponseField.TYPE).lower() in OUTPUT_TEXT_TYPES and content.text(ResponseField.TEXT)
        ]
        return NEWLINE.join(chunks).strip()


@dataclass(frozen=True)
class OpenAiUsage:
    """Токены одного ответа OpenAI, как их назвал сам ответ: модель и тариф — фактические, а не запрошенные."""

    tokens: TokenCounts
    response_id: str
    model: str
    service_tier: str

    @classmethod
    def from_response(cls, response: SdkObject) -> OpenAiUsage | None:
        """Расход из ответа; нет `usage` или в нём нет входа и выхода — None (расход неизвестен)."""
        usage: SdkObject = response.part(ResponseField.USAGE)
        input_tokens: int | None = usage.integer(ResponseField.INPUT_TOKENS)
        output_tokens: int | None = usage.integer(ResponseField.OUTPUT_TOKENS)
        if input_tokens is None or output_tokens is None:
            return None
        input_details: SdkObject = usage.part(ResponseField.INPUT_DETAILS)
        total: int | None = usage.integer(ResponseField.TOTAL_TOKENS)
        tokens: TokenCounts = TokenCounts(
            input_tokens=input_tokens,
            cached_input_tokens=input_details.count(ResponseField.CACHED_TOKENS),
            cache_write_tokens=input_details.count(ResponseField.CACHE_WRITE_TOKENS),
            output_tokens=output_tokens,
            thinking_tokens=usage.part(ResponseField.OUTPUT_DETAILS).count(ResponseField.REASONING_TOKENS),
            total_tokens=total if total is not None else input_tokens + output_tokens,
        )
        return cls(
            tokens=tokens,
            response_id=response.text(ResponseField.ID),
            model=response.text(ResponseField.MODEL),
            service_tier=response.text(ResponseField.SERVICE_TIER),
        )

    @property
    def tier(self) -> ServiceTierRule:
        """Тариф, по которому ответ посчитан; ответ не назвал — тариф по умолчанию."""
        return ServiceTierRule.of(self.service_tier)

    def served(self, requested: OpenAiModel) -> OpenAiModel:
        """Модель, по которой считается цена: названная ответом, а не названа — запрошенная."""
        return OpenAiModel(self.model) if self.model else requested

    def to_request_usage(self, request: OpenAiRequest, tariffs: OpenAiTariffs) -> RequestUsage:
        """Общий расход разъёма: токены, фактический тариф и стоимость по ценам OpenAI."""
        return RequestUsage(
            tokens=self.tokens,
            response_id=self.response_id,
            model=self.model,
            tier=self.tier.value,
            label=request.request.label,
            cost_usd=tariffs.cost(self.served(request.model), self.tokens, self.tier),
        )


@dataclass(frozen=True)
class OpenAiReply:
    """Один ответ SDK, разобранный: текст, причина обрыва, расход. `text` в `repr` не печатается."""

    text: str = field(repr=False)
    incomplete_reason: str
    usage: OpenAiUsage | None

    @classmethod
    def of(cls, raw: Any) -> OpenAiReply:
        response: SdkObject = SdkObject(raw)
        return cls(
            text=response.output_text,
            incomplete_reason=response.part(ResponseField.INCOMPLETE_DETAILS).text(ResponseField.REASON).lower(),
            usage=OpenAiUsage.from_response(response),
        )

    @property
    def hit_max_output(self) -> bool:
        return self.incomplete_reason == INCOMPLETE_MAX_OUTPUT

    def request_usage(self, request: OpenAiRequest, tariffs: OpenAiTariffs) -> RequestUsage | None:
        """Расход ответа в общем виде; ответ его не сообщил — None."""
        return self.usage.to_request_usage(request, tariffs) if self.usage is not None else None

    def to_response(self, request: OpenAiRequest) -> LlmResponse:
        """Общий ответ разъёма: JSON разбирается, только если запрос просил схему; модель — названная ответом."""
        return LlmResponse(
            text=self.text,
            structured=ParsedJson.first_object(self.text).data if request.request.is_structured else None,
            model=self.usage.model if self.usage is not None and self.usage.model else request.model.name,
        )
