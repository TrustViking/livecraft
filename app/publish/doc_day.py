"""Документ объявлений одного дня (CLAUDE.md §3 шаг 6a, §13 задача 4.4, §14 решение 51).

`DocDay` — день объявлений (`PublishDay`: дата DD-MM-YYYY, инвариант 4, форма ключей и слоты по порядку) и таблицы его
слотов в документе. День сам строит имя своего документа
(«{дата}_Ежедневные стримы - Everyday streams_{HH:MM создания}», дата — DD-MM-YYYY; второй и следующий день той же даты —
с другой формой — с номером «_2», «_3»: иначе у документов и их копий .docx было бы одно имя) и шапку для стримеров:
дата для людей — DD.MM.YYYY («Эфир 17.03.2027», §14 решение 31), время первого эфира дня по
CET/CEST, по поясу программы и по GMT; срок сдачи ключей — на час раньше первого эфира; ссылка на форму ключей его
слотов; блок контактов — только когда они заданы (`docs.contacts`); по слоту — «UK - 19:00» и название. Шапка встаёт в
начало тела нового документа (индекс 1) одним пакетом правок.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from app.config.settings import LivecraftSettings
from app.publish.day import PublishDay
from app.publish.doc_slot import DocSlot
from app.publish.doc_texts import DocLines, DocTextKey, DocTexts

# Тело нового документа начинается с индекса 1: на 0 стоит разрыв раздела.
HEADER_START_INDEX: Final[int] = 1
# Номер документа среди документов той же даты — со второго: «_2», «_3».
NAME_NUMBER_TEMPLATE: Final[str] = "{name}_{number}"


@dataclass(frozen=True)
class DocDay:
    """День объявлений и слоты его документа в том же порядке. Своей группировки и своего расчёта времени нет: дни —
    у `PublishDay.days`, время шапки — у `PublishDay.times`."""

    day: PublishDay
    slots: tuple[DocSlot, ...]

    @classmethod
    def of(cls, day: PublishDay, covers: Mapping[str, str], texts: DocTexts) -> DocDay:
        """Слоты дня с обложками — копиями превью на Диске этого запуска по ссылкам видео."""
        return cls(day=day, slots=tuple(DocSlot.of(slot, covers, texts) for slot in day.slots))

    @property
    def date(self) -> str:
        """Дата DD-MM-YYYY: имя документа, ключ документа даты и лог."""
        return self.day.date

    @property
    def human_date(self) -> str:
        """Дата эфиров DD.MM.YYYY — для шапки и строк консоли (§14 решение 31)."""
        return self.day.human_date

    def name(self, texts: DocTexts, created: datetime) -> str:
        """Имя документа: дата эфиров и время его создания; второй и следующий день той же даты — с номером."""
        name: str = texts.name(self.date, created)
        return name if self.day.number == 1 else NAME_NUMBER_TEMPLATE.format(name=name, number=self.day.number)

    def header(self, texts: DocTexts, settings: LivecraftSettings) -> DocLines:
        """Шапка: время и срок ключей, форма слотов дня, контакты (если заданы), перечень эфиров «язык - время» и
        названий."""
        parts: list[DocLines] = [texts.lines(DocTextKey.HEADER, **self.day.times.values, form_url=self.day.form.url)]
        if settings.docs.has_contacts:
            parts.append(texts.lines(DocTextKey.CONTACTS, contacts=settings.docs.contacts))
        parts.append(texts.lines(DocTextKey.SLOTS))
        for place, slot in enumerate(self.slots):
            if place:
                parts.append(texts.lines(DocTextKey.SLOT_GAP))
            parts.append(texts.lines(DocTextKey.SLOT, heading=slot.heading, title=slot.slot.title))
        return DocLines(tuple(line for part in parts for line in part.lines))
