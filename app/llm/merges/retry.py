"""Профиль повтора merge: что дописать в промт повторной попытки.

`RetryProfile.targeted` — направленный повтор: сигнал отказа задаёт строки (шаблон `merge_retry_reinforcements.json`,
при его отсутствии — запасные строки) и подстановки из `RetryFacts`. `RetryProfile.standard` — обычный повтор без
инструкции. Блок инструкции (`instruction_block`) промт дописывает последним (`MergePrompt.text`).

Какой профиль после отказа — `RetryProfile.after_reject`: первый код отказа в порядке `SIGNAL_ORDER` задаёт сигнал,
кода со своим профилем нет — обычный повтор с причинами отказа.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.sequence import unique_in_order
from app.core.text_format import NEWLINE
from app.llm.merges import rules
from app.llm.merges.prompt_texts import MergePromptTexts, Placeholder
from app.llm.merges.reject import MergeRejectCode
from app.observability.log_event import LogValue

INSTRUCTION_HEADER: Final[str] = "RETRY INSTRUCTION:"


class RetryMode(str, Enum):
    TARGETED = "targeted"
    STANDARD = "standard"


class RetrySignal(str, Enum):
    """Отказ, у которого есть свой профиль повтора. Значение — код отказа и ключ строк в шаблоне повтора."""

    INSUFFICIENT_BULLET_COVERAGE = MergeRejectCode.INSUFFICIENT_BULLET_COVERAGE.value
    DUPLICATE_PARAGRAPH = MergeRejectCode.DUPLICATE_PARAGRAPH.value
    HOOK_ECHO_IN_BODY = MergeRejectCode.HOOK_ECHO_IN_BODY.value
    OVERLOADED_BULLET = MergeRejectCode.OVERLOADED_BULLET.value
    PARAGRAPH_OVERFLOW = MergeRejectCode.PARAGRAPH_OVERFLOW.value
    PARAGRAPH_UNDERFLOW = MergeRejectCode.PARAGRAPH_UNDERFLOW.value
    COMPACT_BULLET_OVERFLOW = MergeRejectCode.COMPACT_BULLET_OVERFLOW.value
    CTA_AS_FIRST_PARAGRAPH = MergeRejectCode.CTA_AS_FIRST_PARAGRAPH.value

    @property
    def reject_signals(self) -> tuple[str, ...]:
        """Коды отказа, которые закрывает профиль; повтор абзаца закрывает ещё и оба призыва."""
        return tuple(code.value for code in REJECT_SIGNALS.get(self, (MergeRejectCode(self.value),)))

    @property
    def focus_tags(self) -> tuple[str, ...]:
        return FOCUS_TAGS[self]

    @classmethod
    def first_of(cls, codes: Iterable[str]) -> RetrySignal | None:
        """Сигнал повтора по причинам отказа — первый в порядке `SIGNAL_ORDER`; своего профиля нет — None."""
        present: frozenset[MergeRejectCode | None] = frozenset(MergeRejectCode.of(code) for code in codes)
        return next((signal for code, signal in SIGNAL_ORDER if code in present), None)


# Порядок выбора профиля: причина, найденная раньше, задаёт профиль. Повтор абзаца и призыв в тезисе — одна беда,
# у обоих профиль повтора абзаца.
SIGNAL_ORDER: Final[tuple[tuple[MergeRejectCode, RetrySignal], ...]] = (
    (MergeRejectCode.OVERLOADED_BULLET, RetrySignal.OVERLOADED_BULLET),
    (MergeRejectCode.INSUFFICIENT_BULLET_COVERAGE, RetrySignal.INSUFFICIENT_BULLET_COVERAGE),
    (MergeRejectCode.CTA_AS_FIRST_PARAGRAPH, RetrySignal.CTA_AS_FIRST_PARAGRAPH),
    (MergeRejectCode.HOOK_ECHO_IN_BODY, RetrySignal.HOOK_ECHO_IN_BODY),
    (MergeRejectCode.DUPLICATE_PARAGRAPH, RetrySignal.DUPLICATE_PARAGRAPH),
    (MergeRejectCode.CTA_IN_HOOK, RetrySignal.DUPLICATE_PARAGRAPH),
    (MergeRejectCode.PARAGRAPH_UNDERFLOW, RetrySignal.PARAGRAPH_UNDERFLOW),
    (MergeRejectCode.PARAGRAPH_OVERFLOW, RetrySignal.PARAGRAPH_OVERFLOW),
    (MergeRejectCode.COMPACT_BULLET_OVERFLOW, RetrySignal.COMPACT_BULLET_OVERFLOW),
)
REJECT_SIGNALS: Final[Mapping[RetrySignal, tuple[MergeRejectCode, ...]]] = {
    RetrySignal.DUPLICATE_PARAGRAPH: (
        MergeRejectCode.DUPLICATE_PARAGRAPH,
        MergeRejectCode.CTA_AS_FIRST_PARAGRAPH,
        MergeRejectCode.CTA_IN_HOOK,
    ),
}
FOCUS_TAGS: Final[Mapping[RetrySignal, tuple[str, ...]]] = {
    RetrySignal.INSUFFICIENT_BULLET_COVERAGE: ("bullet_coverage",),
    RetrySignal.DUPLICATE_PARAGRAPH: ("no_hook_duplication", "hook_first"),
    RetrySignal.HOOK_ECHO_IN_BODY: ("no_hook_echo",),
    RetrySignal.OVERLOADED_BULLET: ("split_overloaded_bullet",),
    RetrySignal.PARAGRAPH_OVERFLOW: ("paragraph_structure",),
    RetrySignal.PARAGRAPH_UNDERFLOW: ("paragraph_structure",),
    RetrySignal.COMPACT_BULLET_OVERFLOW: ("bullet_count",),
    RetrySignal.CTA_AS_FIRST_PARAGRAPH: ("cta_position",),
}


@dataclass(frozen=True)
class RetryFacts:
    """Числа отвергнутой попытки, которые подставляются в строки повтора; каждому сигналу нужны свои."""

    source_count: int = 0
    actual_bullets: int = 0
    required_bullets: int = 0
    min_bullets: int = 0
    max_bullets: int = 0
    overloaded_count: int = 0
    actual_paragraphs: int = 0
    max_paragraphs: int = 0

    def placeholders(self, signal: RetrySignal) -> Mapping[Placeholder, object]:
        """Подстановки сигнала — ключи и порядок, в котором их ждут строки повтора."""
        if signal is RetrySignal.INSUFFICIENT_BULLET_COVERAGE:
            return {
                Placeholder.ACTUAL_BULLETS: self.actual_bullets,
                Placeholder.REQUIRED_BULLETS: self.required_bullets,
                Placeholder.SOURCE_COUNT: self.source_count,
            }
        if signal is RetrySignal.OVERLOADED_BULLET:
            return {
                Placeholder.OVERLOADED_COUNT: self.overloaded_count,
                Placeholder.BULLET_NAME_LIMIT: rules.BULLET_OVERLOAD_NAME_LIMIT,
                Placeholder.BULLET_CHAR_LIMIT: rules.BULLET_OVERLOAD_CHAR_LIMIT,
            }
        if signal is RetrySignal.PARAGRAPH_OVERFLOW:
            return {Placeholder.ACTUAL_PARAGRAPHS: self.actual_paragraphs, Placeholder.MAX_PARAGRAPHS: self.max_paragraphs}
        if signal is RetrySignal.COMPACT_BULLET_OVERFLOW:
            return {
                Placeholder.ACTUAL_BULLETS: self.actual_bullets,
                Placeholder.MIN_BULLETS: self.min_bullets,
                Placeholder.MAX_BULLETS: self.max_bullets,
            }
        return {}


@dataclass(frozen=True)
class RetryProfile:
    """Профиль повтора: режим, сигналы отказа, метки фокуса для лога и строки инструкции модели."""

    mode: RetryMode
    reject_signals: tuple[str, ...]
    focus_tags: tuple[str, ...]
    reinforcement_lines: tuple[str, ...]

    @property
    def enabled(self) -> bool:
        """Инструкция пишется в промт только у направленного профиля со строками."""
        return self.mode is RetryMode.TARGETED and bool(self.reinforcement_lines)

    @property
    def focus_label(self) -> str:
        return LogValue.LIST_SEPARATOR.join(self.focus_tags) or LogValue.EMPTY.value

    @property
    def reject_signal_label(self) -> str:
        return LogValue.LIST_SEPARATOR.join(self.reject_signals) or LogValue.EMPTY.value

    @property
    def instruction_block(self) -> str:
        """`RETRY INSTRUCTION:` и строки профиля; выключенный профиль — пусто."""
        if not self.enabled:
            return ""
        return f"{INSTRUCTION_HEADER}{NEWLINE}{NEWLINE.join(self.reinforcement_lines)}"

    @classmethod
    def targeted(cls, signal: RetrySignal, facts: RetryFacts, texts: MergePromptTexts) -> RetryProfile:
        """Направленный профиль по сигналу отказа."""
        return cls(
            mode=RetryMode.TARGETED,
            reject_signals=signal.reject_signals,
            focus_tags=signal.focus_tags,
            reinforcement_lines=texts.reinforcement_lines(signal.value, facts.placeholders(signal)),
        )

    @classmethod
    def after_reject(cls, signals: tuple[str, ...], facts: RetryFacts, texts: MergePromptTexts) -> RetryProfile:
        """Профиль следующей попытки после отказа: направленный по первому сигналу в порядке `SIGNAL_ORDER`, иначе
        обычный с сигналами отказа. Числа — из отвергнутой попытки (`facts`)."""
        signal: RetrySignal | None = RetrySignal.first_of(signals)
        if signal is None:
            return cls.standard(signals)
        return cls.targeted(signal, facts, texts)

    @classmethod
    def standard(cls, reject_signals: Iterable[str] = ()) -> RetryProfile:
        """Обычный повтор без инструкции; сигналы — без повторов, пустые после `strip` выпадают (сами не срезаются)."""
        signals: tuple[str, ...] = tuple(signal for signal in unique_in_order(reject_signals) if signal.strip())
        return cls(mode=RetryMode.STANDARD, reject_signals=signals, focus_tags=(), reinforcement_lines=())
