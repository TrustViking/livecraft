"""Сейф тестов: значения, пришедшие в загруженном токене доступа, и свои значения — тем же путём, что их пишет программа."""
from __future__ import annotations

import threading
from collections.abc import Callable

import pytest

from app.paths import LivecraftPaths
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultLoad, VaultStore
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.ui import messages_ru as msg

# Что пришло в токене доступа (§14 решения 16, 44): обязательные для таблицы и нейросети поля; токена бота в нём нет —
# готовый корень тестов работает без объявлений (§13 задача 4.1).
TOKEN_VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-fromtoken-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",
    SecretField.SHEETS_ID: "1fromtoken-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
}
# Что программа говорит громко, когда личный сейф есть, но не прочитан (§16): поля — их названиями.
LOCAL_UNREADABLE_WARNING: str = msg.VAULT_LOCAL_UNREADABLE.format(
    fields=msg.LIST_JOINER.join(field.human_label for field in SecretField)
)


def vault_of(values: dict[SecretField, str], origin: VaultOrigin) -> Vault:
    """Сейф с этими значениями одного происхождения."""
    vault: Vault = Vault.empty()
    for field, value in values.items():
        vault = vault.with_field(field, SecretValue(field=field, value=value), origin)
    return vault


def write_token_vault(paths: LivecraftPaths, values: dict[SecretField, str]) -> None:
    """Значения из токена — так их кладёт загрузка токена (VaultStore.save_token): слой токена заменяется целиком."""
    VaultStore.open(paths).save_token(vault_of(values, VaultOrigin.TOKEN))


def save_own_values(paths: LivecraftPaths, values: dict[SecretField, str]) -> None:
    """Свои значения в личный сейф — тем же путём, что пишет настройщик (VaultStore.save_local): поверх прочитанного
    личного слоя, как вкладка окна пишет свои поля, не трогая чужих."""
    store: VaultStore = VaultStore.open(paths)
    own: Vault = store.load_for_setup().own
    for field, value in values.items():
        own = own.with_field(field, SecretValue(field=field, value=value), VaultOrigin.OWN)
    store.save_local(own)


class VaultReads:
    """Сколько раз главный поток прочитал файлы сейфа: строгим путём (`VaultStore.load`) и мягким
    (`VaultStore.load_for_setup`). Фоновые проверки окна читают сейф сами — их чтения не считаются."""

    def __init__(self) -> None:
        self.strict: int = 0
        self.lenient: int = 0

    @classmethod
    def counted(cls, monkeypatch: pytest.MonkeyPatch) -> VaultReads:
        """Чтения сейфа до конца теста считаются; читает сейф по-прежнему VaultStore."""
        reads: VaultReads = cls()
        load: Callable[[VaultStore], VaultLoad] = VaultStore.load
        load_for_setup: Callable[[VaultStore], VaultLoad] = VaultStore.load_for_setup

        def strict(store: VaultStore) -> VaultLoad:
            reads.strict += reads.main_thread
            return load(store)

        def lenient(store: VaultStore) -> VaultLoad:
            reads.lenient += reads.main_thread
            return load_for_setup(store)

        monkeypatch.setattr(VaultStore, "load", strict)
        monkeypatch.setattr(VaultStore, "load_for_setup", lenient)
        return reads

    @property
    def main_thread(self) -> int:
        """1 — чтение в главном потоке (окно), 0 — в фоновом (проверка по кнопке)."""
        return int(threading.current_thread() is threading.main_thread())

    @property
    def both(self) -> tuple[int, int]:
        return self.strict, self.lenient
