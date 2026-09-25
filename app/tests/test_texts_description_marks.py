from __future__ import annotations

import pytest

from app.resources.loader import TextResource
from app.texts.description_marks import (
    ALLOWED_BULLET_MARKERS,
    CTA_HINTS_RESOURCE,
    CTA_PREFIXES_RESOURCE,
    URL_LINE_PATTERN,
    CtaLexicon,
    bullet_marker_for_line,
    extract_named_entities,
    is_bullet_line,
    is_official_links_heading,
    starts_with_cta_prefix,
)

DONOR_CTA_PREFIXES: tuple[str, ...] = (
    "Підпишіть", "Підписуйт", "Слідкуй", "Subscribe", "Watch", "Follow", "Join", "Смотри", "Подпишит", "Следи",
    "Поширюйт", "Поділіться", "Приєднуйт", "Подпишитесь", "Leave a comment", "Write a comment",
    "Напишіть у коментар", "Залиште коментар", "Напишите в комментар", "Оставьте комментар", "Оставляйте комментар",
)


# --- донор: test_heading_resolver.py::test_is_official_links_heading_accepts_multi_language_input
@pytest.mark.parametrize("value", ["🌐 Hivatalos linkek:", "🌐 Officiële links:", "🌐 公式リンク:", "🌐 Officiel lenker:"])
def test_official_links_heading_in_any_language(value: str) -> None:
    assert is_official_links_heading(value) is True


@pytest.mark.parametrize("value", ["Hivatalos linkek:", "🌐 :", "random text", "🌐 Foo: bar", "", "🌐 Foo"])
def test_not_an_official_links_heading(value: str) -> None:
    assert is_official_links_heading(value) is False


def test_heading_edges_are_ignored() -> None:
    assert is_official_links_heading("   🌐Links:   ") is True


def test_cta_lexicon_is_the_donor_file() -> None:
    assert CtaLexicon.load().prefixes == DONOR_CTA_PREFIXES
    assert TextResource(CTA_PREFIXES_RESOURCE).path.is_file()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Підпишіться та напишіть у коментарях", True),
        ("  subscribe to the channel", True),
        ("Watching the vote is key", True),        # префикс, а не слово: так у донора
        ("Сьогодні розбираємо рішення", False),
        ("", False),
    ],
)
def test_starts_with_cta_prefix(text: str, expected: bool) -> None:
    assert starts_with_cta_prefix(text, DONOR_CTA_PREFIXES) is expected
    assert CtaLexicon(DONOR_CTA_PREFIXES).starts_with_prefix(text) is expected


def test_markers_and_url_line() -> None:
    assert ALLOWED_BULLET_MARKERS == ("🔹", "📌", "🎤", "🎥", "⚖", "🌐", "✅")
    assert URL_LINE_PATTERN.fullmatch("HTTPS://YouTu.be/x") is not None
    assert URL_LINE_PATTERN.fullmatch("https://example.org/a b") is None


# --- 3.11b: подсказки призыва (донор: core\cta_detection.py), пункты и имена (merge_text_utils.py)
DONOR_CTA_HINTS: tuple[str, ...] = (
    "watch", "learn more", "join", "subscribe", "follow", "read more", "links below", "details below", "дивіться",
    "долуч", "підпис", "узнать больше", "смотрите", "подпис", "подробности", "comment", "leave a comment",
    "write a comment", "коментар", "напишіть у коментар", "залиште коментар", "комментар", "оставьте комментар",
    "напишите комментар", "оставляйте комментар",
)
LEXICON: CtaLexicon = CtaLexicon.load()


def test_cta_hints_are_the_donor_file() -> None:
    assert LEXICON.hints == DONOR_CTA_HINTS
    assert TextResource(CTA_HINTS_RESOURCE).path.is_file()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Watch the stream", True),
        ("Watching the vote", False),              # «watch» — целое слово
        ("Підписуйтесь на канал", True),            # «підпис» — начало слова
        ("Залиште коментарі", True),
        ("Comments are welcome", True),            # «comment» — начало слова
        ("Прескоментар", False),                   # слева граница слова обязательна
        ("   ", False),
        ("Budget review", False),
    ],
)
def test_looks_like_cta_line(text: str, expected: bool) -> None:
    assert LEXICON.looks_like_cta_line(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Смотрите эфир и делитесь мнением.", True),
        ("Budget talk tonight #stream", True),
        ("Budget talk " * 20 + "#stream", False),    # хештег, но абзац длиннее 220 знаков и без подсказки
        ("Line one\nLine two\nwatch now", False),     # больше двух строк
        ("🌐 Links:\nwatch", False),
        ("🔹 subscribe", False),
        ("- subscribe", False),
        ("Subscribe\nhttps://example.org", False),
        ("Plain factual paragraph", False),
        ("", False),
    ],
)
def test_looks_like_cta_paragraph(text: str, expected: bool) -> None:
    assert LEXICON.looks_like_cta_paragraph(text) is expected


def test_lexicon_without_hints_only_sees_hashtags() -> None:
    bare: CtaLexicon = CtaLexicon(DONOR_CTA_PREFIXES)
    assert bare.looks_like_cta_paragraph("Watch the stream") is False
    assert bare.looks_like_cta_paragraph("Watch the stream #tag") is True


@pytest.mark.parametrize(
    ("line", "is_bullet", "marker"),
    [
        ("🔹 point", True, "🔹"),
        ("  ✅ done", True, "✅"),
        ("🔹point", False, ""),
        ("- point", True, "-"),
        ("• point", True, "•"),
        ("12) point", True, "12)"),
        ("3. point", True, "3."),
        ("— point", True, "—"),
        ("-point", False, ""),
        ("🌐 Official links:", False, "🌐"),    # правило донора: заголовок ссылок маркер 🌐 сохраняет
        ("🌐 site.org", True, "🌐"),
        ("", False, ""),
    ],
)
def test_bullet_line_and_marker(line: str, is_bullet: bool, marker: str) -> None:
    assert is_bullet_line(line) is is_bullet
    assert bullet_marker_for_line(line) == marker


def test_named_entities() -> None:
    text: str = "John Smith met Віталій Орлов and Anna Karenina Lee; Al Bo is too short, Kyiv alone too."
    assert extract_named_entities(text) == {"john smith", "віталій орлов", "anna karenina lee"}
    assert extract_named_entities("") == set()
