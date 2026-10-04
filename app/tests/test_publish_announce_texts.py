"""Тексты объявлений в Telegram (app\\publish\\announce_texts.py, CLAUDE.md §13 задача 4.5): значения экранированы для
HTML-режима, шапка со строками документа и без них, флаги языков, подпись пакета с датами DD.MM.YYYY."""
from __future__ import annotations

from datetime import date, datetime

import pytest

from app.packages.package import PackagePeriod
from app.publish.announce_texts import AnnounceTexts
from app.publish.day import DayTimes
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.tests.fixtures.announce import KYIV, stream_slot

TEXTS: AnnounceTexts = AnnounceTexts()
TIMES: DayTimes = DayTimes("16.10.2026", "18:00", "19:00", "16:00", "18:00", "15:00")
FORM: str = "https://docs.google.com/forms/d/e/1FAIpQL/viewform?usp=pp_url&entry.1=a<b>"
FORM_ESCAPED: str = "https://docs.google.com/forms/d/e/1FAIpQL/viewform?usp=pp_url&amp;entry.1=a&lt;b&gt;"
DOC: str = "https://docs.google.com/document/d/doc1/edit?a=1&b=2"
HEADER: list[str] = [
    "Ежедневные стримы / Everyday streams",
    "18:00 CET/CEST (19:00 Kiev, 16:00 GMT)",
    "",
    "❇️ Эфир 🚨 16.10.2026 / Скинуть ключи за час до эфира",
    "Broadcast / Drop the keys off 1 hour before the stream",
    "",
    "❇️ Форма для ключей / Form for keys",
    FORM_ESCAPED,
]


def test_the_header_without_a_document_has_no_document_lines() -> None:
    assert TEXTS.header(TIMES, FORM, None).split("\n") == HEADER


def test_the_header_with_a_document_links_it_below() -> None:
    assert TEXTS.header(TIMES, FORM, DOC).split("\n") == [
        *HEADER, "", "❇️ Описание / Description", "https://docs.google.com/document/d/doc1/edit?a=1&amp;b=2",
    ]


def test_the_slot_block_escapes_the_title_and_the_description() -> None:
    """Голый & Bot API отвергает кодом 400, а < и > он читает как разметку: значения экранируются, шаблон — нет."""
    texts: SlotTexts = SlotTexts(
        title="Q&A <live>", description="Ціни > 5 & <b>не жирно</b>", origin=SlotTextOrigin.SOURCE_SINGLE
    )
    block: str = TEXTS.slot(stream_slot(datetime(2026, 10, 16, 19, 0, tzinfo=KYIV), "uk", texts))
    assert block.split("\n") == [
        "16.10.2026 на 19:00 по Киеву",
        "",
        "📌Название и описание эфира 🇺🇦🇺🇦🇺🇦",
        "Name and description of stream",
        "",
        "Q&amp;A &lt;live&gt;",
        "",
        "Ціни &gt; 5 &amp; &lt;b&gt;не жирно&lt;/b&gt;",
    ]


def test_the_form_reminder_escapes_the_link() -> None:
    assert TEXTS.form_reminder(FORM).split("\n") == [
        "📌📌📌 Форма для ключей 🔑 ( Key registration form) 📍", FORM_ESCAPED,
    ]


def test_the_day_starts_and_ends_with_its_marks() -> None:
    assert TEXTS.day_start == "🔵" * 12
    assert TEXTS.day_end == "✨" * 7


@pytest.mark.parametrize(
    ("language", "flags"),
    [
        ("uk", "🇺🇦🇺🇦🇺🇦"),          # страна по языку
        ("en", "🇬🇧🇬🇧🇬🇧"),
        ("fr", "🇫🇷🇫🇷🇫🇷"),          # страны по языку нет — код языка
        ("zh-hant", "🌐🌐🌐"),       # не две буквы
        ("ук", "🌐🌐🌐"),            # не латиница
    ],
)
def test_the_flag_of_a_language(language: str, flags: str) -> None:
    assert TEXTS.flags(language) == flags


def test_the_package_caption_names_the_period_with_dots_and_is_not_escaped() -> None:
    period: PackagePeriod = PackagePeriod(first=date(2026, 10, 16), last=date(2026, 10, 17))
    assert TEXTS.package_caption(period, 3, 4) == "📦 Пакет эфиров: 16.10.2026 — 17.10.2026\nСлотов: 3, обложек: 4"
