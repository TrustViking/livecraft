"""Корень livecraft и его папки (CLAUDE.md §5): рядом с exe (frozen) или корень репо (dev).

Одна папка данных на роль (§6, инвариант 10): secrets\\ — всё секретное и все конфиги,
image\\ — превью, bcast\\ — пакеты plan_*.bcast, keystreams\\ — ключи потоков, state\\ — замок и служебные отметки,
logs\\ — лог и отчёт, tools\\ — внешние бинарники. Всё остальное — в app\\.
Ставить программу в папку с правом записи (D:\\_exe\\Livecraft), не в Program Files.
"""
from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final

ROOT_ENV_VAR: Final[str] = "LIVECRAFT_ROOT"  # подмена корня — только для тестов и отладки
TEMP_FILE_SUFFIX: Final[str] = ".tmp"


def resolve_root() -> Path:
    """LIVECRAFT_ROOT, если задан; иначе папка exe (frozen) или корень репо (родитель app\\)."""
    override: str = os.environ.get(ROOT_ENV_VAR, "").strip()
    if override:
        return Path(override).resolve()
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class LivecraftPaths:
    """Где что лежит — знает только этот объект; модули получают готовый путь полем, а не собирают его сами."""

    root: Path
    secrets_dir: Path              # secrets\ — всё секретное и все конфиги (§6, инвариант 10)
    config_file: Path              # secrets\livecraft.json — технические настройки, поставляются со сборкой (§5)
    channels_file: Path            # secrets\channels.json — каналы владельца (§5)
    channels_previous_file: Path   # secrets\channels.previous.json — channels.json до выравнивания
    channels_passport_file: Path   # secrets\channels_passport.json — ник ↔ id YouTube ↔ файл токена (§6, инвариант 5)
    client_secret_file: Path       # secrets\client_secret.json — паспорт программы, OAuth-клиент Desktop (§9)
    sheets_token_file: Path        # secrets\sheets.token.json — токен оператора на чтение плана (§9)
    cookies_file: Path             # secrets\cookies.txt — cookies для yt-dlp
    records_file: Path             # secrets\livecraft.sqlite3 — память: что сделано на YouTube и что подтвердила форма
    vault_file: Path               # secrets\vault.dat — поставочный сейф, программный ключ (§7.3)
    vault_local_file: Path         # secrets\vault.local.dat — личный сейф пользователя, DPAPI (§7.3)
    program_key_file: Path         # secrets\program.key — ключ поставочного сейфа в dev-режиме (§7.3)
    tools_dir: Path                # tools\ — внешние бинарники, обновляются сами
    ytdlp_exe: Path                # tools\yt-dlp.exe — метаданные и превью источников
    deno_exe: Path                 # tools\deno.exe — нужен yt-dlp для части извлекателей
    image_dir: Path                # image\ — превью по шаблону {date}\{language}
    bcast_dir: Path                # bcast\ — пакеты plan_*.bcast: пишет режим А, читает режим Б (§14 решения 13, 18)
    keystreams_dir: Path           # keystreams\ — ключи потоков для ручной передачи
    keys_file: Path                # keystreams\keys.txt
    state_dir: Path                # state\ — замок одного экземпляра и отметки автообновлений
    lock_file: Path                # state\livecraft.lock (§6, инвариант 12)
    logs_dir: Path                 # logs\ — лог запуска и отчёт
    startup_log_file: Path         # logs\startup.log — захват и освобождение замка, до настройки логов (§6, инвариант 12)

    @property
    def directories(self) -> tuple[Path, ...]:
        """Папки, которые создаёт ensure_dirs; файлы в них программа сама не создаёт."""
        return (
            self.secrets_dir,
            self.tools_dir,
            self.image_dir,
            self.bcast_dir,
            self.keystreams_dir,
            self.state_dir,
            self.logs_dir,
        )


def build_paths(root: Path) -> LivecraftPaths:
    secrets_dir: Path = root / "secrets"
    tools_dir: Path = root / "tools"
    keystreams_dir: Path = root / "keystreams"
    state_dir: Path = root / "state"
    logs_dir: Path = root / "logs"
    return LivecraftPaths(
        root=root,
        secrets_dir=secrets_dir,
        config_file=secrets_dir / "livecraft.json",
        channels_file=secrets_dir / "channels.json",
        channels_previous_file=secrets_dir / "channels.previous.json",
        channels_passport_file=secrets_dir / "channels_passport.json",
        client_secret_file=secrets_dir / "client_secret.json",
        sheets_token_file=secrets_dir / "sheets.token.json",
        cookies_file=secrets_dir / "cookies.txt",
        records_file=secrets_dir / "livecraft.sqlite3",
        vault_file=secrets_dir / "vault.dat",
        vault_local_file=secrets_dir / "vault.local.dat",
        program_key_file=secrets_dir / "program.key",
        tools_dir=tools_dir,
        ytdlp_exe=tools_dir / "yt-dlp.exe",
        deno_exe=tools_dir / "deno.exe",
        image_dir=root / "image",
        bcast_dir=root / "bcast",
        keystreams_dir=keystreams_dir,
        keys_file=keystreams_dir / "keys.txt",
        state_dir=state_dir,
        lock_file=state_dir / "livecraft.lock",
        logs_dir=logs_dir,
        startup_log_file=logs_dir / "startup.log",
    )


def ensure_dirs(paths: LivecraftPaths) -> None:
    """Только папки: конфиги и сейф в secrets\\ программа не создаёт — их пишет настройщик (§8)."""
    for directory in paths.directories:
        directory.mkdir(parents=True, exist_ok=True)


def write_text_atomically(path: Path, text: str, encoding: str) -> None:
    """Временный файл рядом + os.replace: читатель видит либо прежний файл, либо новый целиком. Сбой — OSError."""
    handle, temp_name = tempfile.mkstemp(prefix=path.name, suffix=TEMP_FILE_SUFFIX, dir=path.parent)
    temp_path: Path = Path(temp_name)
    try:
        with os.fdopen(handle, "w", encoding=encoding, newline="") as stream:
            stream.write(text)
        os.replace(temp_path, path)
    except OSError:
        temp_path.unlink(missing_ok=True)
        raise
