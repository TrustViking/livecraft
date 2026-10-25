"""Тексты объявлений в Telegram (app\\publish\\announce_texts.py, CLAUDE.md §13 задачи 4.5, 9.13): значения экранированы
для HTML-режима, разметка `*…*` названия и описания — `<b>…</b>` (§14 решение 63), шапка со строками документа и без
них, блок слота без флага языка (§14 решение 64), подпись пакета с датами DD.MM.YYYY."""
from __future__ import annotations

from datetime import date, datetime

from app.packages.package import PackagePeriod
from app.publish.announce_texts import AnnounceTexts
from app.publish.day import DayTimes
from app.publish.telegram_api import MessageText
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
    assert TEXTS.header(TIMES, FORM, None).text.split("\n") == HEADER


def test_the_header_with_a_document_links_it_below() -> None:
    assert TEXTS.header(TIMES, FORM, DOC).text.split("\n") == [
        *HEADER, "", "❇️ Описание / Description", "https://docs.google.com/document/d/doc1/edit?a=1&amp;b=2",
    ]


def test_the_slot_block_escapes_the_title_and_the_description() -> None:
    """Голый & Bot API отвергает кодом 400, а < и > он читает как разметку: значения экранируются, шаблон — нет."""
    texts: SlotTexts = SlotTexts(
        title="Q&A <live>", description="Ціни > 5 & <b>не жирно</b>", origin=SlotTextOrigin.SOURCE_SINGLE
    )
    block: str = TEXTS.slot(stream_slot(datetime(2026, 10, 16, 19, 0, tzinfo=KYIV), "uk", texts)).text
    assert block.split("\n") == [
        "16.10.2026 на 19:00 по Киеву",
        "",
        "📌Название и описание эфира",
        "Name and description of stream",
        "",
        "Q&amp;A &lt;live&gt;",
        "",
        "Ціни &gt; 5 &amp; &lt;b&gt;не жирно&lt;/b&gt;",
    ]


def test_the_marked_parts_of_the_title_and_the_description_go_bold_with_escaped_text() -> None:
    """Разметка `*…*` — в `<b>…</b>` без звёздочек; `&`, `<`, `>` экранируются и внутри тега, и снаружи; звёздочки, что
    разметкой не стали, остаются."""
    texts: SlotTexts = SlotTexts(
        title="*Q&A:* <live>",
        description="📌 *Тема <1> & 2:* огляд\n• *Підсумок* і 5*3*2 > 1",
        origin=SlotTextOrigin.SOURCE_SINGLE,
    )
    block: str = TEXTS.slot(stream_slot(datetime(2026, 10, 16, 19, 0, tzinfo=KYIV), "uk", texts)).text
    assert block.split("\n")[5:] == [
        "<b>Q&amp;A:</b> &lt;live&gt;",
        "",
        "📌 <b>Тема &lt;1&gt; &amp; 2:</b> огляд",
        "• <b>Підсумок</b> і 5*3*2 &gt; 1",
    ]


def test_a_long_description_with_marks_is_cut_between_lines_and_no_tag_is_torn() -> None:
    """Длинное описание с разметкой в каждой строке режется по переводу строки: в каждом куске теги парные."""
    lines: list[str] = [f"🔹 *Пункт {number}:* {'текст ' * 20}" for number in range(60)]
    texts: SlotTexts = SlotTexts(title="Ефір", description="\n".join(lines), origin=SlotTextOrigin.SOURCE_SINGLE)
    block: str = TEXTS.slot(stream_slot(datetime(2026, 10, 16, 19, 0, tzinfo=KYIV), "uk", texts)).text
    chunks: tuple[str, ...] = MessageText(block).chunks
    assert len(chunks) > 1 and "".join(chunks) == block
    for chunk in chunks:
        assert chunk.count("<b>") == chunk.count("</b>") > 0 and "*" not in chunk


def test_only_the_broadcast_block_goes_without_a_link_preview() -> None:
    """Блок эфира — без предпросмотра: Telegram показал бы видео первой ссылки описания и сделал бы время эфира меткой
    времени этого видео (§14 решение 72); остальные сообщения дня — с предпросмотром, и каждый кусок длинного блока —
    тоже без него."""
    lines: list[str] = [f"🔹 Пункт {number}: {'текст ' * 20}" for number in range(60)]
    texts: SlotTexts = SlotTexts(title="Ефір", description="\n".join(lines), origin=SlotTextOrigin.SOURCE_SINGLE)
    block: MessageText = TEXTS.slot(stream_slot(datetime(2026, 10, 16, 19, 0, tzinfo=KYIV), "uk", texts))
    assert not block.has_preview and len(block.pieces) > 1
    assert all(not piece.has_preview for piece in block.pieces)
    others: tuple[MessageText, ...] = (
        TEXTS.day_start, TEXTS.header(TIMES, FORM, DOC), TEXTS.form_reminder(FORM), TEXTS.day_end
    )
    assert all(text.has_preview for text in others)


def test_the_form_reminder_escapes_the_link() -> None:
    assert TEXTS.form_reminder(FORM).text.split("\n") == [
        "📌📌📌 Форма для ключей 🔑 ( Key registration form) 📍", FORM_ESCAPED,
    ]


def test_the_day_starts_and_ends_with_its_marks() -> None:
    assert TEXTS.day_start.text == "🔵" * 12
    assert TEXTS.day_end.text == "✨" * 7


def test_the_package_caption_names_the_period_with_dots_and_is_not_escaped() -> None:
    period: PackagePeriod = PackagePeriod(first=date(2026, 10, 16), last=date(2026, 10, 17))
    assert TEXTS.package_caption(period, 3, 4) == "📦 Пакет эфиров: 16.10.2026 — 17.10.2026\nЭфиров: 3, превью: 4"
