"""Клиент OpenAI Responses API (CLAUDE.md §2 строки про llm\\: `llm_client.py` restreamer; §7.4).

Ключ OpenAI — только из сейфа (`SecretValue`), не из окружения. Он раскрывается в одной точке —
`OpenAiClient._api`, в параметр `api_key` при создании клиента SDK, который ставит его в заголовок
`Authorization` (§7.4, первая точка). SDK-клиент создаётся лениво и живёт в поле объекта (у донора —
глобальный кеш клиентов модуля).

Цепочка отката донора (`OpenAIResponsesTransport`), снаружи внутрь — методы объекта `LlmExchange`:

    run                 ответ упёрся в max_output_tokens → один повтор с удвоенным пределом
    _with_flex          тариф flex ответил 429 → ожидания FLEX_RETRY_DELAYS_SEC, затем тариф по умолчанию
    _with_temperature   модель не принимает температуру → повтор без неё
    _with_retries       таймаут, обрыв, 5xx, 429 вне flex → повторы по RetryPolicy (§11; у SDK max_retries=0)
    _call               одно обращение

В лог уходят модель, тариф, токены, стоимость и лимиты — ни текста промта, ни ключа, ни текста ответа.
"""
from __future__ import annotations

import dataclasses
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Final

import openai

from app.config.loader import LlmSettings, ReasoningEffort, ServiceTier
from app.core.retry import RetryPolicy
from app.llm.errors import LlmErrorKind, LlmRequestError
from app.llm.json_text import parse_json_object
from app.llm.model import LlmModel, ServiceTierRule
from app.llm.rate_limits import RateLimitSnapshot
from app.llm.usage import RequestUsage, RunUsage, read_field
from app.observability.logging_setup import get_logger
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault

LOGGER_NAME: Final[str] = "llm"
LOGGER = get_logger(LOGGER_NAME)

# Ожидания перед повторами на тарифе flex после 429 resource_unavailable; после последнего запрос уходит на
# тариф по умолчанию. Это правило тарифа, а не политика сетевых повторов: flex дешевле вдвое и честно
# говорит «сейчас нет мощностей» — ждать дольше обычного выгодно (restreamer `FLEX_RETRY_DELAYS_SEC`).
FLEX_RETRY_DELAYS_SEC: Final[tuple[float, ...]] = (20.0, 40.0, 80.0)
MAX_OUTPUT_GROWTH: Final[int] = 2                # исчерпан max_output_tokens — один повтор с удвоенным пределом
DEFAULT_TEMPERATURE: Final[float] = 0.0          # донор шлёт 0.0 моделям, которые её принимают
DEFAULT_SCHEMA_NAME: Final[str] = "merge_v1"     # имя формата json_schema, если схема своего не назвала
# Проба доступа к модели (донор `probe_openai_model_access`): самый дешёвый настоящий запрос. Любой ответ HTTP,
# даже обрезанный, доказывает, что проект может пользоваться моделью с этим уровнем reasoning.
PROBE_PROMPT: Final[str] = "Reply with OK."
PROBE_MAX_OUTPUT_TOKENS: Final[int] = 16
PROBE_TIMEOUT_SEC: Final[float] = 30.0
PROBE_LABEL: Final[str] = "model_probe"
SDK_MAX_RETRIES: Final[int] = 0                  # повторы делает RetryPolicy, а не SDK
INCOMPLETE_MAX_OUTPUT: Final[str] = "max_output_tokens"
OUTPUT_TEXT_TYPES: Final[frozenset[str]] = frozenset({"output_text", "text"})
TEXT_JOINER: Final[str] = "\n"
MILLISECONDS: Final[float] = 1000.0
COST_FORMAT: Final[str] = "{:.6f}"
UNKNOWN: Final[str] = "unknown"


