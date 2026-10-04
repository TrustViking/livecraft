"""Документ объявлений одной даты (app\\publish\\doc_day.py, CLAUDE.md §13 задачи 4.4, 4.5): дни — общие с Telegram
(`PublishDay`), имя документа и шапка для стримеров — время дня (`DayTimes`, его правила — test_publish_day.py), форма,
контакты и перечень эфиров."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.config.docs import DocAccess, DocsSettings
from app.config.settings import LivecraftSettings
from app.publish.doc_copy import DocCopySaved
from app.publish.doc_day import DocDay
from app.publish.doc_stage import DocDocument
from app.publish.doc_texts import DocLine, DocLines, DocTexts
from app.tests.conftest import FORM_URL
from app.tests.fixtures.publish import CREATED, KYIV, doc_run, doc_settings, doc_video
from app.tests.fixtures.settings import with_docs
from app.ui import messages_ru as msg

TEXTS: DocTexts = DocTexts()
LINK_A: str = "https://youtu.be/dQw4w9WgXcQ"
LINK_B: str = "https://youtu.be/aB3_-xYz012"


def _days(tmp_path: Path, *starts: tuple[datetime, str]) -> tuple[DocDay, ...]:
    """Дни документа по видео с этими стартами и языками — через ту же часть, что в запуске."""
    links: tuple[str, ...] = (LINK_A, LINK_B, "https://youtu.be/Zx9_8yW7v6U")
    videos = [doc_video(row + 2, links[row], start, language) for row, (start, language) in enumerate(starts)]
    return doc_run(tmp_path, videos, on_drive=False).doc_days(TEXTS)


def _texts(lines: DocLines) -> list[str]:
    return [line.text for line in lines.lines]


def test_slots_are_grouped_by_date_in_slot_order(tmp_path: Path) -> None:
    days: tuple[DocDay, ...] = _days(
        tmp_path,
        (datetime(2026, 9, 29, 19, 0, tzinfo=KYIV), "uk"),
        (datetime(2026, 9, 28, 21, 0, tzinfo=KYIV), "en"),
        (datetime(2026, 9, 28, 20, 0, tzinfo=KYIV), "uk"),
    )
    assert [day.date for day in days] == ["28-09-2026", "29-09-2026"]
    assert [slot.heading for slot in days[0].slots] == ["UK - 20:00", "EN - 21:00"]
    assert [slot.slot for slot in days[0].slots] == list(days[0].day.slots)


def test_the_name_carries_the_date_and_the_creation_time(tmp_path: Path) -> None:
    [day] = _days(tmp_path, (datetime(2026, 9, 28, 19, 0, tzinfo=KYIV), "uk"))
    assert day.name(TEXTS, CREATED) == "28-09-2026_Ежедневные стримы - Everyday streams_10:05"


def test_people_see_the_date_with_dots_the_name_and_the_key_keep_dashes(tmp_path: Path) -> None:
    """Дата для людей — «17.03.2027» (§14 решение 31): в шапке и в строках консоли; имя документа, ключ документа
    даты и лог — «17-03-2027»."""
    [day] = _days(tmp_path, (datetime(2027, 3, 17, 19, 0, tzinfo=KYIV), "uk"))
    assert (day.date, day.human_date) == ("17-03-2027", "17.03.2027")
    assert day.name(TEXTS, CREATED).startswith("17-03-2027_")
    assert "❇️ Эфир 17.03.2027  Скинуть ключи до 18:00 по Киеву" in _texts(day.header(TEXTS, doc_settings()))
    url: str = "https://docs.google.com/document/d/doc1/edit"
    shown: str = str(Path("docs", "17-03-2027", "copy.docx"))
    copy: DocCopySaved = DocCopySaved(path=tmp_path / shown, shown=shown)
    document: DocDocument = DocDocument(day, day.name(TEXTS, CREATED), url, 1, 0, copy)
    assert document.date == "17-03-2027"
    assert document.console_line == (
        msg.DOC_LINE.format(date="17.03.2027", url=url, placed=1, total=1) + msg.DOC_COPY_SAVED.format(path=shown)
    )
    assert document.event.text.startswith("doc_created date=17-03-2027 ")


def test_the_header_takes_the_times_of_its_day(tmp_path: Path) -> None:
    """Время шапки — время дня (`PublishDay.times`): лето, 29-03-2027 — Киев UTC+3, Берлин UTC+2."""
    [day] = _days(tmp_path, (datetime(2027, 3, 29, 19, 0, tzinfo=KYIV), "uk"))
    lines: list[str] = _texts(day.header(TEXTS, doc_settings()))
    assert lines[:9] == [
        "Ежедневные стримы / Everyday streams",
        "18:00 CET/CEST (19:00 Kiev, 16:00 GMT)",
        "",
        "❇️ Эфир 29.03.2027  Скинуть ключи до 18:00 по Киеву",
        "Drop the keys off before 15:00 GMT",
        "",
        "❇️ Форма для ключей /  Form for keys",
        FORM_URL,
        "",
    ]


def test_without_contacts_there_is_no_contacts_block_and_the_slots_follow(tmp_path: Path) -> None:
    day: DocDay = _days(
        tmp_path, (datetime(2026, 9, 28, 19, 0, tzinfo=KYIV), "uk"), (datetime(2026, 9, 28, 20, 0, tzinfo=KYIV), "en")
    )[0]
    lines: DocLines = day.header(TEXTS, doc_settings())
    assert _texts(lines)[9:] == [
        "❇️ Опис / Description / Описание", "", "UK - 19:00", "Видео 2", "", "EN - 20:00", "Видео 3",
    ]
    assert not any("Contact" in text for text in _texts(lines))
    bold: list[str] = [line.text for line in lines.lines if line.is_bold and line.text]
    assert bold == [
        "Ежедневные стримы / Everyday streams", "❇️ Эфир 28.09.2026  Скинуть ключи до 18:00 по Киеву",
        "❇️ Форма для ключей /  Form for keys", "❇️ Опис / Description / Описание", "UK - 19:00", "EN - 20:00",
    ]


def test_contacts_add_their_block_after_the_form(tmp_path: Path) -> None:
    [day] = _days(tmp_path, (datetime(2026, 9, 28, 19, 0, tzinfo=KYIV), "uk"))
    settings: LivecraftSettings = with_docs(doc_settings(), DocsSettings(access=DocAccess.WRITER, contacts="@help"))
    lines: DocLines = day.header(TEXTS, settings)
    assert lines.lines[9:12] == (
        DocLine("При технических проблемах / In case of technical problems", True),
        DocLine("Contact: @help", False),
        DocLine("", False),
    )
