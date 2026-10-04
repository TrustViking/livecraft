"""Часть «эфиры» в тестах (CLAUDE.md §11): зависимости на подделках площадки и формы, запуск части тем же путём, что у
программы (`BroadcastStage.run`), память — файлом во временном корне теста.

Момент тестов — 16.03.2027 12:00 по Киеву; форма ключей — тренировочная (даты 11–13.09.2026 и 17.03.2027, языки uk,
ru, en): её страница — ответ на первое чтение, ответ на отправку задаёт тест. Каждый запуск — новые книга каналов и
формы (как у нового запуска программы), площадка — та же: второй запуск видит, что сделал первый.
"""
from __future__ import annotations

import dataclasses
import random
from typing import Any
from dataclasses import dataclass, field
from datetime import datetime

from app.broadcasts.run import BroadcastSlots
from app.broadcasts.services import BroadcastServices
from app.broadcasts.stage import BroadcastPartResult, BroadcastStage
from app.config.channel import ChannelConfig, ConfiguredChannels
from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.core.text_format import TEXT_ENCODING
from app.form.book import FormBook
from app.output.report import RunReport
from app.packages.run_slots import RunSlots
from app.paths import FileName, LivecraftPaths
from app.records.record_store import RecordStore
from app.records.slot_record import SlotRecord
from app.pipeline.progress import RunProgress
from app.platforms.channel_book import ChannelBook
from app.platforms.channel_console import ChannelConsole
from app.platforms.channel_sync import ChannelSync
from app.platforms.verified import VerifiedPlatform
from app.run.mode import RunMode
from app.run.request import RunRequest
from app.slots.slot import StreamSlot
from app.tests.fixtures.clock import StoppedClock
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.form import (
    REFUSAL_PAGE,
    SUCCESS_PAGE,
    TRAINING_FORM_TITLE,
    FakeFormResponse,
    FakeForms,
    FormCall,
    build_html,
    build_payload,
    default_items,
)
from app.tests.fixtures.pipeline import CLOCK, FORM, NOW, SETTINGS
from app.tests.fixtures.platform import FakePlatform, two_channels, written_channels, written_token
from app.ui.console import Console

LANGUAGE_OPTIONS: tuple[str, ...] = ("Украинский ( Ukranian)", "Русский ( Russian)", "Английский ( English)")
FORM_TITLE_GAP: int = 6
STREAM_URLS: tuple[str, ...] = ("rtmp://a.rtmp.youtube.com/live2/", "rtmp://x.rtmp.youtube.com/live2/")
BENCH_SETTINGS: LivecraftSettings = dataclasses.replace(SETTINGS, form=FORM)
FORM_REFUSED: FakeFormResponse = FakeFormResponse(REFUSAL_PAGE, status_code=400)


