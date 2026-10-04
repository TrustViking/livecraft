"""Сверка объектов эфиров с площадкой (CLAUDE.md §3 шаг 10, §6 инварианты 1, 8, 9). Истина — только на площадке.

Память сверка не видит: решение и ключ найденного эфира — только по ответу площадки. Объект too_late сверяется только
на чтение: опознание и ключ, решение остаётся TOO_LATE. Не допущенный объект: канал не READY — к площадке по этому
каналу не обращаемся вовсе, объекты остаются NOT_ADMITTED; канал READY, не допущен по форме — только опознание и ключ,
как too_late. Решения и найденное записываются в сами объекты; наружу отдаются только эфиры с меткой программы без
своего объекта (сироты и перенесённые, `ChannelUpcoming.orphans`). Эфир без метки программы (ручной), найденный на
минуте слота, программа усыновляет: расхождение по метке исправимо, как прочие поля `FIXABLE_FIELDS`. Обложка
сверяется по заглушкам канала; память главнее картинки: обложку этому же эфиру ставила программа — обложка своя,
картинка просто ещё не обновилась. Сбой канала изолируется: его допущенные объекты — ERROR, остальные каналы
сверяются. Строки прогресса — до чтения каждого канала и после ответа.
"""
from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, tzinfo

from app.config.channel import ChannelConfig
from app.core.youtube_video import YouTubeVideoId
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.observability.logging_setup import mask_stream_key
from app.pipeline.decision import Decision
from app.pipeline.event import PipelineEvent
from app.pipeline.match import BroadcastMatch
from app.pipeline.orphan import ChannelFailure, MarkedBroadcast, MarkedScan, OrphanBroadcast
from app.pipeline.outcome import OutcomeError, OutcomeWarning, WarningStep
from app.pipeline.plan import PlannedBroadcast
from app.pipeline.progress import RunProgress
from app.pipeline.upcoming import CandidatePick, ChannelUpcoming, StreamReader
from app.platforms.base import BroadcastPlatform
from app.platforms.broadcast import UpcomingBroadcast
from app.platforms.channel import Channel, ChannelStatus
from app.platforms.error import PlatformError
from app.platforms.spec import BroadcastSpec, ChangedField

LOGGER = get_logger(LogArea.PIPELINE)


@dataclass(frozen=True)
class ChannelPlans:
    """Объекты одного канала; `channel` — значения канала сейчас (после фазы входов, §14 решение 25)."""

    channel: ChannelConfig
    items: tuple[PlannedBroadcast, ...]

    @classmethod
    def grouped(
        cls, planned: Sequence[PlannedBroadcast], channels: Sequence[ChannelConfig]
    ) -> tuple[ChannelPlans, ...]:
        """Каналы запуска по порядку, затем каналы объектов, которых среди них нет; канал без объектов тоже читается —
        ради его сирот."""
        configs: dict[str, ChannelConfig] = {channel.key: channel for channel in channels}
        members: dict[str, list[PlannedBroadcast]] = {key: [] for key in configs}
        for item in planned:
            config: ChannelConfig = item.admission.channel_config(item.channel)
            configs.setdefault(config.key, config)
            members.setdefault(config.key, []).append(item)
        return tuple(cls(configs[key], tuple(members[key])) for key in configs)

    @property
    def channel_object(self) -> Channel | None:
        """У всех объектов одного канала — один объект канала."""
        return next((item.admission.channel for item in self.items if item.admission.channel is not None), None)

    @property
    def status(self) -> ChannelStatus | None:
        found: Channel | None = self.channel_object
        return None if found is None else found.status

    @property
    def is_not_ready(self) -> bool:
        return self.status not in (None, ChannelStatus.READY)