@dataclass(frozen=True)
class LlmRequest:
    """Один запрос к модели: всё, что уходит в Responses API. Откаты строят новый запрос, а не правят этот.

    `prompt` и `schema` не печатаются в `repr`: текст промта в лог не идёт. `temperature` None — не слать.
    """

    prompt: str = field(repr=False)
    model: LlmModel
    max_output_tokens: int
    reasoning_effort: ReasoningEffort
    service_tier: ServiceTierRule
    timeout_sec: float
    label: str
    schema: dict[str, Any] | None = field(default=None, repr=False, compare=False)
    temperature: float | None = DEFAULT_TEMPERATURE

    @classmethod
    def from_settings(
        cls, settings: LlmSettings, model: LlmModel, prompt: str, label: str, schema: dict[str, Any] | None = None
    ) -> LlmRequest:
        """Запрос с пределами, reasoning и тарифом из настроек `llm` livecraft.json."""
        return cls(
            prompt=prompt,
            model=model,
            max_output_tokens=settings.max_output_tokens,
            reasoning_effort=settings.reasoning_effort,
            service_tier=ServiceTierRule.of(settings.service_tier),
            timeout_sec=float(settings.timeout_sec),
            label=label,
            schema=schema,
        )

    @classmethod
    def probe(cls, settings: LlmSettings, model: LlmModel) -> LlmRequest:
        """Проба доступа к модели: тот же reasoning, тариф по умолчанию, 16 токенов, не дольше 30 с."""
        return cls(
            prompt=PROBE_PROMPT,
            model=model,
            max_output_tokens=PROBE_MAX_OUTPUT_TOKENS,
            reasoning_effort=settings.reasoning_effort,
            service_tier=ServiceTierRule.of(ServiceTier.DEFAULT),
            timeout_sec=min(PROBE_TIMEOUT_SEC, float(settings.timeout_sec)),
            label=PROBE_LABEL,
        )

    def to_kwargs(self) -> dict[str, Any]:
        """Аргументы `responses.create`: правило `_build_openai_responses_request_kwargs` донора."""
        kwargs: dict[str, Any] = {
            "model": self.model.name,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": self.prompt}]}],
            "max_output_tokens": self.max_output_tokens,
            "timeout": self.timeout_sec,
        }
        if self.model.supports_reasoning:
            kwargs["reasoning"] = {"effort": self.reasoning_effort.value}
        tier: str | None = self.service_tier.request_value
        if tier is not None:
            kwargs["service_tier"] = tier
        if self.schema is not None and self.model.supports_structured_output:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": self.schema.get("name", DEFAULT_SCHEMA_NAME),
                    "strict": True,
                    "schema": self.schema["schema"],
                }
            }
        if self.temperature is not None and self.model.supports_temperature:
            kwargs["temperature"] = float(self.temperature)
        return kwargs

    def with_more_output(self) -> LlmRequest:
        return dataclasses.replace(self, max_output_tokens=self.max_output_tokens * MAX_OUTPUT_GROWTH)

    def on_default_tier(self) -> LlmRequest:
        return dataclasses.replace(self, service_tier=ServiceTierRule.of(ServiceTier.DEFAULT))

    def without_temperature(self) -> LlmRequest:
        return dataclasses.replace(self, temperature=None)

    @property
    def sends_temperature(self) -> bool:
        return self.temperature is not None and self.model.supports_temperature

    @property
    def log_line(self) -> str:
        """Что за запрос — без его текста: ярлык, модель, тариф, пределы, длина промта."""
        return (
            f"label={self.label} model={self.model.name} family={self.model.family.value} "
            f"service_tier={self.service_tier.value} reasoning_effort={self.reasoning_effort.value} "
            f"max_output_tokens={self.max_output_tokens} structured={'yes' if self.schema is not None else 'no'} "
            f"temperature={'yes' if self.sends_temperature else 'no'} prompt_chars={len(self.prompt)}"
        )


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


def _incomplete_reason(response: Any) -> str:
    details: Any = read_field(response, "incomplete_details")
    return str(read_field(details, "reason") or "").strip().lower() if details is not None else ""


@dataclass(frozen=True)
class LlmResponse:
    """Ответ модели: текст, разобранный JSON (если просили схему), расход, лимиты и сколько обращений ушло."""

    text: str = field(repr=False)
    structured: dict[str, Any] | None = field(repr=False)
    model: str
    incomplete_reason: str
    usage: RequestUsage | None
    rate_limits: RateLimitSnapshot | None
    attempts: int
    service_tier_used: str

    @classmethod
    def from_sdk(
        cls, response: Any, request: LlmRequest, rate_limits: RateLimitSnapshot | None, attempts: int
    ) -> LlmResponse:
        text: str = _output_text(response)
        usage: RequestUsage | None = RequestUsage.from_response(response)
        return cls(
            text=text,
            structured=parse_json_object(text) if request.schema is not None else None,
            model=usage.model if usage is not None and usage.model else request.model.name,
            incomplete_reason=_incomplete_reason(response),
            usage=usage,
            rate_limits=rate_limits,
            attempts=attempts,
            service_tier_used=usage.tier.value if usage is not None and usage.service_tier else request.service_tier.value,
        )

    @property
    def hit_max_output(self) -> bool:
        return self.incomplete_reason == INCOMPLETE_MAX_OUTPUT

    @property
    def log_line(self) -> str:
        return (
            f"served_model={self.model} service_tier={self.service_tier_used} attempts={self.attempts} "
            f"output_chars={len(self.text)} finish_reason={self.incomplete_reason or 'completed'}"
        )


