"""То, что введено в строку канала на вкладке «Эфиры YouTube» (CLAUDE.md §8.2 п.4, §14 решение 25).

Черновик — поля строки как в окне, их описание (`FIELDS`) и одно правило: перевести введённое в объект
channels.json (`to_data`). Ключи объекта — `ChannelKey`, перевод значения — вид поля (`DraftField.data`).
Своих проверок у черновика нет: годность канала решает тот же загрузчик, что читает файл, поэтому окно и файл
не могут разойтись в том, какой канал правильный. У канала один язык (§14 решение 21), но черновик держит
коды кортежем: канал старого файла с несколькими языками показывается как есть, пока его не пересохранят.

Название канала человек не вводит (§14 решение 25): поля в окне нет, но в channels.json оно остаётся — его читают
форма ключей и planers. Черновик держит его сам: у канала из файла — прежнее, у нового — ник без «@»; сменившееся
на YouTube название выравнивает проверка канала по id. Видимость в окне — словами, в файл уходит значение `Privacy`.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import ClassVar, Final

from app.config.channel import ChannelConfig, ChannelHandle, ChannelKey, Platform, Privacy
from app.setup.fields.draft_field import DraftField, DraftKind
from app.ui.messages import msg

FIELD_WIDTH_CHARS: Final[int] = 40      # все поля строки канала одной ширины: выбор и ввод стоят столбцом
PRIVACY_CHOICES: Final[tuple[str, ...]] = tuple(privacy.value for privacy in Privacy)
PRIVACY_LABELS: Final[tuple[str, ...]] = tuple(msg.SETUP_PRIVACY_LABELS[choice] for choice in PRIVACY_CHOICES)
HANDLE_FIELD: Final[DraftField] = DraftField(ChannelKey.HANDLE, DraftKind.HANDLE, width=FIELD_WIDTH_CHARS)


@dataclass(frozen=True)
class ChannelDraft:
    """Строка канала: текст полей, коды языков и название канала (не поле окна). Площадка не вводится: в v1 она
    всегда YouTube (§1)."""

    FIELDS: ClassVar[tuple[DraftField, ...]] = (
        HANDLE_FIELD,
        DraftField(ChannelKey.GOOGLE_ACCOUNT, DraftKind.TEXT, width=FIELD_WIDTH_CHARS),
        DraftField(ChannelKey.LANGUAGES, DraftKind.LANGUAGE, width=FIELD_WIDTH_CHARS),
        DraftField(
            ChannelKey.PRIVACY, DraftKind.CHOICE, choices=PRIVACY_CHOICES, labels=PRIVACY_LABELS, width=FIELD_WIDTH_CHARS
        ),
    )

    handle: str
    google_account: str
    languages: tuple[str, ...]
    privacy: str
    account_name: str = ""

    @classmethod
    def blank(cls) -> ChannelDraft:
        """Пустая строка нового канала: языка нет, видимость — первый вариант перечня, названия ещё нет."""
        return cls(handle="", google_account="", languages=(), privacy=PRIVACY_CHOICES[0])

    @classmethod
    def of(cls, channel: ChannelConfig) -> ChannelDraft:
        """Черновик уже годного канала — то, что окно показывает в строке; название — прежнее."""
        return cls(
            handle=channel.handle,
            google_account=channel.google_account,
            languages=channel.languages,
            privacy=channel.privacy.value,
            account_name=channel.account_name,
        )

    def as_new(self) -> ChannelDraft:
        """Тот же черновик как новый канал: названия ещё нет — его даст ник."""
        return dataclasses.replace(self, account_name="")

    @property
    def channel_name(self) -> str:
        """Название канала для файла: прежнее, а у нового — ник без «@»."""
        return self.account_name or str(HANDLE_FIELD.data(self.handle)).removeprefix(ChannelHandle.PREFIX)

    def to_data(self) -> dict[str, object]:
        """Объект channels.json из введённого, поля в порядке ключей: площадка — YouTube, название — `channel_name`,
        прочее — по виду поля.

        Регистр языков не исправляется: правило строчных — у загрузчика, и он назовёт ошибку сам.
        """
        data: dict[str, object] = {
            ChannelKey.PLATFORM.value: Platform.YOUTUBE.value, ChannelKey.ACCOUNT_NAME.value: self.channel_name,
        }
        data.update({field.key_path: field.data(getattr(self, field.name)) for field in self.FIELDS})
        return data
