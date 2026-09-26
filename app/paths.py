"""Корень livecraft и его папки (CLAUDE.md §5): рядом с exe (frozen) или корень репо (dev).

Одна папка данных на роль (§6, инвариант 10) — `DataDir`: secrets\\ — всё секретное и все конфиги,
image\\ — превью, bcast\\ — пакеты plan_*.bcast, keystreams\\ — ключи потоков, state\\ — замок и служебные отметки,
logs\\ — лог и отчёт, tools\\ — внешние бинарники. Всё остальное — в app\\.
Ставить программу в папку с правом записи (D:\\_exe\\Livecraft), не в Program Files.
"""
from __future__ import annotations

import os
import sys
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

ROOT_ENV_VAR: Final[str] = "LIVECRAFT_ROOT"  # подмена корня — только для тестов и отладки
TEMP_FILE_SUFFIX: Final[str] = ".tmp"


class ProcessAttr(str, Enum):
    """Признаки процесса в модуле sys, по которым видно, как запущена программа."""

    FROZEN = "frozen"      # PyInstaller ставит sys.frozen в собранном exe


class DataDir(str, Enum):
    """Папки данных в корне (§6, инвариант 10). Значение — имя папки."""

    SECRETS = "secrets"          # всё секретное и все конфиги
    TOOLS = "tools"              # внешние бинарники, обновляются сами
    IMAGE = "image"              # превью по шаблону {date}\{language}
    BCAST = "bcast"              # пакеты plan_*.bcast: пишет режим А, читает режим Б (§14 решения 13, 18)
    KEYSTREAMS = "keystreams"    # ключи потоков для ручной передачи
    STATE = "state"              # замок одного экземпляра и отметки автообновлений
    LOGS = "logs"                # лог запуска и отчёт


class FileName(str, Enum):
    """Имена файлов в папках данных, которые читает программа."""

    CONFIG = "livecraft.json"
    CHANNELS = "channels.json"
    CHANNELS_PREVIOUS = "channels.previous.json"
    CLIENT_SECRET = "client_secret.json"
    SHEETS_TOKEN = "sheets.token.json"
    COOKIES = "cookies.txt"
    VAULT = "vault.dat"
    VAULT_LOCAL = "vault.local.dat"
    PROGRAM_KEY = "program.key"
    YTDLP = "yt-dlp.exe"
    DENO = "deno.exe"
    LOCK = "livecraft.lock"
    STARTUP_LOG = "startup.log"


