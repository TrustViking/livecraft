"""Нейросеть OpenAI за разъёмом `LlmBackend` (CLAUDE.md §2 строки про llm\\, §7.4).

`OpenAiClient` — реализация разъёма: общий `LlmRequest` она дополняет своими настройками (`OpenAiRequest`), ответ SDK
возвращает общим `LlmResponse`, отказ SDK — общим `LlmFailure`.

Ключ OpenAI — только из сейфа (`SecretValue`), не из окружения. Он раскрывается в одной точке —
`OpenAiClient._api`, в параметр `api_key` при создании клиента SDK, который ставит его в заголовок
`Authorization` (§7.4, первая точка). SDK-клиент создаётся лениво и живёт в поле объекта.

Цепочка откатов, снаружи внутрь — методы объекта `LlmExchange`:

    run                 ответ упёрся в max_output_tokens → один повтор с удвоенным пределом
    _with_flex          тариф flex ответил 429 → ожидания FLEX_RETRY_DELAYS_SEC, затем тариф по умолчанию
    _with_temperature   модель не принимает температуру → повтор без неё
    _with_retries       таймаут, обрыв, 5xx, 429 вне flex → повторы RetryLoop (§11; у SDK max_retries=0)
    _call               одно обращение

Каждый откат пишет свою строку лога (`llm_max_output_retry`, `llm_flex_fallback_to_default`,
`llm_temperature_unsupported_retry`); расход каждого обращения ложится в `run_usage` клиента. В лог уходят модель,
тариф, токены, стоимость и лимиты — ни текста промта, ни ключа, ни текста ответа.
"""
from __future__ import annotations

import logging
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Final

import openai

from app.config.settings import LlmSettings
from app.core.clock import Clock
from app.core.retry import AttemptFailure, RetryLoop, RetryPolicy, RetryRun, RetryStep
from app.llm.backend import LlmRequest, LlmResponse
from app.llm.backends.openai_errors import OpenAiFailure, OpenAiParam
from app.llm.backends.openai_model import OpenAiTariffs
from app.llm.backends.openai_rate_limits import RateLimitSnapshot
from app.llm.backends.openai_request import BACKEND_NAME, OpenAiRequest
from app.llm.backends.openai_response import OpenAiReply
from app.llm.errors import LlmErrorKind, LlmEvent, LlmFailure, LlmRequestError
from app.llm.usage import COST_FORMAT, RequestUsage, RunUsage
from app.observability.log_event import LogArea, LogEvent, LogValue, get_logger
from app.secretsafe.field import SecretField
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault

LOGGER = get_logger(LogArea.LLM)

# Ожидания перед повторами на тарифе flex после 429 resource_unavailable; после последнего запрос уходит на
# тариф по умолчанию. Это правило тарифа, а не политика сетевых повторов: flex дешевле вдвое и честно
# говорит «сейчас нет мощностей» — ждать дольше обычного выгодно.
FLEX_RETRY_DELAYS_SEC: Final[tuple[float, ...]] = (20.0, 40.0, 80.0)
SDK_MAX_RETRIES: Final[int] = 0                  # повторы делает RetryPolicy, а не SDK
MILLISECONDS: Final[float] = 1000.0
FINISH_COMPLETED: Final[str] = "completed"       # ответ не оборван


class OpenAiEvent(str, Enum):
    """События обмена с OpenAI в логе."""

    NOT_CONFIGURED = "llm_not_configured"
    CLIENT_CREATED = "llm_client_created"
    REQUEST_RETRY = "llm_request_retry"
    RESPONSE = "llm_response"
    MAX_OUTPUT_RETRY = "llm_max_output_retry"
    FLEX_UNAVAILABLE = "llm_flex_unavailable"
    FLEX_FALLBACK = "llm_flex_fallback_to_default"
    TEMPERATURE_RETRY = "llm_temperature_unsupported_retry"


