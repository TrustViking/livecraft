"""Свежий tools\\yt-dlp.exe и всё, что ему нужно перед чтением видео (CLAUDE.md §2: `runtime\\ytdlp_updater.py`
restreamer).

Устаревший yt-dlp через несколько недель перестаёт читать YouTube, поэтому программа обновляет его сама: не чаще раза в
`YTDLP_CHECK_DAYS` суток (отметка `state\\ytdlp_last_check.json`) она зовёт `yt-dlp -U` — yt-dlp сам берёт последний
выпуск с GitHub, сверяет его контрольную сумму и заменяет себя. Версия до и после — по `--version`: стала другой —
обновлён, та же — свежий. yt-dlp не справился (код не 0, таймаут, не запустился) — работа на прежней версии, отметка не
ставится: следующий запуск проверит снова. Файла нет — сам себя он не скачает: строка с тем, что сделать.

`SourceTools` — то, что зовёт запуск (app\\main.py) в начале прогона таблицы плана, до источников, и в пробном запуске
тоже (бинарник — не «снаружи»): yt-dlp, затем его среда JavaScript deno (app\\runtime\\deno_updater.py), затем cookies
(app\\runtime\\cookies_updater.py — проверка входа идёт уже обновлённым yt-dlp). Служебные режимы, окно настройки и
эфиры из пакетов источников не читают — обновлений там нет.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.clock import Clock
from app.core.text_format import TEXT_ENCODING
from app.paths import FileName, LivecraftPaths
from app.runtime.cookies_updater import CookiesCheck, CookiesStatus
from app.runtime.deno_updater import CheckMark, DenoUpdater, ToolBinary, ToolProblem, ToolStatus, ToolUpdate
from app.ui.console import EncodingErrors

YTDLP_CHECK_DAYS: Final[int] = 7            # как часто проверять новую версию yt-dlp, в сутках
YTDLP_VERSION_WORD: Final[int] = 0          # «2026.08.19» — номер первым словом
SELF_UPDATE_TIMEOUT_SEC: Final[float] = 30.0


class YtDlpArg(str, Enum):
    """Ключ самообновления yt-dlp."""

    UPDATE = "-U"


@dataclass(frozen=True)
class YtDlpUpdater:
    """Обновление tools\\yt-dlp.exe: бинарник (его `run` запускает и `-U`) и отметка проверки."""

    binary: ToolBinary
    mark: CheckMark

    @classmethod
    def of(cls, paths: LivecraftPaths, clock: Clock) -> YtDlpUpdater:
        binary: ToolBinary = ToolBinary(paths.file(FileName.YTDLP), YTDLP_VERSION_WORD)
        return cls(binary, CheckMark(paths.file(FileName.YTDLP_CHECK), clock))

    @property
    def tool(self) -> str:
        return self.binary.path.stem

    def update(self) -> ToolUpdate:
        """Нет файла — строка; рано — ничего, и бинарник не запускается (под нагрузкой один `--version` — до 10 с
        впустую); пора — версия до, `yt-dlp -U` и версия после."""
        if not self.binary.path.is_file():
            return ToolUpdate(self.tool, ToolStatus.MISSING, None)
        if not self.mark.is_due(YTDLP_CHECK_DAYS):
            return ToolUpdate(self.tool, ToolStatus.NOT_DUE, None)
        before: str | None = self.binary.version
        failure: str | None = self._self_update()
        if failure is not None:
            return ToolUpdate.failed(self.tool, before, ToolProblem.SELF_UPDATE_FAILED, failure)
        self.mark.write()
        after: str | None = self.binary.version
        return ToolUpdate(self.tool, ToolStatus.FRESH if after == before else ToolStatus.UPDATED, before, after)

    def _self_update(self) -> str | None:
        """`yt-dlp -U`; справился — None, иначе подробность для лога: последняя строка его вывода или имя сбоя."""
        command: list[str] = [str(self.binary.path), YtDlpArg.UPDATE.value]
        try:
            answer: subprocess.CompletedProcess[str] = self.binary.run(
                command, capture_output=True, check=False, timeout=SELF_UPDATE_TIMEOUT_SEC,
                encoding=TEXT_ENCODING, errors=EncodingErrors.REPLACE.value,
            )
        except (OSError, subprocess.SubprocessError) as error:
            return type(error).__name__
        if answer.returncode == 0:
            return None
        said: list[str] = (answer.stderr or answer.stdout or "").strip().splitlines()
        return said[-1] if said else str(answer.returncode)


@dataclass(frozen=True)
class SourceToolsCheck:
    """Итог подготовки yt-dlp к чтению видео: проверки бинарников по порядку и cookies."""

    updates: tuple[ToolUpdate, ...]
    cookies: CookiesStatus

    @property
    def console_lines(self) -> tuple[str, ...]:
        """Строки раздела «Запуск»: что обновлено или почему не проверено, затем что с cookies."""
        return (*(line for update in self.updates for line in update.console_lines), *self.cookies.console_lines)

    @property
    def stops(self) -> bool:
        """Файл cookies не того вида: прогон таблицы не идёт (ошибка настройки)."""
        return self.cookies.stops


@dataclass(frozen=True)
class SourceTools:
    """yt-dlp, его среда JavaScript deno и cookies — перед чтением видео таблицы плана."""

    ytdlp: YtDlpUpdater
    deno: DenoUpdater
    cookies: CookiesCheck

    @classmethod
    def of(cls, paths: LivecraftPaths, clock: Clock) -> SourceTools:
        return cls(YtDlpUpdater.of(paths, clock), DenoUpdater.of(paths, clock), CookiesCheck.of(paths, clock))

    def refresh(self) -> SourceToolsCheck:
        """Обновить yt-dlp и deno, затем проверить cookies; каждый итог — строкой лога."""
        updates: tuple[ToolUpdate, ...] = (self.ytdlp.update(), self.deno.update())
        cookies: CookiesStatus = self.cookies.status()
        for update in updates:
            update.log()
        cookies.log()
        return SourceToolsCheck(updates, cookies)
