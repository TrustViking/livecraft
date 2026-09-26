from __future__ import annotations

import pytest

from app.llm.merges.description import MergedDescription

NEUTRAL: str = chr(0x1F539)
LINE_60: str = "Tonight we align the Brussels vote with the Kharkiv transport shock"


def test_meta_lines_are_removed() -> None:
    text: str = "Title: x\r\nBody line.  \n  sources : a\nDescription:y\nTitles: kept"
    assert MergedDescription(text).without_meta_lines().text == "Body line.\nTitles: kept"


def test_duplicate_paragraphs_rule() -> None:
    assert MergedDescription("Same long text here enough tokens.\n\nSame long text here enough tokens.").has_duplicate_paragraphs
    assert not MergedDescription("Hi.\n\nHi.").has_duplicate_paragraphs


def test_repr_hides_the_text() -> None:
    assert "secret words" not in repr(MergedDescription("secret words"))


# --- перегруженные пункты, выгрузка по источникам
def test_very_long_bullet_is_overloaded_without_names() -> None:
    assert MergedDescription(f"Hook paragraph.\n\n🔹 {'слово ' * 85}\n🔹 Short bullet.").overloaded_bullet_count >= 1


def test_medium_bullet_without_names_is_not_overloaded() -> None:
    assert MergedDescription(f"Hook paragraph.\n\n🔹 {'слово ' * 50}\n🔹 Short.").overloaded_bullet_count == 0


def test_medium_bullet_with_three_names_is_overloaded() -> None:
    names: str = "John Smith, Maria Ivanova and Luigi Corvaglia"
    long_bullet: str = f"📌 {names} {'discuss the budget ' * 15}"
    plain_bullet: str = f"- {names} {'discuss the budget ' * 15}"
    assert MergedDescription(f"Hook.\n\n{long_bullet}\n{plain_bullet}").overloaded_bullet_count == 1


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Source 1: a\nSource 2: b", True),
        ("video 1) a\r\nVIDEO 2 - b", True),
        ("We compare source 1 and source 2 today.", True),
        ("Source 1: a only", False),
        ("Video 1 and source 2", False),
    ],
)
def test_per_source_dump(text: str, expected: bool) -> None:
    assert MergedDescription(text).looks_like_per_source_dump is expected


# --- ссылки, повторы строк и абзацев


def test_official_links_are_counted_once_per_key_without_youtube() -> None:
    text: str = (
        "Sites: https://www.example.org/ https://example.org/uk (https://example.org/about?utm_source=x).\n"
        "https://youtu.be/aaaaaaaaaaa https://t.me/channel?si=1 https://[bad"
    )
    # example.org (три записи одного сайта), example.org/about), t.me/channel
    assert MergedDescription(text).official_link_count == 3


def test_youtube_links_are_counted_by_video_id() -> None:
    text: str = (
        "https://youtu.be/aaaaaaaaaaa https://www.youtube.com/watch?v=aaaaaaaaaaa&t=5 "
        "https://m.youtube.com/watch?feature=share&v=bbbbbbbbbbb https://youtube.com/@channel "
        "https://example.org/watch?v=ccccccccccc https://[bad"
    )
    assert MergedDescription(text).youtube_link_count == 2


def test_adjacent_lines_with_a_long_common_start_repeat() -> None:
    assert MergedDescription(f"{LINE_60} tonight\n{LINE_60} again").has_adjacent_duplicate_lines


def test_adjacent_lines_with_the_same_words_repeat() -> None:
    first: str = "sanctions vote budget amendments customs delays commission session Brussels today"
    second: str = "Brussels today: commission session, customs delays, budget amendments and the sanctions vote"
    assert MergedDescription(f"{first}\n{second}").has_adjacent_duplicate_lines


@pytest.mark.parametrize(
    "text",
    [
        "Short line one\nShort line one",                     # короче 60 знаков
        f"{LINE_60} tonight\n\n{LINE_60} again",              # между ними пустая строка
        f"{LINE_60} tonight\nA completely different line that talks about other things entirely.",
    ],
)
def test_lines_that_do_not_repeat(text: str) -> None:
    assert not MergedDescription(text).has_adjacent_duplicate_lines


def test_paragraphs_with_a_long_common_start_are_similar() -> None:
    body: str = LINE_60 + " and explain why the next operational window matters to everyone"
    text: str = f"{body} tonight.\n\nMiddle.\n\n{body} tomorrow and later."
    assert MergedDescription(text).has_similar_paragraph_prefixes


def test_short_or_different_paragraphs_are_not_similar() -> None:
    assert not MergedDescription("Same start here.\n\nSame start here too.").has_similar_paragraph_prefixes
    assert not MergedDescription(f"{LINE_60} and more words to pass eighty chars.\n\nOther text " + "x" * 90).has_similar_paragraph_prefixes
