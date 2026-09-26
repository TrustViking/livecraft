"""Выбор модели запуска: основная или запасная (CLAUDE.md §2 строки про llm\\).

Основная проверяется одним настоящим запросом (пробой); на запасную переходим только когда основная недоступна
именно этому проекту (`LlmFailure.is_fallback_reason`: модели нет или нет доступа). Таймаут, 429 и 5xx о доступе
ничего не говорят — модель остаётся, с пометкой «не проверена». Выбор идёт через разъём `LlmBackend` и о конкретной
нейросети ничего не знает: модели — имена. Отказ настройки (ключ не принят, запрос не той формы) или отказ доступа
к последней модели — моделей нет: поле `failure` и пустой `chosen`; решение, что делать дальше, за запуском.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

from app.llm.backend import LlmBackend, LlmResponse
from app.llm.errors import LlmFailure
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.LLM)


class ChoiceReason(str, Enum):
    """Почему выбрана эта модель."""

    PRIMARY_CONFIRMED = "primary_confirmed"      # основная ответила на пробу
    PRIMARY_UNCHECKED = "primary_unchecked"      # проба основной не удалась не из-за доступа — основная остаётся
    FALLBACK_CONFIRMED = "fallback_confirmed"    # основная недоступна, запасная ответила
    FALLBACK_UNCHECKED = "fallback_unchecked"    # основная недоступна, проба запасной не удалась не из-за доступа
    REFUSED = "refused"                          # моделей нет: ключ, форма запроса или доступ к последней модели

    @property
    def human(self) -> str:
        return msg.LLM_CHOICE_REASON_TEXT[self.value]


class ChoiceEvent(str, Enum):
    """События выбора модели в логе."""

    FALLBACK = "llm_model_fallback"
    SELECTED = "llm_model_selected"


class FallbackField(str, Enum):
    """Поля строки перехода на запасную модель: с какой и на какую."""

    SOURCE = "from"
    TARGET = "to"


@dataclass(frozen=True)
class ModelPair:
    """Основная модель и запасная; запасной нет, если она пустая или та же, что основная, без учёта регистра."""

    primary: str
    fallback: str | None

    @classmethod
    def of(cls, primary: str, fallback: str) -> ModelPair:
        main: str = primary.strip()
        spare: str = fallback.strip()
        return cls(primary=main, fallback=spare if spare and spare.lower() != main.lower() else None)


@dataclass(frozen=True)
class ModelChoice:
    """Какая модель работает в этом запуске и почему. `chosen` None — работать не на чем, причина — `failure`.

    `failure` у «не проверена» — сбой пробы, из-за которого модель осталась непроверенной; у запасной после отказа
    основной — отказ основной.
    """

    models: ModelPair
    chosen: str | None
    reason: ChoiceReason
    failure: LlmFailure | None

    @classmethod
    def select(cls, backend: LlmBackend, primary: str, fallback: str) -> ModelChoice:
        """Основная — `primary`, запасная — `fallback`: проба основной решает, на какой модели работать."""
        models: ModelPair = ModelPair.of(primary, fallback)
        outcome: LlmResponse | LlmFailure = backend.probe(models.primary)
        if isinstance(outcome, LlmResponse):
            return cls(models, models.primary, ChoiceReason.PRIMARY_CONFIRMED, None).logged()
        if outcome.is_fallback_reason and models.fallback is not None:
            moved: dict[str, object] = {FallbackField.SOURCE.value: models.primary, FallbackField.TARGET.value: models.fallback}
            outcome.extend(LogEvent.of(ChoiceEvent.FALLBACK, **moved)).emit(LOGGER, logging.WARNING)
            return cls._after_denial(backend, models, models.fallback, outcome)
        if outcome.is_model_configuration:
            return cls(models, None, ChoiceReason.REFUSED, outcome).logged()
        return cls(models, models.primary, ChoiceReason.PRIMARY_UNCHECKED, outcome).logged()

    @classmethod
    def _after_denial(cls, backend: LlmBackend, models: ModelPair, spare: str, denial: LlmFailure) -> ModelChoice:
        """Основная недоступна: проба запасной `spare` решает между «запасная», «запасная не проверена» и «моделей нет»."""
        outcome: LlmResponse | LlmFailure = backend.probe(spare)
        if isinstance(outcome, LlmResponse):
            return cls(models, spare, ChoiceReason.FALLBACK_CONFIRMED, denial).logged()
        if outcome.is_model_configuration:
            return cls(models, None, ChoiceReason.REFUSED, outcome).logged()
        return cls(models, spare, ChoiceReason.FALLBACK_UNCHECKED, outcome).logged()

    def logged(self) -> ModelChoice:
        """Записать выбор в лог (моделей нет — ERROR) и вернуть его же."""
        self.event.emit(LOGGER, logging.INFO if self.is_usable else logging.ERROR)
        return self

    @property
    def is_usable(self) -> bool:
        return self.chosen is not None

    @property
    def human(self) -> str:
        """Строка для оператора: какая модель и почему; моделей нет — причина отказа."""
        if self.chosen is None:
            reason: str = self.failure.human if self.failure is not None else self.reason.human
            return msg.LLM_CHOICE_REFUSED.format(reason=reason)
        return msg.LLM_CHOICE_LINE.format(model=self.chosen, reason=self.reason.human)

    @property
    def event(self) -> LogEvent:
        """Строка `llm_model_selected`: выбранная, основная и запасная модели, почему; сбой пробы — его поля."""
        selected: LogEvent = LogEvent.of(
            ChoiceEvent.SELECTED,
            chosen=self.chosen,
            primary=self.models.primary,
            fallback=self.models.fallback,
            reason=self.reason,
        )
        return self.failure.extend(selected) if self.failure is not None else selected.extended(reason_code=None)
