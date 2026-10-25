"""Вкладка «Cookies YouTube» без окна: статус файла, загрузка и проверка (CLAUDE.md §8.2, §14 решение 73).

Статус (`status_line`) — без сети и yt-dlp: есть ли secrets\\cookies.txt, того ли он вида, когда выгружен и не закончился
ли срок напоминания. Загрузка (`choose`): файл с любого места диска встаёт на место secrets\\cookies.txt копией со
временем изменения источника (`CookiesFile.place_from`); не тот вид — прежний файл не тронут, итог с причиной;
загруженный сразу проверяется. Проверка (`check`) — тот же код, что у запуска (`CookiesCheck.status`): вид, дата
выгрузки, срок напоминания и cookies входа в файле; затем — есть ли по ним вход в YouTube (`CookiesLoginProbe`: yt-dlp
открывает ленту вошедшего; §14 решение 80 — только по кнопке, запуск вход не проверяет). Срок напоминания — из настроек,
как они сейчас на диске (его меняют на этой же вкладке). Итог — `CookiesVerdict`: строки окна со знаками и строка
входа — её окно пишет синим: на работу программы вход не влияет. Модель не знает ни потоков, ни Tk: окно запускает её в
фоновом потоке.
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from app.config.files import SettingsFile
from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.core.dates import format_human_date
from app.core.text_format import NEWLINE
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.paths import LivecraftPaths
from app.runtime.cookies_file import CookiesPlaceProblem
from app.runtime.cookies_updater import CookiesCheck, CookiesLoginProbe, CookiesState, CookiesStatus
from app.runtime.ytdlp_launch import YtDlpLaunch
from app.ui.messages import msg

LOGGER = get_logger(LogArea.SETUP)


class CookiesTabEvent(str, Enum):
    """События вкладки «Cookies YouTube» в логе."""

    LOADED = "cookies_file_loaded"


@dataclass(frozen=True)
class CookiesVerdict:
    """Итог загрузки или проверки cookies: всё ли годно, строки для окна и строка входа в YouTube (`login`; проверки
    не было — пусто)."""

    is_ok: bool
    text: str
    login: str = ""

    @classmethod
    def failed(cls, problem: str) -> CookiesVerdict:
        return cls(is_ok=False, text=msg.CHECK_PROBLEM_LINE.format(line=problem))

    def then(self, after: CookiesVerdict) -> CookiesVerdict:
        """Строки загрузки, затем строки проверки и её строка входа; годно — когда годно и то, и другое."""
        return CookiesVerdict(self.is_ok and after.is_ok, NEWLINE.join((self.text, after.text)), after.login)


@dataclass(frozen=True)
class CookiesFileCheck:
    """Cookies установки `paths`; `run` — запуск yt-dlp проверки входа: `subprocess.run` или подделка (в тестах)."""

    paths: LivecraftPaths
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run

    @property
    def status_line(self) -> str:
        """Строка статуса: файла нет, не тот вид, когда выгружен — или что срок напоминания закончился."""
        status: CookiesStatus = self._check.status()
        if status.state is CookiesState.ABSENT:
            return msg.CHECK_PROBLEM_LINE.format(line=msg.COOKIES_WINDOW_ABSENT.format(path=status.shown))
        if status.exported is None:     # не тот вид: даты выгрузки у такого файла не смотрят
            return msg.CHECK_PROBLEM_LINE.format(line=msg.SETUP_COOKIES_STATUS_BAD.format(path=status.shown))
        date: str = format_human_date(status.exported)
        if status.is_stale:
            stale: str = msg.SETUP_COOKIES_STATUS_STALE.format(path=status.shown, date=date)
            return msg.CHECK_PROBLEM_LINE.format(line=stale)
        return msg.CHECK_OK_LINE.format(line=msg.SETUP_COOKIES_STATUS_SET.format(path=status.shown, date=date))

    def choose(self, source: Path) -> CookiesVerdict:
        """Файл `source` — на место secrets\\cookies.txt, затем проверка; не встал — причина, прежний файл не тронут."""
        check: CookiesCheck = self._check
        problem: CookiesPlaceProblem | None = check.file.place_from(source)
        LogEvent.of(CookiesTabEvent.LOADED, source=Quoted(str(source)), problem=problem).emit(LOGGER)
        if problem is not None:
            return CookiesVerdict.failed(msg.COOKIES_PLACE_FAILED.format(reason=problem.human))
        loaded: str = msg.SETUP_COOKIES_LOADED.format(path=check.shown)
        return CookiesVerdict(is_ok=True, text=msg.CHECK_OK_LINE.format(line=loaded)).then(self.check())

    def check(self) -> CookiesVerdict:
        """Проверка файла тем же кодом, что у запуска, затем — вход в YouTube по нему."""
        status: CookiesStatus = self._check.status()
        status.log()
        login: str = CookiesLoginProbe(YtDlpLaunch.of(self.paths), self.run).login(status).window_line
        return CookiesVerdict(is_ok=status.is_ok, text=NEWLINE.join(status.window_lines), login=login)

    @property
    def _check(self) -> CookiesCheck:
        """Проверка cookies в поясе и со сроком напоминания настроек, как они сейчас на диске: срок меняют на этой же
        вкладке."""
        settings: LivecraftSettings = SettingsFile.of(self.paths).latest
        return CookiesCheck.of(self.paths, Clock(settings.zone), settings.cookies.remind_days)
