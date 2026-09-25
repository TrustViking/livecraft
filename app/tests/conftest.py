"""Общие фикстуры: папки livecraft в tmp_path, фиксированное «сейчас», корень репо, сейф на диске,
готовый к запуску корень, живой и мёртвый посторонние процессы, готовый источник и лог слотов.
"""
from __future__ import annotations

import atexit
import dataclasses
import logging
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx2
import openai
import pytest

from app.config.loader import (
    LivecraftSettings,
    LlmSettings,
    ReasoningEffort,
    ServiceTier,
    ShippedSettings,
    load_settings,
    save_settings_file,
)
from app.paths import LivecraftPaths, build_paths, ensure_dirs
from app.secretsafe.crypto import FORMAT_VERSION, VAULT_KEY_BYTES, EncryptedField, VaultCrypto, VaultFile
from app.secretsafe.dpapi import Dpapi
from app.secretsafe.store import VAULT_FILE_ENCODING, ProgramKey, VaultStore
from app.secretsafe.value import SecretField
from app.sheets.rows import PlanRow
from app.sources.language import LanguageProfile
from app.sources.metadata import SourceMetadata
from app.sources.preview import Preview
from app.sources.video import SourceVideo
from app.ui import messages_ru as msg

KYIV_WINTER: timezone = timezone(timedelta(hours=2))   # даты и время — по Киеву (CLAUDE.md §6, инвариант 4)
FIXED_NOW: datetime = datetime(2026, 9, 20, 12, 0, tzinfo=KYIV_WINTER)
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SHIPPED_SETTINGS: ShippedSettings = ShippedSettings(template=msg.CONFIG_SETTINGS_TEMPLATE)


def _shipped_settings_file() -> Path:
    """Поставочный livecraft.json, собранный боевым путём (ShippedSettings.install) во временной папке сессии.

    В git файла нет (§5), а secrets\\livecraft.json разработчика — его личные настройки: тесты на них не опираются.
    """
    folder: Path = Path(tempfile.mkdtemp(prefix="livecraft-shipped-"))
    atexit.register(shutil.rmtree, folder, True)
    path: Path = folder / "livecraft.json"
    SHIPPED_SETTINGS.install(path)
    return path


SHIPPED_SETTINGS_FILE: Path = _shipped_settings_file()
REPO_SETTINGS_FILE: Path = SHIPPED_SETTINGS_FILE      # прежнее имя: им пользуются test_setup_migration.py и test_tools_sheets_probe.py
REPO_CHANNELS_EXAMPLE: Path = REPO_ROOT / "app" / "examples" / "channels.example.json"
# Ключ поставочного сейфа во временном корне (secrets\program.key, §7.3) и то, что в поставку положила сборка.
PROGRAM_KEY_BYTES: bytes = bytes(range(VAULT_KEY_BYTES))
SUPPLIED_VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-supplied-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",
    SecretField.SHEETS_ID: "1supplied-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
    SecretField.SHEETS_RANGE: "A:F",
}
# Ссылка на форму в сейфе — так её хранили до §14 решения 15; нужна тестам переноса в livecraft.json.
LEGACY_FORM_URL: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-supplied/viewform"
# Ссылка на форму в livecraft.json для тестов, которым нужна настроенная форма (пакет, эфиры).
FORM_URL: str = "https://forms.gle/AbCdEf123456"
# client_secret.json готового корня: достаточно, что файл есть (§9) — к Google тесты не ходят.
CLIENT_SECRET_STUB: str = '{"installed": {}}'


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


def ready_source(
    row: PlanRow, title: str, description: str, language: str, preview: Preview | None = None
) -> SourceVideo:
    """Годный источник без сети: данные видео как от yt-dlp, язык — настоящим решением по языку видео."""
    link: str = row.link or ""
    metadata: SourceMetadata = SourceMetadata(
        url=link,
        video_id=link.rsplit("/", 1)[-1],
        title=title,
        description=description,
        thumbnail_url="",
        youtube_language=language,
        channel_language=None,
        duration_seconds=None,
        canonical_url=link,
        audio_languages=(),
        subtitle_languages=(),
        auto_caption_languages=(),
    )
    return SourceVideo(
        row=row,
        metadata=metadata,
        preview=preview,
        failure=None,
        preview_problem=None,
        language=LanguageProfile(video_language=language, channel_language=None).decide(),
    )


class LogCollector(logging.Handler):
    """Свой обработчик прямо на логгере: не зависит от propagate после других тестов."""

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def messages(self, level: int | None = None) -> list[str]:
        return [record.getMessage() for record in self.records if level is None or record.levelno == level]


