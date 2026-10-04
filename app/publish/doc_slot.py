"""Таблица слота в документе объявлений (CLAUDE.md §13 задача 4.4, §14 решение 51).

`DocSource` — источник слота в таблице: ссылка на видео и адреса обложки по порядку — копия превью на Google Диске
(есть, только когда её загрузил этап превью этого запуска), затем обложка YouTube по id видео ссылки. `DocSlot` — слот
любого входа и его источники — ссылки слота (`StreamSlot.sources`). Слот сам строит строки своей таблицы в
одну колонку и их вид — как в restreamer: «UK - 19:00», метка и название, метка и описание, метка превью, по строке на
источник (ссылка, под ней обложка); фон строк заголовка и меток, выравнивание по середине, название и описание —
по ширине. Запросы текста ячеек идут от последней ячейки к первой: вставка в поздней ячейке не сдвигает
ранние; фон ячейки задаётся от начала таблицы. Обложки — тоже от последнего источника к первому.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from app.core.text_format import NEWLINE
from app.core.youtube_video import YouTubeVideoId
from app.google.docs import DocsTable
from app.publish.doc_request import (
    BLANK_PARAGRAPH, Alignment, CellBackground, DocRange, DocRequest, InlineImage, InsertText, PageBreakAtEnd,
    ParagraphStyle, RgbColor, TableAtEnd, TextStyle, utf16_length,
)
from app.publish.doc_texts import DocLabels, DocTexts
from app.slots.slot import StreamSlot

# Фон строк таблицы слота (стартовые данные restreamer): заголовок, метка названия, метка описания, метка превью.
HEADING_COLOR: Final[RgbColor] = RgbColor(0.78, 0.84, 0.94)
TITLE_LABEL_COLOR: Final[RgbColor] = RgbColor(0.85, 0.91, 0.83)
DESCRIPTION_LABEL_COLOR: Final[RgbColor] = RgbColor(0.81, 0.86, 0.78)
PREVIEW_LABEL_COLOR: Final[RgbColor] = RgbColor(0.87, 0.83, 0.76)
COVER_WIDTH_PT: Final[float] = 210
COVER_HEIGHT_PT: Final[float] = 120


@dataclass(frozen=True)
class DocSource:
    """Источник в таблице слота: ссылка на видео и адреса обложки по порядку."""

    link: str
    covers: tuple[str, ...]

    @classmethod
    def of(cls, link: str, covers: Mapping[str, str]) -> DocSource:
        """Обложка — копия превью на Диске этого запуска (по ссылке видео), затем обложка YouTube по id видео ссылки."""
        video: YouTubeVideoId | None = YouTubeVideoId.of(link)
        found: tuple[str | None, ...] = (covers.get(link), None if video is None else video.thumbnail_url)
        return cls(link=link, covers=tuple(cover for cover in found if cover is not None))

    @property
    def cell_text(self) -> str:
        """Текст ячейки источника: ссылка, а под ней пустой абзац — место обложки."""
        return self.link + NEWLINE


@dataclass(frozen=True)
class DocCell:
    """Строка таблицы слота: текст, жирный ли он, выравнивание абзаца и фон ячейки (None — как по умолчанию)."""

    text: str
    is_bold: bool
    alignment: Alignment | None = None
    color: RgbColor | None = None

    def requests(self, start: int) -> tuple[DocRequest, ...]:
        """Текст ячейки с начала её абзаца `start` и его вид; пустой текст не вставляется."""
        styled: str = self.text.rstrip(NEWLINE)
        text: tuple[DocRequest, ...] = ()
        if styled:
            text = (InsertText(self.text, start), TextStyle(DocRange.of_text(start, styled), self.is_bold))
        if self.alignment is None:
            return text
        return (*text, ParagraphStyle(DocRange(start, start + utf16_length(self.text) + 1), self.alignment))


@dataclass(frozen=True)
class CoverSpot:
    """Куда встаёт обложка источника: точка документа — абзац под ссылкой в его ячейке."""

    source: DocSource
    index: int

    def image(self, uri: str) -> InlineImage:
        return InlineImage(self.index, uri, COVER_WIDTH_PT, COVER_HEIGHT_PT)


@dataclass(frozen=True)
class DocSlot:
    """Слот в документе: сам слот, его источники в порядке рядов, заголовок «UK - 19:00» и метки таблицы на его
    языке."""

    slot: StreamSlot
    sources: tuple[DocSource, ...]
    heading: str
    labels: DocLabels

    @classmethod
    def of(cls, slot: StreamSlot, covers: Mapping[str, str], texts: DocTexts) -> DocSlot:
        """Слот и его источники; заголовок и метки — на языке слота."""
        sources: tuple[DocSource, ...] = tuple(DocSource.of(link, covers) for link in slot.sources)
        heading: str = texts.heading(slot.language, slot.time)
        return cls(slot=slot, sources=sources, heading=heading, labels=texts.labels(slot.language))

    @property
    def cells(self) -> tuple[DocCell, ...]:
        """Строки таблицы по порядку: заголовок, название, описание, превью и по строке на источник."""
        return (
            DocCell(self.heading, True, Alignment.CENTER, HEADING_COLOR),
            DocCell(self.labels.title, True, Alignment.CENTER, TITLE_LABEL_COLOR),
            DocCell(self.slot.title, True, Alignment.JUSTIFIED),
            DocCell(self.labels.description, True, Alignment.CENTER, DESCRIPTION_LABEL_COLOR),
            DocCell(self.slot.description, False, Alignment.JUSTIFIED),
            DocCell(self.labels.preview, True, Alignment.CENTER, PREVIEW_LABEL_COLOR),
            *(DocCell(source.cell_text, False) for source in self.sources),
        )

    def table_requests(self, is_first: bool) -> tuple[DocRequest, ...]:
        """Таблица в конец документа: перед первой — пустой абзац, перед остальными — разрыв страницы."""
        before: DocRequest = BLANK_PARAGRAPH if is_first else PageBreakAtEnd()
        return (before, TableAtEnd(rows=len(self.cells)))

    def cell_requests(self, table: DocsTable) -> tuple[DocRequest, ...]:
        """Фон ячеек — от начала таблицы; затем тексты ячеек и их вид — от последней ячейки к первой."""
        cells: tuple[DocCell, ...] = self.cells
        backgrounds: tuple[DocRequest, ...] = tuple(
            CellBackground(table.start_index, row, cell.color)
            for row, cell in enumerate(cells)
            if cell.color is not None
        )
        texts_last_first: tuple[DocRequest, ...] = tuple(
            request for row in reversed(range(len(cells))) for request in cells[row].requests(table.cell_starts[row])
        )
        return (*backgrounds, *texts_last_first)

    def cover_spots(self, table: DocsTable) -> tuple[CoverSpot, ...]:
        """Места обложек — от последнего источника к первому: вставка картинки не сдвигает ранние ячейки."""
        first_source_row: int = len(self.cells) - len(self.sources)
        spots: tuple[CoverSpot, ...] = tuple(
            CoverSpot(source, table.cell_starts[first_source_row + place] + utf16_length(source.cell_text))
            for place, source in enumerate(self.sources)
        )
        return tuple(reversed(spots))