@dataclass(eq=False)
class OpenAiClient:
    """Реализация разъёма `LlmBackend` для OpenAI на один запуск: ключ из сейфа, настройки `llm`, расход, SDK.

    `sdk` — фабрика клиента openai (в тестах — подделка); `policy`, `rng`, `sleep`, `clock` (часы программы:
    длительность обращения и обнуление лимитов) и `flex_delays_sec` — параметрами, в тестах свои; `tariffs` — цены
    OpenAI. SDK-клиент создаётся при первом запросе и дальше переиспользуется.
    """

    key: SecretValue
    settings: LlmSettings
    run_usage: RunUsage = field(default_factory=RunUsage)
    sdk: Callable[..., Any] = openai.OpenAI
    policy: RetryPolicy = field(default_factory=RetryPolicy)
    rng: random.Random = field(default_factory=random.Random, repr=False)
    sleep: Callable[[float], None] = field(default=time.sleep, repr=False)
    clock: Clock = field(default_factory=Clock.utc, repr=False)
    flex_delays_sec: tuple[float, ...] = FLEX_RETRY_DELAYS_SEC
    tariffs: OpenAiTariffs = field(default_factory=OpenAiTariffs.load, repr=False)
    _sdk_client: Any = field(default=None, init=False, repr=False)

    @classmethod
    def from_vault(
        cls, vault: Vault, settings: LlmSettings, sdk: Callable[..., Any] = openai.OpenAI
    ) -> OpenAiClient:
        """Клиент с ключом из сейфа; ключа нет — LlmRequestError(NOT_CONFIGURED), к OpenAI не обращаемся."""
        key: SecretValue | None = vault.get(SecretField.OPENAI_API_KEY)
        if key is None:
            missing: LogEvent = LogEvent.of(OpenAiEvent.NOT_CONFIGURED, backend=BACKEND_NAME)
            missing.extended(field=SecretField.OPENAI_API_KEY.log_label).emit(LOGGER, logging.WARNING)
            raise LlmRequestError(LlmFailure(LlmErrorKind.NOT_CONFIGURED, BACKEND_NAME))
        return cls(key=key, settings=settings, sdk=sdk)

    @property
    def name(self) -> str:
        return BACKEND_NAME

    def complete(self, request: LlmRequest) -> LlmResponse:
        """Запрос со всей цепочкой откатов; ответ без текста — LlmRequestError(EMPTY_OUTPUT)."""
        return LlmExchange(client=self, request=OpenAiRequest.of(request, self.settings)).run()

    def probe(self, model_name: str) -> LlmResponse | LlmFailure:
        """Проба доступа: одно обращение без повторов и откатов; отказ возвращается значением."""
        try:
            return LlmExchange(client=self, request=OpenAiRequest.probe(model_name, self.settings)).once()
        except LlmRequestError as error:
            return error.failure

    @property
    def _api(self) -> Any:
        """SDK-клиент. Единственная точка раскрытия ключа OpenAI (§7.4: заголовок Authorization клиента OpenAI)."""
        if self._sdk_client is None:
            self._sdk_client = self.sdk(
                api_key=self.key.reveal(), timeout=float(self.settings.timeout_sec), max_retries=SDK_MAX_RETRIES
            )
            created: LogEvent = LogEvent.of(OpenAiEvent.CLIENT_CREATED, key=self.key.log_label)
            created.extended(timeout_sec=self.settings.timeout_sec).emit(LOGGER)
        return self._sdk_client

    def create_raw(self, kwargs: dict[str, Any]) -> Any:
        """Одно обращение к Responses API: сырой ответ (с заголовками лимитов)."""
        return self._api.responses.with_raw_response.create(**kwargs)

    def failure(self, error: Exception) -> LlmFailure:
        """Отказ SDK → общий отказ разъёма с подробностью, из которой вычеркнут ключ."""
        return OpenAiFailure.of(error).to_failure(BACKEND_NAME).cleaned(self.key.scrub)


