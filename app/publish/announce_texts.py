"""Тексты объявлений в Telegram (CLAUDE.md §3 шаг 6a, §13 задача 4.5, §14 решения 19, 23, 24, 31, 72).

Тексты — стартовые данные restreamer (секция telegram `templates.yaml` и `app_config.example.yaml`) в ресурсе
`announce_texts.json`: строки каждого текста — списком, соединяются переводом строки. Флага языка эфира в объявлениях
нет (§14 решение 64).
Объявления читают стримеры разных стран, поэтому на язык окна они не переводятся (решение 24); строки консоли о них —
в каталогах msg.

Сообщения уходят с разметкой HTML (`BotRequest.message`), поэтому правило одно и живёт здесь: каждое значение,
которое подставляется в шаблон сообщения, экранируется (`&`, `<`, `>`) — голый `&` Bot API отвергает кодом 400;
разметки в шаблонах нет. Название и описание эфира несут разметку жирного `*…*` (§14 решение 63): размеченная часть
уходит в `<b>…</b>` без звёздочек, текст внутри и снаружи тега экранируется тем же правилом. Тег не пересекает перевод
строки (`BoldText`), поэтому нарезка длинного сообщения по строкам (`MessageText.chunks`) его не рвёт. Блок эфира
уходит без предпросмотра ссылки (§14 решение 72): иначе Telegram показывает видео первой ссылки описания, а не сам эфир,
и время эфира делает меткой времени этого видео; остальные сообщения — с предпросмотром. Подпись пакета уходит без
разметки и не экранируется.
"""
from __future__ import annotations

import html
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.core.text_format import NEWLINE
from app.packages.package import PackagePeriod
from app.publish.day import DayTimes
from app.publish.telegram_api import MessageText
from app.resources.loader import TextResource
from app.slots.slot import StreamSlot
from app.texts.bold_marks import BoldText

ANNOUNCE_TEXTS_RESOURCE: Final[str] = "announce_texts.json"
BOLD_HTML_TEMPLATE: Final[str] = "<b>{text}</b>"     # жирная часть текста эфира в HTML-режиме Bot API


class AnnounceKey(str, Enum):
    """Ключи ресурса текстов объявлений."""

    DAY_START = "day_start"
    HEADER = "header"                  # шапка дня: время, срок ключей, форма
    DOC = "doc"                        # строки документа даты — только когда он есть
    SLOT = "slot"                      # блок эфира: дата и время, название, описание
    FORM_REMINDER = "form_reminder"
    DAY_END = "day_end"
    PACKAGE_CAPTION = "package_caption"


@dataclass(frozen=True)
class AnnounceTexts:
    """Тексты объявлений из ресурса: каждый — готовой строкой сообщения."""

    resource: TextResource = field(default_factory=lambda: TextResource(ANNOUNCE_TEXTS_RESOURCE))

    @property
    def day_start(self) -> MessageText:
        return MessageText(self._message(AnnounceKey.DAY_START))

    @property
    def day_end(self) -> MessageText:
        return MessageText(self._message(AnnounceKey.DAY_END))

    def header(self, times: DayTimes, form_url: str, doc_url: str | None) -> MessageText:
        """Шапка дня; документ даты есть — под ней строки со ссылкой на него."""
        header: str = self._message(AnnounceKey.HEADER, **times.values, form_url=form_url)
        if doc_url is None:
            return MessageText(header)
        return MessageText(header + NEWLINE + self._message(AnnounceKey.DOC, doc_url=doc_url))

    def slot(self, slot: StreamSlot) -> MessageText:
        """Блок эфира: дата DD.MM.YYYY и время по Киеву, название и описание — без предпросмотра ссылки."""
        text: str = self._message(
            AnnounceKey.SLOT, date=slot.human_date, time=slot.time,
            title=BoldText.of(slot.title), description=BoldText.of(slot.description),
        )
        return MessageText(text, has_preview=False)

    def form_reminder(self, form_url: str) -> MessageText:
        return MessageText(self._message(AnnounceKey.FORM_REMINDER, form_url=form_url))

    def package_caption(self, period: PackagePeriod, slots: int, previews: int) -> str:
        """Подпись пакета: период DD.MM.YYYY, число эфиров и превью. Уходит без разметки — не экранируется."""
        return self._joined(AnnounceKey.PACKAGE_CAPTION).format(
            period_from=period.first_human, period_to=period.last_human, slots=slots, previews=previews
        )

    def _message(self, key: AnnounceKey, **values: str | BoldText) -> str:
        """Текст сообщения HTML: значения экранированы, шаблон разметки не несёт."""
        escaped: dict[str, str] = {name: self._escaped(value) for name, value in values.items()}
        return self._joined(key).format(**escaped)

    def _escaped(self, value: str | BoldText) -> str:
        """Значение для HTML-режима — одно правило экранирования; у текста эфира жирные части — в `<b>…</b>`."""
        if isinstance(value, str):
            return html.escape(value, quote=False)
        return "".join(
            BOLD_HTML_TEMPLATE.format(text=self._escaped(part.text)) if part.is_bold else self._escaped(part.text)
            for part in value.parts
        )

    def _joined(self, key: AnnounceKey) -> str:
        lines: Sequence[str] = self.resource.data[key]
        return NEWLINE.join(lines)
