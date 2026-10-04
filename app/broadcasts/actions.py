"""Действия полного запуска по решениям сверки (CLAUDE.md §3 шаги 10–11, §6 инварианты 1, 1a, 7, 9).

По объекту: создать эфир (эфир → поток с меткой → привязка → обложка) | привязать поток к эфиру без потока | исправить
только нужными вызовами (`FieldFixes.fix_calls`) → настройки видео одним проходом (язык, категория, видимость,
аудитория) → снимок фактов → сразу ключ в форму (`KeySender`). Настройки видео и факты — только у эфира, который
программа считает своим (`BroadcastMatch.own_broadcast_id`). Сбой шага, который эфир не отменяет (обложка, настройки
видео, факты), — предупреждение; отказ площадки при создании, привязке или правке — ошибка объекта
(`OutcomeError.of_platform`, `Decision.ERROR`), остальные объекты идут дальше, а уже взятый ключ всё равно уходит.
"""
from __future__ import annotations

import logging

from app.broadcasts.event import BroadcastsEvent, FactsLog
from app.broadcasts.key_sender import KeySender
from app.broadcasts.services import BroadcastServices
from app.config.channel import ChannelConfig
from app.core.youtube_video import YouTubeVideoId
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.observability.logging_setup import mask_stream_key
from app.pipeline.decision import Decision
from app.pipeline.fixes import FieldFixes, FixCall
from app.pipeline.memory import ReplacedBroadcast
from app.pipeline.outcome import AUDIENCE_FIXED_CODE, OutcomeError, OutcomeWarning, WarningStep
from app.pipeline.plan import PlannedBroadcast
from app.pipeline.progress import BroadcastStep
from app.platforms.broadcast import BroadcastFacts, CreatedBroadcast, UpcomingBroadcast
from app.platforms.error import PlatformError
from app.platforms.spec import ChangedField
from app.platforms.video import VideoFixes, VideoSettings
from app.platforms.youtube_item import AGE_RESTRICTED_RATING

LOGGER = get_logger(LogArea.BROADCASTS)