@dataclass
class BroadcastBench:
    """Корень, площадка, каналы, настройки, часы и ответ формы на отправку; обращения к формам всех запусков — в
    `forms`, консоль всех запусков — в `record`."""

    paths: LivecraftPaths
    platform: FakePlatform = field(default_factory=FakePlatform)
    channels: tuple[ChannelConfig, ...] = field(default_factory=two_channels)
    settings: LivecraftSettings = BENCH_SETTINGS
    clock: Clock = CLOCK
    post_replies: tuple[FakeFormResponse | BaseException, ...] = (FakeFormResponse(SUCCESS_PAGE),)
    form_page: str = REFUSAL_PAGE
    forms: list[FakeForms] = field(default_factory=list)
    record: ConsoleRecord = field(default_factory=ConsoleRecord)

    @classmethod
    def with_tokens(cls, paths: LivecraftPaths, *channels: ChannelConfig) -> BroadcastBench:
        """Каналы в channels.json и с токенами: проверка без браузера подтверждает их, входов нет."""
        bench: BroadcastBench = cls(paths, channels=channels or two_channels())
        written_channels(paths, *bench.channels)
        for channel in bench.channels:
            written_token(paths, channel.handle)
        return bench

    def services(self) -> BroadcastServices:
        """Зависимости одного запуска: новая книга каналов и новые формы, площадка — та же; консоль — общая запись."""
        return self.services_on(self.record.console)

    def services_on(self, console: Console) -> BroadcastServices:
        """Зависимости одного запуска со строками на консоль `console` (окно настройщика пишет их в свою запись)."""
        self.platform.paths = self.paths
        forms: FakeForms = FakeForms.answering(self.form_page, *self.post_replies)
        self.forms.append(forms)
        sync: ChannelSync = ChannelSync(self.platform, self.paths, self.clock)
        book: ChannelBook = ChannelBook(self.platform, sync, ChannelConsole(console))
        return BroadcastServices(
            paths=self.paths,
            settings=self.settings,
            platform=VerifiedPlatform(self.platform, book),
            book=book,
            forms=FormBook(reader=forms.reader(self.paths.logs_dir)),
            usage=self.platform.gateway.usage,
            clock=self.clock,
            rng=random.Random(0),
            progress=RunProgress(console),
        )

    def run(
        self, *slots: StreamSlot, dry_run: bool = False, started: datetime = NOW, to_form: bool = True
    ) -> BroadcastPartResult:
        """Часть «эфиры» по этим слотам — как у запуска с таблицей: форма — из настроек; `to_form` — идёт ли линия
        «Ключи в форму»."""
        run: RunSlots = RunSlots.of_table(slots, self.settings.form)
        slots_of_run: BroadcastSlots = BroadcastSlots.of_table(run, self.settings, self.paths.bcast_dir)
        return self.stage(RunMode.RUN, dry_run, started).run(slots_of_run, to_form)

    def run_slots(self, slots: BroadcastSlots, started: datetime = NOW) -> BroadcastPartResult:
        """Часть «эфиры» по готовым слотам части — как у режима Б."""
        return self.stage(RunMode.RUN, False, started).run(slots, True)

    def status(self, started: datetime = NOW) -> BroadcastPartResult:
        """Сверка --status: эфиры программы на каналах, keys.txt и отчёт."""
        return self.stage(RunMode.STATUS, False, started).status()

    def stage(self, mode: RunMode, dry_run: bool, started: datetime) -> BroadcastStage:
        """Часть одного запуска: новые книга каналов и формы, та же площадка."""
        request: RunRequest = RunRequest(mode=mode, auth_handle=None, dry_run=dry_run, debug=False)
        return BroadcastStage(self.services(), ConfiguredChannels(self.channels), request, started)

    def memory_since(self, moment: datetime) -> None:
        """Память программы уже была: создана в `moment` прошлым запуском, записей в ней нет."""
        RecordStore.open(self.paths.file(FileName.RECORDS), False, StoppedClock.at(moment)).close()

    def stored(self, slot_id: str, channel: ChannelConfig | None = None) -> SlotRecord | None:
        """Запись памяти эфира слота на канале (по умолчанию — первом): как её прочтёт следующий запуск."""
        config: ChannelConfig = channel if channel is not None else self.channels[0]
        store: RecordStore = RecordStore.open(self.paths.file(FileName.RECORDS), True, self.clock)
        try:
            return store.find(slot_id, FakePlatform.default_channel_info(config).youtube_channel_id)
        finally:
            store.close()

    @property
    def posts(self) -> list[FormCall]:
        """Отправки ответов формы всех запусков по порядку."""
        return [post for forms in self.forms for post in forms.posts]

    @property
    def keys_text(self) -> str:
        return self.paths.file(FileName.KEYS).read_text(encoding=TEXT_ENCODING)

    @property
    def has_keys_file(self) -> bool:
        return self.paths.file(FileName.KEYS).is_file()


def form_page(*dates: str, stream_urls: tuple[str, ...] = STREAM_URLS) -> str:
    """Страница формы ключей с тренировочными вопросами: в «Время стрима» — только эти даты (17.03.2027), в
    «Stream-URL (YT)» — только эти адреса; языки — uk, ru, en; заголовок — как у тренировочной формы."""
    items: list[Any] = default_items()
    items[0][4][0][1] = [[option] for option in LANGUAGE_OPTIONS]
    items[2][4][0][1] = [[f"{date} Дата стрима"] for date in dates]
    items[6][4][0][1] = [[url] for url in stream_urls]
    payload: list[Any] = build_payload(items)
    payload[1].extend([None] * FORM_TITLE_GAP + [TRAINING_FORM_TITLE])      # [1][2..7] — пусто, [1][8] — заголовок
    return build_html(payload)


def report_of(result: BroadcastPartResult) -> RunReport:
    """Отчёт части: у запуска со слотами для YouTube он есть всегда."""
    assert result.report is not None
    return result.report


def report_text(result: BroadcastPartResult) -> str:
    """Текст части «Эфиры YouTube» отчёта запуска — так часть попадает в файл отчёта."""
    return "\n".join(result.part_report.lines)


def sent_values(call: FormCall) -> list[str]:
    """Все значения ответа формы одной отправки."""
    return [value for values in call.body.values() for value in (values if isinstance(values, list) else [values])]
