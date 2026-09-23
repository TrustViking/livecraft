from __future__ import annotations

import base64
import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

from app.paths import LivecraftPaths
from app.secretsafe.crypto import VAULT_KEY_BYTES, VaultFormatError
from app.secretsafe.store import GENERATED_KEY_MODULE, GENERATED_KEY_PARTS, ProgramKey, VaultStore

KEY: bytes = bytes(range(VAULT_KEY_BYTES))


@pytest.fixture
def dev_key_path(livecraft_paths: LivecraftPaths) -> Path:
    """Путь ключа разработчика: secrets\\program.key, файла ещё нет (§7.3)."""
    return livecraft_paths.program_key_file


# --- ключ разработчика: файл secrets\program.key


def test_the_key_is_read_from_the_developer_file(dev_key_path: Path) -> None:
    dev_key_path.write_bytes(KEY)
    program_key: ProgramKey = ProgramKey.load(dev_key_path)
    assert program_key.is_available
    assert program_key.material == KEY


def test_the_key_may_be_written_as_base64(dev_key_path: Path) -> None:
    """Файл руками удобнее заполнять текстом: base64 от 32 байт читается так же."""
    dev_key_path.write_bytes(base64.b64encode(KEY))
    assert ProgramKey.load(dev_key_path).material == KEY


def test_a_base64_key_with_a_trailing_newline_is_read(dev_key_path: Path) -> None:
    dev_key_path.write_bytes(base64.b64encode(KEY) + b"\r\n")
    assert ProgramKey.load(dev_key_path).material == KEY


def test_without_the_file_the_key_is_absent(dev_key_path: Path) -> None:
    """Обычная установка без своего ключа: поставочный сейф просто не читается (§7.3)."""
    assert not dev_key_path.exists()
    program_key: ProgramKey = ProgramKey.load(dev_key_path)
    assert not program_key.is_available
    assert program_key.material is None


@pytest.mark.parametrize(
    "raw",
    [b"", b"short", bytes(VAULT_KEY_BYTES - 1), bytes(VAULT_KEY_BYTES + 1), b"not a key at all, just text"],
)
def test_a_key_of_the_wrong_length_counts_as_absent(dev_key_path: Path, raw: bytes) -> None:
    """Огрызок ключа хуже отсутствия: с ним сейф «почти читается». Такой ключ считается отсутствующим."""
    dev_key_path.write_bytes(raw)
    assert not ProgramKey.load(dev_key_path).is_available


def test_a_key_file_that_does_not_open_is_a_format_error_not_absent(dev_key_path: Path) -> None:
    """«Не открылся» — это не «нет» (§16): иначе оператор получил бы неверную причину «не хватает полей»."""
    dev_key_path.mkdir()
    with pytest.raises(VaultFormatError) as raised:
        ProgramKey.load(dev_key_path)
    text: str = str(raised.value)
    assert "program.key" in text
    assert str(dev_key_path.parent) not in text          # только имя файла, без папки
    assert isinstance(raised.value.__cause__, OSError)


def test_a_key_file_that_does_not_open_stops_the_store_from_opening(livecraft_paths: LivecraftPaths) -> None:
    """Боевой путь: VaultStore.open → ProgramKey.load; дальше Readiness превращает ошибку в код 2."""
    livecraft_paths.program_key_file.mkdir()
    with pytest.raises(VaultFormatError) as raised:
        VaultStore.open(livecraft_paths)
    assert "program.key" in str(raised.value)


def test_the_wrong_length_is_reported_without_the_key_bytes(
    dev_key_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Причина уходит в лог, сами байты — нет (§7.4)."""
    dev_key_path.write_bytes(b"secret-but-too-short")
    with caplog.at_level("WARNING"):
        assert not ProgramKey.load(dev_key_path).is_available
    assert "program_key_wrong_length" in caplog.text
    assert "secret-but-too-short" not in caplog.text


# --- сгенерированный сборкой модуль


def test_the_generated_module_is_absent_in_dev_and_that_is_normal(dev_key_path: Path) -> None:
    """Модуль генерирует build_release.bat перед PyInstaller; в репо его нет и ImportError здесь штатный."""
    assert GENERATED_KEY_MODULE not in sys.modules
    with pytest.raises(ImportError):
        importlib.import_module(GENERATED_KEY_MODULE)
    assert not ProgramKey.load(dev_key_path).is_available      # без модуля и без файла ключа нет


def test_the_generated_module_wins_over_the_developer_file(
    dev_key_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """В собранной программе ключ даёт сборка: файл разработчика рядом с exe её не перебивает."""
    dev_key_path.write_bytes(bytes(VAULT_KEY_BYTES))
    monkeypatch.setitem(sys.modules, GENERATED_KEY_MODULE, _fake_module(_halves(KEY)))
    assert ProgramKey.load(dev_key_path).material == KEY


def test_the_key_is_assembled_from_several_parts(
    dev_key_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ключ не лежит в модуле одной строкой: части склеиваются в момент использования (§7.3)."""
    parts: tuple[bytes, ...] = (KEY[:8], KEY[8:20], KEY[20:])
    monkeypatch.setitem(sys.modules, GENERATED_KEY_MODULE, _fake_module(parts))
    assert ProgramKey.load(dev_key_path).material == KEY


@pytest.mark.parametrize(
    "parts",
    [
        (KEY[:8],),                       # части не складываются в 32 байта
        (KEY, KEY),                       # длиннее, чем нужно
        ("текст", "вместо", "байтов"),    # не байты
        (),                               # пусто
    ],
)
def test_a_malformed_generated_module_counts_as_absent(
    dev_key_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    parts: tuple[Any, ...],
) -> None:
    monkeypatch.setitem(sys.modules, GENERATED_KEY_MODULE, _fake_module(parts))
    assert not ProgramKey.load(dev_key_path).is_available


def test_a_generated_module_without_the_parts_name_counts_as_absent(
    dev_key_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    empty: Any = type(sys)(GENERATED_KEY_MODULE)
    monkeypatch.setitem(sys.modules, GENERATED_KEY_MODULE, empty)
    assert not ProgramKey.load(dev_key_path).is_available


def test_a_malformed_generated_module_falls_back_to_the_developer_file(
    dev_key_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Битый модуль сборки не роняет запуск и не съедает ключ разработчика: разбор идёт дальше, к файлу."""
    dev_key_path.write_bytes(KEY)
    monkeypatch.setitem(sys.modules, GENERATED_KEY_MODULE, _fake_module(("не", "байты")))
    assert ProgramKey.load(dev_key_path).material == KEY


def test_a_malformed_generated_module_without_a_developer_file_leaves_no_key(
    dev_key_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(sys.modules, GENERATED_KEY_MODULE, _fake_module(("не", "байты")))
    assert not ProgramKey.load(dev_key_path).is_available


def _halves(key: bytes) -> tuple[bytes, ...]:
    middle: int = len(key) // 2
    return (key[:middle], key[middle:])


def _fake_module(parts: tuple[Any, ...]) -> Any:
    """Подделка модуля, который в боевой сборке генерирует build_release.bat (этап 6)."""
    module: Any = type(sys)(GENERATED_KEY_MODULE)
    setattr(module, GENERATED_KEY_PARTS, parts)
    return module
