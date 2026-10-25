"""Сводка блока ВНИМАНИЕ консоли: одинаковое — одной строкой (CLAUDE.md §14 решение 78).

Не допущенные эфиры с одной и той же единственной причиной (вид, код, поле настроек, вопрос и форма) и одним исходом на
канале (`NotAdmittedCase`) — одна строка: число эфиров, значения без повторов по порядку эфиров (у причины без значения —
сами эфиры), действие и что программа сделает на следующем запуске. Эфир один или причин у него несколько — прежняя
строка эфира (`ResultText.not_admitted`). Прочие одинаковые строки ВНИМАНИЕ — одной строкой с числом (`AttentionLines`).
Отчёт, лог и keys.txt — по-прежнему поштучно: сводка только для консоли.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.core.text_format import SPACE
from app.form.failure import FormProblem
from app.form.question import NO_VALUE
from app.output.result import BroadcastResult
from app.output.result_text import NotAdmittedCase, ResultText
from app.pipeline.admission import AdmissionKind, AdmissionReason
from app.ui.messages import msg


@dataclass(frozen=True)
class NotAdmittedKey:
    """Причина недопуска без значения и исход на канале: у эфиров с одним ключом — одна строка консоли."""

    kind: AdmissionKind
    code: str
    field: str | None
    question: str
    form_name: str
    case: NotAdmittedCase

    @classmethod
    def of(cls, result: BroadcastResult) -> NotAdmittedKey | None:
        """Ключ эфира с единственной причиной; причин несколько — None: у такого эфира своя строка."""
        if len(result.reasons) != 1:
            return None
        reason: AdmissionReason = result.reasons[0]
        case: NotAdmittedCase = ResultText(result).not_admitted_case
        return cls(reason.kind, reason.code, reason.field, reason.question, reason.form_name, case)


@dataclass(frozen=True)
class NotAdmittedGroup:
    """Не допущенные эфиры одного ключа по порядку эфиров запуска; эфир без ключа — группа из него одного."""

    results: tuple[BroadcastResult, ...]

    @property
    def line(self) -> str:
        """Один эфир — его строка; несколько — строка с числом эфиров и общими словами причины."""
        first: BroadcastResult = self.results[0]
        if len(self.results) == 1:
            return msg.CONSOLE_ATTENTION_NOT_ADMITTED.format(text=ResultText(first).not_admitted)
        reason: AdmissionReason = first.reasons[0]
        case: NotAdmittedCase = ResultText(first).not_admitted_case
        text: str = msg.NOT_ADMITTED_GROUP_LINE.format(
            problem=self._problem(reason),
            consequence=case.group_consequence,
            action=self._action(reason),
            next_run=case.group_next_run,
        )
        return msg.CONSOLE_ATTENTION_NOT_ADMITTED_GROUP.format(count=len(self.results), text=text)

    def _problem(self, reason: AdmissionReason) -> str:
        """Нет вариантов в форме — перечень вариантов без повторов; у причины без значения — перечень эфиров."""
        if self._has_options(reason):
            values: dict[str, None] = dict.fromkeys(result.reasons[0].value for result in self.results)
            return msg.ADMISSION_MISSING_OPTIONS.format(
                form=reason.form_name, question=reason.question, values=msg.LIST_JOINER.join(values)
            )
        broadcasts: str = msg.ITEM_JOINER.join(result.label.text for result in self.results)
        return reason.wording.problem + SPACE + msg.NOT_ADMITTED_GROUP_BROADCASTS.format(broadcasts=broadcasts)

    def _action(self, reason: AdmissionReason) -> str:
        return msg.ADMISSION_ACTION_MISSING_OPTIONS if self._has_options(reason) else reason.wording.action

    def _has_options(self, reason: AdmissionReason) -> bool:
        """Причина — вариант, которого нет в форме: у неё есть значение («-» — настройки не дали текста варианта)."""
        return reason.code == FormProblem.MISSING_OPTION.value and reason.value != NO_VALUE


@dataclass(frozen=True)
class NotAdmittedSummary:
    """Не допущенные эфиры запуска по порядку; строки ВНИМАНИЕ — по группе на ключ, на месте первого эфира группы."""

    results: tuple[BroadcastResult, ...]

    @property
    def lines(self) -> tuple[str, ...]:
        groups: dict[NotAdmittedKey | int, list[BroadcastResult]] = {}
        for place, result in enumerate(self.results):
            key: NotAdmittedKey | None = NotAdmittedKey.of(result)
            groups.setdefault(place if key is None else key, []).append(result)
        return tuple(NotAdmittedGroup(tuple(members)).line for members in groups.values())


@dataclass(frozen=True)
class AttentionLines:
    """Строки блока ВНИМАНИЕ по порядку."""

    lines: Sequence[str]

    @property
    def collapsed(self) -> tuple[str, ...]:
        """Одинаковые строки — одной, на месте первой, с числом повторов."""
        counts: dict[str, int] = {}
        for line in self.lines:
            counts[line] = counts.get(line, 0) + 1
        return tuple(
            line if count == 1 else msg.CONSOLE_ATTENTION_REPEATED.format(text=line, count=count)
            for line, count in counts.items()
        )
