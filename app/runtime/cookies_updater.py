"""Проверка файла cookies YouTube перед чтением видео (CLAUDE.md §2: `runtime\\cookies_updater.py` restreamer).

secrets\\cookies.txt — по желанию: без него yt-dlp читает открытые видео, с ним — и те, что YouTube показывает только
вошедшему. Проверка по порядку:

- файла нет — строка лога, человеку ничего: cookies не обязательны;
- первая непустая строка — не заголовок Netscape — yt-dlp не примет файл и не прочитает ни одного видео: строка с тем,
  как выгрузить cookies заново, и прогон таблицы не идёт (`stops`, код 2 — ошибка настройки);
- дата выгрузки — время последней записи файла (программа его не пишет: yt-dlp получает копию); старше
  `COOKIES_WARN_DAYS` суток — строка с тем, как выгрузить заново;
- вход: yt-dlp с копией cookies открывает ленту истории, которую YouTube показывает только вошедшему
  (`:ythistory`). Признак «cookies больше не действуют» или «нужен вход» — при любом коде выхода: yt-dlp, который
  предупредил, что cookies не действуют, и отработал, дальше работает без входа — строка с тем, как выгрузить заново;
  прочее (нет сети, таймаут) — только лог: читать видео это не мешает. Вход проверяется не в каждом запуске (под
  нагрузкой одна проба — до 30 с впустую): только когда нет отметки удачной проверки (`state\\cookies_last_check.json`),
  ей не меньше `COOKIES_PROBE_DAYS` суток или cookies выгружены после неё. Отметку ставит только удачный вход: отказ и
  неясный итог проверяются и в следующем запуске.
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
from app.core.errors import DETAIL_MAX_CHARS
from app.core.text_format import TEXT_ENCODING
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import FileName, LivecraftPaths
from app.runtime.deno_updater import CheckMark
from app.runtime.ytdlp_launch import LaunchEvent, YtDlpLaunch
from app.ui.console import EncodingErrors
from app.ui.messages import msg

LOGGER = get_logger(LogArea.RUNTIME)

COOKIES_WARN_DAYS: Final[int] = 15          # срок cookies от даты выгрузки, в сутках
COOKIES_PROBE_DAYS: Final[int] = 1          # как часто проверять вход по тем же cookies, в сутках
NETSCAPE_HEADER: Final[str] = "# Netscape HTTP Cookie File"
BOM_TOLERANT_ENCODING: Final[str] = "utf-8-sig"     # файл, выгруженный с BOM, — тоже Netscape
LOGIN_PROBE_URL: Final[str] = ":ythistory"   # лента истории открывается только вошедшему
LOGIN_PROBE_TIMEOUT_SEC: Final[float] = 30.0
# Признаки в stderr yt-dlp (сравнение без регистра): cookies не действуют; входа нет.
INVALID_COOKIES_MARKER: Final[str] = "cookies are no longer valid"
LOGIN_REQUIRED_MARKER: Final[str] = "login details are needed"


class CookiesState(str, Enum):
    """Файл cookies. Значение — идентификатор для лога."""

    ABSENT = "absent"            # файла нет: cookies не обязательны
    BAD_FORMAT = "bad_format"    # не Netscape: yt-dlp его не примет
    READY = "ready"


class CookiesLogin(str, Enum):
    """Вход yt-dlp в YouTube по cookies. Значение — идентификатор для лога и ключ `msg.COOKIES_LOGIN_FAILURES`."""

    LOGGED_IN = "logged_in"          # лента вошедшего открылась
    INVALID = "invalid"              # cookies входа есть, но YouTube их больше не принимает
    NO_AUTH = "no_auth"              # в файле нет cookies входа
    UNKNOWN = "unknown"              # проверка не удалась: сеть, таймаут, yt-dlp упал
    NOT_CHECKED = "not_checked"      # проверять нечем, нечего или рано: нет файла, не тот вид, нет yt-dlp, свежая отметка

    @property
    def is_failed(self) -> bool:
        return self in (CookiesLogin.INVALID, CookiesLogin.NO_AUTH)


class CookiesEvent(str, Enum):
    """События проверки cookies в логе."""

    CHECKED = "cookies_checked"
    PROBED = "cookies_login_probe"


class ProbeArg(str, Enum):
    """Ключи вызова yt-dlp для проверки входа: первая запись ленты, только её id."""

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
# Признаки в stderr по порядку: первый найденный решает, что с входом.
LOGIN_MARKERS: Final[tuple[tuple[str, CookiesLogin], ...]] = (
    (INVALID_COOKIES_MARKER, CookiesLogin.INVALID),
    (LOGIN_REQUIRED_MARKER, CookiesLogin.NO_AUTH),
)


@dataclass(frozen=True)
class LoginProbe:
    """Итог проверки входа: что с входом, строка-пояснение и код выхода yt-dlp — для лога."""

    login: CookiesLogin
    detail: str = ""
    exit_code: int | None = None

    @classmethod
    def of(cls, returncode: int, stderr: str) -> LoginProbe:
        """Признак в stderr решает при любом коде выхода: с кодом 0 и предупреждением «cookies больше не действуют»
        yt-dlp отработал уже без входа (прогон 30-09-2026). Без признака: код 0 — вошёл, иначе — неясно."""
        lines: list[str] = [line.strip() for line in stderr.splitlines() if line.strip()]
        for marker, login in LOGIN_MARKERS:
            found: str | None = next((line for line in lines if marker in line.lower()), None)
            if found is not None:
                return cls(login, found[:DETAIL_MAX_CHARS], returncode)
        if returncode == 0:
            return cls(CookiesLogin.LOGGED_IN, exit_code=returncode)
        return cls(CookiesLogin.UNKNOWN, lines[0][:DETAIL_MAX_CHARS] if lines else "", returncode)


@dataclass(frozen=True)
class CookiesStatus:
    """Итог проверки cookies: путь для людей, файл, дата выгрузки и возраст в сутках, вход."""

    shown: str
    state: CookiesState
    exported: datetime | None = None
    age_days: int = 0
    probe: LoginProbe = LoginProbe(CookiesLogin.NOT_CHECKED)

    @property
    def stops(self) -> bool:
        """Файл не того вида: yt-dlp не прочитал бы ни одного видео — прогон таблицы не идёт."""
        return self.state is CookiesState.BAD_FORMAT

    @property
    def is_stale(self) -> bool:
        return self.exported is not None and self.age_days > COOKIES_WARN_DAYS

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Строки человеку — только когда нужно выгрузить cookies заново: что не так, затем как выгрузить."""
        lines: list[str] = []
        if self.stops:
            lines.append(msg.COOKIES_BAD_FORMAT.format(path=self.shown, header=NETSCAPE_HEADER))
        if self.probe.login.is_failed:
            lines.append(msg.COOKIES_LOGIN_FAILED.format(reason=msg.COOKIES_LOGIN_FAILURES[self.probe.login.value]))
        if self.is_stale and self.exported is not None:
            exported: str = format_human_date(self.exported)
            lines.append(msg.COOKIES_STALE.format(date=exported, days=self.age_days, limit=COOKIES_WARN_DAYS))
        if lines:
            lines.append(msg.COOKIES_REEXPORT.format(path=self.shown))
        return tuple(lines)

    def log(self) -> None:
        """Строка лога — всегда; то, что требует человека, — предупреждением."""
        level: int = logging.WARNING if self.console_lines else logging.INFO
        exported: str | None = self.exported.isoformat() if self.exported is not None else None
        event: LogEvent = LogEvent.of(CookiesEvent.CHECKED, state=self.state, exported=exported, age_days=self.age_days)
        event.extended(limit_days=COOKIES_WARN_DAYS, login=self.probe.login, detail=self.probe.detail).emit(LOGGER, level)


