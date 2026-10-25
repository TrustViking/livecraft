"""Проверка файла cookies YouTube — перед чтением видео и на вкладке «Cookies YouTube» окна (CLAUDE.md §2:
`runtime\\cookies_updater.py` restreamer; §14 решения 54, 73).

secrets\\cookies.txt — по желанию: без него yt-dlp читает открытые видео, с ним — и те, что YouTube показывает только
вошедшему. Правила самого файла (вид, дата выгрузки, cookies входа и их срок) — у `CookiesFile`
(app\\runtime\\cookies_file.py). Проверка по порядку:

- файла нет — строка лога, человеку ничего: cookies не обязательны;
- не Netscape — yt-dlp файл не примет: вызовы идут без cookies (`YtDlpLaunch.cookies_copy`), запуск не стоит;
- в файле нет cookies входа или их срок прошёл — входа по ним не будет;
- дата выгрузки — время изменения файла; с неё прошло больше `remind_days` суток (`cookies.remind_days` настроек) —
  срок напоминания закончился: выгрузить заново.

Работа программы от входа в YouTube не зависит (§14 решение 80): запуск о cookies человеку не пишет — всё, что не так
с файлом, — строкой лога `cookies_checked` с предупреждением. Окно — строку на каждое правило, со знаком «✓» или «✗»
(`window_lines`). Строки не шире 90 знаков (§14 решение 63).

Вход в YouTube проверяет только кнопка «Проверить» вкладки «Cookies YouTube» (`CookiesLoginProbe`): yt-dlp с копией
cookies открывает ленту истории `:ythistory` — она открывается только вошедшему. Итог — вход есть, входа нет или
проверить не удалось; окно пишет его синим: на работу программы вход не влияет, без него недоступны только описания
видео 18+. Без годных cookies входа (файла нет, не тот вид, нет cookies входа, их срок прошёл) входа нет и без вопроса
YouTube.
"""
from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Final

from app.core.clock import Clock
from app.core.dates import format_human_date
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import FileName, LivecraftPaths
from app.runtime.cookies_file import NETSCAPE_HEADER, CookiesFile
from app.runtime.ytdlp_launch import YtDlpLaunch
from app.ui.console import EncodingErrors
from app.ui.messages import msg

LOGGER = get_logger(LogArea.RUNTIME)

LOGIN_PROBE_URL: Final[str] = ":ythistory"   # лента истории открывается только вошедшему
LOGIN_PROBE_TIMEOUT_SEC: Final[float] = 30.0
# Признаки в stderr yt-dlp (сравнение без регистра), что входа нет: cookies не действуют; нужен вход.
NO_LOGIN_MARKERS: Final[tuple[str, ...]] = ("cookies are no longer valid", "login details are needed")


class CookiesState(str, Enum):
    """Файл cookies. Значение — идентификатор для лога."""

    ABSENT = "absent"            # файла нет: cookies не обязательны
    BAD_FORMAT = "bad_format"    # не Netscape: yt-dlp его не примет
    NO_LOGIN = "no_login"        # в файле нет cookies входа в аккаунт YouTube
    EXPIRED = "expired"          # срок cookies входа прошёл
    READY = "ready"


class CookiesEvent(str, Enum):
    """События проверки cookies в логе."""

    CHECKED = "cookies_checked"
    PROBED = "cookies_login_probe"


class CookiesLogin(str, Enum):
    """Вход yt-dlp в YouTube по cookies. Значение — идентификатор для лога."""

    LOGGED_IN = "logged_in"      # лента вошедшего открылась
    NO_LOGIN = "no_login"        # годных cookies входа нет, или YouTube их не принял
    UNKNOWN = "unknown"          # проверить не удалось: нет yt-dlp или копии cookies, сеть, таймаут, сбой yt-dlp

    @classmethod
    def of_answer(cls, returncode: int, stderr: str) -> CookiesLogin:
        """Признак «входа нет» в stderr решает при любом коде выхода: с кодом 0 и предупреждением «cookies больше не
        действуют» yt-dlp отработал уже без входа (прогон 30-09-2026). Без признака: код 0 — вошёл, иначе — неясно."""
        folded: str = stderr.casefold()
        if any(marker in folded for marker in NO_LOGIN_MARKERS):
            return cls.NO_LOGIN
        return cls.LOGGED_IN if returncode == 0 else cls.UNKNOWN

    @property
    def window_line(self) -> str:
        """Строка окна: вход есть, входа нет или проверить не удалось — и что работе программы это не мешает."""
        if self is CookiesLogin.LOGGED_IN:
            return msg.COOKIES_WINDOW_LOGIN_YES
        return msg.COOKIES_WINDOW_LOGIN_NO if self is CookiesLogin.NO_LOGIN else msg.COOKIES_WINDOW_LOGIN_UNKNOWN


