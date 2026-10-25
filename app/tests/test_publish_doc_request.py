"""Запросы documents.batchUpdate документа объявлений (app\\publish\\doc_request.py, CLAUDE.md §13 задача 4.4): длина в
единицах UTF-16 и формы тел Docs API v1."""
from __future__ import annotations

from app.publish.doc_request import (
    BLANK_PARAGRAPH, Alignment, CellBackground, DocRange, InlineImage, InsertText, PageBreakAtEnd, ParagraphStyle,
    RgbColor, TableAtEnd, TextStyle, utf16_length,
)


def test_the_length_is_counted_in_utf16_units() -> None:
    """«❇️» — знак и селектор вида: две единицы; эмодзи вне BMP — пара суррогатов; кириллица — по одной."""
    assert utf16_length("❇️") == 2
    assert utf16_length("❇️ Эфир") == 7
    assert utf16_length("😀") == 2 and len("😀") == 1
    assert utf16_length("") == 0
    assert DocRange.of_text(10, "❇️ Эфир") == DocRange(10, 17)


def test_text_goes_to_an_index_or_to_the_end() -> None:
    assert InsertText("Шапка", 1).body == {"insertText": {"location": {"index": 1}, "text": "Шапка"}}
    assert BLANK_PARAGRAPH.body == {"insertText": {"endOfSegmentLocation": {}, "text": "\n"}}


def test_the_table_and_the_page_break_go_to_the_end() -> None:
    assert TableAtEnd(rows=7).body == {"insertTable": {"rows": 7, "columns": 1, "endOfSegmentLocation": {}}}
    assert PageBreakAtEnd().body == {"insertPageBreak": {"endOfSegmentLocation": {}}}


def test_the_text_style_is_arial_13_bold_or_not() -> None:
    assert TextStyle(DocRange(1, 5), True).body == {
        "updateTextStyle": {
            "range": {"startIndex": 1, "endIndex": 5},
            "textStyle": {"weightedFontFamily": {"fontFamily": "Arial"}, "fontSize": {"magnitude": 13, "unit": "PT"},
                          "bold": True},
            "fields": "weightedFontFamily,fontSize,bold",
        }
    }


def test_the_paragraph_style_sets_only_the_alignment() -> None:
    assert ParagraphStyle(DocRange(65, 70), Alignment.CENTER).body == {
        "updateParagraphStyle": {
            "range": {"startIndex": 65, "endIndex": 70}, "paragraphStyle": {"alignment": "CENTER"}, "fields": "alignment",
        }
    }


def test_the_cell_background_is_located_from_the_table_start() -> None:
    body = CellBackground(table_start=62, row=3, color=RgbColor(0.81, 0.86, 0.78)).body
    assert body == {
        "updateTableCellStyle": {
            "tableRange": {
                "tableCellLocation": {"tableStartLocation": {"index": 62}, "rowIndex": 3, "columnIndex": 0},
                "rowSpan": 1, "columnSpan": 1,
            },
            "tableCellStyle": {"backgroundColor": {"color": {"rgbColor": {"red": 0.81, "green": 0.86, "blue": 0.78}}}},
            "fields": "backgroundColor",
        }
    }


def test_the_image_has_its_place_address_and_size_in_points() -> None:
    assert InlineImage(90, "https://i.ytimg.com/vi/x/hqdefault.jpg", 210, 120).body == {
        "insertInlineImage": {
            "location": {"index": 90},
            "uri": "https://i.ytimg.com/vi/x/hqdefault.jpg",
            "objectSize": {"height": {"magnitude": 120, "unit": "PT"}, "width": {"magnitude": 210, "unit": "PT"}},
        }
    }