@dataclass(eq=False)
class OpenAiClient:
    """Клиент одного запуска: ключ из сейфа, настройки `llm`, учёт расхода запуска и SDK-клиент.

    `sdk` — фабрика клиента openai (в тестах — подделка); `policy`, `rng`, `sleep`, `clock` и `flex_delays_sec`
    — параметрами, в тестах свои. SDK-клиент создаётся при первом запросе и дальше переиспользуется.
    """

    key: SecretValue
    settings: LlmSettings
    run_usage: RunUsage = field(default_factory=RunUsage)
    sdk: Callable[..., Any] = openai.OpenAI
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random, repr=False)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    clock: Callable[[], float] = field(default=time.monotonic, repr=False)
    flex_delays_sec: tuple[float, ...] = FLEX_RETRY_DELAYS_SEC
    _sdk_client: Any = field(default=None, init=False, repr=False)

    @classmethod
    def from_vault(
        cls, vault: Vault, settings: LlmSettings, sdk: Callable[..., Any] = openai.OpenAI
    ) -> OpenAiClient:
        """Клиент с ключом из сейфа; ключа нет — LlmRequestError(NOT_CONFIGURED), к OpenAI не обращаемся."""
        key: SecretValue | None = vault.get(SecretField.OPENAI_API_KEY)
        if key is None:
            LOGGER.warning("llm_not_configured field=%s", SecretField.OPENAI_API_KEY.log_label)
            raise LlmRequestError(LlmErrorKind.NOT_CONFIGURED)
        return cls(key=key, settings=settings, sdk=sdk)

    def send(self, request: LlmRequest) -> LlmResponse:
        """Запрос со всей цепочкой откатов; ответ без текста — LlmRequestError(EMPTY_OUTPUT)."""
        return LlmExchange(client=self, request=request).run()

    def probe(self, model: LlmModel) -> LlmResponse | LlmRequestError:
        """Проба доступа: одно обращение без повторов и откатов; отказ возвращается, а не бросается."""
        try:
            return LlmExchange(client=self, request=LlmRequest.probe(self.settings, model)).once()
        except LlmRequestError as error:
            return error

    @property
    def _api(self) -> Any:
        """SDK-клиент. Единственная точка раскрытия ключа OpenAI (§7.4: заголовок Authorization клиента OpenAI)."""
        if self._sdk_client is None:
            self._sdk_client = self.sdk(
                api_key=self.key.reveal(), timeout=float(self.settings.timeout_sec), max_retries=SDK_MAX_RETRIES
            )
            LOGGER.info("llm_client_created key=%s timeout_sec=%s", self.key.log_label, self.settings.timeout_sec)
        return self._sdk_client

    def create_raw(self, kwargs: dict[str, Any]) -> Any:
        """Одно обращение к Responses API: сырой ответ (с заголовками лимитов)."""
        return self._api.responses.with_raw_response.create(**kwargs)

    def record_usage(self, usage: RequestUsage | None, request: LlmRequest) -> float | None:
        """Учесть ответ в расходе запуска; вернуть его стоимость (None — неизвестна)."""
        cost: float | None = usage.cost(request.model) if usage is not None else None
        self.run_usage.add(usage, cost)
        return cost