@dataclass(frozen=True)
class CookiesCheck:
    """Проверка cookies: запуск yt-dlp (`launch` — его cookies и есть проверяемый файл), часы программы, путь файла для
    людей, отметка последнего удачного входа (`mark`) и запуск процесса (`run` — `subprocess.run` или подделка в
    тестах)."""

    launch: YtDlpLaunch
    clock: Clock
    shown: str
    mark: CheckMark
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run

    @classmethod
    def of(cls, paths: LivecraftPaths, clock: Clock) -> CookiesCheck:
        launch: YtDlpLaunch = YtDlpLaunch.of(paths)
        mark: CheckMark = CheckMark(paths.file(FileName.COOKIES_CHECK), clock)
        return cls(launch, clock, paths.shown(launch.cookies), mark)

    def status(self) -> CookiesStatus:
        """Нет файла, не тот вид или годный — с датой выгрузки, возрастом и проверкой входа."""
        cookies: Path = self.launch.cookies
        if not cookies.is_file():
            return CookiesStatus(self.shown, CookiesState.ABSENT)
        if not self._is_netscape():
            return CookiesStatus(self.shown, CookiesState.BAD_FORMAT)
        exported: datetime = datetime.fromtimestamp(cookies.stat().st_mtime, self.clock.zone)
        age_days: int = max(0, (self.clock.now() - exported) // timedelta(days=1))
        return CookiesStatus(self.shown, CookiesState.READY, exported, age_days, self._login(exported))

    def is_probe_due(self, exported: datetime) -> bool:
        """Пора ли проверять вход: удачной проверки не было, ей не меньше `COOKIES_PROBE_DAYS` суток или cookies
        выгружены после неё."""
        return self.mark.is_due(COOKIES_PROBE_DAYS) or self.mark.is_before(exported)

    def _login(self, exported: datetime) -> LoginProbe:
        """Вход — когда пора; удачный вход ставит отметку, отказ и неясный итог — нет: их проверит следующий запуск."""
        if not self.is_probe_due(exported):
            return LoginProbe(CookiesLogin.NOT_CHECKED)
        probe: LoginProbe = self._probe()
        if probe.login is CookiesLogin.LOGGED_IN:
            self.mark.write()
        return probe

    def _is_netscape(self) -> bool:
        """Первая непустая строка — заголовок Netscape (BOM в начале не мешает)."""
        raw: bytes = self.launch.cookies.read_bytes()
        text: str = raw.decode(BOM_TOLERANT_ENCODING, errors=EncodingErrors.REPLACE.value)
        first: str = next((line.strip() for line in text.splitlines() if line.strip()), "")
        return first.startswith(NETSCAPE_HEADER)

    def _probe(self) -> LoginProbe:
        """yt-dlp с копией cookies (свой cookie jar он пишет обратно в файл) открывает ленту вошедшего; копия — в
        secrets\\, удаляется при любом исходе (`YtDlpLaunch.cookies_copy`). Сама лента в лог не идёт."""
        if not self.launch.exe.is_file():
            return LoginProbe(CookiesLogin.NOT_CHECKED)
        with self.launch.cookies_copy() as copy:
            probe: LoginProbe = self._answer(copy)
        probed: LogEvent = LogEvent.of(CookiesEvent.PROBED, login=probe.login, exit_code=probe.exit_code)
        probed.extended(detail=probe.detail).emit(LOGGER, logging.DEBUG)
        return probe

    def _answer(self, copy: Path | None) -> LoginProbe:
        """Ответ yt-dlp на ленту вошедшего с копией cookies `copy`. Копия не сделалась, yt-dlp не запустился или не
        уложился — итог неясен: отметки нет, следующий запуск проверит снова."""
        if copy is None:
            return LoginProbe(CookiesLogin.UNKNOWN, LaunchEvent.COOKIES_COPY_FAILED.value)
        command: list[str] = self.launch.command((ProbeArg.COOKIES.value, str(copy), *PROBE_ARGS))
        try:
            answer: subprocess.CompletedProcess[str] = self.run(
                command, capture_output=True, check=False, timeout=LOGIN_PROBE_TIMEOUT_SEC,
                encoding=TEXT_ENCODING, errors=EncodingErrors.REPLACE.value, env=self.launch.env,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return LoginProbe(CookiesLogin.UNKNOWN, type(error).__name__)
        return LoginProbe.of(answer.returncode, answer.stderr or "")