class Reconciler:
    """list_upcoming — ровно раз на канал; потоки — одним кешем (`StreamReader`); метки — в поясе программы."""

    def __init__(self, platform: BroadcastPlatform, zone: tzinfo, progress: RunProgress) -> None:
        self._platform: BroadcastPlatform = platform
        self._zone: tzinfo = zone
        self._progress: RunProgress = progress
        self._reader: StreamReader = StreamReader(platform)
        self._ambiguous_ids: set[str] = set()   # эфиры-кандидаты AMBIGUOUS: уже показаны предупреждением

    def reconcile(
        self,
        planned: Sequence[PlannedBroadcast],
        known_slots: Mapping[str, datetime],
        channels: Sequence[ChannelConfig],
    ) -> tuple[OrphanBroadcast, ...]:
        """Решения — в объекты; наружу — сироты и перенесённые.

        known_slots — slot_id → момент старта у всех известных слотов (будущих и прошедших); channels — каналы запуска
        со значениями после фазы входов.
        """
        orphans: list[OrphanBroadcast] = []
        for group in ChannelPlans.grouped(planned, channels):
            orphans.extend(self._reconcile_channel(group, known_slots))
        return tuple(orphans)

    def marked_broadcasts(self, channels: Sequence[ChannelConfig]) -> MarkedScan:
        """Все эфиры с меткой программы на каналах (--status); сбой канала не валит остальные."""
        broadcasts: list[MarkedBroadcast] = []
        failures: list[ChannelFailure] = []
        for channel in channels:
            try:
                broadcasts.extend(self._upcoming(channel).marked())
            except PlatformError as error:
                PipelineEvent.CHANNEL_UNAVAILABLE.of(channel, code=error.code).emit(LOGGER, logging.WARNING)
                failures.append(ChannelFailure(channel=channel, error=error))
        broadcasts.sort(key=lambda item: (item.broadcast.start_utc, item.key.language, item.channel.key))
        return MarkedScan(broadcasts=tuple(broadcasts), failures=tuple(failures))

    def _upcoming(self, channel: ChannelConfig) -> ChannelUpcoming:
        """Строка «запрос» — до обращения; вход и проверка канала прошли раньше, в фазе входов."""
        self._progress.channel_read_started(channel)
        broadcasts: list[UpcomingBroadcast] = self._platform.list_upcoming(channel)
        self._progress.channel_read_done(channel, len(broadcasts))
        return ChannelUpcoming(channel=channel, broadcasts=tuple(broadcasts), reader=self._reader, zone=self._zone)

    def _reconcile_channel(
        self, group: ChannelPlans, known_slots: Mapping[str, datetime]
    ) -> tuple[OrphanBroadcast, ...]:
        if group.is_not_ready:
            skipped: LogEvent = PipelineEvent.CHANNEL_SKIPPED_NOT_READY.of(group.channel, status=group.status)
            skipped.extended(planned=len(group.items)).emit(LOGGER)
            return ()
        try:
            upcoming: ChannelUpcoming = self._upcoming(group.channel)
        except PlatformError as error:
            self._fail_channel(group, error)
            return ()
        placeholders: frozenset[str] = upcoming.find_placeholders()
        for item in group.items:
            if item.is_too_late or not item.admission.is_admitted:
                self._read_key_only(item, upcoming)
            else:
                self._decide(item, upcoming, placeholders)
            self._decision_event(item, group.channel).emit(LOGGER)
        shown: frozenset[str] = frozenset(
            item.match.found.broadcast_id for item in group.items if item.match.found is not None
        )
        return upcoming.orphans(known_slots, shown | self._ambiguous_ids)

    def _fail_channel(self, group: ChannelPlans, error: PlatformError) -> None:
        """Площадка не ответила по каналу: допущенные объекты не too_late — ERROR; остальным ключа просто не будет."""
        unavailable: LogEvent = PipelineEvent.CHANNEL_UNAVAILABLE.of(group.channel, code=error.code)
        unavailable.extended(planned=len(group.items)).emit(LOGGER, logging.WARNING)
        for item in group.items:
            if item.is_too_late or not item.admission.is_admitted:
                continue
            item.decision = Decision.ERROR
            item.outcome.error = OutcomeError.of_platform(group.channel, error)

    def _decide(self, item: PlannedBroadcast, upcoming: ChannelUpcoming, placeholders: frozenset[str]) -> None:
        """Эфира на площадке нет — CREATE; найден — сверка всех диктуемых полей; без потока — NO_STREAM."""
        pick: CandidatePick = upcoming.pick(item.slot.slot_id, item.expected.start_minute)
        if pick.is_ambiguous:
            item.decision = Decision.AMBIGUOUS
            self._warn_ambiguous(item, upcoming.channel, pick.ambiguous)
            return
        if pick.broadcast is None:
            item.decision = Decision.CREATE
            return
        match: BroadcastMatch = item.match
        match.found, match.stream = pick.broadcast, pick.stream
        match.actual = BroadcastSpec.from_platform(pick.broadcast, pick.stream, self._platform.limits, placeholders)
        if match.apply_recorded_thumbnail(item.memory.recorded_thumbnail):
            self._thumbnail_event(item, upcoming.channel).emit(LOGGER)
        self._log_not_compared(item, upcoming.channel)
        changed: tuple[ChangedField, ...] = match.actual.diff(item.expected)
        if pick.stream is None:     # поток будет создан уже с меткой программы: чинить метку нечему
            changed = tuple(name for name in changed if name is not ChangedField.MARKER)
        match.fixes.split_changed(changed)
        self._warn_reported(item, upcoming.channel)
        if pick.stream is None:
            item.decision = Decision.NO_STREAM
            return
        item.decision = Decision.UPDATE if match.fixes.changed else Decision.MATCH

    def _read_key_only(self, item: PlannedBroadcast, upcoming: ChannelUpcoming) -> None:
        """too_late и не допущенный: только опознать эфир и взять ключ; решение прежнее, AMBIGUOUS не ставится."""
        pick: CandidatePick = upcoming.pick(item.slot.slot_id, item.expected.start_minute)
        if pick.broadcast is not None and pick.stream is not None:
            item.match.found, item.match.stream = pick.broadcast, pick.stream

    def _decision_event(self, item: PlannedBroadcast, channel: ChannelConfig) -> LogEvent:
        match: BroadcastMatch = item.match
        return PipelineEvent.PAIR_DECISION.of_slot(
            item.slot.slot_id,
            channel,
            decision=item.decision,
            broadcast_id=None if match.found is None else match.found.broadcast_id,
            stream_key=mask_stream_key(match.stream_key),
            fixable=match.fixes.changed,
            reported=match.fixes.reported,
        )

    def _thumbnail_event(self, item: PlannedBroadcast, channel: ChannelConfig) -> LogEvent:
        set_at: str | None = None if item.memory.record is None else item.memory.record.results.thumbnail_set_at
        event: LogEvent = PipelineEvent.THUMBNAIL_FROM_MEMORY.of_slot(item.slot.slot_id, channel)
        return event.extended(broadcast_id=item.match.broadcast_id, set_at=Quoted(set_at))

    def _log_not_compared(self, item: PlannedBroadcast, channel: ChannelConfig) -> None:
        """Диагностика, а не дело владельца: площадка не вернула поле — сверки по нему в этом запуске не было."""
        actual: BroadcastSpec | None = item.match.actual
        skipped: tuple[ChangedField, ...] = () if actual is None else actual.not_compared(item.expected)
        if skipped:
            PipelineEvent.SPEC_FIELDS_NOT_COMPARED.of_slot(item.slot.slot_id, channel, fields=skipped).emit(LOGGER)

    def _warn_reported(self, item: PlannedBroadcast, channel: ChannelConfig) -> None:
        """Расходится, но через API не исправляется: лог и предупреждение объекта, решение не меняется."""
        actual: BroadcastSpec | None = item.match.actual
        for name in item.match.fixes.reported:
            wanted: object = item.expected.value(name)
            found: object = None if actual is None else actual.value(name)
            not_fixable: LogEvent = PipelineEvent.BROADCAST_SETTING_NOT_FIXABLE.of_slot(item.slot.slot_id, channel)
            not_fixable.extended(field=name, wanted=wanted, actual=found).emit(LOGGER, logging.WARNING)
            item.outcome.warn(OutcomeWarning(WarningStep.REPORTED_FIELD, name.value))

    def _warn_ambiguous(
        self, item: PlannedBroadcast, channel: ChannelConfig, candidates: tuple[UpcomingBroadcast, ...]
    ) -> None:
        """Программа не выбирает и не удаляет (инвариант 8), но обязана сказать, какие эфиры мешают."""
        ids: tuple[str, ...] = tuple(broadcast.broadcast_id for broadcast in candidates)
        item.match.ambiguous_urls = tuple(YouTubeVideoId(broadcast_id).watch_url for broadcast_id in ids)
        self._ambiguous_ids.update(ids)
        ambiguous: LogEvent = PipelineEvent.BROADCAST_AMBIGUOUS.of_slot(item.slot.slot_id, channel, candidates=ids)
        ambiguous.emit(LOGGER, logging.WARNING)
        item.outcome.warn(OutcomeWarning(WarningStep.AMBIGUOUS, str(len(candidates))))