class ProbeArg(str, Enum):
    """Ключи вызова yt-dlp для проверки входа: cookies, первая запись ленты, только её id."""

    COOKIES = "--cookies"
    FLAT = "--flat-playlist"
    ITEMS = "--playlist-items"
    FIRST = "1"
    PRINT = "--print"
    ID = "id"


PROBE_ARGS: Final[tuple[str, ...]] = (
    ProbeArg.FLAT.value, ProbeArg.ITEMS.value, ProbeArg.FIRST.value, ProbeArg.PRINT.value, ProbeArg.ID.value,
    LOGIN_PROBE_URL,
)


@dataclass(frozen=True)
class CookiesStatus:
    """Итог проверки cookies: путь для людей, файл, срок напоминания в сутках, дата выгрузки и возраст в сутках и срок
    cookies входа (None — сеансовые или их нет)."""

    shown: str
    state: CookiesState
    remind_days: int
    exported: datetime | None = None
    age_days: int = 0
    login_expires: datetime | None = None

    @property
    def is_stale(self) -> bool:
        """Срок напоминания закончился: с выгрузки прошло больше `remind_days` суток."""
        return self.exported is not None and self.age_days > self.remind_days

    @property
    def is_ok(self) -> bool:
        """Всё годно: файл с действующими cookies входа, срок напоминания не закончился."""
        return self.state is CookiesState.READY and not self.is_stale

    @property
    def window_lines(self) -> tuple[str, ...]:
        """Строки окна по порядку правил: файл, вид, дата выгрузки, cookies входа — каждая со знаком; правило не
        выполнено и дальше проверять нечего — строки на нём кончаются."""
        if self.state is CookiesState.ABSENT:
            return (msg.CHECK_PROBLEM_LINE.format(line=msg.COOKIES_WINDOW_ABSENT.format(path=self.shown)),)
        lines: list[str] = [msg.CHECK_OK_LINE.format(line=msg.COOKIES_WINDOW_FILE.format(path=self.shown))]
        if self.exported is None:       # не тот вид: даты выгрузки и cookies входа у такого файла не смотрят
            bad_format: str = msg.COOKIES_WINDOW_BAD_FORMAT.format(header=NETSCAPE_HEADER)
            return (*lines, msg.CHECK_PROBLEM_LINE.format(line=bad_format))
        lines.append(msg.CHECK_OK_LINE.format(line=msg.COOKIES_WINDOW_NETSCAPE))
        lines.append(self._exported_line(self.exported))
        lines.append(self._login_cookies_line)
        return tuple(lines)

    def log(self) -> None:
        """Строка лога — всегда; файл есть, но что-то с ним не так (вид, cookies входа, срок напоминания), —
        предупреждением: человеку запуск о cookies не пишет."""
        level: int = logging.INFO if self.is_ok or self.state is CookiesState.ABSENT else logging.WARNING
        exported: str | None = self.exported.isoformat() if self.exported is not None else None
        expires: str | None = self.login_expires.isoformat() if self.login_expires is not None else None
        event: LogEvent = LogEvent.of(CookiesEvent.CHECKED, state=self.state, exported=exported, age_days=self.age_days)
        event.extended(limit_days=self.remind_days, stale=self.is_stale, login_expires=expires).emit(LOGGER, level)

    def _exported_line(self, exported: datetime) -> str:
        """Дата выгрузки `exported`, возраст и срок напоминания; срок закончился — «✗» и что делать."""
        date: str = format_human_date(exported)
        if self.is_stale:
            stale: str = msg.COOKIES_WINDOW_STALE.format(date=date, days=self.age_days, limit=self.remind_days)
            return msg.CHECK_PROBLEM_LINE.format(line=stale)
        text: str = msg.COOKIES_WINDOW_EXPORTED.format(date=date, days=self.age_days, limit=self.remind_days)
        return msg.CHECK_OK_LINE.format(line=text)

    @property
    def _login_cookies_line(self) -> str:
        """Cookies входа: нет, срок истёк или есть — до какого числа (сеансовые — до закрытия браузера)."""
        if self.state is CookiesState.NO_LOGIN:
            return msg.CHECK_PROBLEM_LINE.format(line=msg.COOKIES_WINDOW_NO_LOGIN)
        if self.login_expires is None:
            return msg.CHECK_OK_LINE.format(line=msg.COOKIES_WINDOW_LOGIN_SESSION)
        date: str = format_human_date(self.login_expires)
        if self.state is CookiesState.EXPIRED:
            return msg.CHECK_PROBLEM_LINE.format(line=msg.COOKIES_WINDOW_LOGIN_EXPIRED.format(date=date))
        return msg.CHECK_OK_LINE.format(line=msg.COOKIES_WINDOW_LOGIN_UNTIL.format(date=date))


