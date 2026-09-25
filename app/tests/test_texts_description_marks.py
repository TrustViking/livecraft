from __future__ import annotations

import pytest

from app.resources.loader import TextResource
from app.texts.description_marks import (
    ALLOWED_BULLET_MARKERS,
    CTA_PREFIXES_RESOURCE,
    URL_LINE_PATTERN,
    CtaLexicon,
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
