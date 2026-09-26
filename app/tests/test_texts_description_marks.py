from __future__ import annotations

import pytest

from app.core.web_link import URL_LINE_PATTERN
from app.resources.loader import TextResource
from app.texts.description_marks import (
    ALLOWED_BULLET_MARKERS,
    CTA_HINTS_RESOURCE,
    CTA_PREFIXES_RESOURCE,
    BulletLine,
    CtaLexicon,
    FinalParagraph,
    TextTail,
    extract_named_entities,
    is_official_links_heading,
)

CTA_PREFIXES: tuple[str, ...] = (
    "Підпишіть", "Підписуйт", "Слідкуй", "Subscribe", "Watch", "Follow", "Join", "Смотри", "Подпишит", "Следи",
    "Поширюйт", "Поділіться", "Приєднуйт", "Подпишитесь", "Leave a comment", "Write a comment",
    "Напишіть у коментар", "Залиште коментар", "Напишите в комментар", "Оставьте комментар", "Оставляйте комментар",
)


@pytest.mark.parametrize("value", ["🌐 Hivatalos linkek:", "🌐 Officiële links:", "🌐 公式リンク:", "🌐 Officiel lenker:"])
def test_official_links_heading_in_any_language(value: str) -> None:
    assert is_official_links_heading(value) is True


@pytest.mark.parametrize("value", ["Hivatalos linkek:", "🌐 :", "random text", "🌐 Foo: bar", "", "🌐 Foo"])
def test_not_an_official_links_heading(value: str) -> None:
    assert is_official_links_heading(value) is False


def test_heading_edges_are_ignored() -> None:
    assert is_official_links_heading("   🌐Links:   ") is True


def test_cta_lexicon_is_the_resource_file() -> None:
    assert CtaLexicon.load().prefixes == CTA_PREFIXES
    assert TextResource(CTA_PREFIXES_RESOURCE).path.is_file()


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Підпишіться та напишіть у коментарях", True),
        ("  subscribe to the channel", True),
        ("Watching the vote is key", True),        # префикс, а не слово
        ("Сьогодні розбираємо рішення", False),
        ("", False),
    ],
)
def test_starts_with_cta_prefix(text: str, expected: bool) -> None:
    assert CtaLexicon(CTA_PREFIXES).starts_with_prefix(text) is expected


def test_blank_prefixes_never_match() -> None:
    assert CtaLexicon(("", "  ")).starts_with_prefix("anything") is False
    assert CtaLexicon(("", "watch")).starts_with_prefix("WATCH now") is True


def test_markers_and_url_line() -> None:
    assert ALLOWED_BULLET_MARKERS == ("🔹", "📌", "🎤", "🎥", "⚖", "🌐", "✅")
    assert URL_LINE_PATTERN.fullmatch("HTTPS://YouTu.be/x") is not None
    assert URL_LINE_PATTERN.fullmatch("https://example.org/a b") is None


CTA_HINTS: tuple[str, ...] = (
    "watch", "learn more", "join", "subscribe", "follow", "read more", "links below", "details below", "дивіться",
    "долуч", "підпис", "узнать больше", "смотрите", "подпис", "подробности", "comment", "leave a comment",
    "write a comment", "коментар", "напишіть у коментар", "залиште коментар", "комментар", "оставьте комментар",
    "напишите комментар", "оставляйте комментар",
)
LEXICON: CtaLexicon = CtaLexicon.load()


def test_cta_hints_are_the_resource_file() -> None:
    assert LEXICON.hints == CTA_HINTS
    assert TextResource(CTA_HINTS_RESOURCE).path.is_file()


def test_word_start_hints_are_the_resource_file() -> None:
    assert LEXICON.prefix_hints == {"долуч", "підпис", "подпис", "коментар", "комментар", "comment"}
    assert LEXICON.prefix_hints <= set(LEXICON.hints)


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
    bare: CtaLexicon = CtaLexicon(CTA_PREFIXES)
    assert bare.looks_like_cta_paragraph("Watch the stream") is False
    assert bare.looks_like_cta_paragraph("Watch the stream #tag") is True


