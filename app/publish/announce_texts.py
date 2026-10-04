"""Тексты объявлений в Telegram (CLAUDE.md §3 шаг 6a, §13 задача 4.5, §14 решения 19, 23, 24, 31).

Тексты — стартовые данные restreamer (секция telegram `templates.yaml` и `app_config.example.yaml`, флаги языков
`language_display.py`) в ресурсе `announce_texts.json`: строки каждого текста — списком, соединяются переводом строки.
Объявления читают стримеры разных стран, поэтому на язык окна они не переводятся (решение 24); строки консоли о них —
в каталогах msg.

Сообщения уходят с разметкой HTML (`BotRequest.message`), поэтому правило одно и живёт здесь: каждое значение,
которое подставляется в шаблон сообщения, экранируется (`&`, `<`, `>`) — голый `&` Bot API отвергает кодом 400;
разметки в шаблонах нет. Подпись пакета уходит без разметки и не экранируется.
"""
from __future__ import annotations

import html
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.core.text_format import NEWLINE
from app.packages.package import PackagePeriod
from app.publish.day import DayTimes
from app.resources.loader import TextResource
from app.slots.slot import StreamSlot

ANNOUNCE_TEXTS_RESOURCE: Final[str] = "announce_texts.json"
# Флаг — пара региональных знаков Unicode: «A» кода страны — U+1F1E6, дальше по алфавиту.
REGIONAL_INDICATOR_A: Final[int] = 0x1F1E6
LATIN_A: Final[str] = "A"
COUNTRY_CODE_LENGTH: Final[int] = 2


class AnnounceKey(str, Enum):
    """Ключи ресурса текстов объявлений."""

    DAY_START = "day_start"
    HEADER = "header"                  # шапка дня: время, срок ключей, форма
    DOC = "doc"                        # строки документа даты — только когда он есть
    SLOT = "slot"                      # блок слота: дата и время, название, описание
    FORM_REMINDER = "form_reminder"
    DAY_END = "day_end"
    PACKAGE_CAPTION = "package_caption"
    FLAG_REPEAT = "flag_repeat"
    FLAG_COUNTRIES = "flag_countries"  # код страны флага по языку; нет — сам код языка
    FLAG_FALLBACK = "flag_fallback"    # код не из двух латинских букв


@dataclass(frozen=True)
class AnnounceTexts:
    """Тексты объявлений из ресурса: каждый — готовой строкой сообщения."""

    resource: TextResource = field(default_factory=lambda: TextResource(ANNOUNCE_TEXTS_RESOURCE))

    @property
    def day_start(self) -> str:
        return self._message(AnnounceKey.DAY_START)

    @property
    def day_end(self) -> str:
        return self._message(AnnounceKey.DAY_END)

    def header(self, times: DayTimes, form_url: str, doc_url: str | None) -> str:
        """Шапка дня; документ даты есть — под ней строки со ссылкой на него."""
        header: str = self._message(AnnounceKey.HEADER, **times.values, form_url=form_url)
        if doc_url is None:
            return header
        return header + NEWLINE + self._message(AnnounceKey.DOC, doc_url=doc_url)

    def flags(self, language: str) -> str:
        """Флаг языка слота, повторённый `flag_repeat` раз."""
        countries: Mapping[str, str] = self.resource.data[AnnounceKey.FLAG_COUNTRIES]
        country: str = countries.get(language, language.upper())
        is_latin_pair: bool = len(country) == COUNTRY_CODE_LENGTH and country.isascii() and country.isalpha()
        flag: str = self._flag(country.upper()) if is_latin_pair else self.resource.data[AnnounceKey.FLAG_FALLBACK]
        return flag * int(self.resource.data[AnnounceKey.FLAG_REPEAT])

    def slot(self, slot: StreamSlot) -> str:
        """Блок слота: дата DD.MM.YYYY и время по Киеву, флаги, название и описание."""
        return self._message(
            AnnounceKey.SLOT, date=slot.human_date, time=slot.time, flags=self.flags(slot.language),
            title=slot.title, description=slot.description,
        )

    def form_reminder(self, form_url: str) -> str:
        return self._message(AnnounceKey.FORM_REMINDER, form_url=form_url)

    def package_caption(self, period: PackagePeriod, slots: int, previews: int) -> str:
        """Подпись пакета: период DD.MM.YYYY, число слотов и обложек. Уходит без разметки — не экранируется."""
        return self._joined(AnnounceKey.PACKAGE_CAPTION).format(
            period_from=period.first_human, period_to=period.last_human, slots=slots, previews=previews
        )

    def _message(self, key: AnnounceKey, **values: str) -> str:
        """Текст сообщения HTML: значения экранированы, шаблон разметки не несёт."""
        escaped: dict[str, str] = {name: html.escape(value, quote=False) for name, value in values.items()}
        return self._joined(key).format(**escaped)

    def _joined(self, key: AnnounceKey) -> str:
        lines: Sequence[str] = self.resource.data[key]
        return NEWLINE.join(lines)

    def _flag(self, country: str) -> str:
        """Пара региональных знаков по двум латинским буквам кода страны."""
        return "".join(chr(REGIONAL_INDICATOR_A + ord(letter) - ord(LATIN_A)) for letter in country)
