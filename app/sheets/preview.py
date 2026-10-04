"""Что программа пишет в строку видео на листе плана: язык видео и ссылку на копию превью (CLAUDE.md §6 инвариант 3,
§14 решения 27, 29).

`SheetOutput` — вывод программы в строку видео: язык, который она определила по видео, и ссылка на копию превью на
Google Диске. Каждый вывод знает названия своей колонки (ресурс), заголовок колонки, которую программа добавит сама,
ищется ли колонка и по части названия и обрезается ли длинный текст ячейки краем (CLIP).

`OutputColumn` — где колонка вывода на листе и что в ней сейчас: колонка находится по названию среди колонок, не
занятых планом (ссылку, дату и время программа не перезапишет никогда) и колонкой другого вывода; нет такой — первая
колонка справа от последнего непустого заголовка, у которой все прочитанные ячейки пусты и которую не взял другой
вывод: туда программа сама впишет заголовок. `SheetWrite` — что именно записать: по каждому выводу только ячейки, где
значение отличается от нынешнего, и заголовок добавленной колонки; одним телом values.batchUpdate, а «обрезать» — только
ячейки превью. Выполняет запись читатель таблицы (`SheetsReader.write_outputs`) — через единственную точку раскрытия id
таблицы.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from app.core.sheet_text import column_letters, quoted_sheet_title
from app.resources.loader import TextResource
from app.sheets.plan import FIRST_DATA_ROW_NUMBER, SheetHeader, SheetPlan

# Заголовки колонок, которые добавляет программа, — содержимое таблицы, как в образце таблицы плана, а не текст окна.
PREVIEW_HEADER: Final[str] = "Preview (Google Drive)"
# Колонка языка, которую программа добавляет, — «Lang» (решение 29): «L» путалась; старый заголовок «L» узнаётся
# по-прежнему (ресурс sheet_header_language.txt), и такая таблица второй колонки языка не получает.
LANGUAGE_HEADER: Final[str] = "Lang"
# Ссылка и код языка пишутся как есть, без разбора Google (не формула и не дата).
VALUE_INPUT_OPTION: Final[str] = "RAW"
CLIP_STRATEGY: Final[str] = "CLIP"
CLIP_FIELDS: Final[str] = "userEnteredFormat.wrapStrategy"
CELL_TEMPLATE: Final[str] = "{sheet}!{column}{row}"
HEADER_ROW_NUMBER: Final[int] = 1          # шапка — первая строка листа


class SheetOutput(str, Enum):
    """Вывод программы в строку видео. Значение — идентификатор для лога."""

    PREVIEW = "preview"     # ссылка на копию превью на Google Диске (§14 решение 27)
    LANGUAGE = "language"   # код языка, который программа определила по видео (§14 решение 29)

    @property
    def aliases(self) -> tuple[str, ...]:
        """Названия колонки вывода из ресурса — по порядку."""
        return TextResource(OUTPUT_ALIAS_RESOURCES[self]).lines

    @property
    def header(self) -> str:
        """Заголовок колонки, которую программа добавляет сама, когда своей колонки на листе нет."""
        return OUTPUT_HEADERS[self]

    @property
    def is_found_by_part(self) -> bool:
        """Колонка ищется и по части заголовка. Язык — только по точному: однобуквенное «L» нашлось бы в «Links»."""
        return self is SheetOutput.PREVIEW

    @property
    def is_clipped(self) -> bool:
        """Длинный текст ячейки обрезается её краем: ссылка на превью длинная, код языка — нет."""
        return self is SheetOutput.PREVIEW

    def is_same(self, current: str, wanted: str) -> bool:
        """Значение ячейки уже то, что нужно. Код языка — без учёта регистра и краёв: «RU» и «ru» — один язык."""
        if self is SheetOutput.LANGUAGE:
            return current.strip().casefold() == wanted.strip().casefold()
        return current == wanted


OUTPUT_ALIAS_RESOURCES: Final[dict[SheetOutput, str]] = {
    SheetOutput.LANGUAGE: "sheet_header_language.txt",
    SheetOutput.PREVIEW: "sheet_header_preview.txt",
}
OUTPUT_HEADERS: Final[dict[SheetOutput, str]] = {
    SheetOutput.LANGUAGE: LANGUAGE_HEADER,
    SheetOutput.PREVIEW: PREVIEW_HEADER,
}


class SheetsWriteKey(str, Enum):
    """Поля тел запросов записи Sheets API v4: values.batchUpdate и spreadsheets.batchUpdate (repeatCell)."""

    VALUE_INPUT_OPTION = "valueInputOption"
    DATA = "data"
    RANGE = "range"
    VALUES = "values"
    REQUESTS = "requests"
    REPEAT_CELL = "repeatCell"
    SHEET_ID = "sheetId"
    START_ROW = "startRowIndex"
    END_ROW = "endRowIndex"
    START_COLUMN = "startColumnIndex"
    END_COLUMN = "endColumnIndex"
    CELL = "cell"
    USER_FORMAT = "userEnteredFormat"
    WRAP_STRATEGY = "wrapStrategy"
    FIELDS = "fields"


@dataclass(frozen=True)
class OutputCell:
    """Значение вывода для строки таблицы с номером `row_number`: код языка или ссылка на копию превью."""

    row_number: int
    text: str


@dataclass(frozen=True)
class OutputColumn:
    """Колонка вывода на листе: индекс (с 0), есть ли у неё заголовок и непустые ячейки сейчас по номерам строк."""

    output: SheetOutput
    index: int
    has_header: bool
    cells: Mapping[int, str]

    @classmethod
    def of(cls, plan: SheetPlan, output: SheetOutput, taken: frozenset[int]) -> OutputColumn:
        """Колонка по названию среди колонок, которых нет в `taken` (план и другой вывод); нет — первая пустая
        справа от шапки, которой нет в `taken`."""
        names: tuple[str, ...] = tuple("" if index in taken else name for index, name in enumerate(plan.header.names))
        header: SheetHeader = SheetHeader(names)
        found: int | None = (
            header.index_of(output.aliases) if output.is_found_by_part else header.exact_index_of(output.aliases)
        )
        index: int = cls._first_empty(plan, taken) if found is None else found
        cells: dict[int, str] = {
            row_number: text
            for row_number, row in enumerate(plan.values[1:], start=FIRST_DATA_ROW_NUMBER)
            if index < len(row) and (text := row[index].strip())
        }
        return cls(output=output, index=index, has_header=found is not None, cells=cells)

    @classmethod
    def _first_empty(cls, plan: SheetPlan, taken: frozenset[int]) -> int:
        """Первая колонка справа от последнего непустого заголовка: все прочитанные ячейки пусты, в `taken` её нет."""
        names: list[str] = list(plan.header.names)
        while names and not names[-1]:
            names.pop()
        index: int = len(names)
        while index in taken or any(index < len(row) and row[index].strip() for row in plan.values):
            index += 1
        return index

    @property
    def letters(self) -> str:
        return column_letters(self.index)

    def change(self, cells: Sequence[OutputCell]) -> OutputChange:
        """Что записать в колонку: только ячейки, где значение не то, что нужно; сколько уже стояли."""
        changed: tuple[OutputCell, ...] = tuple(
            cell for cell in cells if not self.output.is_same(self.cells.get(cell.row_number, ""), cell.text)
        )
        return OutputChange(column=self, changed=changed, unchanged=len(cells) - len(changed))


@dataclass(frozen=True)
class OutputChange:
    """Запись одного вывода: колонка, изменившиеся ячейки и сколько значений уже стояли."""

    column: OutputColumn
    changed: tuple[OutputCell, ...]
    unchanged: int

    @property
    def output(self) -> SheetOutput:
        return self.column.output

    @property
    def header_cell(self) -> OutputCell | None:
        """Заголовок добавленной колонки — только когда в неё есть что записать."""
        if self.column.has_header or not self.changed:
            return None
        return OutputCell(row_number=HEADER_ROW_NUMBER, text=self.output.header)

    @property
    def cells(self) -> tuple[OutputCell, ...]:
        """Ячейки values.batchUpdate этого вывода: заголовок, если колонку добавила программа, и изменившиеся."""
        header: OutputCell | None = self.header_cell
        return self.changed if header is None else (header, *self.changed)

    @property
    def clipped(self) -> tuple[OutputCell, ...]:
        """Ячейки, у которых длинный текст обрезается краем: записанные ссылки на превью."""
        return self.changed if self.output.is_clipped else ()


@dataclass(frozen=True)
class SheetWrite:
    """Что записать в строки видео листа `sheet_title` (id листа `sheet_id`): записи выводов в порядке `SheetOutput`."""

    sheet_title: str
    sheet_id: int
    changes: tuple[OutputChange, ...]

    @classmethod
    def of(cls, plan: SheetPlan, values: Mapping[SheetOutput, Sequence[OutputCell]]) -> SheetWrite:
        """Запись выводов на лист плана. Колонка ищется только у вывода, которому есть что писать; колонка,
        выбранная одним выводом, другому не достаётся — две добавляемые колонки не совпадают."""
        taken: frozenset[int] = plan.columns.indexes if plan.columns is not None else frozenset()
        changes: list[OutputChange] = []
        for output in SheetOutput:
            cells: Sequence[OutputCell] = values.get(output, ())
            if not cells:
                continue
            column: OutputColumn = OutputColumn.of(plan, output, taken)
            taken = taken | {column.index}
            changes.append(column.change(cells))
        return cls(sheet_title=plan.sheet_title, sheet_id=plan.sheet_id, changes=tuple(changes))

    @property
    def is_empty(self) -> bool:
        return not any(change.changed for change in self.changes)

    @property
    def has_clip(self) -> bool:
        """Есть ячейки, которые обрезать: записаны ссылки на превью."""
        return any(change.clipped for change in self.changes)

    def written(self, output: SheetOutput) -> int:
        """Сколько значений вывода записывается."""
        return sum(len(change.changed) for change in self.changes if change.output is output)

    def unchanged(self, output: SheetOutput) -> int:
        """Сколько значений вывода уже стояли."""
        return sum(change.unchanged for change in self.changes if change.output is output)

    @property
    def values_body(self) -> dict[str, object]:
        """Тело values.batchUpdate: у каждого вывода заголовок добавленной колонки и изменившиеся ячейки."""
        data: list[dict[str, object]] = [
            self._cell(change.column, cell) for change in self.changes for cell in change.cells
        ]
        return {SheetsWriteKey.VALUE_INPUT_OPTION.value: VALUE_INPUT_OPTION, SheetsWriteKey.DATA.value: data}

    @property
    def clip_body(self) -> dict[str, object]:
        """Тело spreadsheets.batchUpdate: у каждой записанной ссылки на превью длинный текст обрезается краем ячейки."""
        requests: list[dict[str, object]] = [
            self._clip(change.column, cell) for change in self.changes for cell in change.clipped
        ]
        return {SheetsWriteKey.REQUESTS.value: requests}

    def _cell(self, column: OutputColumn, cell: OutputCell) -> dict[str, object]:
        target: str = CELL_TEMPLATE.format(
            sheet=quoted_sheet_title(self.sheet_title), column=column.letters, row=cell.row_number
        )
        return {SheetsWriteKey.RANGE.value: target, SheetsWriteKey.VALUES.value: [[cell.text]]}

    def _clip(self, column: OutputColumn, cell: OutputCell) -> dict[str, object]:
        """repeatCell на одну ячейку: строки и колонки в запросе — с 0, конец — не включая."""
        grid: dict[str, int] = {
            SheetsWriteKey.SHEET_ID.value: self.sheet_id,
            SheetsWriteKey.START_ROW.value: cell.row_number - 1,
            SheetsWriteKey.END_ROW.value: cell.row_number,
            SheetsWriteKey.START_COLUMN.value: column.index,
            SheetsWriteKey.END_COLUMN.value: column.index + 1,
        }
        wrap: dict[str, object] = {
            SheetsWriteKey.USER_FORMAT.value: {SheetsWriteKey.WRAP_STRATEGY.value: CLIP_STRATEGY}
        }
        repeat: dict[str, object] = {
            SheetsWriteKey.RANGE.value: grid, SheetsWriteKey.CELL.value: wrap, SheetsWriteKey.FIELDS.value: CLIP_FIELDS
        }
        return {SheetsWriteKey.REPEAT_CELL.value: repeat}