@pytest.mark.parametrize(
    ("line", "is_list_item", "marker"),
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
        ("🌐 Official links:", False, "🌐"),    # заголовок ссылок — не пункт, но маркер 🌐 у него есть
        ("🌐 site.org", True, "🌐"),
        ("", False, ""),
    ],
)
def test_bullet_line_and_marker(line: str, is_list_item: bool, marker: str) -> None:
    assert BulletLine.of(line).is_list_item is is_list_item
    assert BulletLine.of(line).marker == marker


def test_links_heading_is_a_bullet_for_sanitation_but_not_for_the_answer_check() -> None:
    heading: BulletLine = BulletLine.of("🌐 Official links:")
    assert heading.is_bullet is True
    assert heading.is_list_item is False


@pytest.mark.parametrize(
    ("line", "content", "has_marker_prefix"),
    [
        ("🔹 point", "point", True),
        ("  📌   pinned ", "pinned", True),
        ("🔹point", "🔹point", True),                # маркер без пробела — не пункт, но строка начинается маркером
        ("- dash point", "dash point", False),
        ("2) numbered", "numbered", False),
        ("plain text", "plain text", False),
        ("", "", False),
    ],
)
def test_bullet_content_and_marker_prefix(line: str, content: str, has_marker_prefix: bool) -> None:
    bullet: BulletLine = BulletLine.of(line)
    assert bullet.content == content
    assert bullet.has_marker_prefix is has_marker_prefix


def test_named_entities() -> None:
    text: str = "John Smith met Віталій Орлов and Anna Karenina Lee; Al Bo is too short, Kyiv alone too."
    assert extract_named_entities(text) == {"john smith", "віталій орлов", "anna karenina lee"}
    assert extract_named_entities("") == set()


# --- правила хвоста-призыва


@pytest.mark.parametrize(
    "line",
    [
        "Напишите в комментариях, какие вопросы вы считаете ключевыми.",
        "Напишіть у коментарях, що ви думаєте про це.",
        "Write a comment and share your thoughts on this topic.",
        "- Subscribe to our channel",
        "Watch the full stream here",
    ],
)
def test_standalone_cta_lines(line: str) -> None:
    assert LEXICON.is_standalone_line(line)


def test_long_factual_text_with_a_comment_word_is_not_a_standalone_cta() -> None:
    long_text: str = (
        "Юрист прокомментировал ситуацию и дал развёрнутый комментарий о позиции защиты, "
        "включая анализ доказательной базы, свидетельских показаний и процедурных нарушений, "
        "которые были допущены в ходе следствия по делу обвиняемого."
    )
    assert not LEXICON.is_standalone_line(long_text)
    assert not LEXICON.is_standalone_line("   ")


def test_the_last_cta_sentence_or_the_whole_cta_paragraph_goes_to_the_tail() -> None:
    assert LEXICON.split_final_sentence("Facts come first. Join us tonight and share your thoughts.") == TextTail(
        text="Facts come first.", tail="Join us tonight and share your thoughts."
    )
    assert LEXICON.split_final_sentence("Subscribe to our channel") == TextTail(text="", tail="Subscribe to our channel")
    assert LEXICON.split_final_sentence("Facts come first. More facts arrive later.") == TextTail(
        text="Facts come first. More facts arrive later."
    )
    assert LEXICON.split_final_sentence("  ") == TextTail(text="")


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("", FinalParagraph.EMPTY),
        ("Subscribe to our channel", FinalParagraph.SINGLE_PARAGRAPH),
        ("Facts about the vote.\n\nSubscribe to our channel", FinalParagraph.CTA),
        ("Facts about the vote.\n\nMore facts arrive later.", FinalParagraph.NOT_CTA),
        ("Facts about the vote.\n\n\U0001F539 Subscribe to our channel", FinalParagraph.NOT_CTA),
    ],
)
def test_the_final_paragraph_of_the_body(body: str, expected: FinalParagraph) -> None:
    assert LEXICON.final_paragraph(body) is expected
