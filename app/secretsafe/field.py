"""Поля сейфа и происхождение значений: словарь, общий для шифра, секрета и сейфа (CLAUDE.md §7.3, §7.5).

Модуль ниже `crypto.py`, `value.py` и `vault.py`: шифру нужно имя поля (к нему привязан блоб), секрету — правило
маски своего поля, сейфу — происхождение значения. Поэтому ни шифр, ни секрет друг о друге через этот словарь
не узнают.
"""
from __future__ import annotations

from enum import Enum
from typing import Final

from app.ui import messages_ru as msg


class MaskStyle(str, Enum):
    """Как показать значение человеку, чтобы он узнал своё и не прочитал чужое."""

    TAIL = "tail"                # «sk-…dc7f»: так принято показывать ключ API
    FINGERPRINT = "fingerprint"  # «форма ключей (…9c2b)»: у ссылок и id даже хвост подсказывает лишнее


class SecretField(str, Enum):
    """Поля сейфа (CLAUDE.md §7.3, §7.5). Имя значения — имя поля в файле сейфа и в AAD шифра."""

    OPENAI_API_KEY = "openai_api_key"
    SHEETS_ID = "sheets_id"
    SHEETS_RANGE = "sheets_range"
    # Устаревшее поле (§14 решение 15): ссылка на форму теперь открытая настройка livecraft.json (form.url).
    # Поле остаётся, чтобы старый файл сейфа читался и ссылку из него можно было один раз перенести
    # (app\setup\migration.py); удаляется на этапе «Токен доступа» вместе с переносом.
    KEY_FORM_URL = "key_form_url"

    @classmethod
    def current(cls) -> tuple[SecretField, ...]:
        """Поля, которые программа требует для запуска и показывает человеку: все, кроме устаревших."""
        return tuple(field for field in cls if not field.is_legacy)

    @classmethod
    def names(cls) -> frozenset[str]:
        """Имена всех полей, как они лежат в файле сейфа: по ним узнаются чужие записи файла."""
        return frozenset(field.value for field in cls)

    @property
    def is_legacy(self) -> bool:
        """Устаревшее поле: читается из старого сейфа и вычёркивается из логов, но не требуется и не показывается."""
        return self in _LEGACY_FIELDS

    @property
    def log_label(self) -> str:
        """Ярлык для машинного следа: в лог уходит он и отпечаток, но никогда значение (§7.4)."""
        return _LOG_LABELS[self]

    @property
    def human_label(self) -> str:
        """Русское название поля; сам текст — в messages_ru (§11), здесь только отображение поля на него."""
        return _HUMAN_LABELS[self]

    @property
    def mask_style(self) -> MaskStyle:
        """Ключ API узнаётся по хвосту; ссылки, id и диапазон — только по отпечатку."""
        return MaskStyle.TAIL if self is SecretField.OPENAI_API_KEY else MaskStyle.FINGERPRINT


class VaultOrigin(str, Enum):
    """Чьё значение или файл сейфа: пришло с программой или вписано самим пользователем.

    Одно слово на оба смысла: поле с происхождением «своё» лежит в личном файле, «поставка» — в поставочном.
    Значение — английский идентификатор для лога (путь к файлу сейфа в лог не идёт); для человека — `human_label`.
    """

    SUPPLIED = "supplied"   # пришло со сборкой: поставочный сейф Артура (§7.2)
    OWN = "own"             # вписал сам пользователь: личный сейф под его Windows-аккаунтом

    @property
    def human_label(self) -> str:
        """Русское название; текст — в messages_ru (§11), здесь только отображение на него."""
        return _ORIGIN_LABELS[self]


_LEGACY_FIELDS: Final[frozenset[SecretField]] = frozenset({SecretField.KEY_FORM_URL})
_LOG_LABELS: Final[dict[SecretField, str]] = {
    SecretField.OPENAI_API_KEY: "openai-key",
    SecretField.SHEETS_ID: "sheets-plan",
    SecretField.SHEETS_RANGE: "sheets-range",
    SecretField.KEY_FORM_URL: "key-form",
}
_HUMAN_LABELS: Final[dict[SecretField, str]] = {
    SecretField.OPENAI_API_KEY: msg.VAULT_FIELD_OPENAI_API_KEY,
    SecretField.SHEETS_ID: msg.VAULT_FIELD_SHEETS_ID,
    SecretField.SHEETS_RANGE: msg.VAULT_FIELD_SHEETS_RANGE,
    SecretField.KEY_FORM_URL: msg.VAULT_FIELD_KEY_FORM_URL,
}
_ORIGIN_LABELS: Final[dict[VaultOrigin, str]] = {
    VaultOrigin.SUPPLIED: msg.VAULT_ORIGIN_SUPPLIED,
    VaultOrigin.OWN: msg.VAULT_ORIGIN_OWN,
}
