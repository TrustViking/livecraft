"""Прогон части «эфиры» по слотам для YouTube (CLAUDE.md §3 шаги 7–12; поведение — runner planers).

Порядок: отбор объектов → даты формы → фаза входов (после неё браузер не открывается) → допуск → записи памяти →
сверка с каналами после входов → эфиры старше памяти → действия и ключи (полный запуск) или только решение о ключе по
памяти (--dry-run) → keys.txt (полный запуск) → отчёт; полный запуск чистит память по keep_days. Линия «Ключи в форму»
не идёт (§14 решение 37) — форма не читается, допуск только по каналу, ключи — только в keys.txt. Истина об эфирах и
ключах — на площадке; память — только о том, что форма уже отправляла и подтвердила. Слоты прогона — `BroadcastSlots`:
одинаково для входа «Таблица» (слоты таблицы для YouTube с формой настроек) и входа «Пакеты» (слоты полки bcast\\ с
формой своего пакета, прошедшие слоты и строки пакетов — в отчёт). Известные слоты сверки от таблицы — и слоты таблицы,
и слоты папки пакетов: эфир, созданный по пакету этой папки, — не «перенесён или отменён?» (§13 этап 6).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.broadcasts.actions import BroadcastActions
from app.broadcasts.admitting import BroadcastAdmission
from app.broadcasts.key_sender import KeySender
from app.broadcasts.record_keeper import RecordKeeper
from app.broadcasts.services import BroadcastServices
from app.config.channel import ChannelConfig, ConfiguredChannels
from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.form.book import FormBook
from app.output.keys_file import KeyRow, KeysFile
from app.output.report import ReportKind, ReportRequest, RunReport
from app.output.result import SlotLabel
from app.output.run_failure import RunFailure
from app.packages.package_line import PackageLines
from app.packages.package_shelf import PackageShelf
from app.packages.package_slot import PackageSlot
from app.packages.run_slots import RunSlots
from app.pipeline.orphan import OrphanBroadcast
from app.pipeline.plan import KeyRoute, PlannedBroadcast
from app.pipeline.reconciler import Reconciler
from app.pipeline.selection import Selection, SelectionRequest
from app.platforms.notice import PlatformNotice
from app.records.slot_record import SlotStage
from app.slots.slot import SlotEntry
from app.ui.messages import msg


@dataclass(frozen=True)
class BroadcastSlots:
    """Слоты части: для YouTube — с формой ключей каждого; `known` — slot_id → старт всех слотов плана (эфир известного
    слота на другой минуте — «перенесён», а не сирота); `past` — прошедшие слоты (режим Б); `packages` — строки пакетов
    полки (режим Б)."""

    slots: tuple[PackageSlot, ...]
    known: Mapping[str, datetime]
    past: tuple[SlotEntry, ...] = ()
    packages: PackageLines = field(default_factory=PackageLines)

    @classmethod
    def of_table(cls, slots: RunSlots, settings: LivecraftSettings, folder: Path) -> BroadcastSlots:
        """Вход «Таблица»: слоты запуска для YouTube с формой настроек; известные — все слоты полки папки пакетов
        `folder` (будущие и прошедшие) и все слоты запуска. Один slot_id в таблице и в пакете — старт таблицы: план —
        она."""
        shelf: PackageShelf = PackageShelf.read(folder, settings.zone, Clock(settings.zone).now())
        known: dict[str, datetime] = {**shelf.known, **{slot.slot_id: slot.start for slot in slots.slots}}
        return cls(slots.for_youtube.items, known)

    @classmethod
    def of_shelf(cls, shelf: PackageShelf, packages: PackageLines) -> BroadcastSlots:
        """Вход «Пакеты»: будущие слоты полки с формой своего пакета, известные — и прошедшие, строки пакетов."""
        return cls(shelf.slots, shelf.known, shelf.past, packages)


@dataclass(frozen=True)
class BroadcastRun:
    """Один прогон: зависимости, память, каналы после проверки без браузера, вид запуска, его начало (штамп отчёта) и
    идут ли ключи в форму (`to_form`)."""

    services: BroadcastServices
    keeper: RecordKeeper
    channels: ConfiguredChannels
    kind: ReportKind
    started: datetime
    to_form: bool

    @property
    def route(self) -> KeyRoute:
        """Правила ключей запуска: линия «Ключи в форму» и повторная передача из настроек."""
        return KeyRoute(to_form=self.to_form, resend=self.services.settings.broadcasts.resend_keys)

    def run(self, slots: BroadcastSlots) -> RunReport:
        """Отбор по слотам для YouTube; сверка — со всеми известными слотами плана; прошедшие и пакеты — в отчёт."""
        selection: Selection = self._select(slots.slots)
        channels: tuple[ChannelConfig, ...] = self._channels_after_logins()
        orphans: tuple[OrphanBroadcast, ...] = Reconciler(
            self.services.platform, self.services.settings.zone, self.services.progress
        ).reconcile(selection.planned, slots.known, channels)
        notices: tuple[PlatformNotice, ...] = self.services.platform.take_notices()
        keys_file: Path | RunFailure | None = self._act(selection.planned)
        warnings: tuple[str, ...] = (
            *self.services.book.sync.take_warnings(), *self._given_up(selection.planned),
            *self.keeper.store.take_warnings(),
        )
        request: ReportRequest = ReportRequest(
            kind=self.kind,
            started=self.started,
            selection=selection,
            settings=self.services.settings,
            limits=self.services.platform.limits,
            channels=channels,
            paths=self.services.paths,
            past_slots=slots.past,
            packages=slots.packages,
            orphans=orphans,
            notices=notices,
            warnings=warnings,
            keys_file=keys_file,
        )
        return RunReport.of(request)

    def _select(self, slots: tuple[PackageSlot, ...]) -> Selection:
        """Отбор → даты формы (до входов и до площадки) → фаза входов → допуск → записи памяти."""
        services: BroadcastServices = self.services
        selection: Selection = Selection.of(
            SelectionRequest(
                slots=slots,
                channels=self.channels.channels,
                settings=services.settings,
                limits=services.platform.limits,
                now=services.clock.now(),
            )
        )
        forms: FormBook | None = services.forms if self.to_form else None
        admission: BroadcastAdmission = BroadcastAdmission(services.book, forms, services.progress)
        admission.check_form_dates(selection.planned)
        # к площадке обращаемся только по каналам, у которых есть объекты (и too_late): входы — все до сверки
        services.book.log_in_needed([item.channel for item in selection.planned])
        admission.admit_all(selection.planned)
        self.keeper.load(selection.planned)
        return selection

    def _given_up(self, planned: tuple[PlannedBroadcast, ...]) -> tuple[str, ...]:
        """Ключи, которые форма не подтвердила ни в первый раз, ни повтором и которые сами больше не уходят, — строкой
        на эфир с действием (§14 решение 49); ключи в форму не идут — строк нет."""
        if not self.to_form:
            return ()
        given_up: tuple[PlannedBroadcast, ...] = tuple(item for item in planned if item.is_key_given_up)
        return tuple(msg.KEYS_GIVEN_UP.format(prefix=SlotLabel.of(item).text) for item in given_up)

    def _channels_after_logins(self) -> tuple[ChannelConfig, ...]:
        """Каналы запуска со значениями после фазы входов, в порядке channels.json: иначе выровненный при входе канал
        читался бы второй раз, а его сироты повторялись бы."""
        return tuple(self.services.book.channel(config).config for config in self.channels.channels)

    def _act(self, planned: tuple[PlannedBroadcast, ...]) -> Path | RunFailure | None:
        """Полный запуск: по объекту — действия и ключ, затем keys.txt. --dry-run: решение о ключе по памяти, чтобы
        «отправим ключ» было правдой; keys.txt не пишется."""
        services: BroadcastServices = self.services
        route: KeyRoute = self.route
        if self.kind is ReportKind.DRY_RUN:
            for item in planned:
                if item.match.stream_key:
                    item.decide_key_delivery(route)
            return None
        for item in planned:
            if item.admission.is_admitted and not item.is_too_late:
                self.keeper.save(item, SlotStage.ADMITTED)
        keys: KeySender = KeySender(self.keeper, services.forms.sender, services.clock, services.progress, route)
        actions: BroadcastActions = BroadcastActions(services, keys)
        for item in planned:
            actions.execute(item)
        # все будущие эфиры с ключом, включая слоты внутри min_lead_minutes и не допущенные
        rows: tuple[KeyRow, ...] = tuple(
            KeyRow.of_planned(item, services.settings.zone, self.to_form) for item in planned if item.match.stream_key
        )
        return KeysFile(rows, services.clock.now()).write(services.paths)
