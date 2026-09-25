"""Ответ OpenAI Responses API: текст, причина обрыва и расход (CLAUDE.md §2 строки про llm\\). Только для OpenAI.

Правила донора: текст — `output_text`, иначе куски `output[].content[]` типов output_text/text
(`llm_client.py`); расход — поля `ResponseUsage` openai (`llm_usage_tracker.py`): input_tokens,
input_tokens_details.{cached_tokens, cache_write_tokens}, output_tokens, output_tokens_details.reasoning_tokens,
total_tokens. Здесь ответ SDK становится общими объектами разъёма — `RequestUsage` со стоимостью по ценам
OpenAI и `LlmResponse`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from app.llm.backend import LlmResponse
from app.llm.backends.openai_model import OpenAiModel, ServiceTierRule
from app.llm.json_text import parse_json_object
from app.llm.usage import RequestUsage

if TYPE_CHECKING:      # только для аннотаций: openai.py сам импортирует этот модуль
    from app.llm.backends.openai import OpenAiRequest

INT_PATTERN: Final[re.Pattern[str]] = re.compile(r"-?\d+")
THOUSANDS_SEPARATOR: Final[str] = ","
INCOMPLETE_MAX_OUTPUT: Final[str] = "max_output_tokens"
OUTPUT_TEXT_TYPES: Final[frozenset[str]] = frozenset({"output_text", "text"})
TEXT_JOINER: Final[str] = "\n"


def read_field(container: Any, name: str) -> Any:
    """Поле ответа SDK: у объекта — атрибут, у словаря — ключ; нет — None."""
    if isinstance(container, dict):
        return container.get(name)
    return getattr(container, name, None)


def parse_int(raw: Any) -> int | None:
    """Целое из числа или строки «1,234»; логическое, дробная строка и мусор — None (правило донора)."""
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw)
    text: str = str(raw or "").strip().replace(THOUSANDS_SEPARATOR, "")
    return int(text) if INT_PATTERN.fullmatch(text) else None


def _int_field(container: Any, name: str) -> int:
    return parse_int(read_field(container, name)) or 0


@dataclass(frozen=True)
class OpenAiUsage:
    """Токены одного ответа OpenAI, как их назвал сам ответ: модель и тариф — фактические, а не запрошенные."""

    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    reasoning_tokens: int
    total_tokens: int
    response_id: str
    model: str
    service_tier: str

    @classmethod
    def from_response(cls, response: Any) -> OpenAiUsage | None:
        """Расход из ответа; нет `usage` или в нём нет входа и выхода — None (расход неизвестен)."""
        usage: Any = read_field(response, "usage")
        if usage is None:
            return None
        input_tokens: int | None = parse_int(read_field(usage, "input_tokens"))
        output_tokens: int | None = parse_int(read_field(usage, "output_tokens"))
        if input_tokens is None or output_tokens is None:
            return None
        input_details: Any = read_field(usage, "input_tokens_details")
        total: int | None = parse_int(read_field(usage, "total_tokens"))
        return cls(
            input_tokens=input_tokens,
            cached_input_tokens=_int_field(input_details, "cached_tokens"),
            cache_write_tokens=_int_field(input_details, "cache_write_tokens"),
            output_tokens=output_tokens,
            reasoning_tokens=_int_field(read_field(usage, "output_tokens_details"), "reasoning_tokens"),
            total_tokens=total if total is not None else input_tokens + output_tokens,
            response_id=str(read_field(response, "id") or ""),
            model=str(read_field(response, "model") or ""),
            service_tier=str(read_field(response, "service_tier") or ""),
        )

    @property
    def tier(self) -> ServiceTierRule:
        """Тариф, по которому ответ посчитан; ответ не назвал — тариф по умолчанию."""
        return ServiceTierRule.of(self.service_tier)

    def cost(self, requested: OpenAiModel) -> float | None:
        """Стоимость по фактической модели ответа; ответ её не назвал — по запрошенной (правило донора)."""
        served: OpenAiModel = OpenAiModel(self.model) if self.model.strip() else requested
        return served.cost(self, self.tier)

    def to_request_usage(self, requested: OpenAiModel, label: str) -> RequestUsage:
        """Общий расход разъёма: токены, фактический тариф и стоимость по ценам OpenAI."""
        return RequestUsage(
            input_tokens=self.input_tokens,
            cached_input_tokens=self.cached_input_tokens,
            cache_write_tokens=self.cache_write_tokens,
            output_tokens=self.output_tokens,
            thinking_tokens=self.reasoning_tokens,
            total_tokens=self.total_tokens,
            response_id=self.response_id,
            model=self.model,
            tier=self.tier.value,
            label=label,
            cost_usd=self.cost(requested),
        )


@dataclass(frozen=True)
class OpenAiReply:
    """Один ответ SDK, разобранный: текст, причина обрыва, расход. `text` в `repr` не печатается."""

    text: str = field(repr=False)
    incomplete_reason: str
    usage: OpenAiUsage | None

    @classmethod
    def of(cls, response: Any) -> OpenAiReply:
        return cls(
            text=cls._output_text(response),
            incomplete_reason=cls._incomplete_reason(response),
            usage=OpenAiUsage.from_response(response),
        )

    @staticmethod
    def _output_text(response: Any) -> str:
        """Текст ответа: `output_text`, иначе куски `output[].content[]` типов output_text/text (правило донора)."""
        direct: Any = read_field(response, "output_text")
        if isinstance(direct, str) and direct.strip():
            return direct.strip()
        items: Any = read_field(response, "output")
        if not isinstance(items, list):
            return ""
        chunks: list[str] = []
        for item in items:
            contents: Any = read_field(item, "content")
            if not isinstance(contents, list):
                continue
            for content in contents:
                text: Any = read_field(content, "text")
                kind: str = str(read_field(content, "type") or "").strip().lower()
                if kind in OUTPUT_TEXT_TYPES and isinstance(text, str) and text.strip():
                    chunks.append(text.strip())
        return TEXT_JOINER.join(chunks).strip()

    @staticmethod
    def _incomplete_reason(response: Any) -> str:
        details: Any = read_field(response, "incomplete_details")
        return str(read_field(details, "reason") or "").strip().lower() if details is not None else ""

    @property
    def hit_max_output(self) -> bool:
        return self.incomplete_reason == INCOMPLETE_MAX_OUTPUT

    def request_usage(self, request: OpenAiRequest) -> RequestUsage | None:
        """Расход ответа в общем виде; ответ его не сообщил — None."""
        if self.usage is None:
            return None
        return self.usage.to_request_usage(request.model, request.request.label)

    def to_response(self, request: OpenAiRequest, attempts: int, notes: tuple[str, ...]) -> LlmResponse:
        """Общий ответ разъёма: JSON разбирается, только если запрос просил схему."""
        return LlmResponse(
            text=self.text,
            structured=parse_json_object(self.text) if request.request.is_structured else None,
            model=self.usage.model if self.usage is not None and self.usage.model else request.model.name,
            incomplete_reason=self.incomplete_reason,
            usage=self.request_usage(request),
            attempts=attempts,
            notes=notes,
            hit_max_output=self.hit_max_output,
        )
