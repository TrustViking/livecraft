"""Секрет в памяти: обёртка, которая не вытекает ни в один вывод (CLAUDE.md §7.3, §7.4).

Правило §7.4 дословно: расшифрованное значение живёт **только** в `SecretValue` и только в памяти.
Получить его можно единственным методом доступа (он ниже, один во всём проекте), и зовут его ровно в трёх
точках применения: заголовок `Authorization` клиента OpenAI, `spreadsheetId` клиента Sheets, базовый URL
клиента формы. Поэтому имя этого метода встречается в пакете ровно один раз — там, где он объявлен;
поиск по нему показывает все точки применения и стережёт правило §7.4.

Всё остальное, что делают с секретом, должно давать маску. Поэтому `__str__`, `__repr__` и `__format__`
переопределены все три: секрет, случайно попавший в `f"{...}"`, в `logging.info("%s", …)`, в `repr`
объекта-владельца или в текст исключения, выходит маской. `__format__` намеренно **игнорирует**
спецификатор: без этого `f"{secret:>40}"` ушёл бы в `str.__format__` и напечатал значение.

Ни одной свободной функции с доступом к значению в этом модуле нет (§7.3): смотреть на значение умеет
только сам `SecretValue`.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.ui import messages_ru as msg

FINGERPRINT_CHARS: Final[int] = 4      # первые 4 hex sha256: различить два значения — да, восстановить — нет
TAIL_HEAD_CHARS: Final[int] = 3        # у ключа API показываем начало…
TAIL_CHARS: Final[int] = 4             # …и хвост, чтобы владелец узнал свой ключ
TAIL_MIN_LENGTH: Final[int] = 8        # короче — показывать нечего, скрываем целиком
MASK_ELLIPSIS: Final[str] = "…"
MASK_HIDDEN: Final[str] = "…"          # значение целиком скрыто
LOG_LABEL_TEMPLATE: Final[str] = "{label}({fingerprint})"


class MaskStyle(str, Enum):
    """Как показать значение человеку, чтобы он узнал своё и не прочитал чужое."""

    TAIL = "tail"                # «sk-…dc7f»: так принято показывать ключ API
    FINGERPRINT = "fingerprint"  # «форма ключей (…9c2b)»: у ссылок и id даже хвост подсказывает лишнее


class SecretField(str, Enum):
    """Поля сейфа (CLAUDE.md §7.3, §7.5). Имя значения — имя поля в файле сейфа и в AAD шифра."""

    OPENAI_API_KEY = "openai_api_key"
    SHEETS_ID = "sheets_id"
    SHEETS_RANGE = "sheets_range"
    KEY_FORM_URL = "key_form_url"

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


@dataclass(frozen=True)
class SecretValue:
    """Секретная строка и всё, что о ней можно сказать не раскрывая её.

    `value` приватно по смыслу: наружу оно не отдаётся ничем, кроме единственного метода доступа. `repr`
    тоже маска — иначе `dataclass` печатал бы поле `value` в каждой трассировке.
    """

    field: SecretField
    value: str

    def reveal(self) -> str:
        """Единственный способ получить значение. Зовётся только в точке применения (§7.4)."""
        return self.value

    @property
    def masked(self) -> str:
        """То, что видят люди: по `mask_style` своего поля."""
        if self.field.mask_style is MaskStyle.TAIL:
            return self._tail_mask
        return msg.VAULT_MASK_FINGERPRINT.format(label=self.field.human_label, fingerprint=self.fingerprint)

    @property
    def fingerprint(self) -> str:
        """Первые 4 hex sha256 от значения (§7.4): различить две формы в одном запуске — да, восстановить — нет."""
        return hashlib.sha256(self.value.encode("utf-8")).hexdigest()[:FINGERPRINT_CHARS]

    @property
    def log_label(self) -> str:
        """Что уходит в лог вместо значения: `key-form(9c2b)` (§7.4)."""
        return LOG_LABEL_TEMPLATE.format(label=self.field.log_label, fingerprint=self.fingerprint)

    @property
    def _tail_mask(self) -> str:
        """«sk-…dc7f»; короткое значение скрывается целиком — из трёх символов складывается весь секрет."""
        if len(self.value) < TAIL_MIN_LENGTH:
            return MASK_HIDDEN
        return f"{self.value[:TAIL_HEAD_CHARS]}{MASK_ELLIPSIS}{self.value[-TAIL_CHARS:]}"

    def __str__(self) -> str:
        return self.masked

    def __repr__(self) -> str:
        return self.masked

    def __format__(self, format_spec: str) -> str:
        """Спецификатор игнорируется намеренно: f"{secret:>40}" не должен обойти маску."""
        return self.masked