@dataclass(eq=False)
class LlmExchange:
    """Один `complete` или `probe`: текущий запрос (откаты его заменяют) и число обращений.

    Откат тарифа flex на тариф по умолчанию и снятие температуры — до конца обмена: следующий повтор
    уже не просит flex и не шлёт температуру.
    """

    client: OpenAiClient
    request: OpenAiRequest
    attempts: int = 0

    def run(self) -> LlmResponse:
        reply: OpenAiReply = self._with_flex()
        if reply.hit_max_output:
            self._fall_back(self.request.with_more_output(), OpenAiEvent.MAX_OUTPUT_RETRY)
            reply = self._with_flex()
        if not reply.text.strip():
            failure: LlmFailure = LlmFailure(LlmErrorKind.EMPTY_OUTPUT, BACKEND_NAME)
            failure.extend(self.request.event(LlmEvent.REQUEST_FAILED)).emit(LOGGER, logging.ERROR)
            raise LlmRequestError(failure)
        return reply.to_response(self.request)

    def once(self) -> LlmResponse:
        return self._call().to_response(self.request)

    def _fall_back(self, request: OpenAiRequest, event: OpenAiEvent) -> None:
        """Сменить запрос до конца обмена и записать строку лога."""
        self.request = request
        self.request.event(event).emit(LOGGER, logging.WARNING)

    def _with_flex(self) -> OpenAiReply:
        """Тариф flex: на 429 — ждать FLEX_RETRY_DELAYS_SEC и повторять, затем уйти на тариф по умолчанию."""
        waits: Iterator[float] = iter(self.client.flex_delays_sec)
        while True:
            try:
                return self._with_temperature()
            except LlmRequestError as error:
                if not (self.request.service_tier.is_flex and error.reason is LlmErrorKind.RATE_LIMIT):
                    raise
                self._wait_flex(next(waits, None))

    def _wait_flex(self, delay: float | None) -> None:
        """Flex занят: подождать перед следующим повтором; ожидания кончились — тариф по умолчанию."""
        if delay is None:
            self._fall_back(self.request.on_default_tier(), OpenAiEvent.FLEX_FALLBACK)
            return
        self.request.event(OpenAiEvent.FLEX_UNAVAILABLE).extended(retry_in_sec=round(delay)).emit(LOGGER, logging.WARNING)
        self.client.sleep(delay)

    def _with_temperature(self) -> OpenAiReply:
        try:
            return self._with_retries()
        except LlmRequestError as error:
            if not (OpenAiParam.TEMPERATURE.is_refused_in(error.failure) and self.request.sends_temperature):
                raise
            self._fall_back(self.request.without_temperature(), OpenAiEvent.TEMPERATURE_RETRY)
            return self._with_retries()

    def _with_retries(self) -> OpenAiReply:
        """Сбои связи и нагрузки — повторы RetryLoop; 429 на flex решает `_with_flex`, не здесь."""
        loop: RetryLoop = RetryLoop(self.client.policy, self.client.rng, self.client.sleep)
        run: RetryRun[OpenAiReply] = loop.run(self._attempt, self._note_retry)
        if run.failure is not None and run.failure.cause is not None:
            raise run.failure.cause         # отказ последнего обращения как есть: его исходная ошибка — __cause__
        return run.value

    def _attempt(self) -> OpenAiReply | AttemptFailure:
        """Одно обращение; отказ — неудача цикла: повторяется, если отказ повторяемый и это не занятый flex."""
        try:
            return self._call()
        except LlmRequestError as error:
            failure: LlmFailure = error.failure
            is_flex_busy: bool = failure.kind is LlmErrorKind.RATE_LIMIT and self.request.service_tier.is_flex
            return AttemptFailure(failure.kind, failure.retryable and not is_flex_busy, cause=error)

    def _note_retry(self, step: RetryStep) -> None:
        retry: LogEvent = self.request.event(OpenAiEvent.REQUEST_RETRY)
        retry = retry.extended(reason_code=step.failure.reason, retry=step.retry, delay_sec=round(step.delay_sec, 1))
        retry.emit(LOGGER, logging.WARNING)

    def _call(self) -> OpenAiReply:
        """Одно обращение: разобранный ответ либо LlmRequestError с вычищенной подробностью (исходная — `__cause__`)."""
        self.attempts += 1
        started: datetime = self.client.clock.now()
        try:
            raw: Any = self.client.create_raw(self.request.to_kwargs())
        except openai.APIError as error:
            failure: LlmFailure = self.client.failure(error)
            failure.extend(self._attempt_event(LlmEvent.REQUEST_FAILED, started)).emit(LOGGER, logging.WARNING)
            raise LlmRequestError(failure) from error
        return self._received(raw, started)

    def _received(self, raw: Any, started: datetime) -> OpenAiReply:
        """Ответ получен: лимиты и расход — в лог, расход — в расход запуска."""
        limits: RateLimitSnapshot | None = RateLimitSnapshot.from_raw_response(raw, self.client.clock)
        if limits is not None:
            limits.event(self.request.model.name, self.request.request.label).emit(LOGGER)
        reply: OpenAiReply = OpenAiReply.of(raw.parse())
        usage: RequestUsage | None = reply.request_usage(self.request, self.client.tariffs)
        self.client.run_usage.add(usage)
        event: LogEvent = self._attempt_event(OpenAiEvent.RESPONSE, started)
        event = usage.extend(event) if usage is not None else event.extended(usage=LogValue.UNKNOWN)
        cost: float | None = usage.cost_usd if usage is not None else None
        event = event.extended(cost_usd=COST_FORMAT.format(cost) if cost is not None else LogValue.UNKNOWN)
        event.extended(finish_reason=reply.incomplete_reason or FINISH_COMPLETED).emit(LOGGER)
        return reply

    def _attempt_event(self, name: Enum, started: datetime) -> LogEvent:
        """Строка лога об обращении: поля запроса, номер обращения и сколько оно длилось."""
        return self.request.event(name).extended(attempt=self.attempts, elapsed_ms=self._elapsed_ms(started))

    def _elapsed_ms(self, started: datetime) -> int:
        return int(round((self.client.clock.now() - started).total_seconds() * MILLISECONDS))
