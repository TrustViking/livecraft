"""Сверка --status: эфиры программы на каналах, keys.txt и отчёт — без таблицы, пакетов и нейросети (CLAUDE.md §10;
поведение — runner planers `_run_status`).

Порядок: фаза входов всех каналов → эфиры с меткой программы на каждом канале (сбой канала не валит остальные) →
keys.txt: ключ и адрес — с площадки, строка «форма» — из памяти (только чтение; в форму этот режим ничего не шлёт) →
отчёт вида STATUS.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path

from app.broadcasts.record_keeper import RecordKeeper
from app.broadcasts.services import BroadcastServices
from app.config.channel import ChannelConfig, ConfiguredChannels
from app.output.keys_file import KeyRow, KeysFile
from app.output.report import ReportKind, ReportRequest, RunReport
from app.output.run_failure import RunFailure
from app.pipeline.orphan import MarkedBroadcast, MarkedScan
from app.pipeline.reconciler import Reconciler
from app.pipeline.selection import Selection
from app.platforms.channel import Channel
from app.records.record_results import RecordResults


@dataclass(frozen=True)
class StatusRun:
    """Зависимости, память на чтение, каналы после проверки без браузера и начало запуска (штамп отчёта)."""

    services: BroadcastServices
    keeper: RecordKeeper
    channels: ConfiguredChannels
    started: datetime

    def run(self) -> RunReport:
        """Каналы после входов — в порядке channels.json; ключи и отчёт — по эфирам с меткой программы."""
        services: BroadcastServices = self.services
        services.book.log_in_needed(self.channels.channels)
        channels: tuple[ChannelConfig, ...] = tuple(
            services.book.channel(config).config for config in self.channels.channels
        )
        zone: tzinfo = services.settings.zone
        scan: MarkedScan = Reconciler(services.platform, zone, services.progress).marked_broadcasts(channels)
        rows: tuple[KeyRow, ...] = tuple(KeyRow.of_marked(item, self._results(item), zone) for item in scan.broadcasts)
        keys_file: Path | RunFailure = KeysFile(rows, services.clock.now()).write(services.paths)
        request: ReportRequest = ReportRequest(
            kind=ReportKind.STATUS,
            started=self.started,
            selection=Selection(planned=(), skipped=()),
            settings=services.settings,
            limits=services.platform.limits,
            channels=channels,
            paths=services.paths,
            scan=scan,
            notices=services.platform.take_notices(),
            warnings=(*services.book.sync.take_warnings(), *self.keeper.store.take_warnings()),
            keys_file=keys_file,
        )
        return RunReport.of(request)

    def _results(self, marked: MarkedBroadcast) -> RecordResults:
        """Что память знает об эфире: запись по метке слота и id канала на YouTube."""
        channel: Channel = self.services.book.channel(marked.channel)
        channel_id: str | None = None if channel.info is None else channel.info.youtube_channel_id
        return self.keeper.results_of(marked.stream.title, channel_id)
