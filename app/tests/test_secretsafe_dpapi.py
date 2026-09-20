"""Тесты DPAPI. Livecraft — программа для Windows (§5, §8, инвариант 11), поэтому боевой путь здесь
проверяется без оговорок: на не-Windows эти тесты обязаны упасть, а не тихо пройти. Ветка недоступности
проверяется отдельно, объектом без библиотек и подменённой платформой.
"""
from __future__ import annotations

import sys

import pytest

from app.secretsafe.dpapi import DATA_DESCRIPTION, Dpapi, DpapiUnavailable

SECRET: bytes = "ключ OpenAI sk-proj-Ab3dEfGh0123456789dc7f".encode("utf-8")
BINARY: bytes = bytes(range(256))
IS_WINDOWS: bool = sys.platform == "win32"


@pytest.fixture
def dpapi() -> Dpapi:
    """Боевой объект: библиотеки грузятся так же, как их загрузит настройщик и VaultStore."""
    return Dpapi.load()


@pytest.fixture
def unavailable() -> Dpapi:
    """Объект без библиотек — та же ветка, что на не-Windows: строится штатно, в работе честно отказывает."""
    return Dpapi()


# --- боевой круговой ход под текущим пользователем Windows


def test_dpapi_is_available_on_windows(dpapi: Dpapi) -> None:
    """§7.3: на Windows локальный сейф возможен; на другой системе его просто не будет."""
    assert IS_WINDOWS, "livecraft — программа для Windows; DPAPI проверяется на ней"
    assert dpapi.is_available


def test_protect_and_unprotect_return_the_same_bytes(dpapi: Dpapi) -> None:
    """Живой вызов CryptProtectData без CRYPTPROTECT_LOCAL_MACHINE и обратный разбор тем же пользователем."""
    assert dpapi.unprotect(dpapi.protect(SECRET)) == SECRET


def test_the_protected_blob_does_not_contain_the_secret(dpapi: Dpapi) -> None:
    """Смысл локального сейфа: в файле нет ни значения, ни его куска."""
    blob: bytes = dpapi.protect(SECRET)
    assert blob != SECRET
    assert SECRET not in blob
    assert b"sk-proj" not in blob
    assert len(blob) > len(SECRET)


def test_any_bytes_survive_the_round_trip(dpapi: Dpapi) -> None:
    """Через DPAPI ходят байты файла сейфа, а не текст: нули и старшие байты должны выживать."""
    assert dpapi.unprotect(dpapi.protect(BINARY)) == BINARY
    assert dpapi.unprotect(dpapi.protect(b"")) == b""


def test_two_protections_of_one_value_differ(dpapi: Dpapi) -> None:
    assert dpapi.protect(SECRET) != dpapi.protect(SECRET)


def test_a_damaged_blob_does_not_unprotect(dpapi: Dpapi) -> None:
    """DPAPI проверяет целостность сам: подмена байта — отказ вызова, а не мусор наружу."""
    blob: bytes = dpapi.protect(SECRET)
    damaged: bytes = blob[:-1] + bytes([blob[-1] ^ 0xFF])
    with pytest.raises(DpapiUnavailable):
        dpapi.unprotect(damaged)


def test_unprotecting_something_that_is_not_a_blob_fails(dpapi: Dpapi) -> None:
    with pytest.raises(DpapiUnavailable):
        dpapi.unprotect(b"not a dpapi blob at all")


def test_repeated_use_of_one_object_works(dpapi: Dpapi) -> None:
    """Подписи объявляются один раз при load: второй и третий вызов должны работать так же."""
    for _ in range(3):
        assert dpapi.unprotect(dpapi.protect(SECRET)) == SECRET


# --- ветка недоступности: без skip и xfail, на любой машине


def test_an_object_without_libraries_reports_itself_unavailable(unavailable: Dpapi) -> None:
    assert not unavailable.is_available


def test_protect_without_dpapi_refuses_instead_of_returning_the_data(unavailable: Dpapi) -> None:
    """Молча вернуть данные как есть запрещено: «локальный сейф» открытым текстом хуже отсутствия сейфа."""
    with pytest.raises(DpapiUnavailable):
        unavailable.protect(SECRET)


def test_unprotect_without_dpapi_refuses(unavailable: Dpapi) -> None:
    with pytest.raises(DpapiUnavailable):
        unavailable.unprotect(SECRET)


def test_the_refusal_text_says_what_is_missing_and_carries_no_secret(unavailable: Dpapi) -> None:
    with pytest.raises(DpapiUnavailable) as raised:
        unavailable.protect(SECRET)
    text: str = str(raised.value)
    assert "crypt32.dll" in text and sys.platform in text
    assert SECRET.decode("utf-8") not in text


def test_a_non_windows_platform_gives_an_unavailable_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """На Linux и macOS локального сейфа нет: load отдаёт недоступный объект, а не падает на импорте."""
    monkeypatch.setattr(sys, "platform", "linux")
    loaded: Dpapi = Dpapi.load()
    assert not loaded.is_available
    with pytest.raises(DpapiUnavailable):
        loaded.protect(SECRET)


def test_a_library_that_does_not_load_gives_an_unavailable_object(monkeypatch: pytest.MonkeyPatch) -> None:
    """Обрезанная или подменённая система: crypt32 не грузится — отказ, а не трассировка наружу."""
    import ctypes

    def _refuse(name: str, *args: object, **kwargs: object) -> object:
        raise OSError(f"cannot load {name}")

    monkeypatch.setattr(ctypes, "WinDLL", _refuse)
    loaded: Dpapi = Dpapi.load()
    assert not loaded.is_available
    with pytest.raises(DpapiUnavailable):
        loaded.unprotect(SECRET)


# --- описание блоба


def test_the_description_is_the_one_section_seven_names() -> None:
    assert DATA_DESCRIPTION == "Livecraft local vault"
