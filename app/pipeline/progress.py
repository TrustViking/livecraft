"""Прогресс запуска контура B в консоли: строка на каждый долгий шаг между шапкой и итогом (CLAUDE.md §3 шаги 7–12).

Здесь — только живые строки по ходу работы: пакеты bcast\\ (режим Б), даты формы, чтение каналов, создание и
исправление эфиров, отправка ключей, отчёт. Итоговые блоки печатает вывод (app\\output\\). Без консоли (тесты,
служебные вызовы) прогресс молчит.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from app.config.channel import ChannelConfig
from app.form.coverage import DateCoverage
from app.packages.package_line import PackageLines
from app.pipeline.plan import PlannedBroadcast
from app.slots.slot import SlotKey
from app.ui.console import Console
from app.ui.messages import msg


class BroadcastStep(str, Enum):
    """Действие по эфиру, о котором говорит строка прогресса."""

    CREATE = "create"
    FIX = "fix"

    @property
    def template(self) -> str:
        return msg.PROGRESS_BROADCAST_CREATE if self is BroadcastStep.CREATE else msg.PROGRESS_BROADCAST_FIX


@dataclass(frozen=True)
class RunProgress:
    """Строки прогресса на консоль оператора; `console` None — молчит."""

    console: Console | None = None

    def packages_read(self, packages: PackageLines) -> None:
        """Режим Б: сколько пакетов прочитано и сколько в них слотов — тем же счётом, что раздел «Пакеты» отчёта."""
        self._say(packages.progress_line)

    def form_dates_checked(self, coverage: DateCoverage) -> None:
        """Одна строка на форму: все ли даты запуска в ней есть. Вопроса даты нет — строки нет."""
        line: str | None = coverage.line
        if line is not None:
            self._say(line)

    def channel_read_started(self, channel: ChannelConfig) -> None:
        """До чтения запланированных эфиров канала."""
        self._say(msg.PROGRESS_CHANNEL_READ_STARTED.format(account_name=channel.account_name, handle=channel.handle))

    def channel_read_done(self, channel: ChannelConfig, upcoming: int) -> None:
        """После успешного ответа площадки: сколько запланированных эфиров на канале."""
        done: str = msg.PROGRESS_CHANNEL_READ_DONE
        self._say(done.format(account_name=channel.account_name, handle=channel.handle, count=upcoming))

    def broadcast_step_started(self, item: PlannedBroadcast, step: BroadcastStep) -> None:
        """До создания или правки эфира на площадке."""
        self._say(self._about(step.template, item))

    def key_send_started(self, item: PlannedBroadcast) -> None:
        """До отправки ключа эфира в форму."""
        self._say(self._about(msg.PROGRESS_KEY_SEND, item))

    def report_started(self) -> None:
        self._say(msg.PROGRESS_REPORT)

    def _about(self, template: str, item: PlannedBroadcast) -> str:
        """Строка об эфире: канал — значения после фазы входов, дата — для людей (17.03.2027)."""
        channel: ChannelConfig = item.admission.channel_config(item.channel)
        key: SlotKey = item.slot.key
        return template.format(
            account_name=channel.account_name,
            handle=channel.handle,
            date=key.human_date,
            time=key.time_text,
            language=key.language,
        )

    def _say(self, text: str) -> None:
        if self.console is not None:
            self.console.say(text)