@dataclass(eq=False)
class LlmExchange:
    """Один `send` или `probe`: текущий запрос (откаты его заменяют), число обращений и последние лимиты.

    Откат тарифа flex на тариф по умолчанию и снятие температуры — до конца обмена: следующий повтор
    уже не просит flex и не шлёт температуру.
    """

    client: OpenAiClient
    request: LlmRequest
    attempts: int = 0
    rate_limits: RateLimitSnapshot | None = None

    def run(self) -> LlmResponse:
        response: LlmResponse = self._response(self._with_flex())
        if response.hit_max_output:
            self.request = self.request.with_more_output()
            LOGGER.warning("llm_max_output_retry %s", self.request.log_line)
            response = self._response(self._with_flex())
        if not response.text.strip():
            error: LlmRequestError = LlmRequestError(LlmErrorKind.EMPTY_OUTPUT)
            LOGGER.error("llm_request_failed %s %s", self.request.log_line, error.log_line)
            raise error
        return response

    def once(self) -> LlmResponse:
        return self._response(self._call())

    def _response(self, sdk_response: Any) -> LlmResponse:
        return LlmResponse.from_sdk(sdk_response, self.request, self.rate_limits, self.attempts)

    def _with_flex(self) -> Any:
        """Тариф flex: на 429 — ждать FLEX_RETRY_DELAYS_SEC и повторять, затем уйти на тариф по умолчанию."""
        if not self.request.service_tier.is_flex:
            return self._with_temperature()
        for delay in self.client.flex_delays_sec:
            try:
                return self._with_temperature()
            except LlmRequestError as error:
                if error.kind is not LlmErrorKind.RATE_LIMIT:
                    raise
                LOGGER.warning("llm_flex_unavailable %s retry_in_sec=%.0f", self.request.log_line, delay)
                self.client.sleep(delay)
        try:
            return self._with_temperature()
        except LlmRequestError as error:
            if error.kind is not LlmErrorKind.RATE_LIMIT:
                raise
            self.request = self.request.on_default_tier()
            LOGGER.warning("llm_flex_fallback_to_default %s", self.request.log_line)
            return self._with_temperature()

    def _with_temperature(self) -> Any:
        try:
            return self._with_retries()
        except LlmRequestError as error:
            if not (error.is_temperature_unsupported and self.request.sends_temperature):
                raise
            self.request = self.request.without_temperature()
            LOGGER.warning("llm_temperature_unsupported_retry %s", self.request.log_line)
            return self._with_retries()

    def _with_retries(self) -> Any:
        """Сбои связи и нагрузки — повторы по RetryPolicy; 429 на flex решает `_with_flex`, не здесь."""
        retry_number: int = 0
        while True:
            try:
                return self._call()
            except LlmRequestError as error:
                is_flex_busy: bool = error.kind is LlmErrorKind.RATE_LIMIT and self.request.service_tier.is_flex
                retry_number += 1
                if not error.retryable or is_flex_busy or not self.client.policy.has_retry_left(retry_number):
                    raise
                delay: float = self.client.policy.delay_sec(retry_number, self.client.rng)
                LOGGER.warning(
                    "llm_request_retry %s reason_code=%s retry=%d delay_sec=%.1f",
                    self.request.log_line,
                    error.kind.value,
                    retry_number,
                    delay,
                )
                self.client.sleep(delay)

    def _call(self) -> Any:
        """Одно обращение: ответ SDK либо LlmRequestError с вычищенной подробностью (исходная — `__cause__`)."""
        self.attempts += 1
        started: float = self.client.clock()
        try:
            raw: Any = self.client.create_raw(self.request.to_kwargs())
        except openai.APIError as error:
            failure: LlmRequestError = LlmRequestError.classify(error).scrubbed(self.client.key.scrub)
            LOGGER.warning(
                "llm_request_failed %s attempt=%d elapsed_ms=%d %s",
                self.request.log_line,
                self.attempts,
                self._elapsed_ms(started),
                failure.log_line,
            )
            raise failure from error
        self.rate_limits = RateLimitSnapshot.from_raw_response(raw)
        if self.rate_limits is not None:
            LOGGER.info("%s", self.rate_limits.log_line(self.request.model.name, self.request.label))
        response: Any = raw.parse()
        usage: RequestUsage | None = RequestUsage.from_response(response)
        cost: float | None = self.client.record_usage(usage, self.request)
        LOGGER.info(
            "llm_response %s attempt=%d elapsed_ms=%d %s cost_usd=%s finish_reason=%s",
            self.request.log_line,
            self.attempts,
            self._elapsed_ms(started),
            usage.log_fields if usage is not None else "usage=unknown",
            COST_FORMAT.format(cost) if cost is not None else UNKNOWN,
            _incomplete_reason(response) or "completed",
        )
        return response

    def _elapsed_ms(self, started: float) -> int:
        return int(round((self.client.clock() - started) * MILLISECONDS))
