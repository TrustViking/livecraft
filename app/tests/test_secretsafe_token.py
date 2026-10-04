"""Токен доступа одним файлом (app\\secretsafe\\token.py; CLAUDE.md §7.3, §14 решения 16, 44, 45): ключ — внутри файла,
заголовок — AAD шифра, срок — в заголовке; токен прежней версии не читается."""
from __future__ import annotations

import struct
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from app.secretsafe.crypto import VAULT_KEY_BYTES
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.token import (
    TOKEN_HEADER,
    TOKEN_MAGIC,
    TOKEN_SUFFIX,
    AccessToken,
    IssuedToken,
    TokenContent,
    TokenError,
    TokenOrder,
    TokenProblem,
)
from app.tests.fixtures.token import NETWORK_NOW
from app.tests.fixtures.vault import vault_of
from app.ui import messages_ru as msg

OWN_VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-mine-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",
    SecretField.SHEETS_ID: "1mine-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
}
SETTINGS: dict[str, str] = {"form.url": "https://forms.gle/AbCdEf123456", "telegram.private_chat_id": "123456789"}
CONTENT: TokenContent = TokenContent(vault=vault_of(OWN_VALUES, VaultOrigin.OWN), settings=SETTINGS)
STEM: str = "livecraft_29-09-2026_150000"
VERSION_OFFSET: int = 4          # байт версии — сразу после магии
TOKEN_ID_OFFSET: int = 5         # id токена — после магии и версии
CREATED_OFFSET: int = 21         # момент создания (старший байт) — после магии, версии и id токена
CREATED_LAST_BYTE: int = 28      # младший байт момента создания
KEY_OFFSET: int = TOKEN_HEADER.size                      # ключ — сразу после заголовка
CIPHERTEXT_OFFSET: int = TOKEN_HEADER.size + VAULT_KEY_BYTES
# Заголовок токена версии 1 (до §14 решения 45): магия, версия, вид (пара или один файл), id пары, моменты, нонс.
VERSION_1_HEADER: struct.Struct = struct.Struct(">4sBB16sqq12s")


def _issue(tmp_path: Path, days: int = 3) -> Path:
    return IssuedToken.of(CONTENT, TokenOrder(days=days), NETWORK_NOW).write(tmp_path / STEM)


def _flip(path: Path, offset: int) -> None:
    data: bytearray = bytearray(path.read_bytes())
    data[offset] ^= 0x01
    path.write_bytes(bytes(data))


def _refusal(token: Path, now: datetime = NETWORK_NOW) -> TokenError:
    with pytest.raises(TokenError) as raised:
        AccessToken.read(token).open(now)
    return raised.value


def _values(content: TokenContent) -> dict[SecretField, str]:
    return {field: entry.secret.reveal() for field, entry in content.vault.entries.items()}


# --- один файл с ключом внутри (§14 решение 45)


def test_a_token_is_one_file_that_opens_by_itself(tmp_path: Path) -> None:
    written: Path = _issue(tmp_path)
    assert written.name == STEM + TOKEN_SUFFIX
    assert [path.name for path in tmp_path.iterdir()] == [written.name]
    content: TokenContent = AccessToken.read(written).open(NETWORK_NOW)
    assert _values(content) == OWN_VALUES
    assert all(entry.origin is VaultOrigin.TOKEN for entry in content.vault.entries.values())
    assert dict(content.settings) == SETTINGS


def test_the_file_is_binary_and_carries_no_value_in_plain_sight(tmp_path: Path) -> None:
    """В блокноте не прочитать: ни значений, ни ссылки на форму, ни id чата."""
    data: bytes = _issue(tmp_path).read_bytes()
    for value in (*OWN_VALUES.values(), *SETTINGS.values()):
        assert value.encode() not in data
    assert b"sheets_id" not in data and b"form.url" not in data


def test_the_period_is_in_the_header(tmp_path: Path) -> None:
    token: AccessToken = AccessToken.read(_issue(tmp_path, days=5))
    assert token.header.created == NETWORK_NOW
    assert token.header.valid_until == NETWORK_NOW + timedelta(days=5)


def test_the_token_opens_until_the_end_of_its_period(tmp_path: Path) -> None:
    written: Path = _issue(tmp_path, days=3)
    assert _values(AccessToken.read(written).open(NETWORK_NOW + timedelta(days=3))) == OWN_VALUES


