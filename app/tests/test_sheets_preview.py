"""Колонки языка и превью на листе плана и запись в них (app\\sheets\\preview.py, CLAUDE.md §6 инвариант 3,
§14 решения 27, 29). Сети нет: тела запросов строит сама запись, их выполняет читатель таблицы."""
from __future__ import annotations

import pytest

from app.sheets.plan import SheetPlan
from app.sheets.preview import (
    LANGUAGE_HEADER, PREVIEW_HEADER, OutputCell, OutputChange, OutputColumn, SheetOutput, SheetWrite,
)

LINK: str = "https://youtu.be/dQw4w9WgXcQ"
URL_A: str = "https://drive.google.com/uc?export=download&id=aaa"
URL_B: str = "https://drive.google.com/uc?export=download&id=bbb"
NOTHING_TAKEN: frozenset[int] = frozenset()


def _plan(*rows: list[str]) -> SheetPlan:
    return SheetPlan.from_values("План 'осень'", 11, list(rows))


def _column(plan: SheetPlan, output: SheetOutput) -> OutputColumn:
    """Колонка вывода среди колонок, не занятых планом, — как её выбирает запись."""
    assert plan.columns is not None
    return OutputColumn.of(plan, output, plan.columns.indexes)


def _write(plan: SheetPlan, **values: list[OutputCell]) -> SheetWrite:
    return SheetWrite.of(plan, {SheetOutput(name): cells for name, cells in values.items()})


def _change(write: SheetWrite, output: SheetOutput) -> OutputChange:
    [change] = [change for change in write.changes if change.output is output]
    return change


# --- колонка превью


@pytest.mark.parametrize(
    "name", ["Preview (Google Drive)", "Превью", "Прев'ю", "превʼю", "Thumbnail link"]
)
def test_the_preview_column_is_found_by_its_name(name: str) -> None:
    plan: SheetPlan = _plan(["Notes", "Links", name, "Date", "Time"], ["x", LINK, URL_A, "16.10.2026", "19:00"])
    column: OutputColumn = _column(plan, SheetOutput.PREVIEW)
    assert (column.index, column.letters, column.has_header) == (2, "C", True)
    assert column.cells == {2: URL_A}


def test_a_plan_column_is_never_taken_for_the_preview_column() -> None:
    """«Ссылка на превью» — колонка ссылки плана: её программа не перезапишет, превью ищется дальше."""
    plan: SheetPlan = _plan(["Ссылка на превью", "Дата", "Время", "Preview"], [LINK, "16.10.2026", "19:00"])
    assert plan.columns is not None and plan.columns.link == 0
    assert _column(plan, SheetOutput.PREVIEW).index == 3


def test_without_the_column_it_is_the_first_empty_one_right_of_the_header() -> None:
    """Справа от последнего непустого заголовка; колонка, где в строках что-то есть, пропускается."""
    plan: SheetPlan = _plan(
        ["Links", "", "Date", "Time", "", ""],
        [LINK, "note", "16.10.2026", "19:00", "someone's text"],
        [LINK, "", "17.10.2026", "20:00"],
    )
    column: OutputColumn = _column(plan, SheetOutput.PREVIEW)
    assert (column.index, column.has_header, column.cells) == (5, False, {})


def test_only_the_links_that_differ_are_written_and_the_header_only_when_missing() -> None:
    plan: SheetPlan = _plan(
        ["Links", "Date", "Time", PREVIEW_HEADER],
        [LINK, "16.10.2026", "19:00", URL_A],
        [LINK, "17.10.2026", "20:00", "old"],
        [LINK, "18.10.2026", "21:00"],
    )
    write: SheetWrite = _write(plan, preview=[OutputCell(2, URL_A), OutputCell(3, URL_B), OutputCell(4, URL_B)])
    change: OutputChange = _change(write, SheetOutput.PREVIEW)
    assert [cell.row_number for cell in change.changed] == [3, 4] and change.unchanged == 1
    assert write.values_body == {
        "valueInputOption": "RAW",
        "data": [
            {"range": "'План ''осень'''!D3", "values": [[URL_B]]},
            {"range": "'План ''осень'''!D4", "values": [[URL_B]]},
        ],
    }


def test_a_new_column_gets_its_header_with_the_links() -> None:
    plan: SheetPlan = _plan(["Links", "Date", "Time"], [LINK, "16.10.2026", "19:00"])
    write: SheetWrite = _write(plan, preview=[OutputCell(2, URL_A)])
    assert write.values_body["data"] == [
        {"range": "'План ''осень'''!D1", "values": [[PREVIEW_HEADER]]},
        {"range": "'План ''осень'''!D2", "values": [[URL_A]]},
    ]


def test_the_written_links_are_clipped_by_the_cell_edge() -> None:
    plan: SheetPlan = _plan(["Links", "Date", "Time"], [LINK, "16.10.2026", "19:00"], [LINK, "17.10.2026", "20:00"])
    write: SheetWrite = _write(plan, preview=[OutputCell(3, URL_A)])
    assert write.has_clip
    assert write.clip_body == {
        "requests": [
            {
                "repeatCell": {
                    "range": {
                        "sheetId": 11, "startRowIndex": 2, "endRowIndex": 3, "startColumnIndex": 3, "endColumnIndex": 4
                    },
                    "cell": {"userEnteredFormat": {"wrapStrategy": "CLIP"}},
                    "fields": "userEnteredFormat.wrapStrategy",
                }
            }
        ]
    }


