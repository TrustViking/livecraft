"""Тексты документа объявлений: имя, строки шапки и метки таблицы слота (CLAUDE.md §13 задача 4.4, §14 решение 23).

Тексты — стартовые данные restreamer (секция google_doc `templates.yaml`, строки шапки `build_daily_doc_header`) в
ресурсе `doc_texts.json`: у каждой строки шапки — признак, жирная ли она. Документ читают стримеры разных стран,
поэтому он не переводится на язык окна (решение 24): шапка двуязычная, метки таблицы — на языке слота (uk, en, ru;
прочие — метки `labels_fallback`).

`DocLine` — строка с признаком жирной, `DocLines` — строки подряд: сами дают свой текст и запросы вставки с индекса
(текст целиком, Arial 13, жирные строки поверх).
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Final

from app.core.dates import format_time
from app.core.text_format import NEWLINE
from app.publish.doc_request import DocRange, DocRequest, InsertText, TextStyle, utf16_length
from app.resources.loader import TextResource

DOC_TEXTS_RESOURCE: Final[str] = "doc_texts.json"


class DocTextKey(str, Enum):
    """Ключи ресурса текстов документа."""

    NAME = "name"
    HEADER = "header"            # шапка до контактов
    CONTACTS = "contacts"        # блок контактов — только когда они заданы
    SLOTS = "slots"              # заголовок перечня эфиров
    SLOT = "slot"                # эфир в перечне: язык и время, название
    SLOT_GAP = "slot_gap"        # между эфирами перечня
    HEADING = "heading"
    LABELS = "labels"
    LABELS_FALLBACK = "labels_fallback"
    TEXT = "text"
    BOLD = "bold"


class DocLabel(str, Enum):
    """Метки таблицы слота."""

    TITLE = "title"
    DESCRIPTION = "description"
    PREVIEW = "preview"


@dataclass(frozen=True)
class DocLine:
    """Строка текста документа и жирная ли она."""

    text: str
    is_bold: bool


@dataclass(frozen=True)
class DocLines:
    """Строки подряд — одним текстом через перевод строки."""

    lines: tuple[DocLine, ...]

    @property
    def text(self) -> str:
        return NEWLINE.join(line.text for line in self.lines)

    def requests(self, start: int) -> tuple[DocRequest, ...]:
        """Вставить текст с `start`: весь — обычным, затем жирные непустые строки — жирными."""
        requests: list[DocRequest] = [
            InsertText(self.text, start), TextStyle(DocRange.of_text(start, self.text), False)
        ]
        cursor: int = start
        for line in self.lines:
            if line.is_bold and line.text:
                requests.append(TextStyle(DocRange.of_text(cursor, line.text), True))
            cursor += utf16_length(line.text + NEWLINE)
        return tuple(requests)


@dataclass(frozen=True)
class DocLabels:
    """Метки таблицы слота на его языке."""

    title: str
    description: str
    preview: str


@dataclass(frozen=True)
class DocTexts:
    """Тексты документа из ресурса."""

    resource: TextResource = field(default_factory=lambda: TextResource(DOC_TEXTS_RESOURCE))

    def name(self, date: str, created: datetime) -> str:
        """Имя документа: дата эфиров и время создания HH:MM."""
        return str(self.resource.data[DocTextKey.NAME]).format(date=date, created=format_time(created.time()))

    def lines(self, key: DocTextKey, **values: str) -> DocLines:
        """Строки части шапки с подставленными значениями."""
        raw: Sequence[Mapping[str, str | bool]] = self.resource.data[key]
        return DocLines(
            tuple(DocLine(str(line[DocTextKey.TEXT]).format(**values), bool(line[DocTextKey.BOLD])) for line in raw)
        )

    def heading(self, language: str, time: str) -> str:
        """«UK - 19:00»: код языка слота прописными и время старта."""
        return str(self.resource.data[DocTextKey.HEADING]).format(language=language.upper(), time=time)

    def labels(self, language: str) -> DocLabels:
        """Метки на языке слота; нет такого языка — запасные."""
        by_language: Mapping[str, Mapping[str, str]] = self.resource.data[DocTextKey.LABELS]
        fallback: str = self.resource.data[DocTextKey.LABELS_FALLBACK]
        chosen: Mapping[str, str] = by_language.get(language) or by_language[fallback]
        return DocLabels(*(chosen[label] for label in DocLabel))
