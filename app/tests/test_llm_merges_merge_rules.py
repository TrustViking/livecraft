"""Правила merge одним плоским объектом: словари читаются один раз, проверка перед публикацией — из тех же словарей."""
from __future__ import annotations

import pytest

from app.llm.merges.merge_rules import MergeLexicons, MergeRules, PublishGate

RULES: MergeRules = MergeRules.load()


def test_the_lexicons_are_read_once_per_process() -> None:
    assert MergeLexicons.load() is MergeLexicons.load() is RULES.lexicons


def test_the_gate_uses_the_lexicons_of_the_rules() -> None:
    assert RULES.gate == PublishGate(bad_hooks=RULES.lexicons.bad_hooks, cta=RULES.lexicons.cta)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Climate change accelerates in Arctic regions.\n\n\U0001F539 New data shows...", False),
        ("Subscribe to our channel for updates!\n\n\U0001F539 Today we discuss...", True),
        ("Leave a comment with what stood out most.\n\n\U0001F539 Today we discuss...", True),
        ("Напишіть у коментар ваші думки.\n\n\U0001F539 Сьогодні розглянемо...", True),
        ("Оставляйте комментарии по фактам.\n\n\U0001F539 Сегодня разберем...", True),
        ("This video is part of our coverage of the vote.\n\n\U0001F539 Facts.", True),
        ("", False),
    ],
)
def test_gate_opener_cta(text: str, expected: bool) -> None:
    assert RULES.gate.has_opener_cta(text) is expected
