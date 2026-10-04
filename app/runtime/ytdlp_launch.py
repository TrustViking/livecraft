"""Запуск yt-dlp с данными пользователя (CLAUDE.md §14 решение 56): всё, что пишут yt-dlp и deno, остаётся в папке
программы — удаление программы уносит это вместе с ней.

- кэш yt-dlp — `--cache-dir state\\yt-dlp-cache` (без ключа yt-dlp пишет в %USERPROFILE%\\.cache\\yt-dlp);
- кэш deno, которого yt-dlp зовёт решать задачи страницы YouTube, — `DENO_DIR=state\\deno-cache` (без него deno пишет
  в %LOCALAPPDATA%\\deno);
- cookies — копией на один вызов в secrets\\: yt-dlp пишет свой cookie jar обратно в файл `--cookies`, а оригинал
  трогать нельзя — время его записи и есть дата выгрузки cookies. Копия удаляется при любом исходе; копия в %TEMP%
  после прерванного запуска осталась бы вне папки программы.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import FileName, LivecraftPaths

LOGGER = get_logger(LogArea.RUNTIME)

CACHE_DIR_ARG: Final[str] = "--cache-dir"
DENO_DIR_ENV: Final[str] = "DENO_DIR"
COOKIES_COPY_PREFIX: Final[str] = "livecraft_cookies_"
COOKIES_COPY_SUFFIX: Final[str] = ".txt"


class LaunchEvent(str, Enum):
    """События запуска yt-dlp в логе."""

    COOKIES_COPY_FAILED = "ytdlp_cookies_copy_failed"


@dataclass(frozen=True)
class YtDlpLaunch:
    """Как запускать yt-dlp: exe, cookies пользователя, папки кэша yt-dlp и deno в state\\. Единственное правило
    запуска yt-dlp с данными пользователя — его берут чтение видео и проверка входа по cookies."""

    exe: Path
    cookies: Path
    cache_dir: Path
    deno_dir: Path

    @classmethod
    def of(cls, paths: LivecraftPaths) -> YtDlpLaunch:
        return cls(
            exe=paths.file(FileName.YTDLP),
            cookies=paths.file(FileName.COOKIES),
            cache_dir=paths.file(FileName.YTDLP_CACHE),
            deno_dir=paths.file(FileName.DENO_CACHE),
        )

    def command(self, args: Sequence[str]) -> list[str]:
        """Команда вызова: exe, папка кэша, затем ключи вызова."""
        return [str(self.exe), CACHE_DIR_ARG, str(self.cache_dir), *args]

    @property
    def env(self) -> dict[str, str]:
        """Окружение процесса и папка кэша deno."""
        return {**os.environ, DENO_DIR_ENV: str(self.deno_dir)}

    @contextmanager
    def cookies_copy(self) -> Iterator[Path | None]:
        """Копия cookies на один вызов; удаляется при любом исходе. Нет cookies или копия не сделалась (нет места,
        файл не читается) — None: вызов идёт без cookies, причина — в лог."""
        copy: Path | None = self._copy() if self.cookies.is_file() else None
        try:
            yield copy
        finally:
            if copy is not None:
                copy.unlink(missing_ok=True)

    def _copy(self) -> Path | None:
        """Копия cookies рядом с ними, в secrets\\; не вышло — None, недоделанная копия удалена."""
        copy: Path | None = None
        try:
            folder: Path = self.cookies.parent
            handle, name = tempfile.mkstemp(prefix=COOKIES_COPY_PREFIX, suffix=COOKIES_COPY_SUFFIX, dir=folder)
            os.close(handle)
            copy = Path(name)
            shutil.copyfile(self.cookies, copy)
        except OSError as error:
            LogEvent.of(LaunchEvent.COOKIES_COPY_FAILED, error=type(error).__name__).emit(LOGGER, logging.WARNING)
            if copy is not None:
                copy.unlink(missing_ok=True)
            return None
        return copy
