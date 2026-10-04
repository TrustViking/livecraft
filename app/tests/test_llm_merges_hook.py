"""Негодный первый абзац: самореклама канала, призыв, редакторская преамбула вместо факта."""
from __future__ import annotations

import pytest

from app.llm.merges.hook import BAD_HOOK_PATTERNS_RESOURCE, BadHookLexicon
from app.resources.loader import TextResource

# Признаки негодного тезиса — стартовые данные: значения и порядок ресурса.
SHIPPED_BAD_HOOK_PATTERNS: tuple[str, ...] = (
    "наш канал", "наш некомерційний", "наш неприбутковий", "наш неприбутков", "не просуває", "не пропагує",
    "не продвигает", "не пропагандирует", "our channel", "our nonprofit", "if you want more", "if you'd like more",
    "хочете продовження", "хотите продолжения", "write in the comments", "напишіть у коментарях",
    "напишите в комментариях", "поширюйте", "поділіться", "приєднуйтесь", "stay tuned", "поделитесь",
    "смотрите полный", "watch the full", "follow the full", "если вы смотрели стрим",
    "если вы смотрели стрим, напишите",
    "матеріал подано", "матеріал представлено", "матеріал підготовлено", "матеріал розміщено",
    "цей матеріал є частиною", "цей матеріал подано", "матеріал публікується", "материал подан",
    "материал представлен", "материал подготовлен", "материал публикуется", "этот материал является частью",
    "данный материал", "this material is presented", "this material is part of", "this content is presented",
    "this video is part of", "presented as part of", "in the context of", "within the context of",
    "as part of an ongoing", "в контексті", "в рамках обговорення", "в рамках обсуждения", "в рамках розслідування",
    "в рамках расследования", "в рамках документального",
)


def test_bad_hook_resource_keeps_its_values_and_order() -> None:
    assert BadHookLexicon.load().patterns.phrases == SHIPPED_BAD_HOOK_PATTERNS


def test_bad_hook_resource_starts_with_the_origin_comment() -> None:
    first_line: str = TextResource(BAD_HOOK_PATTERNS_RESOURCE).path.read_text(encoding="utf-8").splitlines()[0]
    assert first_line.startswith("#")


def test_soft_cta_opener_is_a_bad_hook() -> None:
    soft_cta_line: str = (
        "Если вы смотрели стрим, напишите, какие эпизоды февраля 2026 года показались вам самыми показательными."
    )
    assert BadHookLexicon.load().matches(soft_cta_line)


@pytest.mark.parametrize(
    ("paragraph", "expected"),
    [("OUR   CHANNEL is great", True), ("Факти дня про енергетику", False), ("", False), ("   ", False)],
)
def test_bad_hook_matches_ignoring_case_and_spacing(paragraph: str, expected: bool) -> None:
    assert BadHookLexicon.load().matches(paragraph) is expected
