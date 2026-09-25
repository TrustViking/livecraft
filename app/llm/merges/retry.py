"""Профиль повтора merge: что дописать в промт повторной попытки (restreamer `app\\llm\\merges\\merge_retry.py`).

`RetryProfile.targeted` — восемь `_targeted_*_retry_profile` донора: сигнал отказа задаёт строки (боевой шаблон
`merge_retry_reinforcements.json`, при его отсутствии — запасные строки донора) и подстановки из `RetryFacts`.
`RetryProfile.expanded` — `_build_expanded_retry_profile` (строки только встроенные, по первому сигналу, плюс строки для
трёх и четырёх источников), `RetryProfile.standard` — `_standard_expanded_retry_profile` (инструкции нет).
Блок инструкции (`instruction_block`) — `_retry_instruction_block`: промт дописывает его последним (`MergePrompt.text`).
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.llm.merges import rules
from app.llm.merges.prompt_texts import MergePromptTexts

INSTRUCTION_HEADER: Final[str] = "RETRY INSTRUCTION:"
LABEL_JOINER: Final[str] = ","
NONE_LABEL: Final[str] = "none"
SIGNALS_JOINER: Final[str] = ", "
UNKNOWN_SIGNALS: Final[str] = "unknown"
LINE_BREAK: Final[str] = "\n"

# Ключи `merge_retry_expanded_lines.json` помимо сигналов.
EXPANDED_UNKNOWN_KEY: Final[str] = "unknown"
EXPANDED_THREE_PLUS_KEY: Final[str] = "three_plus_sources"
EXPANDED_FOUR_PLUS_KEY: Final[str] = "four_plus_sources"
EXPANDED_THREE_PLUS_SOURCES: Final[int] = 3
EXPANDED_FOUR_PLUS_SOURCES: Final[int] = 4
REJECT_SIGNALS_PLACEHOLDER: Final[str] = "{reject_signals}"

# Первый сигнал расширенного профиля → метка фокуса (донор: ветки `_build_expanded_retry_profile`).
EXPANDED_FOCUS_TAGS: Final[dict[str, str]] = {
    "insufficient_expanded_body": "body_depth",
    "too_few_expanded_bullets": "bullet_sufficiency",
    "overly_generic_body": "source_specificity",
    "hook_dominates_body": "hook_restraint",
    "weak_source_coverage": "source_spread",
}


class RetryMode(str, Enum):
    TARGETED = "targeted"
    STANDARD = "standard"


class RetrySignal(str, Enum):
    """Отказ, на который у донора есть свой профиль повтора. Значение — ключ строк в шаблоне повтора."""

    INSUFFICIENT_BULLET_COVERAGE = "insufficient_bullet_coverage"
    DUPLICATE_PARAGRAPH = "duplicate_paragraph"
    HOOK_ECHO_IN_BODY = "hook_echo_in_body"
    OVERLOADED_BULLET = "overloaded_bullet"
    PARAGRAPH_OVERFLOW = "paragraph_overflow"
    PARAGRAPH_UNDERFLOW = "paragraph_underflow"
    COMPACT_BULLET_OVERFLOW = "compact_bullet_overflow"
    CTA_AS_FIRST_PARAGRAPH = "cta_as_first_paragraph"

    @property
    def reject_signals(self) -> tuple[str, ...]:
        """Сигналы профиля; повтор абзаца у донора закрывает ещё и оба призыва."""
        return _REJECT_SIGNALS.get(self, (self.value,))

    @property
    def focus_tags(self) -> tuple[str, ...]:
        return _FOCUS_TAGS[self]


_REJECT_SIGNALS: Final[dict[RetrySignal, tuple[str, ...]]] = {
    RetrySignal.DUPLICATE_PARAGRAPH: ("duplicate_paragraph", "cta_as_first_paragraph", "cta_in_hook"),
}
_FOCUS_TAGS: Final[dict[RetrySignal, tuple[str, ...]]] = {
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

    def placeholders(self, signal: RetrySignal) -> dict[str, object]:
        """Подстановки сигнала — ровно те ключи и в том порядке, что `placeholder_values` донора."""
        if signal is RetrySignal.INSUFFICIENT_BULLET_COVERAGE:
            return {
                "actual_bullets": self.actual_bullets,
                "required_bullets": self.required_bullets,
                "source_count": self.source_count,
            }
        if signal is RetrySignal.OVERLOADED_BULLET:
            return {
                "overloaded_count": self.overloaded_count,
                "bullet_name_limit": rules.BULLET_OVERLOAD_NAME_LIMIT,
                "bullet_char_limit": rules.BULLET_OVERLOAD_CHAR_LIMIT,
            }
        if signal is RetrySignal.PARAGRAPH_OVERFLOW:
            return {"actual_paragraphs": self.actual_paragraphs, "max_paragraphs": self.max_paragraphs}
        if signal is RetrySignal.COMPACT_BULLET_OVERFLOW:
            return {"actual_bullets": self.actual_bullets, "min_bullets": self.min_bullets, "max_bullets": self.max_bullets}
        return {}


def _unique_in_order(signals: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(signals))


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
        return LABEL_JOINER.join(self.focus_tags) or NONE_LABEL

    @property
    def reject_signal_label(self) -> str:
        return LABEL_JOINER.join(self.reject_signals) or NONE_LABEL

    @property
    def instruction_block(self) -> str:
        """`RETRY INSTRUCTION:` и строки профиля; выключенный профиль — пусто."""
        if not self.enabled:
            return ""
        return f"{INSTRUCTION_HEADER}{LINE_BREAK}{LINE_BREAK.join(self.reinforcement_lines)}"

    @classmethod
    def targeted(cls, signal: RetrySignal, facts: RetryFacts, texts: MergePromptTexts) -> RetryProfile:
        """Направленный профиль по сигналу отказа (восемь `_targeted_*_retry_profile` донора)."""
        return cls(
            mode=RetryMode.TARGETED,
            reject_signals=signal.reject_signals,
            focus_tags=signal.focus_tags,
            reinforcement_lines=texts.reinforcement_lines(signal.value, facts.placeholders(signal)),
        )

    @classmethod
    def expanded(cls, source_count: int, reject_signals: Iterable[str], texts: MergePromptTexts) -> RetryProfile:
        """Расширенный профиль: строки по первому сигналу (неизвестный — общие строки с перечнем сигналов), затем строки
        для трёх и для четырёх источников. Сигналы — без повторов (по исходному виду) и без пустых после `strip`."""
        signals: tuple[str, ...] = tuple(
            cleaned for raw in _unique_in_order(str(signal or "") for signal in reject_signals) if (cleaned := raw.strip())
        )
        primary: str = signals[0] if signals else ""
        focus: str | None = EXPANDED_FOCUS_TAGS.get(primary)
        base: tuple[str, ...]
        if focus is not None:
            base = texts.expanded_retry[primary]
        else:
            joined: str = SIGNALS_JOINER.join(signals) or UNKNOWN_SIGNALS
            base = tuple(line.replace(REJECT_SIGNALS_PLACEHOLDER, joined) for line in texts.expanded_retry[EXPANDED_UNKNOWN_KEY])
        extra: tuple[str, ...] = ()
        if source_count >= EXPANDED_THREE_PLUS_SOURCES:
            extra = texts.expanded_retry[EXPANDED_THREE_PLUS_KEY]
        if source_count >= EXPANDED_FOUR_PLUS_SOURCES:
            extra = extra + texts.expanded_retry[EXPANDED_FOUR_PLUS_KEY]
        return cls(
            mode=RetryMode.TARGETED,
            reject_signals=signals,
            focus_tags=(focus,) if focus is not None else (),
            reinforcement_lines=base + extra,
        )

    @classmethod
    def standard(cls, reject_signals: Iterable[str] = ()) -> RetryProfile:
        """Обычный повтор без инструкции; сигналы — без повторов, пустые после `strip` выпадают (сами не срезаются)."""
        signals: tuple[str, ...] = tuple(
            signal for signal in _unique_in_order(reject_signals) if str(signal or "").strip()
        )
        return cls(mode=RetryMode.STANDARD, reject_signals=signals, focus_tags=(), reinforcement_lines=())