class BroadcastActions:
    """Действия по объектам одного полного запуска; сбой объекта изолирован в нём самом."""

    def __init__(self, services: BroadcastServices, keys: KeySender) -> None:
        self._services: BroadcastServices = services
        self._keys: KeySender = keys

    def execute(self, item: PlannedBroadcast) -> None:
        """Действия по объекту и сразу его ключ: ошибка шага отправку уже взятого ключа не отменяет."""
        try:
            self._dispatch(item)
            self._finish(item)
        except PlatformError as error:
            BroadcastsEvent.PAIR_FAILED.of(item, code=error.code).emit(LOGGER, logging.WARNING)
            item.outcome.error = OutcomeError.of_platform(self._channel(item), error)
            item.decision = Decision.ERROR
        self._keys.deliver(item)

    def _dispatch(self, item: PlannedBroadcast) -> None:
        """CREATE — создать; эфир без потока — привязать поток; UPDATE — исправить. MATCH и прочие — действий нет:
        ключ совпавшего эфира сверка уже взяла с площадки."""
        if item.decision is Decision.CREATE:
            self._create(item)
            return
        found: UpcomingBroadcast | None = item.match.found
        if found is None:
            return
        if item.decision is Decision.NO_STREAM:
            self._attach_stream(item, found.broadcast_id)
        elif item.decision is Decision.UPDATE:
            self._resend(item, found.broadcast_id, with_marker=True)

    def _create(self, item: PlannedBroadcast) -> None:
        self._services.progress.broadcast_step_started(item, BroadcastStep.CREATE)
        created: CreatedBroadcast = self._services.platform.create_broadcast(self._channel(item), item.expected)
        item.match.take_new_key(created)
        masked: str = mask_stream_key(created.stream_key)
        BroadcastsEvent.BROADCAST_CREATED.of(item, broadcast_id=created.broadcast_id, stream_key=masked).emit(LOGGER)
        # до записи published: прежний эфир и его подтверждённый ключ известны только из прежней записи
        replaced: ReplacedBroadcast | None = item.memory.remember_replaced(created)
        if replaced is not None:
            previous_key: str = mask_stream_key(replaced.stream_key)
            previous: LogEvent = BroadcastsEvent.BROADCAST_REPLACED.of(
                item, previous_broadcast_id=replaced.broadcast_id, previous_stream_key=previous_key
            )
            previous.extended(broadcast_id=created.broadcast_id, stream_key=masked).emit(LOGGER)
        self._set_thumbnail(item, created.broadcast_id)

    def _attach_stream(self, item: PlannedBroadcast, broadcast_id: str) -> None:
        """Эфир есть, потока нет: поток — с меткой программы, дальше как с найденным эфиром."""
        attached: CreatedBroadcast = self._services.platform.attach_stream(
            self._channel(item), broadcast_id, item.expected
        )
        item.match.stream_attached = True
        item.match.take_new_key(attached)
        masked: str = mask_stream_key(attached.stream_key)
        BroadcastsEvent.STREAM_ATTACHED.of(item, broadcast_id=broadcast_id, stream_key=masked).emit(LOGGER)
        # исправимые поля сверка уже посчитала; метку новый поток получил при создании
        item.decision = Decision.UPDATE if item.match.fixes.changed else Decision.MATCH
        if item.match.fixes.changed:
            self._resend(item, broadcast_id, with_marker=True)

    def _resend(self, item: PlannedBroadcast, broadcast_id: str, *, with_marker: bool) -> None:
        """Одна правка на эфир за запуск: только вызовы, которых требуют расхождения. Поля видео (видимость,
        категория) правит проход настроек видео."""
        self._services.progress.broadcast_step_started(item, BroadcastStep.FIX)
        fixes: FieldFixes = item.match.fixes
        channel: ChannelConfig = self._channel(item)
        if FixCall.BROADCAST in fixes.fix_calls:
            self._services.platform.update_broadcast(channel, broadcast_id, item.expected)
            fixes.mark_fixed(fixes.fields_fixed_by(FixCall.BROADCAST))
        if with_marker and FixCall.STREAM in fixes.fix_calls and item.match.stream is not None:
            # ручной эфир усыновлён: со следующего запуска видно, что ключ уходил стримеру
            self._services.platform.set_stream_marker(channel, item.match.stream.stream_id, item.expected.marker)
            fixes.mark_fixed(fixes.fields_fixed_by(FixCall.STREAM))
        if FixCall.THUMBNAIL in fixes.fix_calls:
            self._set_thumbnail(item, broadcast_id)
        updated: LogEvent = BroadcastsEvent.BROADCAST_UPDATED.of(item, broadcast_id=broadcast_id, fields=fixes.changed)
        updated.emit(LOGGER)

    def _finish(self, item: PlannedBroadcast) -> None:
        """Настройки видео и снимок фактов — по каждому эфиру, который программа считает своим."""
        broadcast_id: str | None = item.match.own_broadcast_id(item.decision)
        if broadcast_id is None:
            return
        was_match: bool = item.decision is Decision.MATCH
        fixes: VideoFixes | None = self._apply_video_settings(item, broadcast_id)
        if was_match and item.decision is Decision.UPDATE:
            # видимость или категория разошлись у ресурса видео: эфир исправлен, настройки второй раз не проходятся
            self._resend(item, broadcast_id, with_marker=False)
        self._read_facts(item, broadcast_id, fixes)

    def _apply_video_settings(self, item: PlannedBroadcast, broadcast_id: str) -> VideoFixes | None:
        """Язык, категория, видимость и аудитория — одним проходом по ресурсу видео (инвариант 7).

        Возвращает ответ площадки на запись: снимок фактов сверяется с ним. None — вызов не удался.
        """
        settings: VideoSettings = VideoSettings(
            language=item.slot.language,
            category_id=self._services.settings.category_id,
            privacy=item.channel.privacy.value,
        )
        try:
            fixes: VideoFixes = self._services.platform.apply_video_settings(
                self._channel(item), broadcast_id, settings
            )
        except PlatformError as error:
            self._warn(item, BroadcastsEvent.VIDEO_SETTINGS_FAILED, WarningStep.SETTINGS, error)
            return None
        if fixes.audience_cleared:
            item.outcome.warn(OutcomeWarning(WarningStep.AUDIENCE, AUDIENCE_FIXED_CODE))
        if item.match.found is not None:
            # у созданного эфира категорию и видимость ставит программа; у найденного это исправление
            self._take_video_fixes(item, fixes)
        return fixes

    def _take_video_fixes(self, item: PlannedBroadcast, fixes: VideoFixes) -> None:
        """Поля видео, исправленные у найденного эфира: совпавший эфир становится исправленным."""
        added: tuple[ChangedField, ...] = item.match.fixes.take_video_fixes(fixes)
        if not added:
            return
        if item.decision is Decision.MATCH:
            item.decision = Decision.UPDATE
        BroadcastsEvent.VIDEO_FIELDS_FIXED.of(item, fields=added).emit(LOGGER)

    def _read_facts(self, item: PlannedBroadcast, broadcast_id: str, fixes: VideoFixes | None) -> None:
        """Один раз на объект: что по факту лежит на площадке. Поля, записанные этим же запуском, — из ответа записи
        (`VideoFixes.apply_to_facts`): перечитывание сразу после неё может отдать ещё старое значение."""
        try:
            read: BroadcastFacts = self._services.platform.read_facts(self._channel(item), broadcast_id)
        except PlatformError as error:
            self._warn(item, BroadcastsEvent.FACTS_READ_FAILED, WarningStep.FACTS, error)
            return
        facts: BroadcastFacts = read if fixes is None else fixes.apply_to_facts(read)
        item.match.facts = facts
        item.expected.logged(BroadcastsEvent.BROADCAST_EXPECTED.of(item)).emit(LOGGER)
        if item.match.actual is not None:     # созданный этим запуском эфир в списке не находился
            item.match.actual.logged(BroadcastsEvent.BROADCAST_FOUND.of(item)).emit(LOGGER)
        FactsLog(facts).logged(BroadcastsEvent.BROADCAST_FACTS.of(item)).emit(LOGGER)
        if facts.age_restricted:
            url: str = YouTubeVideoId(broadcast_id).watch_url
            item.outcome.warn(OutcomeWarning(WarningStep.AGE_RESTRICTED, AGE_RESTRICTED_RATING, url))

    def _set_thumbnail(self, item: PlannedBroadcast, broadcast_id: str) -> None:
        """Обложка не критична: эфир и ключ остаются в силе. Поставлена — факт в память объекта; канал уже отказал
        в загрузке обложек — без обращения. Ставится, только если так велит спека (livecraft.json и превью слота)."""
        if item.expected.has_own_thumbnail is not True:
            return
        channel: ChannelConfig = self._channel(item)
        refusal: PlatformError | None = self._services.platform.thumbnail_refusal(channel)
        if refusal is not None:
            self._thumbnail_failed(item, refusal)
            return
        preview: bytes = self._services.rng.choice(item.slot.previews).data
        try:
            self._services.platform.set_thumbnail(channel, broadcast_id, preview)
        except PlatformError as error:
            self._thumbnail_failed(item, error)
            return
        item.memory.remember_thumbnail(broadcast_id, self._services.clock)
        item.match.fixes.mark_fixed(item.match.fixes.fields_fixed_by(FixCall.THUMBNAIL))

    def _thumbnail_failed(self, item: PlannedBroadcast, error: PlatformError) -> None:
        """Обложка не встала: предупреждение, а поле обложки, которое надо было исправить, — не исправлено."""
        self._warn(item, BroadcastsEvent.THUMBNAIL_FAILED, WarningStep.THUMBNAIL, error)
        for name in item.match.fixes.fields_fixed_by(FixCall.THUMBNAIL):
            item.match.fixes.mark_unfixed(name)

    def _warn(self, item: PlannedBroadcast, event: BroadcastsEvent, step: WarningStep, error: PlatformError) -> None:
        """Шаг не удался, эфир и ключ в силе: строка лога и предупреждение объекта."""
        event.of(item, code=error.code).emit(LOGGER, logging.WARNING)
        item.outcome.warn(OutcomeWarning(step, error.code, error.message))

    def _channel(self, item: PlannedBroadcast) -> ChannelConfig:
        """Канал эфира сейчас — значения после фазы входов (§14 решение 25)."""
        return item.admission.channel_config(item.channel)