def test_nothing_changed_is_an_empty_write() -> None:
    plan: SheetPlan = _plan(["Links", "Date", "Time", PREVIEW_HEADER], [LINK, "16.10.2026", "19:00", URL_A])
    write: SheetWrite = _write(plan, preview=[OutputCell(2, URL_A)])
    assert write.is_empty and write.unchanged(SheetOutput.PREVIEW) == 1
    assert _write(plan).is_empty and _write(plan, preview=[]).is_empty


# --- колонка языка (§14 решение 29)


@pytest.mark.parametrize("name", ["L", "l", "Lang", "Language", "Язык", "Мова"])
def test_the_language_column_is_found_by_its_exact_name(name: str) -> None:
    plan: SheetPlan = _plan([name, "Chips", "Links", "Date", "Time"], ["ru", "", LINK, "16.10.2026", "19:00"])
    column: OutputColumn = _column(plan, SheetOutput.LANGUAGE)
    assert (column.index, column.letters, column.has_header, column.cells) == (0, "A", True, {2: "ru"})


def test_links_is_not_a_language_column_and_the_language_goes_to_an_added_lang() -> None:
    """По вхождению однобуквенное «L» нашлось бы в «Links» и в «Language notes»: колонку языка ищут только по точному
    имени; нет её — язык ложится в добавленную колонку «Lang», «Links» не тронута."""
    plan: SheetPlan = _plan(["Links", "Language notes", "Date", "Time"], [LINK, "note", "16.10.2026", "19:00"])
    write: SheetWrite = _write(plan, language=[OutputCell(2, "uk")])
    assert write.values_body["data"] == [
        {"range": "'План ''осень'''!E1", "values": [[LANGUAGE_HEADER]]},
        {"range": "'План ''осень'''!E2", "values": [["uk"]]},
    ]
    assert LANGUAGE_HEADER == "Lang"


def test_an_old_l_column_takes_the_language_and_no_lang_column_is_added() -> None:
    """Таблица со старым заголовком «L»: язык ложится в неё, второй колонки языка программа не добавляет."""
    plan: SheetPlan = _plan(["L", "Links", "Date", "Time"], ["", LINK, "16.10.2026", "19:00"])
    write: SheetWrite = _write(plan, language=[OutputCell(2, "uk")])
    assert write.values_body["data"] == [{"range": "'План ''осень'''!A2", "values": [["uk"]]}]


def test_without_both_columns_the_two_added_columns_differ() -> None:
    plan: SheetPlan = _plan(["Links", "Date", "Time"], [LINK, "16.10.2026", "19:00"])
    write: SheetWrite = _write(plan, preview=[OutputCell(2, URL_A)], language=[OutputCell(2, "ru")])
    assert write.values_body["data"] == [
        {"range": "'План ''осень'''!D1", "values": [[PREVIEW_HEADER]]},
        {"range": "'План ''осень'''!D2", "values": [[URL_A]]},
        {"range": "'План ''осень'''!E1", "values": [[LANGUAGE_HEADER]]},
        {"range": "'План ''осень'''!E2", "values": [["ru"]]},
    ]


def test_only_changed_languages_are_written_regardless_of_case() -> None:
    """«RU» и «ru» — один язык: такая ячейка не переписывается; пустая и другой язык — пишутся."""
    plan: SheetPlan = _plan(
        [LANGUAGE_HEADER, "Links", "Date", "Time"],
        [" RU ", LINK, "16.10.2026", "19:00"],
        ["", LINK, "17.10.2026", "20:00"],
        ["en", LINK, "18.10.2026", "21:00"],
    )
    write: SheetWrite = _write(plan, language=[OutputCell(2, "ru"), OutputCell(3, "uk"), OutputCell(4, "uk")])
    assert write.written(SheetOutput.LANGUAGE) == 2 and write.unchanged(SheetOutput.LANGUAGE) == 1
    assert write.values_body["data"] == [
        {"range": "'План ''осень'''!A3", "values": [["uk"]]},
        {"range": "'План ''осень'''!A4", "values": [["uk"]]},
    ]


def test_languages_are_not_clipped() -> None:
    plan: SheetPlan = _plan([LANGUAGE_HEADER, "Links", "Date", "Time"], ["", LINK, "16.10.2026", "19:00"])
    write: SheetWrite = _write(plan, language=[OutputCell(2, "ru")])
    assert not write.is_empty and not write.has_clip and write.clip_body == {"requests": []}


def test_both_outputs_go_in_one_body_and_only_links_are_clipped() -> None:
    """Таблица как в образце таблицы плана: язык — A «Lang», чип — B, план — C, D, E, превью — F."""
    plan: SheetPlan = _plan(
        [LANGUAGE_HEADER, "Chips", "Links", "Date", "Time", PREVIEW_HEADER],
        ["", "", LINK, "16.10.2026", "19:00", ""],
    )
    write: SheetWrite = _write(plan, preview=[OutputCell(2, URL_A)], language=[OutputCell(2, "ru")])
    assert write.values_body["data"] == [
        {"range": "'План ''осень'''!F2", "values": [[URL_A]]},
        {"range": "'План ''осень'''!A2", "values": [["ru"]]},
    ]
    [clip] = write.clip_body["requests"]  # type: ignore[misc]
    assert clip["repeatCell"]["range"]["startColumnIndex"] == 5
