"""То, что пользователь ввёл в поле сейфа, и правила этого поля (CLAUDE.md §7.5, §8.2 п.2, п.3).

Объект сам знает, во что превратить ввод для сейфа (`normalized`), что с вводом не так (`problem`) и какой
секрет из него получится (`secret`). Правило каждого поля — метод объекта, а не свободная функция по месту
вызова (§0); чистые разборы строки без знания о полях лежат в `app\\setup\\validators.py`.

Введённый текст — чужой секрет в открытом виде, поэтому в `repr` объекта его нет (`raw` скрыт из `repr`),
а в строки проблем он не подставляется: иначе ключ, вставленный не в то поле, ушёл бы в трассировку (§7.4).
Создание `SecretValue` из введённого — не раскрытие значения, а наоборот, упаковка его в маскирующую обёртку.
"""
from __future__ import annotations

import dataclasses
import re
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Final
from urllib.parse import SplitResult

from app.core.alphabet import LATIN_LETTERS
from app.core.web_link import HTTPS_SCHEME, split_url
from app.secretsafe.value import SecretField, SecretValue
from app.setup.validators import extract_spreadsheet_id
from app.ui.messages import msg

OPENAI_KEY_PREFIX: Final[str] = "sk-"
OPENAI_KEY_MIN_LENGTH: Final[int] = 20
SHEETS_ID_MIN_LENGTH: Final[int] = 20
SHEETS_ID_EXTRA_CHARS: Final[frozenset[str]] = frozenset("-_")
# Токен бота Telegram: «<id бота>:<секрет>», секрет — от 35 знаков латиницы, цифр, «_» и «-» (так их выдаёт BotFather).
TELEGRAM_BOT_SECRET_MIN_LENGTH: Final[int] = 35
TELEGRAM_BOT_TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(
    f"[0-9]+:[{LATIN_LETTERS}0-9_-]{{{TELEGRAM_BOT_SECRET_MIN_LENGTH},}}"
)
# Папка Google Диска: https://drive.google.com/drive/folders/<id> (бывает …/drive/u/0/folders/<id>?usp=sharing) или сам
# id — латинские буквы, цифры, «_» и «-» (§14 решение 39).
DRIVE_HOST: Final[str] = "drive.google.com"
FOLDERS_SEGMENT: Final[str] = "folders"
DRIVE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(f"[{LATIN_LETTERS}0-9_-]+")


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
    def is_empty(self) -> bool:
        """Ввод без пробелов по краям пуст: вписывать нечего."""
        return not self.text

    @property
    def normalized(self) -> str | None:
        """Значение для сейфа после правил поля; ввод негоден — None."""
        if self.problem is not None:
            return None
        return self._candidate

    @property
    def problem(self) -> str | None:
        """Что не так с вводом — строкой для человека без самого значения; всё в порядке — None."""
        if self.is_empty:
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
        """Что уйдёт в сейф, если правило поля его пропустит: у таблицы и папки Диска — id, а не ссылка (§7.5)."""
        if self.field is SecretField.SHEETS_ID:
            return extract_spreadsheet_id(self.text)
        if self.field is SecretField.DRIVE_FOLDER:
            return self._drive_folder_id or ""
        return self.text

    @property
    def _drive_folder_id(self) -> str | None:
        """id папки Диска: сам ввод, если это id; из ссылки https://drive.google.com/…/folders/<id>; не нашёлся — None.

        Хост сверяется со всем `netloc`: «drive.google.com@чужой.хост» не проходит. Пробелы внутри не прощаются.
        """
        text: str = self.text
        if DRIVE_ID_PATTERN.fullmatch(text) is not None:
            return text
        parts: SplitResult | None = None if any(char.isspace() for char in text) else split_url(text)
        if parts is None or parts.scheme.lower() != HTTPS_SCHEME or parts.netloc.lower() != DRIVE_HOST:
            return None
        segments: tuple[str, ...] = PurePosixPath(parts.path).parts
        found: list[str] = [
            segment for previous, segment in zip(segments, segments[1:])
            if previous == FOLDERS_SEGMENT and DRIVE_ID_PATTERN.fullmatch(segment) is not None
        ]
        return found[0] if found else None

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

    def _telegram_bot_token_problem(self) -> str | None:
        """Токен бота — «<число>:<секрет>» целиком, без пробелов внутри."""
        is_valid: bool = TELEGRAM_BOT_TOKEN_PATTERN.fullmatch(self.text) is not None
        return None if is_valid else msg.SETUP_INPUT_TELEGRAM_BOT_TOKEN.format(minimum=TELEGRAM_BOT_SECRET_MIN_LENGTH)

    def _drive_folder_problem(self) -> str | None:
        """Папка Диска — ссылка на папку или сам id папки."""
        return None if self._drive_folder_id is not None else msg.SETUP_INPUT_DRIVE_FOLDER


_FIELD_RULES: Final[dict[SecretField, Callable[[SecretInput], str | None]]] = {
    SecretField.OPENAI_API_KEY: SecretInput._openai_key_problem,
    SecretField.SHEETS_ID: SecretInput._sheets_id_problem,
    SecretField.TELEGRAM_BOT_TOKEN: SecretInput._telegram_bot_token_problem,
    SecretField.DRIVE_FOLDER: SecretInput._drive_folder_problem,
    SecretField.SUPPORT_BOT_TOKEN: SecretInput._telegram_bot_token_problem,
}
