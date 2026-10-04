"""Итог запуска по одному эфиру: должен ли ключ дойти до стримера, дошёл ли, сбои и предупреждения (CLAUDE.md §6
инварианты 1a, 9).

Ошибка изолируется в объект (`OutcomeError`, с текстом для человека) и уходит в отчёт; остальные эфиры обрабатываются.
Сбой шага, который эфир не отменяет (обложка, язык, настройки видео), — предупреждение (`OutcomeWarning`): строка
в отчёте, код выхода не меняется. Почему ключ этого запуска не дошёл до формы — отказ формы (`FormFailure`).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Final

from app.config.channel import ChannelConfig
from app.form.failure import FormFailure
from app.form.sender import FormConfirmation
from app.platforms.error import PlatformError

# Предупреждение в снимке памяти: шаг и код.
WARNING_RECORD_TEMPLATE: Final[str] = "{step}:{code}"
# Код предупреждения AUDIENCE: площадка держала эфир «для детей», программа это исправила.
AUDIENCE_FIXED_CODE: Final[str] = "fixed"


class WarningStep(str, Enum):
    """Шаги, сбой которых не отменяет эфир; тексты для людей — в каталоге msg (`WARNING_STEP_TEXT`, app\\output\\)."""

    THUMBNAIL = "thumbnail"
    LANGUAGE = "language"
    AUDIENCE = "audience"
    SETTINGS = "settings"
    AGE_RESTRICTED = "age_restricted"
    FACTS = "facts"
    REPORTED_FIELD = "reported_field"   # расходится, но через API не исправляется
    AMBIGUOUS = "ambiguous"             # несколько эфиров без метки на минуту старта


@dataclass(frozen=True)
class OutcomeWarning:
    """Шаг не удался, но эфир и ключ в силе."""

    step: WarningStep
    code: str
    message: str = ""

    @property
    def record_text(self) -> str:
        """Предупреждение в снимке памяти: «шаг:код»."""
        return WARNING_RECORD_TEMPLATE.format(step=self.step.value, code=self.code)


@dataclass(frozen=True)
class OutcomeError:
    """Сбой по эфиру: откуда (площадка — значение `Platform`), код, текст для человека и подробность для лога."""

    origin: str
    code: str
    human: str
    message: str = ""

    @classmethod
    def of_platform(cls, channel: ChannelConfig, error: PlatformError) -> OutcomeError:
        """Отказ площадки канала: текст для человека — отказа площадки."""
        return cls(origin=channel.platform.value, code=error.code, human=error.human, message=error.message)


@dataclass
class BroadcastOutcome:
    """Изменяемый намеренно: заполняется по ходу запуска.

    `should_send_key` — ключ должен дойти до стримера в этом запуске (решает `PlannedBroadcast.decide_key_delivery`);
    `is_form_sent` и `form_sent_at` — форма подтвердила ответ этого запуска; `form_failure` — почему ключ этого запуска
    не дошёл до формы: ответ неполный (`FormAnswers.failure`) или форма отказала при отправке (`FormSender.send`).
    """

    should_send_key: bool = False
    is_form_sent: bool = False
    form_sent_at: datetime | None = None
    form_failure: FormFailure | None = None
    error: OutcomeError | None = None
    warnings: list[OutcomeWarning] = field(default_factory=list)

    def warn(self, warning: OutcomeWarning) -> None:
        """Сбой, который не отменяет эфир и не меняет код выхода."""
        self.warnings.append(warning)

    def take_form_reply(self, reply: FormConfirmation | FormFailure, moment: datetime) -> bool:
        """Ответ формы на ключ этого запуска: подтверждение — ключ дошёл в `moment`; отказ — почему не дошёл.

        True — форма подтвердила.
        """
        if isinstance(reply, FormFailure):
            self.form_failure = reply
            return False
        self.is_form_sent = True
        self.form_sent_at = moment
        self.form_failure = None
        return True

    @property
    def last_error(self) -> str | None:
        """Последний сбой для людей: отказ формы, иначе ошибка эфира; сбоев нет — None."""
        if self.form_failure is not None:
            return self.form_failure.human
        return None if self.error is None else self.error.human
