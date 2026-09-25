"""Выбор модели запуска: основная или запасная (CLAUDE.md §2 строки про llm\\: `model_selection.py` restreamer).

Правило донора (`select_llm_model`): основная проверяется одним настоящим запросом; на запасную переходим
только когда основная недоступна именно этому проекту (`LlmRequestError.is_fallback_reason`: модели нет или
нет доступа). Таймаут, 429 и 5xx о доступе ничего не говорят — модель остаётся, с пометкой «не проверена».
Выбор идёт через разъём `LlmBackend` и о конкретной нейросети ничего не знает: модели — имена.
Отказ настройки (ключ не принят, запрос не той формы) или отказ доступа к последней модели — моделей нет:
у донора это было исключение, здесь — поле `error` и пустой `chosen`; решение, что делать дальше, за запуском.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.llm.backend import LlmBackend, LlmResponse
from app.llm.errors import LlmRequestError
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

    primary: str
    fallback: str | None
    chosen: str | None
    reason: ChoiceReason
    error: LlmRequestError | None

    @classmethod
    def select(cls, backend: LlmBackend, primary: str, fallback: str) -> ModelChoice:
        """Основная — `primary`, запасная — `fallback` (пустая или та же, что основная, — запасной нет)."""
        main: str = primary.strip()
        spare: str | None = cls._fallback_of(main, fallback)
        outcome: LlmResponse | LlmRequestError = backend.probe(main)
        if isinstance(outcome, LlmResponse):
            return cls._chosen(main, spare, main, ChoiceReason.PRIMARY_CONFIRMED, None)
        if outcome.is_fallback_reason and spare is not None:
            LOGGER.warning("llm_model_fallback from=%s to=%s %s", main, spare, outcome.log_line)
            return cls._after_denial(backend, main, spare, outcome)
        if outcome.is_model_configuration:
            return cls._chosen(main, spare, None, ChoiceReason.REFUSED, outcome)
        return cls._chosen(main, spare, main, ChoiceReason.PRIMARY_UNCHECKED, outcome)

    @classmethod
    def _after_denial(
        cls, backend: LlmBackend, primary: str, fallback: str, denial: LlmRequestError
    ) -> ModelChoice:
        """Основная недоступна: проба запасной решает между «запасная», «запасная не проверена» и «моделей нет»."""
        outcome: LlmResponse | LlmRequestError = backend.probe(fallback)
        if isinstance(outcome, LlmResponse):
            return cls._chosen(primary, fallback, fallback, ChoiceReason.FALLBACK_CONFIRMED, denial)
        if outcome.is_model_configuration:
            return cls._chosen(primary, fallback, None, ChoiceReason.REFUSED, outcome)
        return cls._chosen(primary, fallback, fallback, ChoiceReason.FALLBACK_UNCHECKED, outcome)

    @classmethod
    def _chosen(
        cls,
        primary: str,
        fallback: str | None,
        chosen: str | None,
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
    def _fallback_of(primary: str, fallback: str) -> str | None:
        """Запасная модель; пустая или совпадающая с основной без учёта регистра — запасной нет (правило донора)."""
        spare: str = fallback.strip()
        if not spare or spare.lower() == primary.lower():
            return None
        return spare

    @property
    def is_usable(self) -> bool:
        return self.chosen is not None

    @property
    def human(self) -> str:
        """Строка для оператора: какая модель и почему; моделей нет — причина отказа."""
        if self.chosen is None:
            reason: str = self.error.human if self.error is not None else self.reason.human
            return msg.LLM_CHOICE_REFUSED.format(reason=reason)
        return msg.LLM_CHOICE_LINE.format(model=self.chosen, reason=self.reason.human)

    @property
    def log_line(self) -> str:
        error: str = self.error.log_line if self.error is not None else f"reason_code={LOG_NONE}"
        return (
            f"llm_model_selected chosen={self.chosen if self.chosen is not None else LOG_NONE} "
            f"primary={self.primary} fallback={self.fallback if self.fallback is not None else LOG_NONE} "
            f"reason={self.reason.value} {error}"
        )
