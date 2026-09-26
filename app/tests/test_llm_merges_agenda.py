"""Заголовок повестки («Что в этом стриме:») — признак пересказа вместо описания."""
from __future__ import annotations

import pytest

from app.llm.merges.agenda import AgendaLexicon


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Hook.\n\nЧто в этом стриме:\n🔹 a", True),
        ("Hook.\n\n  In   this stream — budget", True),
        ("Hook.\n\nПро що поговоримо", True),
        ("Hook.\n\nwhat’s in this stream!", True),
        ("Hook.\n\nIn this stream you'll see:", False),
        ("In this streamline", False),
    ],
)
def test_agenda_heading(text: str, expected: bool) -> None:
    assert AgendaLexicon.load().matches(text) is expected


def test_agenda_lexicon_keeps_its_headings() -> None:
    assert AgendaLexicon.load().headings == (
        "что в этом стриме", "в этом выпуске", "о чем поговорим", "що в цьому стрімі", "про що поговоримо",
        "what's in this stream", "what’s in this stream", "in this stream",
    )
