"""Сейф тестов: ключ поставочного сейфа во временном корне и значения, которые туда положила сборка."""
from __future__ import annotations

from app.core.text_format import TEXT_ENCODING
from app.paths import LivecraftPaths
from app.secretsafe.crypto import VAULT_KEY_BYTES, EncryptedField, VaultCrypto, VaultFile
from app.secretsafe.field import SecretField
from app.ui import messages_ru as msg

# Ключ поставочного сейфа во временном корне (secrets\program.key, §7.3) и то, что в поставку положила сборка.
PROGRAM_KEY_BYTES: bytes = bytes(range(VAULT_KEY_BYTES))
SUPPLIED_VALUES: dict[SecretField, str] = {
    SecretField.OPENAI_API_KEY: "sk-proj-supplied-Ab3dEfGhIjKlMnOpQrStUvWxYz0123456789",
    SecretField.SHEETS_ID: "1supplied-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-abcdefg",
    SecretField.SHEETS_RANGE: "A:F",
}
# Что программа говорит громко, когда личный сейф есть, но не прочитан (§16): поля — нынешними названиями.
LOCAL_UNREADABLE_WARNING: str = msg.VAULT_LOCAL_UNREADABLE.format(
    fields=msg.LIST_JOINER.join(field.human_label for field in SecretField.current())
)


def write_supplied_vault(paths: LivecraftPaths, values: dict[SecretField, str]) -> None:
    """Поставочный сейф так пишет сборка Артура: ключ снаружи (program.key), записи «key» в файле нет.

    Программа этот файл писать не умеет и не должна, поэтому в тестах он собирается прямо из VaultFile.
    """
    paths.program_key_file.write_bytes(PROGRAM_KEY_BYTES)
    crypto: VaultCrypto = VaultCrypto(key=PROGRAM_KEY_BYTES, salt=VaultCrypto.new().salt)
    fields: dict[str, EncryptedField] = {field.value: crypto.encrypt(field, value) for field, value in values.items()}
    paths.vault_file.write_text(VaultFile.new(salt=crypto.salt, fields=fields).render(), encoding=TEXT_ENCODING)
