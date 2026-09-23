"""То, что введено в строку канала на вкладке «Каналы YouTube» (CLAUDE.md §8.2 п.2).

Черновик — текст полей как в окне и одно правило: перевести введённое в объект channels.json (`to_data`).
Своих проверок у черновика нет: годность канала решает тот же загрузчик, что читает файл (§16, решения к
задаче 2.2), поэтому окно и файл не могут разойтись в том, какой канал правильный.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Final

from app.config.loader import HANDLE_PREFIX, ChannelConfig, Platform

# Коды языков в строке ввода разделяются запятыми и пробельными символами: «uk, ru  en».
LANGUAGES_SEPARATOR: Final[re.Pattern[str]] = re.compile(r"[,\s]+")
LANGUAGES_DISPLAY_JOINER: Final[str] = ", "


@dataclass(frozen=True)
class ChannelDraft:
    """Строка канала текстом. Площадка не вводится: в v1 она всегда YouTube (§1)."""

    account_name: str
    handle: str
    google_account: str
    languages: str
    privacy: str

    @classmethod
    def of(cls, channel: ChannelConfig) -> ChannelDraft:
        """Черновик уже годного канала — то, что окно показывает в строке."""
        return cls(
            account_name=channel.account_name,
            handle=channel.handle,
            google_account=channel.google_account,
            languages=LANGUAGES_DISPLAY_JOINER.join(channel.languages),
            privacy=channel.privacy.value,
        )

    def to_data(self) -> dict[str, Any]:
        """Объект channels.json из введённого: пробелы по краям срезаны, ник — с «@», языки — списком.

        Регистр языков не исправляется: правило строчных — у загрузчика, и он назовёт ошибку сам.
        """
        return {
            "platform": Platform.YOUTUBE.value,
            "account_name": self.account_name.strip(),
            "handle": self.handle_text,
            "google_account": self.google_account.strip(),
            "languages": self.language_codes,
            "privacy": self.privacy.strip(),
        }

    @property
    def handle_text(self) -> str:
        """Ник с «@» в начале; пустой ввод остаётся пустым, чтобы загрузчик назвал его пустым, а не коротким."""
        text: str = self.handle.strip()
        if not text or text.startswith(HANDLE_PREFIX):
            return text
        return HANDLE_PREFIX + text

    @property
    def language_codes(self) -> list[str]:
        """Коды языков из строки ввода, пустые куски выброшены."""
        return [code for code in LANGUAGES_SEPARATOR.split(self.languages) if code]
