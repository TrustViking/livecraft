"""Страница ответа формы: записан ли ответ (CLAUDE.md §3 шаг 11, §13 задача 5.1).

Подтверждение структурное, от языка страницы не зависит. Опыт 13-09-2026 (planers): страница успеха — заглушка без
полей формы, в ней нет ни одного entry.<цифры> и нет fbzx; страница отказа — перерисованный раздел формы с полем
entry.<цифры> и скрытым fbzx (иначе её нельзя было бы дозаполнить), пришла с HTTP 400. Записан = HTTP 200 + страница
Google Forms (FB_PUBLIC_LOAD_DATA_) + ни entry.<цифры>, ни fbzx: пустой или чужой ответ 200 доставкой ключа не
считается. Текстовый маркер «ответ записан» — только сигнал в лог: язык страницы Google выбирает сам.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from http import HTTPStatus
from typing import Final

from app.core.text_format import SPACE
from app.form.payload import PAYLOAD_NAME
from app.form.submission import BodyField
from app.form.transport import HttpAnswer
from app.observability.log_event import LogEvent, Quoted

ENTRY_FIELD_PATTERN: Final[re.Pattern[str]] = re.compile(r"entry\.\d+")
PAGE_TITLE_PATTERN: Final[re.Pattern[str]] = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
# Маркер английской страницы ответа (с hl=en страницы опыта 13-09-2026 пришли на английском); сравнение — по
# вхождению в нижнем регистре, без точки.
CONFIRMATION_MARKERS: Final[tuple[str, ...]] = ("your response has been recorded",)


@dataclass(frozen=True)
class ResponsePage:
    """Оба сигнала страницы ответа: решает структурный (`is_confirmed`), маркер и заголовок — только в лог."""

    http_status: int
    entry_fields: int          # вхождений entry.<цифры>: у страницы отказа есть, у успеха нет
    has_fbzx: bool
    is_form_page: bool         # это страница Google Forms, а не пустой или чужой ответ
    marker: str | None         # какой из CONFIRMATION_MARKERS совпал; None — ни один
    title: str                 # заголовок страницы: разбор без открытия сохранённого файла

    @classmethod
    def of(cls, answer: HttpAnswer) -> ResponsePage:
        lowered: str = answer.text.lower()
        title: re.Match[str] | None = PAGE_TITLE_PATTERN.search(answer.text)
        return cls(
            http_status=answer.status,
            entry_fields=len(ENTRY_FIELD_PATTERN.findall(answer.text)),
            has_fbzx=BodyField.FBZX.value in answer.text,
            is_form_page=PAYLOAD_NAME in answer.text,
            marker=next((marker for marker in CONFIRMATION_MARKERS if marker in lowered), None),
            title="" if title is None else SPACE.join(html.unescape(title.group(1)).split()),
        )

    @property
    def is_confirmed(self) -> bool:
        """Ответ записан: HTTP 200, страница Google Forms, ни entry.<цифры>, ни fbzx."""
        is_stub: bool = self.entry_fields == 0 and not self.has_fbzx
        return self.http_status == HTTPStatus.OK and self.is_form_page and is_stub

    def extend(self, event: LogEvent) -> LogEvent:
        """Поля страницы в строке лога."""
        return event.extended(
            http_status=self.http_status,
            entry_fields=self.entry_fields,
            fbzx=self.has_fbzx,
            form_page=self.is_form_page,
            marker=Quoted(self.marker),
        )
