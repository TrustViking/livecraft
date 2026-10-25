"""Слоты, которые до эфиров не дошли (CLAUDE.md §3 шаги 8, 12): уже прошли, до старта меньше min_lead_minutes,
нет канала своего языка.

Прошедшие — только языков каналов запуска: чужие языки человеку этого запуска не нужны. Слот на нескольких каналах —
одна строка. В консоли прошедшие не перечисляются — их число в «Итоге»: сделать с ними нечего.
"""
from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from enum import Enum

from app.pipeline.selection import Selection
from app.slots.slot import SlotEntry, SlotKey
from app.ui.messages import msg


class SkipKind(str, Enum):
    PAST = "past"
    TOO_LATE = "too_late"
    NO_CHANNEL = "no_channel"


@dataclass(frozen=True)
class SkippedLine:
    """Пропущенный слот; `minutes` — только у TOO_LATE: min_lead_minutes."""

    kind: SkipKind
    key: SlotKey
    title: str
    minutes: int = 0

    @property
    def text(self) -> str:
        """Строка раздела «Пропущено»."""
        templates: dict[SkipKind, str] = {
            SkipKind.PAST: msg.SKIP_PAST,
            SkipKind.TOO_LATE: msg.SKIP_TOO_LATE,
            SkipKind.NO_CHANNEL: msg.SKIP_NO_CHANNEL,
        }
        key: SlotKey = self.key
        return templates[self.kind].format(
            date=key.human_date, time=key.time_text, language=key.language, minutes=self.minutes
        )

    @property
    def console_line(self) -> str:
        key: SlotKey = self.key
        return msg.CONSOLE_BROADCAST_LINE.format(
            date=key.human_date, time=key.time_text, language=key.language, title=self.title
        )


@dataclass(frozen=True)
class SkipGroup:
    """Пропуски одной причины (нет канала — одного языка): консоль печатает их группой, «Итог» — числом."""

    kind: SkipKind
    lines: tuple[SkippedLine, ...]

    @property
    def minutes(self) -> int:
        return self.lines[0].minutes

    @property
    def language(self) -> str:
        return self.lines[0].key.language

    @property
    def reason(self) -> str:
        """Причина для строки «Слоты вне работы»."""
        return msg.SUMMARY_SLOTS_REASON[self.kind.value].format(minutes=self.minutes, language=self.language)

    @property
    def console_title(self) -> str:
        if self.kind is SkipKind.TOO_LATE:
            return msg.CONSOLE_SKIP_GROUP_TOO_LATE.format(minutes=self.minutes)
        return msg.CONSOLE_SKIP_GROUP_NO_CHANNEL.format(language=self.language)


@dataclass(frozen=True)
class SkippedSlots:
    """Пропущенные слоты запуска по порядку слотов (`SlotKey.sort_key`)."""

    lines: tuple[SkippedLine, ...] = ()

    @classmethod
    def of(
        cls, selection: Selection, past: Sequence[SlotEntry], languages: Collection[str], minutes: int
    ) -> SkippedSlots:
        """Прошедшие слоты языков каналов, слоты внутри min_lead_minutes (`minutes`) и слоты без канала своего языка."""
        found: list[SkippedLine] = [
            SkippedLine(SkipKind.PAST, slot.key, slot.title.strip()) for slot in past if slot.language in languages
        ]
        found.extend(
            SkippedLine(SkipKind.TOO_LATE, item.slot.key, item.expected.title, minutes)
            for item in selection.planned
            if item.is_too_late
        )
        found.extend(
            SkippedLine(SkipKind.NO_CHANNEL, skipped.slot.key, skipped.slot.title.strip())
            for skipped in selection.skipped
        )
        return cls(tuple(sorted(dict.fromkeys(found), key=lambda line: line.key.sort_key)))

    @property
    def groups(self) -> tuple[SkipGroup, ...]:
        """По причинам: уже прошло, внутри min_lead_minutes, нет канала — по языкам."""
        groups: list[SkipGroup] = [self._of_kind(kind) for kind in (SkipKind.PAST, SkipKind.TOO_LATE)]
        no_channel: SkipGroup = self._of_kind(SkipKind.NO_CHANNEL)
        for language in sorted({line.key.language for line in no_channel.lines}):
            groups.append(SkipGroup(SkipKind.NO_CHANNEL, tuple(
                line for line in no_channel.lines if line.key.language == language
            )))
        return tuple(group for group in groups if group.lines)

    @property
    def summary_line(self) -> str | None:
        """«Слоты вне работы»: одна причина — без числа (оно уже в строке); несколько — число у каждой."""
        groups: tuple[SkipGroup, ...] = self.groups
        if not groups:
            return None
        reasons: str = groups[0].reason
        if len(groups) > 1:
            reasons = msg.LIST_JOINER.join(
                msg.SUMMARY_SLOTS_REASON_COUNTED.format(reason=group.reason, count=len(group.lines)) for group in groups
            )
        return msg.SUMMARY_SLOTS_OUT.format(count=len(self.lines), reasons=reasons)

    @property
    def shown_in_console(self) -> SkippedSlots:
        """Без прошедших: их число — в «Итоге», сделать с ними нечего."""
        return SkippedSlots(tuple(line for line in self.lines if line.kind is not SkipKind.PAST))

    def _of_kind(self, kind: SkipKind) -> SkipGroup:
        return SkipGroup(kind, tuple(line for line in self.lines if line.kind is kind))
