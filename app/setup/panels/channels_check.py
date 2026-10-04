"""Каналы YouTube на вкладке «Эфиры YouTube» без окна: вход в канал и проверка всех (CLAUDE.md §8.2 п.8, §10).

`ChannelsCheck` делает ровно то, что служебные запуски `--auth "<ник>"` и `--check`: готовность их нужд
(`ServiceReadiness`: каналы, настройки, client_secret.json), зависимости части «эфиры» (`BroadcastServices.open`) и
`ChannelService` — тот же код, что у консоли. Одно правило, два вывода: консоль служебного запуска печатает строки в
терминал, а здесь консоль пишет их в запись проверки (`CheckTranscript`), и окно показывает всё сказанное по ходу
проверки и итогом — те же строки, последняя — со знаком «✓» или «✗». Итог — `ChannelsVerdict`: всё ли прошло
(`RunOutcome.DONE`) и строки; нуждам чего-то не хватает — каждая строка нужды со знаком «✗». Вход открывает
браузер — поэтому только по кнопке; строки о браузере говорит сама книга каналов (`ChannelConsole`). Проверка идёт в
фоновом потоке окна: модель не знает ни потоков, ни Tk. Значений сейфа в строках нет: ники, названия и причины.
"""
from __future__ import annotations

import io
from collections.abc import Callable
from dataclasses import dataclass

from app.broadcasts.service import ChannelService
from app.broadcasts.services import BroadcastServices
from app.config.settings import LivecraftSettings
from app.core.text_format import NEWLINE
from app.paths import LivecraftPaths
from app.run.exit_code import RunOutcome
from app.run.mode import RunMode
from app.setup.readiness import ChannelBasis, Readiness, ServiceReadiness
from app.ui.console import Console
from app.ui.messages import msg

# Зависимости части «эфиры» с консолью проверки: в программе — YouTube и входы владельцев, в тестах — подделка.
ServicesSource = Callable[[LivecraftPaths, LivecraftSettings, Console], BroadcastServices]


class CheckTranscript(io.StringIO):
    """Запись консоли проверки: строки копятся; каждая законченная строка отдаёт всё сказанное до неё (`on_text`)."""

    def __init__(self, on_text: Callable[[str], None]) -> None:
        super().__init__()
        self.on_text: Callable[[str], None] = on_text

    @property
    def text(self) -> str:
        """Всё сказанное — без перевода строки в конце."""
        return self.getvalue().rstrip(NEWLINE)

    def write(self, text: str) -> int:
        written: int = super().write(text)
        if NEWLINE in text:
            self.on_text(self.text)
        return written


@dataclass(frozen=True)
class ChannelsVerdict:
    """Итог входа или проверки каналов: всё ли прошло и строки консоли; последняя строка — итог консоли со знаком «✓»
    или «✗» (цвет строки окна — по знаку)."""

    is_ok: bool
    text: str

    @classmethod
    def blocked(cls, lines: tuple[str, ...]) -> ChannelsVerdict:
        """Нуждам служебного запуска чего-то не хватает: каждая строка — проблема."""
        return cls(is_ok=False, text=NEWLINE.join(msg.CHECK_PROBLEM_LINE.format(line=line) for line in lines))

    @classmethod
    def of_run(cls, outcome: RunOutcome, said: str) -> ChannelsVerdict:
        """Всё сказанное служебным запуском; его последняя строка — итог консоли — получает знак: прошло ли всё."""
        is_ok: bool = outcome is RunOutcome.DONE
        *before, last = said.split(NEWLINE)
        mark: str = msg.CHECK_OK_LINE if is_ok else msg.CHECK_PROBLEM_LINE
        return cls(is_ok=is_ok, text=NEWLINE.join((*before, mark.format(line=last))))


@dataclass(frozen=True)
class ChannelsCheck:
    """Вход в канал и проверка всех каналов этой установки: зависимости части «эфиры» — `open_services`."""

    paths: LivecraftPaths
    open_services: ServicesSource

    @classmethod
    def of(cls, paths: LivecraftPaths) -> ChannelsCheck:
        """Боевые зависимости: YouTube с входами владельцев каналов — как у служебных запусков."""
        return cls(paths=paths, open_services=BroadcastServices.open)

    def check_all(self, on_text: Callable[[str], None]) -> ChannelsVerdict:
        """--check: все каналы channels.json; `on_text` — всё сказанное по ходу."""
        return self._run(None, on_text)

    def log_in(self, handle: str, on_text: Callable[[str], None]) -> ChannelsVerdict:
        """--auth "<ник>": вход заново в канал с этим ником; `on_text` — всё сказанное по ходу."""
        return self._run(handle, on_text)

    def _run(self, handle: str | None, on_text: Callable[[str], None]) -> ChannelsVerdict:
        """Нужд не хватает — их строки; иначе служебный запуск по каналам на консоли проверки."""
        mode: RunMode = RunMode.CHECK if handle is None else RunMode.AUTH
        service: ServiceReadiness = ServiceReadiness(Readiness.check(self.paths), mode)
        basis: ChannelBasis | None = service.basis
        if basis is None:
            return ChannelsVerdict.blocked(service.lines)
        transcript: CheckTranscript = CheckTranscript(on_text)
        console: Console = Console(out=transcript, err=transcript)
        services: BroadcastServices = self.open_services(service.readiness.paths, basis.settings, console)
        outcome: RunOutcome = ChannelService(services, basis.channels, console).run(handle)
        return ChannelsVerdict.of_run(outcome, transcript.text)