@dataclass(frozen=True)
class LivecraftPaths:
    """Где что лежит — знает только этот объект; модули получают готовый путь, а не собирают его сами."""

    root: Path

    @classmethod
    def locate(cls) -> LivecraftPaths:
        """LIVECRAFT_ROOT, если задан; иначе папка exe (frozen) или корень репо (родитель app\\)."""
        override: str = os.environ.get(ROOT_ENV_VAR, "").strip()
        if override:
            return cls(Path(override).resolve())
        if getattr(sys, ProcessAttr.FROZEN.value, False):
            return cls(Path(sys.executable).resolve().parent)
        return cls(Path(__file__).resolve().parents[1])

    def dir(self, folder: DataDir) -> Path:
        return self.root / folder.value

    def ensure_dirs(self) -> None:
        """Все папки данных; файлы в них программа сама не создаёт: конфиги и сейф пишет настройщик (§8)."""
        for folder in DataDir:
            self.dir(folder).mkdir(parents=True, exist_ok=True)

    @property
    def config_file(self) -> Path:
        """secrets\\livecraft.json — технические настройки (§5)."""
        return self.dir(DataDir.SECRETS) / FileName.CONFIG.value

    @property
    def channels_file(self) -> Path:
        """secrets\\channels.json — каналы владельца (§5)."""
        return self.dir(DataDir.SECRETS) / FileName.CHANNELS.value

    @property
    def channels_previous_file(self) -> Path:
        """secrets\\channels.previous.json — channels.json до последней записи."""
        return self.dir(DataDir.SECRETS) / FileName.CHANNELS_PREVIOUS.value

    @property
    def client_secret_file(self) -> Path:
        """secrets\\client_secret.json — паспорт программы, OAuth-клиент Desktop (§9)."""
        return self.dir(DataDir.SECRETS) / FileName.CLIENT_SECRET.value

    @property
    def sheets_token_file(self) -> Path:
        """secrets\\sheets.token.json — токен оператора на чтение плана (§9)."""
        return self.dir(DataDir.SECRETS) / FileName.SHEETS_TOKEN.value

    @property
    def cookies_file(self) -> Path:
        """secrets\\cookies.txt — cookies для yt-dlp."""
        return self.dir(DataDir.SECRETS) / FileName.COOKIES.value

    @property
    def vault_file(self) -> Path:
        """secrets\\vault.dat — поставочный сейф, программный ключ (§7.3)."""
        return self.dir(DataDir.SECRETS) / FileName.VAULT.value

    @property
    def vault_local_file(self) -> Path:
        """secrets\\vault.local.dat — личный сейф пользователя, DPAPI (§7.3)."""
        return self.dir(DataDir.SECRETS) / FileName.VAULT_LOCAL.value

    @property
    def program_key_file(self) -> Path:
        """secrets\\program.key — ключ поставочного сейфа в dev-режиме (§7.3)."""
        return self.dir(DataDir.SECRETS) / FileName.PROGRAM_KEY.value

    @property
    def ytdlp_exe(self) -> Path:
        """tools\\yt-dlp.exe — метаданные и превью источников."""
        return self.dir(DataDir.TOOLS) / FileName.YTDLP.value

    @property
    def deno_exe(self) -> Path:
        """tools\\deno.exe — нужен yt-dlp для части извлекателей."""
        return self.dir(DataDir.TOOLS) / FileName.DENO.value

    @property
    def lock_file(self) -> Path:
        """state\\livecraft.lock (§6, инвариант 12)."""
        return self.dir(DataDir.STATE) / FileName.LOCK.value

    @property
    def startup_log_file(self) -> Path:
        """logs\\startup.log — захват и освобождение замка, до настройки логов (§6, инвариант 12)."""
        return self.dir(DataDir.LOGS) / FileName.STARTUP_LOG.value

    @property
    def logs_dir(self) -> Path:
        return self.dir(DataDir.LOGS)

    @property
    def bcast_dir(self) -> Path:
        return self.dir(DataDir.BCAST)


@dataclass(frozen=True)
class AtomicFile:
    """Файл, который пишется целиком или никак: временный файл рядом с целью, затем `os.replace`.

    Читатель видит либо прежний файл, либо новый целиком — недописанного не бывает. `prefix` — начало имени
    временного файла: по нему недописанное легко отличить от готового. Сбой записи — OSError, временный
    файл при любом исходе убирается.
    """

    target: Path
    prefix: str

    @classmethod
    def at(cls, target: Path) -> AtomicFile:
        """Временный файл называется от имени цели."""
        return cls(target=target, prefix=target.name)

    def write(self, fill: Callable[[Path], None]) -> None:
        """`fill` пишет содержимое во временный файл; готовый файл встаёт на место цели одним `os.replace`."""
        handle, temp_name = tempfile.mkstemp(prefix=self.prefix, suffix=TEMP_FILE_SUFFIX, dir=self.target.parent)
        os.close(handle)
        temp_path: Path = Path(temp_name)
        try:
            fill(temp_path)
            os.replace(temp_path, self.target)
        finally:
            temp_path.unlink(missing_ok=True)       # после os.replace файла уже нет — ничего не делает

    def write_text(self, text: str, encoding: str) -> None:
        """Текст как есть: переводы строк не переводятся."""
        self.write(lambda path: path.write_text(text, encoding=encoding, newline=""))


def write_text_atomically(path: Path, text: str, encoding: str) -> None:
    """Текст файла целиком или никак (`AtomicFile`). Сбой — OSError."""
    AtomicFile.at(path).write_text(text, encoding)
