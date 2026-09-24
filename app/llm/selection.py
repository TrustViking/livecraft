"""Выбор модели запуска: основная или запасная (CLAUDE.md §2 строки про llm\\: `model_selection.py` restreamer).

Правило донора (`select_llm_model`): основная проверяется одним настоящим запросом; на запасную переходим
только когда основная недоступна именно этому проекту (`LlmErrorKind.is_fallback_reason`: модели нет или
нет доступа). Таймаут, 429 и 5xx о доступе ничего не говорят — модель остаётся, с пометкой «не проверена».
Отказ настройки (ключ не принят, запрос не той формы) или отказ доступа к последней модели — моделей нет:
у донора это было исключение, здесь — поле `error` и пустой `chosen`; решение, что делать дальше, за запуском.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.config.loader import LlmSettings
from app.llm.client import LlmResponse, OpenAiClient
from app.llm.errors import LlmRequestError
from app.llm.model import LlmModel
from app.observability.logging_setup import get_logger
from app.ui import messages_ru as msg

LOGGER_NAME: Final[str] = "llm"
LOGGER = get_logger(LOGGER_NAME)
LOG_NONE: Final[str] = "none"


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


@dataclass(frozen=True)
class ModelChoice:
    """Какая модель работает в этом запуске и почему. `chosen` None — работать не на чем, причина — `error`.

    `error` у «не проверена» — сбой пробы, из-за которого модель осталась непроверенной; у запасной после отказа
    основной — отказ основной.
    """

    primary: LlmModel
    fallback: LlmModel | None
    chosen: LlmModel | None
    reason: ChoiceReason
    error: LlmRequestError | None

    @classmethod
    def select(cls, client: OpenAiClient, settings: LlmSettings) -> ModelChoice:
        primary: LlmModel = LlmModel(settings.model.strip())
        fallback: LlmModel | None = cls._fallback_of(primary, settings)
        outcome: LlmResponse | LlmRequestError = client.probe(primary)
        if isinstance(outcome, LlmResponse):
            return cls._chosen(primary, fallback, primary, ChoiceReason.PRIMARY_CONFIRMED, None)
        if outcome.kind.is_fallback_reason and fallback is not None:
            LOGGER.warning(
                "llm_model_fallback from=%s to=%s %s", primary.name, fallback.name, outcome.log_line
            )
            return cls._after_denial(client, primary, fallback, outcome)
        if outcome.is_model_configuration:
            return cls._chosen(primary, fallback, None, ChoiceReason.REFUSED, outcome)
        return cls._chosen(primary, fallback, primary, ChoiceReason.PRIMARY_UNCHECKED, outcome)

    @classmethod
    def _after_denial(
        cls, client: OpenAiClient, primary: LlmModel, fallback: LlmModel, denial: LlmRequestError
    ) -> ModelChoice:
        """Основная недоступна: проба запасной решает между «запасная», «запасная не проверена» и «моделей нет»."""
        outcome: LlmResponse | LlmRequestError = client.probe(fallback)
        if isinstance(outcome, LlmResponse):
            return cls._chosen(primary, fallback, fallback, ChoiceReason.FALLBACK_CONFIRMED, denial)
        if outcome.is_model_configuration:
            return cls._chosen(primary, fallback, None, ChoiceReason.REFUSED, outcome)
        return cls._chosen(primary, fallback, fallback, ChoiceReason.FALLBACK_UNCHECKED, outcome)

    @classmethod
    def _chosen(
        cls,
        primary: LlmModel,
        fallback: LlmModel | None,
        chosen: LlmModel | None,
        reason: ChoiceReason,
        error: LlmRequestError | None,
    ) -> ModelChoice:
        choice: ModelChoice = cls(primary=primary, fallback=fallback, chosen=chosen, reason=reason, error=error)
        if choice.is_usable:
            LOGGER.info("%s", choice.log_line)
        else:
            LOGGER.error("%s", choice.log_line)
        return choice

    @staticmethod
    def _fallback_of(primary: LlmModel, settings: LlmSettings) -> LlmModel | None:
        """Запасная модель; пустая или совпадающая с основной — запасной нет (правило донора)."""
        fallback: LlmModel = LlmModel(settings.fallback_model.strip())
        if not fallback.normalized or fallback.normalized == primary.normalized:
            return None
        return fallback

    @property
    def is_usable(self) -> bool:
        return self.chosen is not None

    @property
    def human(self) -> str:
        """Строка для оператора: какая модель и почему; моделей нет — причина отказа."""
        if self.chosen is None:
            reason: str = self.error.human if self.error is not None else self.reason.human
            return msg.LLM_CHOICE_REFUSED.format(reason=reason)
        return msg.LLM_CHOICE_LINE.format(model=self.chosen.name, reason=self.reason.human)

    @property
    def log_line(self) -> str:
        error: str = self.error.log_line if self.error is not None else f"reason_code={LOG_NONE}"
        return (
            f"llm_model_selected chosen={self.chosen.name if self.chosen is not None else LOG_NONE} "
            f"primary={self.primary.name} fallback={self.fallback.name if self.fallback is not None else LOG_NONE} "
            f"reason={self.reason.value} {error}"
        )
