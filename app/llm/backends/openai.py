"""Нейросеть OpenAI за разъёмом `LlmBackend` (CLAUDE.md §2 строки про llm\\: `llm_client.py` restreamer; §7.4).

`OpenAiClient` — реализация разъёма: общий `LlmRequest` она дополняет своими настройками (модель OpenAI,
уровень рассуждения и тариф из `LlmSettings`) — это `OpenAiRequest`; ответ SDK возвращает общим `LlmResponse`.

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

Каждый откат оставляет заметку в `LlmResponse.notes`. В лог уходят модель, тариф, токены, стоимость и
лимиты — ни текста промта, ни ключа, ни текста ответа.
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
from app.llm.backend import LlmRequest, LlmResponse
from app.llm.backends.openai_errors import OpenAiFailure
from app.llm.backends.openai_model import OpenAiModel, ServiceTierRule
from app.llm.backends.openai_rate_limits import RateLimitSnapshot
from app.llm.backends.openai_response import OpenAiReply
from app.llm.errors import LlmErrorKind, LlmRequestError
from app.llm.usage import RequestUsage, RunUsage
from app.observability.logging_setup import get_logger
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault

LOGGER_NAME: Final[str] = "llm"
LOGGER = get_logger(LOGGER_NAME)

BACKEND_NAME: Final[str] = "openai"              # имя реализации в логе и в отказах; название — msg.LLM_BACKEND_TITLE
# Ожидания перед повторами на тарифе flex после 429 resource_unavailable; после последнего запрос уходит на
# тариф по умолчанию. Это правило тарифа, а не политика сетевых повторов: flex дешевле вдвое и честно
# говорит «сейчас нет мощностей» — ждать дольше обычного выгодно (restreamer `FLEX_RETRY_DELAYS_SEC`).
FLEX_RETRY_DELAYS_SEC: Final[tuple[float, ...]] = (20.0, 40.0, 80.0)
MAX_OUTPUT_GROWTH: Final[int] = 2                # исчерпан max_output_tokens — один повтор с удвоенным пределом
DEFAULT_SCHEMA_NAME: Final[str] = "response"     # имя формата json_schema, если схема своего не назвала
SDK_MAX_RETRIES: Final[int] = 0                  # повторы делает RetryPolicy, а не SDK
# Заметки обмена для `LlmResponse.notes` — строки лога, не тексты для человека.
NOTE_FLEX_TO_DEFAULT: Final[str] = "flex→default"
NOTE_MORE_OUTPUT: Final[str] = f"max_output×{MAX_OUTPUT_GROWTH}"
NOTE_NO_TEMPERATURE: Final[str] = "no_temperature"
MILLISECONDS: Final[float] = 1000.0
COST_FORMAT: Final[str] = "{:.6f}"
UNKNOWN: Final[str] = "unknown"


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
        """Аргументы `responses.create`: правило `_build_openai_responses_request_kwargs` донора."""
        request: LlmRequest = self.request
        kwargs: dict[str, Any] = {
            "model": self.model.name,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": request.prompt}]}],
            "max_output_tokens": request.max_output_tokens,
            "timeout": request.timeout_sec,
        }
        if self.model.supports_reasoning:
            kwargs["reasoning"] = {"effort": self.reasoning_effort.value}
        tier: str | None = self.service_tier.request_value
        if tier is not None:
            kwargs["service_tier"] = tier
        if request.schema is not None and self.model.supports_structured_output:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": request.schema.get("name", DEFAULT_SCHEMA_NAME),
                    "strict": True,
                    "schema": request.schema["schema"],
                }
            }
        if self.sends_temperature and request.temperature is not None:
            kwargs["temperature"] = float(request.temperature)
        return kwargs

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
    def log_line(self) -> str:
        """Что за запрос — без его текста: ярлык, модель, тариф, пределы, длина промта."""
        request: LlmRequest = self.request
        return (
            f"label={request.label} model={self.model.name} family={self.model.family.value} "
            f"service_tier={self.service_tier.value} reasoning_effort={self.reasoning_effort.value} "
            f"max_output_tokens={request.max_output_tokens} structured={'yes' if request.is_structured else 'no'} "
            f"temperature={'yes' if self.sends_temperature else 'no'} prompt_chars={len(request.prompt)} "
            f"backend={BACKEND_NAME}"
        )


@dataclass(eq=False)
class OpenAiClient:
    """Реализация разъёма `LlmBackend` для OpenAI на один запуск: ключ из сейфа, настройки `llm`, расход, SDK.

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
            LOGGER.warning("llm_not_configured backend=%s field=%s", BACKEND_NAME, SecretField.OPENAI_API_KEY.log_label)
            raise LlmRequestError(LlmErrorKind.NOT_CONFIGURED, backend=BACKEND_NAME)
        return cls(key=key, settings=settings, sdk=sdk)

    @property
    def name(self) -> str:
        return BACKEND_NAME

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Запрос со всей цепочкой откатов; ответ без текста — LlmRequestError(EMPTY_OUTPUT)."""
        return LlmExchange(client=self, request=OpenAiRequest.of(request, self.settings)).run()

    def probe(self, model_name: str) -> LlmResponse | LlmRequestError:
        """Проба доступа: одно обращение без повторов и откатов; отказ возвращается, а не бросается."""
        try:
            return LlmExchange(client=self, request=OpenAiRequest.probe(model_name, self.settings)).once()
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

    def failure(self, error: Exception) -> LlmRequestError:
        """Отказ SDK → общий отказ разъёма с подробностью, из которой вычеркнут ключ."""
        return OpenAiFailure.of(error).to_error(BACKEND_NAME).scrubbed(self.key.scrub)


@dataclass(eq=False)
class LlmExchange:
    """Один `complete` или `probe`: текущий запрос (откаты его заменяют), число обращений, заметки, лимиты.

    Откат тарифа flex на тариф по умолчанию и снятие температуры — до конца обмена: следующий повтор
    уже не просит flex и не шлёт температуру.
    """

    client: OpenAiClient
    request: OpenAiRequest
    attempts: int = 0
    notes: list[str] = field(default_factory=list)
    rate_limits: RateLimitSnapshot | None = None

    def run(self) -> LlmResponse:
        reply: OpenAiReply = self._with_flex()
        if reply.hit_max_output:
            self._fall_back(self.request.with_more_output(), NOTE_MORE_OUTPUT, "llm_max_output_retry")
            reply = self._with_flex()
        if not reply.text.strip():
            error: LlmRequestError = LlmRequestError(LlmErrorKind.EMPTY_OUTPUT, backend=BACKEND_NAME)
            LOGGER.error("llm_request_failed %s %s", self.request.log_line, error.log_line)
            raise error
        return self._response(reply)

    def once(self) -> LlmResponse:
        return self._response(self._call())

    def _response(self, reply: OpenAiReply) -> LlmResponse:
        return reply.to_response(self.request, self.attempts, tuple(self.notes))

    def _fall_back(self, request: OpenAiRequest, note: str, event: str) -> None:
        """Сменить запрос до конца обмена, записать заметку и строку лога."""
        self.request = request
        self.notes.append(note)
        LOGGER.warning("%s %s", event, self.request.log_line)

    def _with_flex(self) -> OpenAiReply:
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
            self._fall_back(self.request.on_default_tier(), NOTE_FLEX_TO_DEFAULT, "llm_flex_fallback_to_default")
            return self._with_temperature()

    def _with_temperature(self) -> OpenAiReply:
        try:
            return self._with_retries()
        except LlmRequestError as error:
            if not (error.is_temperature_unsupported and self.request.sends_temperature):
                raise
            self._fall_back(self.request.without_temperature(), NOTE_NO_TEMPERATURE, "llm_temperature_unsupported_retry")
            return self._with_retries()

    def _with_retries(self) -> OpenAiReply:
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

    def _call(self) -> OpenAiReply:
        """Одно обращение: разобранный ответ либо LlmRequestError с вычищенной подробностью (исходная — `__cause__`)."""
        self.attempts += 1
        started: float = self.client.clock()
        try:
            raw: Any = self.client.create_raw(self.request.to_kwargs())
        except openai.APIError as error:
            failure: LlmRequestError = self.client.failure(error)
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
            LOGGER.info("%s", self.rate_limits.log_line(self.request.model.name, self.request.request.label))
        reply: OpenAiReply = OpenAiReply.of(raw.parse())
        usage: RequestUsage | None = reply.request_usage(self.request)
        self.client.run_usage.add(usage)
        cost: float | None = usage.cost_usd if usage is not None else None
        LOGGER.info(
            "llm_response %s attempt=%d elapsed_ms=%d %s cost_usd=%s finish_reason=%s",
            self.request.log_line,
            self.attempts,
            self._elapsed_ms(started),
            usage.log_fields if usage is not None else "usage=unknown",
            COST_FORMAT.format(cost) if cost is not None else UNKNOWN,
            reply.incomplete_reason or "completed",
        )
        return reply

    def _elapsed_ms(self, started: float) -> int:
        return int(round((self.client.clock() - started) * MILLISECONDS))
