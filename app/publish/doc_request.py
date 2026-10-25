"""Запросы documents.batchUpdate документа объявлений (CLAUDE.md §13 задача 4.4).

Каждый запрос — значение со своим телом (`body`): вставить текст по индексу или в конец, разрыв страницы, таблицу в
конец, вид текста и абзаца, фон ячейки, картинку по адресу. Формы тел — Docs API v1; вид текста — стартовые данные
restreamer: Arial 13 pt. Индексы Docs считаются в единицах UTF-16 — правило одно, `utf16_length`: «❇️» — две единицы,
а не один знак.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Final, TypeAlias

from app.core.text_format import NEWLINE

UTF16_ENCODING: Final[str] = "utf-16-le"
UTF16_UNIT_BYTES: Final[int] = 2
FONT_FAMILY: Final[str] = "Arial"
FONT_SIZE_PT: Final[float] = 13
POINT_UNIT: Final[str] = "PT"
TEXT_STYLE_FIELDS: Final[str] = "weightedFontFamily,fontSize,bold"
ALIGNMENT_FIELDS: Final[str] = "alignment"
BACKGROUND_FIELDS: Final[str] = "backgroundColor"
ONE_COLUMN: Final[int] = 1

# Тело запроса Docs: вложенные словари и списки.
RequestBody: TypeAlias = dict[str, object]


def utf16_length(text: str) -> int:
    """Длина текста в единицах UTF-16 — так Google Docs считает индексы."""
    return len(text.encode(UTF16_ENCODING)) // UTF16_UNIT_BYTES


class DocsField(str, Enum):
    """Поля тел запросов batchUpdate."""

    INSERT_TEXT = "insertText"
    INSERT_TABLE = "insertTable"
    INSERT_PAGE_BREAK = "insertPageBreak"
    INSERT_INLINE_IMAGE = "insertInlineImage"
    UPDATE_TEXT_STYLE = "updateTextStyle"
    UPDATE_PARAGRAPH_STYLE = "updateParagraphStyle"
    UPDATE_TABLE_CELL_STYLE = "updateTableCellStyle"
    LOCATION = "location"
    END_OF_SEGMENT = "endOfSegmentLocation"
    INDEX = "index"
    TEXT = "text"
    RANGE = "range"
    START_INDEX = "startIndex"
    END_INDEX = "endIndex"
    TEXT_STYLE = "textStyle"
    PARAGRAPH_STYLE = "paragraphStyle"
    FIELDS = "fields"
    FONT = "weightedFontFamily"
    FONT_FAMILY = "fontFamily"
    FONT_SIZE = "fontSize"
    MAGNITUDE = "magnitude"
    UNIT = "unit"
    BOLD = "bold"
    ALIGNMENT = "alignment"
    ROWS = "rows"
    COLUMNS = "columns"
    TABLE_RANGE = "tableRange"
    CELL_LOCATION = "tableCellLocation"
    TABLE_START = "tableStartLocation"
    ROW_INDEX = "rowIndex"
    COLUMN_INDEX = "columnIndex"
    ROW_SPAN = "rowSpan"
    COLUMN_SPAN = "columnSpan"
    CELL_STYLE = "tableCellStyle"
    BACKGROUND = "backgroundColor"
    COLOR = "color"
    RGB = "rgbColor"
    RED = "red"
    GREEN = "green"
    BLUE = "blue"
    URI = "uri"
    OBJECT_SIZE = "objectSize"
    HEIGHT = "height"
    WIDTH = "width"


class Alignment(str, Enum):
    """Выравнивание абзаца."""

    CENTER = "CENTER"
    JUSTIFIED = "JUSTIFIED"
    START = "START"


@dataclass(frozen=True)
class DocRange:
    """Отрезок документа [start, end) в единицах UTF-16."""

    start: int
    end: int

    @classmethod
    def of_text(cls, start: int, text: str) -> DocRange:
        """Отрезок текста, вставленного с `start`."""
        return cls(start, start + utf16_length(text))

    @property
    def body(self) -> RequestBody:
        return {DocsField.START_INDEX.value: self.start, DocsField.END_INDEX.value: self.end}


@dataclass(frozen=True)
class RgbColor:
    """Цвет фона ячейки: доли красного, зелёного и синего (0–1)."""

    red: float
    green: float
    blue: float

    @property
    def body(self) -> RequestBody:
        rgb: RequestBody = {
            DocsField.RED.value: self.red, DocsField.GREEN.value: self.green, DocsField.BLUE.value: self.blue
        }
        return {DocsField.COLOR.value: {DocsField.RGB.value: rgb}}


@dataclass(frozen=True)
class InsertText:
    """Вставить текст по индексу; индекс None — в конец документа."""

    text: str
    index: int | None = None

    @property
    def body(self) -> RequestBody:
        where: RequestBody = {} if self.index is None else {DocsField.INDEX.value: self.index}
        place: str = (DocsField.END_OF_SEGMENT if self.index is None else DocsField.LOCATION).value
        return {DocsField.INSERT_TEXT.value: {place: where, DocsField.TEXT.value: self.text}}


@dataclass(frozen=True)
class PageBreakAtEnd:
    """Разрыв страницы в конце документа."""

    @property
    def body(self) -> RequestBody:
        return {DocsField.INSERT_PAGE_BREAK.value: {DocsField.END_OF_SEGMENT.value: {}}}


@dataclass(frozen=True)
class TableAtEnd:
    """Таблица в одну колонку в конце документа."""

    rows: int

    @property
    def body(self) -> RequestBody:
        table: RequestBody = {
            DocsField.ROWS.value: self.rows, DocsField.COLUMNS.value: ONE_COLUMN, DocsField.END_OF_SEGMENT.value: {}
        }
        return {DocsField.INSERT_TABLE.value: table}


@dataclass(frozen=True)
class TextStyle:
    """Вид текста отрезка: Arial 13 pt, жирный или нет."""

    range: DocRange
    is_bold: bool

    @property
    def body(self) -> RequestBody:
        size: RequestBody = {DocsField.MAGNITUDE.value: FONT_SIZE_PT, DocsField.UNIT.value: POINT_UNIT}
        style: RequestBody = {
            DocsField.FONT.value: {DocsField.FONT_FAMILY.value: FONT_FAMILY},
            DocsField.FONT_SIZE.value: size,
            DocsField.BOLD.value: self.is_bold,
        }
        return {
            DocsField.UPDATE_TEXT_STYLE.value: {
                DocsField.RANGE.value: self.range.body, DocsField.TEXT_STYLE.value: style,
                DocsField.FIELDS.value: TEXT_STYLE_FIELDS,
            }
        }


@dataclass(frozen=True)
class ParagraphStyle:
    """Выравнивание абзацев отрезка."""

    range: DocRange
    alignment: Alignment

    @property
    def body(self) -> RequestBody:
        return {
            DocsField.UPDATE_PARAGRAPH_STYLE.value: {
                DocsField.RANGE.value: self.range.body,
                DocsField.PARAGRAPH_STYLE.value: {DocsField.ALIGNMENT.value: self.alignment.value},
                DocsField.FIELDS.value: ALIGNMENT_FIELDS,
            }
        }


@dataclass(frozen=True)
class CellBackground:
    """Фон ячейки таблицы в одну колонку: таблица — индексом её начала, ячейка — номером строки."""

    table_start: int
    row: int
    color: RgbColor

    @property
    def body(self) -> RequestBody:
        location: RequestBody = {
            DocsField.TABLE_START.value: {DocsField.INDEX.value: self.table_start},
            DocsField.ROW_INDEX.value: self.row,
            DocsField.COLUMN_INDEX.value: 0,
        }
        table_range: RequestBody = {
            DocsField.CELL_LOCATION.value: location, DocsField.ROW_SPAN.value: 1, DocsField.COLUMN_SPAN.value: 1
        }
        return {
            DocsField.UPDATE_TABLE_CELL_STYLE.value: {
                DocsField.TABLE_RANGE.value: table_range,
                DocsField.CELL_STYLE.value: {DocsField.BACKGROUND.value: self.color.body},
                DocsField.FIELDS.value: BACKGROUND_FIELDS,
            }
        }


@dataclass(frozen=True)
class InlineImage:
    """Картинка по адресу в точке документа; размер — ширина и высота в пунктах."""

    index: int
    uri: str
    width_pt: float
    height_pt: float

    @property
    def body(self) -> RequestBody:
        size: RequestBody = {
            DocsField.HEIGHT.value: {DocsField.MAGNITUDE.value: self.height_pt, DocsField.UNIT.value: POINT_UNIT},
            DocsField.WIDTH.value: {DocsField.MAGNITUDE.value: self.width_pt, DocsField.UNIT.value: POINT_UNIT},
        }
        return {
            DocsField.INSERT_INLINE_IMAGE.value: {
                DocsField.LOCATION.value: {DocsField.INDEX.value: self.index},
                DocsField.URI.value: self.uri,
                DocsField.OBJECT_SIZE.value: size,
            }
        }


# Пустой абзац в конце документа: перед первой таблицей — чтобы таблица не прилипла к шапке.
BLANK_PARAGRAPH: Final[InsertText] = InsertText(NEWLINE)
DocRequest: TypeAlias = (
    InsertText | PageBreakAtEnd | TableAtEnd | TextStyle | ParagraphStyle | CellBackground | InlineImage
)
