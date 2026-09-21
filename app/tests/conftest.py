"""Общие фикстуры: папки livecraft в tmp_path, фиксированное «сейчас», корень репо, сейф на диске,
готовый к запуску корень, живой и мёртвый посторонние процессы.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.paths import LivecraftPaths, build_paths, ensure_dirs
from app.secretsafe.crypto import FORMAT_VERSION, VAULT_KEY_BYTES, EncryptedField, VaultCrypto, VaultFile
from app.secretsafe.dpapi import Dpapi
from app.secretsafe.store import VAULT_FILE_ENCODING, ProgramKey, VaultStore
from app.secretsafe.value import SecretField

KYIV_WINTER: timezone = timezone(timedelta(hours=2))   # даты и время — по Киеву (CLAUDE.md §6, инвариант 4)
FIXED_NOW: datetime = datetime(2026, 9, 20, 12, 0, tzinfo=KYIV_WINTER)
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
REPO_SETTINGS_FILE: Path = REPO_ROOT / "secrets" / "livecraft.json"
REPO_CHANNELS_EXAMPLE: Path = REPO_ROOT / "app" / "examples" / "channels.example.json"
# Ключ поставочного сейфа во временном корне (secrets\program.key, §7.3) и то, что в поставку положила сборка.
PROGRAM_KEY_BYTES: bytes = bytes(range(VAULT_KEY_BYTES))
SUPPLIED_VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-supplied-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",
    SecretField.SHEETS_ID: "1supplied-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
    SecretField.SHEETS_RANGE: "A:F",
    SecretField.KEY_FORM_URL: "https://docs.google.com/forms/d/e/1FAIpQLSf-supplied/viewform",
}


def write_supplied_vault(paths: LivecraftPaths, values: dict[SecretField, str]) -> None:
    """Поставочный сейф так пишет сборка Артура: ключ снаружи (program.key), записи «key» в файле нет.

    Программа этот файл писать не умеет и не должна, поэтому в тестах он собирается прямо из VaultFile.
    """
    paths.program_key_file.write_bytes(PROGRAM_KEY_BYTES)
    salt: bytes = VaultFile.empty().salt
    crypto: VaultCrypto = VaultCrypto(key=PROGRAM_KEY_BYTES, salt=salt)
    fields: dict[str, EncryptedField] = {
        field.value: crypto.encrypt(field, value) for field, value in values.items()
    }
    paths.vault_file.write_text(
        VaultFile(version=FORMAT_VERSION, salt=salt, fields=fields).render(), encoding=VAULT_FILE_ENCODING
    )


@pytest.fixture
def livecraft_paths(tmp_path: Path) -> LivecraftPaths:
    """Корень запуска во временной папке: папки созданы, файлов в них нет — как после установки."""
    paths: LivecraftPaths = build_paths(tmp_path / "root")
    ensure_dirs(paths)
    return paths


@pytest.fixture
def now() -> datetime:
    """Фиксированный момент со смещением: часы в тестах не плывут (CLAUDE.md §11)."""
    return FIXED_NOW


@pytest.fixture
def repo_root() -> Path:
    """Корень репо: нужен тестам, которые читают файлы проекта (.gitattributes, livecraft.bat)."""
    return REPO_ROOT


@pytest.fixture
def vault_store(livecraft_paths: LivecraftPaths) -> VaultStore:
    """Сейф на временном корне, собранный боевым путём: оба файла из paths, свой ключ и DPAPI этой машины."""
    return VaultStore(
        supplied_path=livecraft_paths.vault_file,
        local_path=livecraft_paths.vault_local_file,
        program_key=ProgramKey.load(livecraft_paths.program_key_file),
        dpapi=Dpapi.load(),
    )


@pytest.fixture
def dead_pid() -> int:
    """Честный номер мёртвого процесса: запускаем python с пустой командой и дожидаемся его конца."""
    child: subprocess.Popen[bytes] = subprocess.Popen([sys.executable, "-c", ""])
    child.wait()
    return child.pid


@pytest.fixture
def live_foreign_process() -> Iterator[subprocess.Popen[bytes]]:
    """Живой посторонний процесс: его номером занимают замок в проверках «чужой владелец жив»."""
    child: subprocess.Popen[bytes] = subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(60)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        yield child
    finally:
        child.kill()
        child.wait()


@pytest.fixture
def ready_paths(livecraft_paths: LivecraftPaths) -> LivecraftPaths:
    """Корень, готовый к запуску: настройки из поставки репо, каналы из примера, поставочный сейф на все поля."""
    shutil.copyfile(REPO_SETTINGS_FILE, livecraft_paths.config_file)
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, livecraft_paths.channels_file)
    write_supplied_vault(livecraft_paths, SUPPLIED_VALUES)
    return livecraft_paths
