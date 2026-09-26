"""То, что введено в строку канала на вкладке «Каналы YouTube» (CLAUDE.md §8.2 п.2).

Черновик — поля строки как в окне, их описание (`FIELDS`) и одно правило: перевести введённое в объект
channels.json (`to_data`). Ключи объекта — `ChannelKey`, перевод значения — вид поля (`DraftField.data`).
Своих проверок у черновика нет: годность канала решает тот же загрузчик, что читает файл, поэтому окно и файл
не могут разойтись в том, какой канал правильный. У канала один язык (§14 решение 21), но черновик держит
коды кортежем: канал старого файла с несколькими языками показывается как есть, пока его не пересохранят.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Final

from app.config.channel import ChannelConfig, ChannelKey, Platform, Privacy
from app.setup.fields.draft_field import DraftField, DraftKind

FIELD_WIDTH_CHARS: Final[int] = 40      # все поля строки канала одной ширины: выбор и ввод стоят столбцом
PRIVACY_CHOICES: Final[tuple[str, ...]] = tuple(privacy.value for privacy in Privacy)


@dataclass(frozen=True)
class ChannelDraft:
    """Строка канала: текст полей, коды языков. Площадка не вводится: в v1 она всегда YouTube (§1)."""

    FIELDS: ClassVar[tuple[DraftField, ...]] = (
        DraftField(ChannelKey.ACCOUNT_NAME, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
        DraftField(ChannelKey.HANDLE, DraftKind.HANDLE, width=FIELD_WIDTH_CHARS),
        DraftField(ChannelKey.GOOGLE_ACCOUNT, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
        DraftField(ChannelKey.LANGUAGES, DraftKind.LANGUAGE, width=FIELD_WIDTH_CHARS),
        DraftField(ChannelKey.PRIVACY, DraftKind.CHOICE, choices=PRIVACY_CHOICES, width=FIELD_WIDTH_CHARS),
    )

    account_name: str
    handle: str
    google_account: str
    languages: tuple[str, ...]
    privacy: str

    @classmethod
    def blank(cls) -> ChannelDraft:
        """Пустая строка нового канала: языка нет, видимость — первый вариант перечня."""
        return cls(account_name="", handle="", google_account="", languages=(), privacy=PRIVACY_CHOICES[0])

    @classmethod
    def of(cls, channel: ChannelConfig) -> ChannelDraft:
        """Черновик уже годного канала — то, что окно показывает в строке."""
        return cls(
            account_name=channel.account_name,
            handle=channel.handle,
            google_account=channel.google_account,
            languages=channel.languages,
            privacy=channel.privacy.value,
        )

    def to_data(self) -> dict[str, object]:
        """Объект channels.json из введённого, поля в порядке ключей: площадка — YouTube, прочее — по виду поля.

        Регистр языков не исправляется: правило строчных — у загрузчика, и он назовёт ошибку сам.
        """
        data: dict[str, object] = {ChannelKey.PLATFORM.value: Platform.YOUTUBE.value}
        data.update({field.key_path: field.data(getattr(self, field.name)) for field in self.FIELDS})
        return data
