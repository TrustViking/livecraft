"""Разбор FB_PUBLIC_LOAD_DATA_ страницы формы: вопросы, разделы, переходы, заголовок, fbzx."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.form.failure import FormFailure
from app.form.question import PageQuestion, QuestionKind, SectionJump
from app.form.structure import FormStructure
from app.tests.fixtures.form import (
    FACEBOOK_SECTION_ID,
    FBZX,
    REFUSAL_PAGE,
    SHORT_URL,
    TRAINING_FORM_TITLE,
    VIEW_URL,
    YOUTUBE_SECTION_ID,
    FakeForms,
    build_html,
    build_payload,
    page_break,
    question,
)

SUBMIT_FORM_CODE: int = -3


def _read(tmp_path: Path, html: str) -> FormStructure:
    structure: FormStructure | FormFailure = FakeForms.answering(html).reader(tmp_path).read(SHORT_URL)
    assert isinstance(structure, FormStructure)
    return structure


def _read_items(tmp_path: Path, items: list[Any]) -> FormStructure:
    return _read(tmp_path, build_html(build_payload(items)))


def test_structure_is_read_from_the_page(tmp_path: Path) -> None:
    structure: FormStructure = _read(tmp_path, build_html())
    assert structure.view_url == VIEW_URL
    assert structure.response_url == "https://docs.google.com/forms/d/e/ABC/formResponse"
    assert structure.fbzx == FBZX
    assert structure.page_count == 3
    language: PageQuestion | None = structure.question_by_title("Язык стрима ( Language of stream)")
    assert language is not None
    assert (language.entry_id, language.kind, language.is_required) == ("entry.1", QuestionKind.CHOICE, True)
    assert language.options == ("Русский ( Russian)", "Английский ( English)")
    key: PageQuestion | None = structure.question_by_title("You Tube Stream Key")
    assert key is not None and (key.kind, key.page_index) == (QuestionKind.TEXT, 1)
    facebook: PageQuestion | None = structure.question_by_title("Facebook Stream Key")
    assert facebook is not None and facebook.page_index == 2


def test_navigation_map_is_collected(tmp_path: Path) -> None:
    structure: FormStructure = _read(tmp_path, build_html())
    assert structure.navigation["entry.4"] == {
        "You Tube": SectionJump(section_id=YOUTUBE_SECTION_ID, page_index=1),
        "Facebook": SectionJump(section_id=FACEBOOK_SECTION_ID, page_index=2),
    }


def test_section_id_is_translated_to_page_index(tmp_path: Path) -> None:
    """Живой прогон 13-09-2026: переход 1281939289 — это id раздела, номер у него 1."""
    items: list[Any] = [
        question(4, "Платформа (Platform)", 2, [["You Tube", None, YOUTUBE_SECTION_ID]]),
        page_break(YOUTUBE_SECTION_ID, "YouTube"),
        question(5, "You Tube Stream Key", 0),
    ]
    structure: FormStructure = _read_items(tmp_path, items)
    assert structure.navigation["entry.4"]["You Tube"].page_index == 1
    assert structure.page_count == 2


def test_unknown_section_id_leaves_option_without_target(tmp_path: Path) -> None:
    items: list[Any] = [
        question(4, "Платформа (Platform)", 2, [["You Tube", None, 555]]),
        page_break(YOUTUBE_SECTION_ID, "YouTube"),
        question(5, "You Tube Stream Key", 0),
    ]
    structure: FormStructure = _read_items(tmp_path, items)
    assert structure.navigation["entry.4"]["You Tube"] == SectionJump(section_id=555, page_index=None)


def test_negative_target_is_not_a_jump(tmp_path: Path) -> None:
    """Отрицательные значения — служебные коды Google (например, «отправить форму»)."""
    items: list[Any] = [
        question(4, "Платформа (Platform)", 2, [["You Tube", None, SUBMIT_FORM_CODE], ["Facebook"]]),
        page_break(YOUTUBE_SECTION_ID, "YouTube"),
        question(5, "You Tube Stream Key", 0),
    ]
    assert "entry.4" not in _read_items(tmp_path, items).navigation


def test_sections_are_numbered_in_order_regardless_of_ids(tmp_path: Path) -> None:
    """id разрывов идут не по возрастанию, а номера разделов — подряд с нуля; картинка — элемент без вопроса."""
    items: list[Any] = [
        question(
            1,
            "Платформа (Platform)",
            2,
            [["Other", None, 2071313360], ["You Tube", None, 1281939289], ["Rumble", None, 339209492]],
        ),
        page_break(1281939289, "YouTube"),
        question(2, "You Tube Stream Key", 0),
        page_break(643928232, "Facebook"),
        question(3, "Facebook Stream Key", 0),
        page_break(339209492, "Rumble"),
        [333114025, "Пример (Example)", None, 11, None],
        question(4, "Stream Key (rumble)", 0),
        page_break(2071313360, "Other"),
        question(5, "Stream Key", 0),
    ]
    structure: FormStructure = _read_items(tmp_path, items)
    pages: dict[str, int] = {item.title: item.page_index for item in structure.questions}
    assert pages == {
        "Платформа (Platform)": 0,
        "You Tube Stream Key": 1,
        "Facebook Stream Key": 2,
        "Stream Key (rumble)": 3,
        "Stream Key": 4,
    }
    jumps: dict[str, SectionJump] = dict(structure.navigation["entry.1"])
    assert {option: jump.page_index for option, jump in jumps.items()} == {"Other": 4, "You Tube": 1, "Rumble": 3}
    assert structure.page_count == 5


def test_fbzx_falls_back_to_the_payload(tmp_path: Path) -> None:
    assert _read(tmp_path, build_html(with_fbzx=False)).fbzx == FBZX


def test_title_is_read_from_the_training_form_page(tmp_path: Path) -> None:
    """Заголовок для отвечающего — payload[1][8]; payload[3] — не он."""
    assert _read(tmp_path, REFUSAL_PAGE).title == TRAINING_FORM_TITLE


def test_form_without_title_has_an_empty_title(tmp_path: Path) -> None:
    assert _read(tmp_path, build_html()).title == ""
