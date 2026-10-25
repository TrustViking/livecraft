"""Свежий tools\\yt-dlp.exe и всё, что ему нужно перед чтением видео (CLAUDE.md §2: `runtime\\ytdlp_updater.py`
restreamer).

Устаревший yt-dlp через несколько недель перестаёт читать YouTube, поэтому программа обновляет его сама: не чаще раза в
`YTDLP_CHECK_DAYS` суток (отметка `state\\ytdlp_last_check.json`) она говорит на консоль строку проверки и зовёт
`yt-dlp -U` — yt-dlp сам берёт последний выпуск с GitHub, сверяет его контрольную сумму и заменяет себя. Версия до и
после — по `--version`: стала другой — обновлён, та же — свежий. yt-dlp не справился (код не 0, таймаут, не запустился)
— работа на прежней версии, отметка не ставится: следующий запуск проверит снова. Файла нет — `yt-dlp -U` звать некому:
программа скачивает последний выпуск с GitHub сама (`YTDLP_RELEASE`, то же правило, что у deno, со строками хода
загрузки) — установщик бинарников не несёт (§14 решение 65); файл встаёт на место, только если назвал версию выпуска.
Не вышло — строка с причиной, отметки нет: следующий запуск попробует снова. Проверять рано — ни строк, ни запуска
бинарника.

`SourceTools` — то, что зовёт запуск (app\\main.py) в начале прогона таблицы плана, до источников, и в пробном запуске
тоже (бинарник — не «снаружи»): yt-dlp, затем его среда JavaScript deno (app\\runtime\\deno_updater.py), затем cookies
(app\\runtime\\cookies_updater.py — только сам файл, yt-dlp для этого не запускается; итог — только в лог). Строки хода
— сразу на консоль запуска (`say`), итог каждого бинарника — строкой лога сразу после него; строки итога для людей —
о бинарниках, после обоих.
Служебные режимы и эфиры из пакетов источников не читают — обновлений там нет. Окно настройки при открытии ставит
только недостающие бинарники (`install_missing`, §14 решение 74): нет файла — скачать, есть — не трогать (ни `-U`, ни
вопроса GitHub); обновлять их — дело запуска.
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.core.clock import Clock
from app.core.text_format import TEXT_ENCODING
from app.paths import FileName, LivecraftPaths
from app.runtime.cookies_updater import CookiesCheck, CookiesStatus
from app.runtime.deno_updater import CheckMark, DenoUpdater, ReleaseSource, ToolBinary, ToolStatus, ToolUpdate
from app.runtime.github_release import DownloadWatch, GitHubRelease, ToolProblem
from app.ui.console import EncodingErrors
from app.ui.messages import msg

YTDLP_CHECK_DAYS: Final[int] = 7            # как часто проверять новую версию yt-dlp, в сутках
YTDLP_VERSION_WORD: Final[int] = 0          # «2026.08.19» — номер первым словом
SELF_UPDATE_TIMEOUT_SEC: Final[float] = 30.0
YTDLP_RELEASE_URL: Final[str] = "https://api.github.com/repos/yt-dlp/yt-dlp/releases/latest"
YTDLP_DOWNLOAD_TEMPLATE: Final[str] = "https://github.com/yt-dlp/yt-dlp/releases/download/{version}/yt-dlp.exe"
YTDLP_RELEASE: Final[ReleaseSource] = ReleaseSource(YTDLP_RELEASE_URL, YTDLP_DOWNLOAD_TEMPLATE)


class YtDlpArg(str, Enum):
    """Ключ самообновления yt-dlp."""

    UPDATE = "-U"


@dataclass(frozen=True)
class YtDlpUpdater:
    """Обновление tools\\yt-dlp.exe: бинарник (его `run` запускает и `-U`), отметка проверки, строка хода на консоль
    (`say`) и GitHub — скачать недостающий файл."""

    binary: ToolBinary
    mark: CheckMark
    say: Callable[[str], None]
    github: GitHubRelease = field(default_factory=GitHubRelease)

    @classmethod
    def of(cls, paths: LivecraftPaths, clock: Clock, say: Callable[[str], None]) -> YtDlpUpdater:
        binary: ToolBinary = ToolBinary(paths.file(FileName.YTDLP), YTDLP_VERSION_WORD)
        return cls(binary, CheckMark(paths.file(FileName.YTDLP_CHECK), clock), say)

    @property
    def tool(self) -> str:
        return self.binary.path.stem

    @property
    def is_missing(self) -> bool:
        return not self.binary.path.is_file()

    def install_missing(self) -> ToolUpdate | None:
        """Только недостающий файл: нет — скачать последний выпуск; есть — ничего (ни `-U`, ни вопроса GitHub)."""
        return self._download() if self.is_missing else None

    def update(self) -> ToolUpdate:
        """Нет файла — скачать последний выпуск; рано — ничего, и бинарник не запускается (под нагрузкой один
        `--version` — до 10 с впустую); пора — версия до, строка проверки на консоль, `yt-dlp -U` (до
        `SELF_UPDATE_TIMEOUT_SEC`) и версия после."""
        if self.is_missing:
            return self._download()
        if not self.mark.is_due(YTDLP_CHECK_DAYS):
            return ToolUpdate(self.tool, ToolStatus.NOT_DUE, None)
        before: str | None = self.binary.version
        self.say(msg.PROGRESS_TOOL_SELF_UPDATE.format(tool=self.tool))
        failure: str | None = self._self_update()
        if failure is not None:
            return ToolUpdate.failed(self.tool, before, ToolProblem.SELF_UPDATE_FAILED, failure)
        self.mark.write()
        after: str | None = self.binary.version
        return ToolUpdate(self.tool, ToolStatus.FRESH if after == before else ToolStatus.UPDATED, before, after)

    def _download(self) -> ToolUpdate:
        """Недостающий файл: последний выпуск с GitHub на место рабочего (ход загрузки — строками на консоль) и
        отметка; не вышло — причина, отметки нет."""
        latest: str | ToolProblem = YTDLP_RELEASE.latest_version(self.github)
        if isinstance(latest, ToolProblem):
            return ToolUpdate.failed(self.tool, None, latest)
        watch: DownloadWatch = DownloadWatch(self.tool, latest, self.say)
        problem: ToolProblem | None = YTDLP_RELEASE.install(self.github, self.binary, latest, watch)
        if problem is not None:
            return ToolUpdate.failed(self.tool, None, problem, latest)
        self.mark.write()
        return ToolUpdate(self.tool, ToolStatus.UPDATED, None, after=latest)

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
        """Строки раздела «Запуск»: что обновлено или почему не проверено. О cookies запуск человеку не пишет — только
        в лог (`cookies_checked`): работа программы от входа в YouTube не зависит (§14 решение 80)."""
        return tuple(line for update in self.updates for line in update.console_lines)


@dataclass(frozen=True)
class SourceTools:
    """yt-dlp, его среда JavaScript deno и cookies — перед чтением видео таблицы плана."""

    ytdlp: YtDlpUpdater
    deno: DenoUpdater
    cookies: CookiesCheck

    @classmethod
    def of(
        cls, paths: LivecraftPaths, clock: Clock, say: Callable[[str], None], remind_days: int
    ) -> SourceTools:
        """Строки хода загрузок и самообновления — в `say` (консоль запуска или строка окна); `remind_days` — срок
        напоминания о cookies из настроек (`cookies.remind_days`)."""
        ytdlp: YtDlpUpdater = YtDlpUpdater.of(paths, clock, say)
        return cls(ytdlp, DenoUpdater.of(paths, clock, say), CookiesCheck.of(paths, clock, remind_days))

    @property
    def missing(self) -> tuple[str, ...]:
        """Имена бинарников, которых нет в tools\\, по порядку."""
        return tuple(updater.tool for updater in (self.ytdlp, self.deno) if updater.is_missing)

    def install_missing(self) -> tuple[ToolUpdate, ...]:
        """Поставить только недостающие yt-dlp и deno; итог каждого поставленного — строкой лога сразу после него.
        Оба на месте — ничего: ни `-U`, ни вопроса GitHub."""
        updates: list[ToolUpdate] = []
        for updater in (self.ytdlp, self.deno):
            update: ToolUpdate | None = updater.install_missing()
            if update is not None:
                update.log()
                updates.append(update)
        return tuple(updates)

    def refresh(self) -> SourceToolsCheck:
        """Обновить yt-dlp, затем deno, затем проверить cookies; итог каждого — строкой лога сразу после него: обрыв
        запуска посреди загрузки deno не теряет итога yt-dlp."""
        ytdlp: ToolUpdate = self.ytdlp.update()
        ytdlp.log()
        deno: ToolUpdate = self.deno.update()
        deno.log()
        cookies: CookiesStatus = self.cookies.status()
        cookies.log()
        return SourceToolsCheck((ytdlp, deno), cookies)
