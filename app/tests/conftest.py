"""Общие фикстуры: папки livecraft в tmp_path, фиксированное «сейчас», корень репо, сейф на диске,
готовый к запуску корень, живой и мёртвый посторонние процессы и лог слотов.
"""
from __future__ import annotations

import atexit
import logging
import os
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

from app.ui.language import LANGUAGE_ENV_VAR, UiLanguage

# Тесты сравнивают то, что показывает продукт, с messages_ru: каталог выбирается при первом импорте app.ui.messages,
# поэтому язык ставится до всех остальных импортов app (§14 решение 24). Подпроцессы тестов наследуют его.
os.environ[LANGUAGE_ENV_VAR] = UiLanguage.RU.value

from app.config.files import SettingsFile, ShippedSettings
from app.config.settings import LlmSettings, ReasoningEffort, ServiceTier
from app.observability.log_event import LogArea
from app.paths import FileName, LivecraftPaths
from app.tests.fixtures.logs import LogCapture
# Сейф тестов живёт в fixtures\vault.py; здесь его имена — для тестов, которые берут их из conftest.
from app.tests.fixtures.vault import TOKEN_VALUES, write_token_vault

KYIV_WINTER: timezone = timezone(timedelta(hours=2))   # даты и время — по Киеву (CLAUDE.md §6, инвариант 4)
FIXED_NOW: datetime = datetime(2026, 9, 20, 12, 0, tzinfo=KYIV_WINTER)
REPO_ROOT: Path = Path(__file__).resolve().parents[2]
SHIPPED_SETTINGS: ShippedSettings = ShippedSettings()


def _shipped_settings_file() -> Path:
    """Поставочный livecraft.json, собранный боевым путём (SettingsFile.install_shipped) во временной папке сессии.

    В git файла нет (§5), а secrets\\livecraft.json разработчика — его личные настройки: тесты на них не опираются.
    """
    folder: Path = Path(tempfile.mkdtemp(prefix="livecraft-shipped-"))
    atexit.register(shutil.rmtree, folder, True)
    path: Path = folder / "livecraft.json"
    SettingsFile(path).install_shipped()
    return path


SHIPPED_SETTINGS_FILE: Path = _shipped_settings_file()
REPO_SETTINGS_FILE: Path = SHIPPED_SETTINGS_FILE      # прежнее имя: им пользуется test_tools_sheets_probe.py
REPO_CHANNELS_EXAMPLE: Path = REPO_ROOT / "app" / "examples" / "channels.example.json"
# Ссылка на форму в livecraft.json для тестов, которым нужна настроенная форма (пакет, эфиры).
FORM_URL: str = "https://forms.gle/AbCdEf123456"
# client_secret.json готового корня: достаточно, что файл есть (§9) — к Google тесты не ходят.
CLIENT_SECRET_STUB: str = '{"installed": {}}'


@pytest.fixture
def slot_log() -> Iterator[LogCapture]:
    """Записи логгера livecraft.slots за время теста."""
    with LogCapture.on(LogArea.SLOTS, logging.DEBUG) as capture:
        yield capture


@pytest.fixture
def livecraft_paths(tmp_path: Path) -> LivecraftPaths:
    """Корень запуска во временной папке: папки созданы, файлов в них нет — как после установки."""
    paths: LivecraftPaths = LivecraftPaths(tmp_path / "root")
    paths.ensure_dirs()
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
    """Корень, готовый к запуску: настройки из поставки репо, каналы из примера, значения из токена на все нужные поля,
    файл OAuth-клиента на месте (его содержимое читает только вход в Google, в этих тестах входа нет).

    Ссылка на форму в поставочных настройках пуста: пакет и эфиры без неё не готовы — это задают сами тесты."""
    SettingsFile.of(livecraft_paths).install_shipped()
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, livecraft_paths.file(FileName.CHANNELS))
    write_token_vault(livecraft_paths, TOKEN_VALUES)
    livecraft_paths.file(FileName.CLIENT_SECRET).write_text(CLIENT_SECRET_STUB, encoding="utf-8")
    return livecraft_paths


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
