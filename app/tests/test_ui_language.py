"""Язык окна и консоли — по языку отображения Windows, один на процесс (CLAUDE.md §14 решение 24).

Правило выбора проверяется через параметры `UiLanguage.choose`, без подмены окружения и платформы процесса; справка
командной строки — подпроцессом, как её увидит человек.
"""
from __future__ import annotations

import os
import subprocess
import sys
from types import ModuleType

import pytest

from app.tests.conftest import REPO_ROOT
from app.ui import messages_en, messages_ru, messages_uk
from app.ui.language import LANGUAGE_ENV_VAR, UiLanguage

WINDOWS: str = "win32"
LINUX: str = "linux"
UKRAINIAN_LANGID: int = 0x0422
SUBPROCESS_TIMEOUT_SEC: float = 60.0


def _not_asked() -> int:
    raise AssertionError("язык Windows спрашивать не должны")


def _flat(text: str) -> str:
    """argparse переносит длинное описание по ширине терминала: сравниваем текст без переносов."""
    return " ".join(text.split())


@pytest.mark.parametrize(
    ("langid", "language"),
    [(0x0419, UiLanguage.RU), (0x0819, UiLanguage.RU), (0x0422, UiLanguage.UK), (0x0409, UiLanguage.EN), (0, UiLanguage.EN)],
)
def test_the_primary_language_of_the_langid_decides(langid: int, language: UiLanguage) -> None:
    assert UiLanguage.of_langid(langid) is language


@pytest.mark.parametrize("platform", [WINDOWS, LINUX])
@pytest.mark.parametrize("language", list(UiLanguage))
def test_the_variable_decides_on_any_platform(platform: str, language: UiLanguage) -> None:
    assert UiLanguage.choose({LANGUAGE_ENV_VAR: language.value}, platform, _not_asked) is language


@pytest.mark.parametrize("value", ["de", ""])
def test_an_unknown_or_empty_variable_is_as_if_there_were_none(value: str) -> None:
    assert UiLanguage.choose({LANGUAGE_ENV_VAR: value}, WINDOWS, lambda: UKRAINIAN_LANGID) is UiLanguage.UK
    assert UiLanguage.choose({LANGUAGE_ENV_VAR: value}, LINUX, _not_asked) is UiLanguage.EN


def test_without_the_variable_another_system_gets_english_without_asking_windows() -> None:
    assert UiLanguage.choose({}, LINUX, _not_asked) is UiLanguage.EN


@pytest.mark.parametrize(
    ("langid", "language"), [(0x0419, UiLanguage.RU), (0x0422, UiLanguage.UK), (0x0407, UiLanguage.EN)]
)
def test_without_the_variable_windows_decides(langid: int, language: UiLanguage) -> None:
    assert UiLanguage.choose({}, WINDOWS, lambda: langid) is language


def test_the_language_of_this_machine_is_one_of_the_catalogs() -> None:
    """Без переменной — боевой путь: на Windows язык отдаёт kernel32, на другой системе — английский."""
    env: dict[str, str] = {name: value for name, value in os.environ.items() if name != LANGUAGE_ENV_VAR}
    code: str = "from app.ui.language import UiLanguage; print(UiLanguage.current().value)"
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, check=True, cwd=REPO_ROOT, env=env,
        timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    assert result.stdout.strip() in {language.value for language in UiLanguage}


@pytest.mark.parametrize(("language", "catalog"), [(UiLanguage.EN, messages_en), (UiLanguage.UK, messages_uk)])
def test_the_help_speaks_the_language_of_the_process(language: UiLanguage, catalog: ModuleType) -> None:
    env: dict[str, str] = {**os.environ, LANGUAGE_ENV_VAR: language.value, "PYTHONIOENCODING": "utf-8"}
    result: subprocess.CompletedProcess[str] = subprocess.run(
        [sys.executable, "-m", "app.main", "--help"], capture_output=True, encoding="utf-8", cwd=REPO_ROOT, env=env,
        timeout=SUBPROCESS_TIMEOUT_SEC,
    )
    assert result.returncode == 0
    shown: str = _flat(result.stdout)
    assert _flat(catalog.CLI_DESCRIPTION) in shown
    assert _flat(messages_ru.CLI_DESCRIPTION) not in shown
