"""Таблица слота в документе объявлений (app\\publish\\doc_slot.py, CLAUDE.md §13 задачи 4.4, 9.13): строки и их вид,
запросы текста от последней ячейки к первой, фон от начала таблицы, обложки — копия с Диска первой, от последнего
источника; разметка `*…*` — жирным без звёздочек, ссылка на видео — короткая (§14 решение 63)."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from app.google.docs import DocsTable
from app.publish.doc_day import DocDay
from app.publish.doc_request import (
    Alignment, CellBackground, DocRange, InsertText, PageBreakAtEnd, ParagraphStyle, TableAtEnd, TextStyle, BLANK_PARAGRAPH,
)
from app.publish.doc_slot import (
    DESCRIPTION_LABEL_COLOR, HEADING_COLOR, PREVIEW_LABEL_COLOR, TITLE_LABEL_COLOR, CoverSpot, DocCell, DocSlot, DocSource,
)
from app.publish.doc_texts import DocTexts
from app.texts.bold_marks import BoldText
from app.tests.fixtures.docs import LAST_TABLE_CELL_STARTS, LAST_TABLE_START
from app.tests.fixtures.publish import KYIV, DocRun, doc_run, doc_settings, doc_video

START: datetime = datetime(2026, 9, 28, 19, 0, tzinfo=KYIV)
LINK_A: str = "https://youtu.be/dQw4w9WgXcQ"
LINK_B: str = "https://youtu.be/aB3_-xYz012"
# Источник слота — ссылка watch?v=<id> (`StreamSlot.sources`): так её видит документ от любого входа; в ячейке она
# короткая — youtu.be/<id>.
WATCH_A: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
WATCH_B: str = "https://www.youtube.com/watch?v=aB3_-xYz012"
TABLE: DocsTable = DocsTable(start_index=LAST_TABLE_START, cell_starts=LAST_TABLE_CELL_STARTS)


def _slot(tmp_path: Path, on_drive: bool = True, language: str = "uk") -> DocSlot:
    """Слот 19:00 из двух видео (строки 2 и 3) — тем же путём, что в запуске: слоты таблицы → дни → слоты документа."""
    videos = [doc_video(2, LINK_A, START, language), doc_video(3, LINK_B, START, language)]
    run: DocRun = doc_run(tmp_path, videos, on_drive)
    [day] = run.doc_days(DocTexts())
    [slot] = day.slots
    return slot


def _single(tmp_path: Path, title: str) -> DocDay:
    """День со слотом из одного видео с названием `title`: тексты видео идут как есть (§14 решение 61)."""
    run: DocRun = doc_run(tmp_path, [doc_video(2, LINK_A, START, title=title)])
    [day] = run.doc_days(DocTexts())
    return day


def test_the_cells_are_heading_title_description_preview_and_one_row_per_source(tmp_path: Path) -> None:
    slot: DocSlot = _slot(tmp_path)
    assert slot.cells == (
        DocCell(BoldText.unmarked("UK - 19:00"), True, Alignment.CENTER, HEADING_COLOR),
        DocCell(BoldText.unmarked("НАЗВА"), True, Alignment.CENTER, TITLE_LABEL_COLOR),
        DocCell(BoldText.of(slot.slot.title), True, Alignment.JUSTIFIED),
        DocCell(BoldText.unmarked("ОПИС"), True, Alignment.CENTER, DESCRIPTION_LABEL_COLOR),
        DocCell(BoldText.of(slot.slot.description), False, Alignment.JUSTIFIED),
        DocCell(BoldText.unmarked("ПРЕВ'Ю"), True, Alignment.CENTER, PREVIEW_LABEL_COLOR),
        DocCell(BoldText.unmarked(LINK_A + "\n"), False),
        DocCell(BoldText.unmarked(LINK_B + "\n"), False),
    )


def test_the_labels_follow_the_slot_language(tmp_path: Path) -> None:
    """Метки — на языке слота; язык без своих меток (de) — английские."""
    for language, heading in (("en", "EN - 19:00"), ("de", "DE - 19:00")):
        cells: tuple[DocCell, ...] = _slot(tmp_path, language=language).cells
        assert [cells[row].text.plain for row in (0, 1, 3, 5)] == [heading, "TITLE", "DESCRIPTION", "PREVIEW"]


def test_the_cover_is_the_drive_copy_first_then_the_youtube_thumbnail(tmp_path: Path) -> None:
    source = _slot(tmp_path).sources[0]
    assert len(source.covers) == 2 and source.covers[0].startswith("https://drive.google.com/uc?export=download&id=")
    assert source.covers[1] == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    assert _slot(tmp_path, on_drive=False).sources[0].covers == ("https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg",)


def test_the_source_cell_shows_the_short_link_and_the_cover_is_found_by_the_slot_link() -> None:
    """В ячейке — youtu.be/<id>; обложка — по ссылке слота как она есть (watch?v=), ссылка не YouTube — как есть."""
    copy: str = "https://drive.google.com/uc?export=download&id=X"
    source: DocSource = DocSource.of(WATCH_A, {WATCH_A: copy, LINK_A: "https://drive.google.com/other"})
    assert source.link == WATCH_A and source.cell_text == LINK_A + "\n"
    assert source.covers == (copy, "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg")
    other: DocSource = DocSource.of("https://vimeo.com/123", {})
    assert other.cell_text == "https://vimeo.com/123\n" and other.covers == ()


def test_the_table_goes_to_the_end_after_a_blank_paragraph_or_a_page_break(tmp_path: Path) -> None:
    slot: DocSlot = _slot(tmp_path)
    assert slot.table_requests(is_first=True) == (BLANK_PARAGRAPH, TableAtEnd(rows=8))
    assert slot.table_requests(is_first=False) == (PageBreakAtEnd(), TableAtEnd(rows=8))


def test_backgrounds_come_first_and_texts_go_from_the_last_cell_to_the_first(tmp_path: Path) -> None:
    slot: DocSlot = _slot(tmp_path)
    requests = slot.cell_requests(TABLE)
    assert requests[:4] == tuple(
        CellBackground(LAST_TABLE_START, row, color)
        for row, color in ((0, HEADING_COLOR), (1, TITLE_LABEL_COLOR), (3, DESCRIPTION_LABEL_COLOR), (5, PREVIEW_LABEL_COLOR))
    )
    inserts: list[InsertText] = [request for request in requests if isinstance(request, InsertText)]
    assert [insert.index for insert in inserts] == list(reversed(LAST_TABLE_CELL_STARTS))
    assert inserts[0] == InsertText(LINK_B + "\n", LAST_TABLE_CELL_STARTS[7])
    assert inserts[-1] == InsertText("UK - 19:00", LAST_TABLE_CELL_STARTS[0])


def test_each_cell_styles_its_own_text_and_paragraph(tmp_path: Path) -> None:
    """Вид — по отрезку текста ячейки без последнего перевода строки; выравнивание — по всей ячейке."""
    slot: DocSlot = _slot(tmp_path)
    requests = slot.cell_requests(TABLE)
    heading = DocCell(BoldText.unmarked("UK - 19:00"), True, Alignment.CENTER, HEADING_COLOR).requests(65)
    assert heading == (
        InsertText("UK - 19:00", 65), TextStyle(DocRange(65, 75), True), ParagraphStyle(DocRange(65, 76), Alignment.CENTER)
    )
    assert requests[-3:] == heading
    source = DocCell(BoldText.unmarked(LINK_A + "\n"), False).requests(83)
    assert source == (InsertText(LINK_A + "\n", 83), TextStyle(DocRange(83, 83 + len(LINK_A)), False))


def test_an_empty_text_is_not_inserted_but_its_paragraph_is_aligned() -> None:
    assert DocCell(BoldText.of(""), False, Alignment.START).requests(77) == (
        ParagraphStyle(DocRange(77, 78), Alignment.START),
    )


def test_the_description_goes_in_without_stars_and_its_marked_parts_are_bold_by_utf16_offsets() -> None:
    """Описание «🔹 *Тема:* огляд» — без звёздочек; эмодзи — две единицы UTF-16, жирное «Тема:» — с 3 по 8."""
    cell: DocCell = DocCell(BoldText.of("🔹 *Тема:* огляд\n*Підсумок*"), False, Alignment.JUSTIFIED)
    text: str = "🔹 Тема: огляд\nПідсумок"
    assert cell.requests(100) == (
        InsertText(text, 100),
        TextStyle(DocRange(100, 100 + 2 + len(" Тема: огляд\nПідсумок")), False),
        TextStyle(DocRange(103, 108), True),
        TextStyle(DocRange(115, 123), True),
        ParagraphStyle(DocRange(100, 124), Alignment.JUSTIFIED),
    )


def test_the_title_in_the_cell_and_in_the_header_has_no_stars(tmp_path: Path) -> None:
    """Название ячейки — без звёздочек и с жирной частью; в перечне шапки — то же название без звёздочек."""
    day: DocDay = _single(tmp_path, "*Тема:* огляд")
    [slot] = day.slots
    assert slot.slot.title == "*Тема:* огляд"
    inserts: list[InsertText] = [request for request in slot.cell_requests(TABLE) if isinstance(request, InsertText)]
    assert InsertText("Тема: огляд", LAST_TABLE_CELL_STARTS[2]) in inserts
    assert all("*" not in insert.text for insert in inserts)
    header: str = day.header(DocTexts(), doc_settings()).text
    assert "Тема: огляд" in header and "*" not in header


def test_covers_go_under_the_links_from_the_last_source_to_the_first(tmp_path: Path) -> None:
    """Место обложки — под короткой ссылкой ячейки; источник обложки — ссылка слота."""
    slot: DocSlot = _slot(tmp_path)
    spots: tuple[CoverSpot, ...] = slot.cover_spots(TABLE)
    assert [spot.source.link for spot in spots] == [WATCH_B, WATCH_A]
    assert [spot.index for spot in spots] == [86 + len(LINK_B) + 1, 83 + len(LINK_A) + 1]
    image = spots[0].image("https://i.ytimg.com/vi/aB3_-xYz012/hqdefault.jpg")
    assert (image.index, image.width_pt, image.height_pt) == (86 + len(LINK_B) + 1, 210, 120)


def test_a_slot_without_a_drive_copy_of_its_source_gets_the_youtube_thumbnail_only() -> None:
    """Слот из пакета: обложка — копия превью на Диске этого запуска по ссылке видео, её нет — обложка YouTube по id."""
    assert DocSource.of(WATCH_A, {WATCH_A: "https://drive.google.com/uc?export=download&id=X"}).covers == (
        "https://drive.google.com/uc?export=download&id=X", "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
    )
    assert DocSource.of(WATCH_B, {}).covers == ("https://i.ytimg.com/vi/aB3_-xYz012/hqdefault.jpg",)
