"""Прогресс запуска контура B в консоли: строка на каждый долгий шаг между шапкой и итогом (CLAUDE.md §3 шаги 7–12).

Здесь — только живые строки по ходу работы: пакеты bcast\\ (режим Б), даты формы, чтение каналов, создание и
исправление эфиров, отправка ключей, отчёт. В терминале шаги этапа — одна строка, которая обновляется на месте;
последний шаг этапа остаётся на экране, следующий этап пишет с новой строки; создание, правка эфира и отправка его
ключа — один этап «эфиры»; строка дат формы — сообщение и остаётся (§14 решение 78). Шаги чтения каналов и эфиров —
со счётом «n из N» и полосой хода: последняя строка этапа читается как его итог. Шаг этапа «эфиры» — объект с
действием (создание, привязка потока, правка или ключ в форму): объекты прогона по порядку и те, что будут действовать,
прогон говорит до действий (`plan_broadcasts`); объект, чьё действие открылось по ходу (настройки видео), встаёт в счёт
на своё место (`BroadcastSteps`). Итоговые блоки печатает вывод (app\\output\\). Без консоли (тесты, служебные
вызовы) прогресс молчит.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum

from app.config.channel import ChannelConfig
from app.form.coverage import DateCoverage
from app.packages.package_line import PackageLines
from app.pipeline.plan import PlannedBroadcast
from app.slots.slot import SlotKey
from app.ui.console import Console, ProgressStage, StepCount
from app.ui.messages import msg


class BroadcastStep(str, Enum):
    """Действие по эфиру, о котором говорит строка прогресса."""

    CREATE = "create"
    FIX = "fix"

    @property
    def template(self) -> str:
        return msg.PROGRESS_BROADCAST_CREATE if self is BroadcastStep.CREATE else msg.PROGRESS_BROADCAST_FIX


@dataclass(frozen=True)
class StepKey:
    """Объект прогона — слот на канале (инвариант 0): по нему ищется место объекта среди шагов этапа «эфиры»."""

    slot_id: str
    channel: str

    @classmethod
    def of(cls, item: PlannedBroadcast) -> StepKey:
        return cls(item.slot.slot_id, item.channel.key)


@dataclass
class BroadcastSteps:
    """Шаги этапа «эфиры»: объекты прогона по порядку (`order`) и те из них, что действуют (`acting`). Изменяемый
    намеренно: объект, чьё действие открылось по ходу, встаёт в счёт, и «N» растёт."""

    order: tuple[StepKey, ...] = ()
    acting: set[StepKey] = field(default_factory=set)

    def step(self, key: StepKey) -> StepCount:
        """Место действующего объекта среди действующих в порядке прогона и их число."""
        self.acting.add(key)
        place: int = sum(1 for known in self.order[: self.order.index(key) + 1] if known in self.acting)
        return StepCount(place, len(self.acting))


@dataclass(frozen=True)
class RunProgress:
    """Строки прогресса на консоль оператора; `console` None — молчит. `steps` — шаги этапа «эфиры»: заполняет
    `plan_broadcasts`."""

    console: Console | None = None
    steps: BroadcastSteps = field(default_factory=BroadcastSteps, repr=False)

    def packages_read(self, packages: PackageLines) -> None:
        """Режим Б: сколько пакетов прочитано и сколько в них слотов — тем же счётом, что раздел «Пакеты» отчёта."""
        self._say(packages.progress_line, ProgressStage.PACKAGES)

    def form_dates_checked(self, coverage: DateCoverage) -> None:
        """Одна строка на форму: все ли даты запуска в ней есть. Вопроса даты нет — строки нет. Это сообщение, а не шаг:
        оно остаётся на экране."""
        line: str | None = coverage.line
        if line is not None and self.console is not None:
            self.console.say(line)

    def channel_read_started(self, channel: ChannelConfig, step: StepCount) -> None:
        """До чтения запланированных эфиров канала; `step` — место канала среди читаемых."""
        started: str = msg.PROGRESS_CHANNEL_READ_STARTED.format(
            place=step.place, total=step.total, account_name=channel.account_name, handle=channel.handle
        )
        self._say(started, ProgressStage.CHANNEL_READ, step)

    def channel_read_done(self, channel: ChannelConfig, upcoming: int, step: StepCount) -> None:
        """После успешного ответа площадки: сколько запланированных эфиров на канале."""
        done: str = msg.PROGRESS_CHANNEL_READ_DONE.format(
            place=step.place, total=step.total, account_name=channel.account_name, handle=channel.handle, count=upcoming
        )
        self._say(done, ProgressStage.CHANNEL_READ, step)

    def plan_broadcasts(self, planned: Sequence[PlannedBroadcast], acting: Sequence[PlannedBroadcast]) -> None:
        """Объекты прогона по порядку и те, что будут действовать: у каждого действующего — его «n из N»."""
        self.steps.order = tuple(StepKey.of(item) for item in planned)
        self.steps.acting = {StepKey.of(item) for item in acting}

    def broadcast_step_started(self, item: PlannedBroadcast, step: BroadcastStep) -> None:
        """До создания или правки эфира на площадке."""
        self._say_about(step.template, item)

    def key_send_started(self, item: PlannedBroadcast) -> None:
        """До отправки ключа эфира в форму."""
        self._say_about(msg.PROGRESS_KEY_SEND, item)

    def report_started(self) -> None:
        self._say(msg.PROGRESS_REPORT, ProgressStage.REPORT)

    def _say_about(self, template: str, item: PlannedBroadcast) -> None:
        """Шаг этапа «эфиры» об объекте: канал — значения после фазы входов, дата — для людей (17.03.2027)."""
        channel: ChannelConfig = item.admission.channel_config(item.channel)
        key: SlotKey = item.slot.key
        step: StepCount = self.steps.step(StepKey.of(item))
        text: str = template.format(
            place=step.place,
            total=step.total,
            account_name=channel.account_name,
            handle=channel.handle,
            date=key.human_date,
            time=key.time_text,
            language=key.language,
        )
        self._say(text, ProgressStage.BROADCASTS, step)

    def _say(self, text: str, stage: ProgressStage, step: StepCount | None = None) -> None:
        """Шаг этапа `stage` — строкой хода, которая обновляется на месте, со счётом — с полосой хода; шаг другого
        этапа — с новой строки (§14 решение 78)."""
        if self.console is not None:
            self.console.progress(text, stage, step)