@dataclass(frozen=True)
class CookiesCheck:
    """Проверка cookies — одна для окна и запуска: сам файл, часы программы, путь файла для людей и срок напоминания
    в сутках."""

    file: CookiesFile
    clock: Clock
    shown: str
    remind_days: int

    @classmethod
    def of(cls, paths: LivecraftPaths, clock: Clock, remind_days: int) -> CookiesCheck:
        """Проверка cookies установки `paths`; `remind_days` — срок напоминания из настроек (`cookies.remind_days`)."""
        file: CookiesFile = CookiesFile(paths.file(FileName.COOKIES), clock.zone)
        return cls(file, clock, paths.shown(file.path), remind_days)

    def status(self) -> CookiesStatus:
        """Нет файла, не тот вид, нет cookies входа, их срок прошёл или годный — с датой выгрузки, возрастом и сроком
        cookies входа. yt-dlp не запускается."""
        if not self.file.exists:
            return CookiesStatus(self.shown, CookiesState.ABSENT, self.remind_days)
        if not self.file.is_netscape:
            return CookiesStatus(self.shown, CookiesState.BAD_FORMAT, self.remind_days)
        exported: datetime = self.file.exported
        age_days: int = max(0, (self.clock.now() - exported) // timedelta(days=1))
        expires: datetime | None = self.file.login_expires
        return CookiesStatus(self.shown, self._state(expires), self.remind_days, exported, age_days, expires)

    def _state(self, expires: datetime | None) -> CookiesState:
        """Годный файл: есть ли cookies входа и не прошёл ли их срок (`expires` — самый поздний)."""
        if not self.file.login_cookies:
            return CookiesState.NO_LOGIN
        if expires is not None and expires < self.clock.now():
            return CookiesState.EXPIRED
        return CookiesState.READY


@dataclass(frozen=True)
class CookiesLoginProbe:
    """Проверка входа в YouTube по cookies — только по кнопке окна: как запускать yt-dlp (`launch`) и `run` —
    `subprocess.run` или подделка с той же сигнатурой (в тестах)."""

    launch: YtDlpLaunch
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run

    def login(self, status: CookiesStatus) -> CookiesLogin:
        """Вход по cookies `status`: годных cookies входа нет — входа нет без вопроса YouTube; нет yt-dlp — проверить не
        удалось; иначе — ответ YouTube на ленту вошедшего. Копия cookies — в secrets\\, удаляется при любом исходе."""
        if status.state is not CookiesState.READY:
            return CookiesLogin.NO_LOGIN
        if not self.launch.exe.is_file():
            return CookiesLogin.UNKNOWN
        with self.launch.cookies_copy() as copy:
            login: CookiesLogin = CookiesLogin.UNKNOWN if copy is None else self._answer(copy)
        LogEvent.of(CookiesEvent.PROBED, login=login).emit(LOGGER)
        return login

    def _answer(self, copy: Path) -> CookiesLogin:
        """Ответ yt-dlp на ленту вошедшего с копией cookies `copy`; yt-dlp не запустился или не уложился — неясно, имя
        сбоя — в лог. Сама лента в лог не идёт."""
        command: list[str] = self.launch.command((ProbeArg.COOKIES.value, str(copy), *PROBE_ARGS))
        try:
            answer: subprocess.CompletedProcess[str] = self.run(
                command, capture_output=True, check=False, timeout=LOGIN_PROBE_TIMEOUT_SEC,
                encoding=TEXT_ENCODING, errors=EncodingErrors.REPLACE.value, env=self.launch.env,
            )
        except (OSError, subprocess.SubprocessError) as error:
            LogEvent.of(CookiesEvent.PROBED, failed=type(error).__name__).emit(LOGGER, logging.WARNING)
            return CookiesLogin.UNKNOWN
        return CookiesLogin.of_answer(answer.returncode, answer.stderr or "")
