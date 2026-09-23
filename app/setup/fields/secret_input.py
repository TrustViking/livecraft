"""То, что пользователь ввёл в поле сейфа, и правила этого поля (CLAUDE.md §7.5, §8.2 п.1).

Объект сам знает, во что превратить ввод для сейфа (`normalized`), что с вводом не так (`problem`) и какой
секрет из него получится (`secret`). Правило каждого поля — метод объекта, а не свободная функция по месту
вызова (§0); чистые разборы строки без знания о полях лежат в `app\\setup\\validators.py`.

Введённый текст — чужой секрет в открытом виде, поэтому в `repr` объекта его нет (`raw` скрыт из `repr`),
а в строки проблем он не подставляется: иначе ключ, вставленный не в то поле, ушёл бы в трассировку (§7.4).
Создание `SecretValue` из введённого — не раскрытие значения, а наоборот, упаковка его в маскирующую обёртку.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final
from urllib.parse import SplitResult, urlsplit

from app.secretsafe.value import SecretField, SecretValue
from app.setup.validators import extract_spreadsheet_id, is_a1_range
from app.ui import messages_ru as msg

OPENAI_KEY_PREFIX: Final[str] = "sk-"
OPENAI_KEY_MIN_LENGTH: Final[int] = 20
SHEETS_ID_MIN_LENGTH: Final[int] = 20
SHEETS_ID_EXTRA_CHARS: Final[frozenset[str]] = frozenset("-_")
FORM_URL_SCHEME: Final[str] = "https"
FORM_LONG_HOST: Final[str] = "docs.google.com"
FORM_LONG_PATH_PREFIX: Final[str] = "/forms/"
FORM_SHORT_HOST: Final[str] = "forms.gle"
URL_PATH_SEPARATOR: Final[str] = "/"


@dataclass(frozen=True)
class SecretInput:
    """Ввод в одно поле сейфа. Правила: сначала обрезать пробелы по краям; пустой ввод — проблема."""

    field: SecretField
    raw: str = dataclasses.field(repr=False)

    @property
    def text(self) -> str:
        """Ввод без пробелов по краям: с ними не работает ни одно поле."""
        return self.raw.strip()

    @property
    def normalized(self) -> str | None:
        """Значение для сейфа после правил поля; ввод негоден — None."""
        if self.problem is not None:
            return None
        return self._candidate

    @property
    def problem(self) -> str | None:
        """Что не так с вводом — русской строкой без самого значения; всё в порядке — None."""
        if not self.text:
            return msg.SETUP_INPUT_EMPTY
        rule: Callable[[SecretInput], str | None] = _FIELD_RULES[self.field]
        return rule(self)

    @property
    def secret(self) -> SecretValue | None:
        """Готовый секрет для сейфа; ввод негоден — None."""
        value: str | None = self.normalized
        if value is None:
            return None
        return SecretValue(field=self.field, value=value)

    @property
    def _candidate(self) -> str:
        """Что уйдёт в сейф, если правило поля его пропустит: у таблицы — id, а не ссылка (§7.5)."""
        if self.field is SecretField.SHEETS_ID:
            return extract_spreadsheet_id(self.text)
        return self.text

    def _openai_key_problem(self) -> str | None:
        """Ключ OpenAI: «sk-» в начале, ни одного пробельного символа внутри, длина не меньше минимума."""
        text: str = self.text
        is_valid: bool = (
            text.startswith(OPENAI_KEY_PREFIX)
            and not any(char.isspace() for char in text)
            and len(text) >= OPENAI_KEY_MIN_LENGTH
        )
        return None if is_valid else msg.SETUP_INPUT_OPENAI_API_KEY.format(minimum=OPENAI_KEY_MIN_LENGTH)

    def _sheets_id_problem(self) -> str | None:
        """id таблицы (из ссылки или как есть): латиница, цифры, «-» и «_», длина не меньше минимума."""
        sheet_id: str = self._candidate
        is_valid: bool = len(sheet_id) >= SHEETS_ID_MIN_LENGTH and all(
            (char.isascii() and char.isalnum()) or char in SHEETS_ID_EXTRA_CHARS for char in sheet_id
        )
        return None if is_valid else msg.SETUP_INPUT_SHEETS_ID.format(minimum=SHEETS_ID_MIN_LENGTH)

    def _sheets_range_problem(self) -> str | None:
        """Диапазон таблицы — нотация A1 с обеими границами."""
        return None if is_a1_range(self.text) else msg.SETUP_INPUT_SHEETS_RANGE

    def _key_form_url_problem(self) -> str | None:
        """Адрес формы: https, длинный (docs.google.com/forms/…) или короткий (forms.gle/<код>), без пробелов.

        Хост сверяется со всем `netloc`, а не только с именем: «docs.google.com@чужой.хост» и чужой порт
        не проходят. Редирект и viewform разбирает сама форма (задача 4.2), здесь — только чей это адрес.
        """
        text: str = self.text
        if any(char.isspace() for char in text):
            return msg.SETUP_INPUT_KEY_FORM_URL
        parts: SplitResult = urlsplit(text)
        if parts.scheme.lower() != FORM_URL_SCHEME:
            return msg.SETUP_INPUT_KEY_FORM_URL
        host: str = parts.netloc.lower()
        is_long: bool = host == FORM_LONG_HOST and parts.path.startswith(FORM_LONG_PATH_PREFIX)
        is_short: bool = host == FORM_SHORT_HOST and bool(parts.path.strip(URL_PATH_SEPARATOR))
        return None if is_long or is_short else msg.SETUP_INPUT_KEY_FORM_URL


_FIELD_RULES: Final[dict[SecretField, Callable[[SecretInput], str | None]]] = {
    SecretField.OPENAI_API_KEY: SecretInput._openai_key_problem,
    SecretField.SHEETS_ID: SecretInput._sheets_id_problem,
    SecretField.SHEETS_RANGE: SecretInput._sheets_range_problem,
    SecretField.KEY_FORM_URL: SecretInput._key_form_url_problem,
}