def test_two_tokens_have_their_own_keys(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    first: AccessToken = AccessToken.read(_issue(tmp_path / "a"))
    second: AccessToken = AccessToken.read(_issue(tmp_path / "b"))
    assert first.key.material != second.key.material and first.header.token_id != second.header.token_id


# --- что не загружается и почему — словами


@pytest.mark.parametrize("offset", [
    CIPHERTEXT_OFFSET + 3, KEY_OFFSET, KEY_OFFSET + VAULT_KEY_BYTES - 1, TOKEN_ID_OFFSET, CREATED_LAST_BYTE,
    CREATED_OFFSET, TOKEN_HEADER.size - 1,
])
def test_a_changed_byte_of_the_token_is_refused(tmp_path: Path, offset: int) -> None:
    """Шифротекст, ключ в файле, id токена (соль ключа и AAD), момент создания (AAD; старший байт даёт момент, которого
    нет в календаре) и нонс — подмена любого байта ломает чтение."""
    written: Path = _issue(tmp_path)
    _flip(written, offset)
    assert _refusal(written).reason is TokenProblem.DAMAGED


def test_an_expired_token_is_refused(tmp_path: Path) -> None:
    error: TokenError = _refusal(_issue(tmp_path, days=3), NETWORK_NOW + timedelta(days=3, seconds=1))
    assert error.reason is TokenProblem.EXPIRED
    assert error.human == msg.TOKEN_PROBLEM_TEXT["expired"]


def test_a_token_of_another_version_is_refused(tmp_path: Path) -> None:
    written: Path = _issue(tmp_path)
    _flip(written, VERSION_OFFSET)
    with pytest.raises(TokenError) as raised:
        AccessToken.read(written)
    assert raised.value.reason is TokenProblem.VERSION


@pytest.mark.parametrize("kind", [1, 2])
def test_a_token_of_version_1_asks_for_a_new_token(tmp_path: Path, kind: int) -> None:
    """Токен версии 1 — парный (вид 1) или одним файлом (вид 2): не читается, человеку — создать новый."""
    old: Path = tmp_path / ("old" + TOKEN_SUFFIX)
    header: bytes = VERSION_1_HEADER.pack(TOKEN_MAGIC, 1, kind, bytes(16), 0, 0, bytes(12))
    old.write_bytes(header + bytes(VAULT_KEY_BYTES + 64))
    with pytest.raises(TokenError) as raised:
        AccessToken.read(old)
    assert raised.value.reason is TokenProblem.VERSION
    assert str(raised.value) == msg.TOKEN_PROBLEM_TEXT["version"]
    assert "создайте новый токен" in str(raised.value)


def test_files_that_are_not_a_token_are_refused(tmp_path: Path) -> None:
    other: Path = tmp_path / "notes.txt"
    other.write_text("просто текст, но достаточно длинный, чтобы вместить заголовок токена целиком", encoding="utf-8")
    short: Path = tmp_path / "short.lctoken"
    short.write_bytes(TOKEN_MAGIC)
    for path in (other, short):
        with pytest.raises(TokenError) as raised:
            AccessToken.read(path)
        assert raised.value.reason is TokenProblem.NOT_TOKEN


def test_a_file_that_does_not_open_is_refused(tmp_path: Path) -> None:
    with pytest.raises(TokenError) as raised:
        AccessToken.read(tmp_path / "missing.lctoken")
    assert raised.value.reason is TokenProblem.FILE_UNREADABLE


def test_every_problem_has_a_text_in_every_word() -> None:
    assert set(msg.TOKEN_PROBLEM_TEXT) == {problem.value for problem in TokenProblem}


def test_a_refusal_carries_no_value(tmp_path: Path) -> None:
    """Тексты исключений секретов не содержат (§7.4): ни для человека, ни в строке лога."""
    written: Path = _issue(tmp_path)
    _flip(written, CIPHERTEXT_OFFSET + 3)
    error: TokenError = _refusal(written)
    for text in (str(error), error.log_line):
        for value in (*OWN_VALUES.values(), *SETTINGS.values()):
            assert value not in text
    assert error.log_line.startswith("token_refused reason=damaged")
