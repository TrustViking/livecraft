"""Поля сейфа и происхождение значений: словарь, общий для шифра, секрета и сейфа (CLAUDE.md §7.3, §7.5).

Модуль ниже `crypto.py`, `value.py` и `vault.py`: шифру нужно имя поля (к нему привязан блоб), секрету — правило
маски своего поля, сейфу — происхождение значения. Поэтому ни шифр, ни секрет друг о друге через этот словарь
не узнают.
"""
from __future__ import annotations

from enum import Enum
from typing import Final

from app.ui.messages import msg


class MaskStyle(str, Enum):
    """Как показать значение человеку, чтобы он узнал своё и не прочитал чужое."""

    TAIL = "tail"                # «sk-…dc7f»: так принято показывать ключ API
    FINGERPRINT = "fingerprint"  # «форма ключей (…9c2b)»: у ссылок и id даже хвост подсказывает лишнее


class SecretField(str, Enum):
    """Поля сейфа (CLAUDE.md §7.3, §7.5). Имя значения — имя поля в файле сейфа и в AAD шифра."""

    OPENAI_API_KEY = "openai_api_key"
    SHEETS_ID = "sheets_id"
    # Токен бота Telegram (§14 решения 14, 19): нужен только объявлениям.
    TELEGRAM_BOT_TOKEN = "telegram_bot_token"
    # Папка материалов на Google Диске (§14 решения 27, 39): ресурс оператора того же рода, что таблица плана, — в сейфе
    # лежит id папки. Нужна превью на Google Диске и документу объявлений.
    DRIVE_FOLDER = "drive_folder"
    # Токен бота поддержки (§14 решение 58): логи уходят им, а не ботом объявлений — получатель токена меняет бота
    # объявлений на своего, а логи по-прежнему доходят до поддержки.
    SUPPORT_BOT_TOKEN = "support_bot_token"

    @classmethod
    def names(cls) -> frozenset[str]:
        """Имена всех полей, как они лежат в файле сейфа: по ним узнаются чужие записи файла."""
        return frozenset(field.value for field in cls)

    @property
    def log_label(self) -> str:
        """Ярлык для машинного следа: в лог уходит он и отпечаток, но никогда значение (§7.4)."""
        return _LOG_LABELS[self]

    @property
    def human_label(self) -> str:
        """Название поля для человека; сам текст — в каталоге msg (§11), здесь только отображение поля на него."""
        return _HUMAN_LABELS[self]

    @property
    def mask_style(self) -> MaskStyle:
        """Ключ API узнаётся по хвосту; ссылки и id — только по отпечатку."""
        return MaskStyle.TAIL if self is SecretField.OPENAI_API_KEY else MaskStyle.FINGERPRINT


class VaultOrigin(str, Enum):
    """Чьё значение или файл сейфа: пришло в токене доступа или вписано самим пользователем (§14 решения 16, 44).

    Одно слово на оба смысла: поле с происхождением «своё» лежит в личном файле, «из токена» — в файле токена.
    Значение — английский идентификатор для лога (путь к файлу сейфа в лог не идёт); для человека — `human_label`.
    """

    TOKEN = "token"         # пришло в загруженном токене доступа: получатель работает на нём, но не видит его (§7.1)
    OWN = "own"             # вписал сам пользователь: личный сейф под его Windows-аккаунтом

    @property
    def human_label(self) -> str:
        """Название для человека; текст — в каталоге msg (§11), здесь только отображение на него."""
        return _ORIGIN_LABELS[self]


_LOG_LABELS: Final[dict[SecretField, str]] = {
    SecretField.OPENAI_API_KEY: "openai-key",
    SecretField.SHEETS_ID: "sheets-plan",
    SecretField.TELEGRAM_BOT_TOKEN: "telegram-bot",
    SecretField.DRIVE_FOLDER: "drive-folder",
    SecretField.SUPPORT_BOT_TOKEN: "telegram-support-bot",
}
_HUMAN_LABELS: Final[dict[SecretField, str]] = {
    SecretField.OPENAI_API_KEY: msg.VAULT_FIELD_OPENAI_API_KEY,
    SecretField.SHEETS_ID: msg.VAULT_FIELD_SHEETS_ID,
    SecretField.TELEGRAM_BOT_TOKEN: msg.VAULT_FIELD_TELEGRAM_BOT_TOKEN,
    SecretField.DRIVE_FOLDER: msg.VAULT_FIELD_DRIVE_FOLDER,
    SecretField.SUPPORT_BOT_TOKEN: msg.VAULT_FIELD_SUPPORT_BOT_TOKEN,
}
_ORIGIN_LABELS: Final[dict[VaultOrigin, str]] = {
    VaultOrigin.TOKEN: msg.VAULT_ORIGIN_TOKEN,
    VaultOrigin.OWN: msg.VAULT_ORIGIN_OWN,
}
