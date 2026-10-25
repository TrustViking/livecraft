from __future__ import annotations

import pytest

from app.resources.loader import TextResource
from app.texts.phrase_lexicon import SERVICE_HINTS_RESOURCE, PhraseLexicon, ServiceHints

HINTS: ServiceHints = ServiceHints.load()


def test_a_phrase_is_found_as_a_substring_of_the_normalized_text() -> None:
    lexicon: PhraseLexicon = PhraseLexicon(("links below", "подпис"))
    assert lexicon.found_in("see the links below, friends")
    assert lexicon.found_in("подписывайтесь")
    assert not lexicon.found_in("links  below")          # нормализует текст владелец лексикона, а не лексикон
    assert not PhraseLexicon(()).found_in("anything")


def test_service_hints_are_the_resource_file_read_once() -> None:
    assert HINTS.phrases.phrases == TextResource(SERVICE_HINTS_RESOURCE).lines
    assert ServiceHints.load() is ServiceHints.load()


@pytest.mark.parametrize(
    "paragraph",
    ["", "   ", "Subscribe to the channel", "Посилання  нижче: підписуйтесь", "🌐 Official links:", "Links below #stream"],
)
def test_service_tail_paragraph(paragraph: str) -> None:
    assert HINTS.is_tail_paragraph(paragraph)


@pytest.mark.parametrize(
    "paragraph",
    [
        "Tonight we map the sanctions vote and the transport shock in Kharkiv.",
        "watch " + "word " * 12,                                  # тринадцать смысловых слов — уже не служебная строка
        "Subscribe " + "x" * 220,                                 # длиннее 220 знаков
    ],
)
def test_not_a_service_tail_paragraph(paragraph: str) -> None:
    assert not HINTS.is_tail_paragraph(paragraph)


def test_without_phrases_only_empty_and_heading_are_service() -> None:
    bare: ServiceHints = ServiceHints(PhraseLexicon(()))
    assert bare.is_tail_paragraph("")
    assert bare.is_tail_paragraph("🌐 Links:")
    assert not bare.is_tail_paragraph("Subscribe to the channel")
