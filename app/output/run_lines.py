"""Строки отчёта из объектов запуска (CLAUDE.md §3 шаг 12, §6 инварианты 1, 8): предупреждения, особенности площадки,
расхождения с площадкой после действий и эфиры с меткой программы без своего слота.

Предупреждение — эфир и ключ в силе, код выхода не меняется: сбой шага эфира, неисправимое поле, несколько эфиров без
метки на минуту, страница формы, сохранённая в logs\\, замечание площадки о канале. Особенность площадки — не про этот
запуск: только в отчёте, одной строкой на особенность. Время для людей — в поясе программы (инвариант 4).
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path
from typing import Final

from app.core.dates import format_human_datetime, to_minute
from app.core.text_format import NEWLINE, SPACE
from app.core.youtube_video import YouTubeVideoId
from app.form.failure import FormFailure
from app.form.question import NO_VALUE
from app.output.result import ShownValue, SlotLabel
from app.paths import LivecraftPaths
from app.pipeline.decision import Decision
from app.pipeline.orphan import OrphanBroadcast, OrphanKind
from app.pipeline.outcome import OutcomeWarning, WarningStep
from app.pipeline.plan import PlannedBroadcast
from app.platforms.broadcast import BroadcastFacts
from app.platforms.limits import PlatformLimits
from app.platforms.notice import PlatformNotice, PlatformNoticeKind
from app.platforms.spec import BroadcastSpec, ChangedField
from app.ui.messages import msg

MISMATCH_HEAD_CHARS: Final[int] = 200   # описание в отчёт целиком не выводится: длина и начало


@dataclass(frozen=True)
class WarningText:
    """Предупреждения одного эфира: текст из объекта — значения полей и ссылки на эфиры."""

    item: PlannedBroadcast

    def text(self, warning: OutcomeWarning) -> str:
        prefix: str = SlotLabel.of(self.item).text
        if warning.step is WarningStep.REPORTED_FIELD:
            return self._reported(prefix, ChangedField(warning.code))
        if warning.step is WarningStep.AMBIGUOUS:
            urls: str = msg.LIST_JOINER.join(self.item.match.ambiguous_urls)
            return msg.WARNING_AMBIGUOUS.format(prefix=prefix, urls=urls)
        step: str = msg.WARNING_STEP_TEXT[warning.step.value]
        reason: str | None = self._reason(warning)
        if reason is not None:
            return msg.WARNING_REASON_LINE.format(prefix=prefix, step=step, reason=reason)
        return msg.WARNING_LINE.format(prefix=prefix, step=step, code=warning.code, message=warning.message)

    def _reported(self, prefix: str, name: ChangedField) -> str:
        """Расходится, но через API не исправляется: что нужно и что на площадке."""
        actual: BroadcastSpec | None = self.item.match.actual
        return msg.WARNING_REPORTED_FIELD.format(
            prefix=prefix,
            field=msg.CHANGED_FIELD_TEXT[name.value],
            wanted=ShownValue(self.item.expected.value(name)).text,
            actual=ShownValue(None if actual is None else actual.value(name)).text,
        )

    def _reason(self, warning: OutcomeWarning) -> str | None:
        """Известная причина отказа — текстом; у шага обложки своя таблица главнее общей."""
        if warning.step is WarningStep.THUMBNAIL and warning.code in msg.THUMBNAIL_REASON_TEXT:
            return msg.THUMBNAIL_REASON_TEXT[warning.code]
        return msg.YOUTUBE_REASON_TEXT.get(warning.code)


@dataclass(frozen=True)
class Mismatch:
    """Что хотели и что лежит на площадке — словами людей."""

    field: str
    wanted: str
    actual: str

    @property
    def is_different(self) -> bool:
        return self.wanted != self.actual


@dataclass(frozen=True)
class FactsCheck:
    """Факты площадки после действий против плана — тем же diff, что решает сверку: новое поле не забыть."""

    item: PlannedBroadcast
    limits: PlatformLimits
    zone: tzinfo

    @property
    def lines(self) -> tuple[str, ...]:
        """Строки раздела «Расхождения с площадкой»; фактов нет или совпало всё — ни одной."""
        facts: BroadcastFacts | None = self.item.match.facts
        if facts is None:
            return ()
        prefix: str = SlotLabel.of(self.item).text
        return tuple(
            msg.MISMATCH_LINE.format(prefix=prefix, field=found.field, wanted=found.wanted, actual=found.actual)
            for found in (*self._spec_mismatches(facts), *self._fact_mismatches(facts))
        )

    def _spec_mismatches(self, facts: BroadcastFacts) -> Iterator[Mismatch]:
        """Поля спеки; метку только что созданного или привязанного потока перечитывание может ещё не видеть."""
        expected: BroadcastSpec = self.item.expected
        actual: BroadcastSpec = BroadcastSpec.from_facts(facts, self.limits, expected.start_minute)
        is_stream_new: bool = self.item.decision is Decision.CREATE or self.item.match.stream_attached
        for name in actual.diff(expected):
            if name is ChangedField.MARKER and is_stream_new:
                continue
            yield self._spec_mismatch(name, expected, actual)

    def _spec_mismatch(self, name: ChangedField, wanted: BroadcastSpec, actual: BroadcastSpec) -> Mismatch:
        """Описание целиком не выводится: длина и начало каждой стороны."""
        label: str = msg.CHANGED_FIELD_TEXT[name.value]
        if name is ChangedField.DESCRIPTION:
            return Mismatch(label, self._description(wanted.description), self._description(actual.description))
        return Mismatch(label, ShownValue(wanted.value(name)).text, ShownValue(actual.value(name)).text)

    def _fact_mismatches(self, facts: BroadcastFacts) -> Iterator[Mismatch]:
        """Время старта (площадка его не вернула — сравнивать не с чем), язык и аудитория — их в спеке нет."""
        found: list[Mismatch] = []
        if facts.start_utc is not None:
            wanted: str = self._moment(self.item.expected.start_minute)
            found.append(Mismatch(msg.MISMATCH_FIELD_START, wanted, self._moment(to_minute(facts.start_utc))))
        language: str = facts.default_language or NO_VALUE
        found.append(Mismatch(msg.MISMATCH_FIELD_LANGUAGE, self.item.slot.language, language))
        yield from (mismatch for mismatch in found if mismatch.is_different)
        if facts.made_for_kids:
            yield Mismatch(msg.MISMATCH_FIELD_AUDIENCE, msg.AUDIENCE_NOT_FOR_KIDS, msg.AUDIENCE_FOR_KIDS)

    def _moment(self, value: datetime) -> str:
        return format_human_datetime(value.astimezone(self.zone))

    def _description(self, text: str) -> str:
        head: str = text[:MISMATCH_HEAD_CHARS].replace(NEWLINE, SPACE)
        return msg.MISMATCH_DESCRIPTION.format(length=len(text), head=head)


@dataclass(frozen=True)
class OrphanLine:
    """Эфир с меткой программы без своего объекта: дата, время и язык — слота по метке; где стоит — в поясе программы."""

    orphan: OrphanBroadcast
    zone: tzinfo

    @property
    def text(self) -> str:
        orphan: OrphanBroadcast = self.orphan
        template: str = msg.ORPHAN_MOVED_LINE if orphan.kind is OrphanKind.MOVED else msg.ORPHAN_LINE
        return template.format(
            date=orphan.key.human_date,
            time=orphan.key.time_text,
            language=orphan.key.language,
            channel=orphan.channel.label,
            url=YouTubeVideoId(orphan.broadcast.broadcast_id).watch_url,
            actual=format_human_datetime(orphan.broadcast.start_utc.astimezone(self.zone)),
        )


@dataclass(frozen=True)
class RunNotes:
    """Предупреждения и особенности площадки запуска; `warnings` — строки предупреждений запуска (сверка каналов,
    память), `notices` — замечания площадки. Повтор строки — одна строка: канал за запуск читается не раз."""

    planned: tuple[PlannedBroadcast, ...]
    notices: tuple[PlatformNotice, ...]
    warnings: tuple[str, ...]
    paths: LivecraftPaths

    @property
    def run_warnings(self) -> tuple[str, ...]:
        """Предупреждения этого запуска — в консоль и в отчёт."""
        lines: list[str] = list(self.warnings)
        lines.extend(WarningText(item).text(warning) for item in self.planned for warning in item.outcome.warnings)
        lines.extend(msg.WARNING_FORM_DIAGNOSTIC.format(path=self.paths.shown(path)) for path in self._diagnostics)
        lines.extend(notice.text for notice in self.notices if notice.kind is PlatformNoticeKind.CHANNEL)
        return tuple(dict.fromkeys(lines))

    @property
    def platform_notes(self) -> tuple[str, ...]:
        """Так устроена площадка: живой чат у эфиров и служебные эфиры без времени старта — только в отчёт."""
        lines: list[str] = []
        if any(item.match.facts is not None and item.match.facts.live_chat_id for item in self.planned):
            lines.append(msg.WARNING_LIVE_CHAT)
        lines.extend(
            msg.NOTE_UNDATED_BROADCAST.format(
                channel=msg.CHANNEL_LABEL.format(account_name=notice.account_name, handle=notice.handle),
                title=notice.title,
            )
            for notice in self.notices
            if notice.kind is PlatformNoticeKind.UNDATED_BROADCAST
        )
        return tuple(dict.fromkeys(lines))

    @property
    def _diagnostics(self) -> tuple[Path, ...]:
        """Страницы формы, сохранённые в logs\\ при отказе чтения (допуск) и отправки ключа; без повторов."""
        failures: list[FormFailure | None] = [
            failure for item in self.planned for failure in (item.admission.failure, item.outcome.form_failure)
        ]
        paths: list[Path | None] = [None if failure is None else failure.diagnostic for failure in failures]
        return tuple(dict.fromkeys(path for path in paths if path is not None))
