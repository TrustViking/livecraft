"""Поля сейфа и происхождение значений: словарь, общий для шифра, секрета и сейфа (CLAUDE.md §7.3, §7.5).

Модуль ниже `crypto.py`, `value.py` и `vault.py`: шифру нужно имя поля (к нему привязан блоб), секрету — правило
маски своего поля, сейфу — происхождение значения. Поэтому ни шифр, ни секрет друг о друге через этот словарь
не узнают. Записи полей прежних версий, чьё значение перешло в новые поля, — `LegacyField` (§14 решение 60).
"""
from __future__ import annotations

from enum import Enum
from typing import Final, TypeAlias

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
    # Папки Google Диска (§14 решения 27, 39, 60): для превью и для документов объявлений — ресурсы оператора того же
    # рода, что таблица плана, в сейфе лежит id папки. Одна и та же папка или разные — как задал человек.
    DRIVE_PREVIEWS_FOLDER = "drive_previews_folder"
    DRIVE_DOCS_FOLDER = "drive_docs_folder"

    @classmethod
    def names(cls) -> frozenset[str]:
        """Имена всех полей, как они лежат в файле сейфа: по ним узнаются чужие записи файла."""
        return frozenset(field.value for field in cls)

    @property
    def is_drive_folder(self) -> bool:
        """Поле — папка Google Диска: правило ввода у обеих папок одно (ссылка на папку или её id)."""
        return self in DRIVE_FIELDS

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


class LegacyField(str, Enum):
    """Записи полей прежних версий, значение которых перешло в новые поля (§14 решение 60). Имя — как в файле сейфа и в
    AAD блоба: расшифровывается запись под своим прежним именем, а значение получают поля-преемники."""

    DRIVE_FOLDER = "drive_folder"   # одна папка Google Диска на превью и документы объявлений (до решения 60)

    @classmethod
    def names(cls) -> frozenset[str]:
        """Имена прежних записей в файле сейфа: они не чужие — их значение переходит в новые поля."""
        return frozenset(field.value for field in cls)

    @property
    def successors(self) -> tuple[SecretField, ...]:
        """Поля, в которые переходит значение прежней записи."""
        return _SUCCESSORS[self]

    @property
    def log_label(self) -> str:
        """Ярлык прежней записи для лога: без значения (§7.4)."""
        return _LEGACY_LOG_LABELS[self]

    @property
    def human_label(self) -> str:
        """Для человека прежняя запись — это её поля-преемники: их значение она и несёт."""
        return msg.LIST_JOINER.join(field.human_label for field in self.successors)


# Запись файла сейфа: поле этой версии или прежнее — у обоих своё имя в AAD блоба (app\secretsafe\crypto.py).
StoredField: TypeAlias = SecretField | LegacyField


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
    SecretField.DRIVE_PREVIEWS_FOLDER: "drive-previews",
    SecretField.DRIVE_DOCS_FOLDER: "drive-docs",
}
_HUMAN_LABELS: Final[dict[SecretField, str]] = {
    SecretField.OPENAI_API_KEY: msg.VAULT_FIELD_OPENAI_API_KEY,
    SecretField.SHEETS_ID: msg.VAULT_FIELD_SHEETS_ID,
    SecretField.TELEGRAM_BOT_TOKEN: msg.VAULT_FIELD_TELEGRAM_BOT_TOKEN,
    SecretField.DRIVE_PREVIEWS_FOLDER: msg.VAULT_FIELD_DRIVE_PREVIEWS_FOLDER,
    SecretField.DRIVE_DOCS_FOLDER: msg.VAULT_FIELD_DRIVE_DOCS_FOLDER,
}
DRIVE_FIELDS: Final[frozenset[SecretField]] = frozenset(
    {SecretField.DRIVE_PREVIEWS_FOLDER, SecretField.DRIVE_DOCS_FOLDER}
)
# Прежнее общее поле папки Диска — в обе папки (§14 решение 60): человеку вводить ничего не нужно.
_SUCCESSORS: Final[dict[LegacyField, tuple[SecretField, ...]]] = {
    LegacyField.DRIVE_FOLDER: (SecretField.DRIVE_PREVIEWS_FOLDER, SecretField.DRIVE_DOCS_FOLDER),
}
_LEGACY_LOG_LABELS: Final[dict[LegacyField, str]] = {
    LegacyField.DRIVE_FOLDER: "drive-folder",
}
_ORIGIN_LABELS: Final[dict[VaultOrigin, str]] = {
    VaultOrigin.TOKEN: msg.VAULT_ORIGIN_TOKEN,
    VaultOrigin.OWN: msg.VAULT_ORIGIN_OWN,
}
