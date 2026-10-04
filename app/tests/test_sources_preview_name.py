"""Имя файла превью видео (app\\sources\\preview_name.py, CLAUDE.md §14 решение 27): «{номер}_{ЯЗЫК}_{название
латиницей}.jpg», только латиница, цифры и «._-», основа не длиннее 120 знаков."""
from __future__ import annotations

import re

import pytest

from app.sources.preview_name import MAX_STEM_CHARS, PreviewName

SAFE_NAME: re.Pattern[str] = re.compile(r"[A-Za-z0-9._-]+")


@pytest.mark.parametrize(
    ("title", "file_name"),
    [
        ("Привіт, світе! Їжак і ґанок", "1_UK_pryvit_svite_yizhak_i_ganok.jpg"),
        ("Щедрий вечір — Єва", "1_UK_shchedryi_vechir_ieva.jpg"),
        ("Съешь ещё этих мягких булок", "1_UK_sesh_eshchyo_etykh_miahkykh_bulok.jpg"),
        ("Big News: 2026/09/28 (LIVE)", "1_UK_big_news_2026_09_28_live.jpg"),
        ("   ___  ", "1_UK_video.jpg"),
        ("日本語のタイトル", "1_UK_video.jpg"),
    ],
)
def test_the_title_goes_to_latin_with_underscores_between_words(title: str, file_name: str) -> None:
    assert PreviewName(index=1, language="uk", title=title).file_name == file_name


def test_the_number_and_the_language_code_lead_the_name() -> None:
    assert PreviewName(index=12, language="en", title="Evening show").file_name == "12_EN_evening_show.jpg"


def test_the_name_has_only_safe_signs_and_no_double_underscores() -> None:
    name: str = PreviewName(index=3, language="ru", title="«Итоги» — 100% / лучшее?! ё").stem
    assert SAFE_NAME.fullmatch(name) and "__" not in name
    assert not name.startswith(("_", ".", "-")) and not name.endswith(("_", ".", "-"))


def test_the_stem_is_cut_to_120_signs_without_a_trailing_underscore() -> None:
    stem: str = PreviewName(index=1, language="uk", title="слово " * 60).stem
    assert len(stem) <= MAX_STEM_CHARS == 120
    assert not stem.endswith("_") and stem.startswith("1_UK_slovo_slovo")


def test_the_same_video_gives_the_same_name_every_run() -> None:
    """Имя одно и то же: копия с тем же именем и размером на Диске не загружается второй раз."""
    first: PreviewName = PreviewName(index=2, language="uk", title="Ранкова програма")
    assert first.file_name == PreviewName(index=2, language="uk", title="Ранкова програма").file_name