@pytest.fixture
def slot_log() -> Iterator[LogCollector]:
    """Записи логгера livecraft.slots за время теста."""
    logger: logging.Logger = logging.getLogger("livecraft.slots")
    collector: LogCollector = LogCollector()
    level: int = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(collector)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(level)


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
    """Корень, готовый к запуску: настройки из поставки репо, каналы из примера, поставочный сейф на все нужные поля,
    файл OAuth-клиента на месте (его содержимое читает только вход в Google, в этих тестах входа нет).

    Ссылка на форму в поставочных настройках пуста: пакет и эфиры без неё не готовы — это задают сами тесты."""
    SHIPPED_SETTINGS.install(livecraft_paths.config_file)
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, livecraft_paths.channels_file)
    write_supplied_vault(livecraft_paths, SUPPLIED_VALUES)
    livecraft_paths.client_secret_file.write_text(CLIENT_SECRET_STUB, encoding="utf-8")
    return livecraft_paths


def set_form_url(paths: LivecraftPaths, url: str) -> None:
    """Ссылка на форму в livecraft.json — тем же загрузчиком, что пишет настройщик."""
    settings: LivecraftSettings = load_settings(paths.config_file)
    save_settings_file(paths.config_file, dataclasses.replace(settings, form=dataclasses.replace(settings.form, url=url)))


# --- нейросеть без сети: подделка SDK openai (app\llm\backends\openai.py), ответы и отказы OpenAI

OPENAI_URL: str = "https://api.openai.com/v1/responses"
LLM_SETTINGS: LlmSettings = LlmSettings(
    model="gpt-5.6-sol",
    fallback_model="gpt-5.4",
    reasoning_effort=ReasoningEffort.MEDIUM,
    service_tier=ServiceTier.FLEX,
    timeout_sec=900,
    max_output_tokens=8000,
)
_STATUS_ERRORS: dict[int, type[openai.APIStatusError]] = {
    400: openai.BadRequestError,
    401: openai.AuthenticationError,
    403: openai.PermissionDeniedError,
    404: openai.NotFoundError,
    422: openai.UnprocessableEntityError,
    429: openai.RateLimitError,
    500: openai.InternalServerError,
}


class FakeRawResponse:
    """Сырой ответ SDK (`with_raw_response`): заголовки и `parse()` — сам ответ словарём."""

    def __init__(self, response: dict[str, object], headers: dict[str, str]) -> None:
        self.response: dict[str, object] = response
        self.headers: dict[str, str] = headers

    def parse(self) -> dict[str, object]:
        return self.response


class FakeLlmSdk:
    """Подделка `openai.OpenAI`: сама себе фабрика и клиент. Ответы и отказы — по очереди из `outcomes`.

    `created` — с чем создавали клиента (там ключ: тест сверяет, что он дошёл до SDK и никуда больше);
    `calls` — аргументы каждого `responses.with_raw_response.create`.
    """

    def __init__(self, *outcomes: FakeRawResponse | Exception) -> None:
        self.outcomes: list[FakeRawResponse | Exception] = list(outcomes)
        self.created: list[dict[str, object]] = []
        self.calls: list[dict[str, object]] = []
        self.responses: object = self
        self.with_raw_response: object = self

    def __call__(self, **options: object) -> FakeLlmSdk:
        self.created.append(options)
        return self

    def create(self, **kwargs: object) -> FakeRawResponse:
        self.calls.append(kwargs)
        outcome: FakeRawResponse | Exception = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def llm_answer(
    text: str = "OK",
    model: str = "gpt-5.6-sol-2026-08-01",
    service_tier: str = "flex",
    input_tokens: int = 1000,
    cached_tokens: int = 200,
    output_tokens: int = 100,
    reasoning_tokens: int = 40,
    incomplete: str | None = None,
    headers: dict[str, str] | None = None,
) -> FakeRawResponse:
    """Ответ Responses API так, как его отдаёт SDK: текст, модель, тариф, расход, причина обрыва."""
    response: dict[str, object] = {
        "id": "resp_test",
        "model": model,
        "service_tier": service_tier,
        "output_text": text,
        "incomplete_details": {"reason": incomplete} if incomplete is not None else None,
        "usage": {
            "input_tokens": input_tokens,
            "input_tokens_details": {"cached_tokens": cached_tokens},
            "output_tokens": output_tokens,
            "output_tokens_details": {"reasoning_tokens": reasoning_tokens},
            "total_tokens": input_tokens + output_tokens,
        },
    }
    return FakeRawResponse(response, headers if headers is not None else {})


def api_error(status: int, message: str, code: str | None = None, param: str | None = None) -> openai.APIStatusError:
    """Отказ OpenAI с кодом ответа — тем классом SDK, которым его бросает openai."""
    body: dict[str, object] = {"message": message, "code": code, "param": param}
    response: httpx2.Response = httpx2.Response(status, request=httpx2.Request("POST", OPENAI_URL), json={"error": body})
    return _STATUS_ERRORS.get(status, openai.APIStatusError)(message, response=response, body=body)


def timeout_error() -> openai.APITimeoutError:
    return openai.APITimeoutError(request=httpx2.Request("POST", OPENAI_URL))


def connection_error() -> openai.APIConnectionError:
    return openai.APIConnectionError(request=httpx2.Request("POST", OPENAI_URL))
