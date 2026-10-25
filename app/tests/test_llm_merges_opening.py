"""Начало описания: призыв в первой строке, призыв раньше тезиса и пунктов, служебная строка вместо тезиса."""
from __future__ import annotations

from app.llm.merges.description import MergedDescription
from app.llm.merges.hook import BadHookLexicon
from app.llm.merges.opening import DescriptionOpening
from app.texts.description_marks import CtaLexicon
from app.texts.phrase_lexicon import ServiceHints

CTA: CtaLexicon = CtaLexicon.load()
BAD_HOOKS: BadHookLexicon = BadHookLexicon.load()
SERVICE_HINTS: ServiceHints = ServiceHints.load()
NEUTRAL: str = chr(0x1F539)


def of(text: str) -> DescriptionOpening:
    return DescriptionOpening(MergedDescription(text))


def test_opener_cta_looks_only_at_the_first_non_empty_line() -> None:
    assert of("  \nПідпишіться на канал.\n\nДалі.").starts_with_cta(CTA)
    assert not of("Факти дня.\nПідпишіться на канал.").starts_with_cta(CTA)
    assert not of("").starts_with_cta(CTA)
    assert of("  \nПідпишіться на канал.\n\nДалі.").first_line == "Підпишіться на канал."
    assert of("").first_paragraph == "" and of("").first_line == ""


def opening(text: str) -> bool:
    return of(text).cta_before_content(CTA, BAD_HOOKS, SERVICE_HINTS)


def test_cta_before_the_hook_is_found() -> None:
    assert opening("Subscribe to the channel.\nTonight we map the sanctions vote.\n\n🔹 point")


def test_bad_hook_line_before_the_bullets_is_found() -> None:
    """Мягкий призыв («если вы смотрели стрим, напишите…») — негодный тезис: он стоит раньше пунктов."""
    soft_cta: str = (
        "Если вы смотрели стрим, напишите, какие эпизоды февраля 2026 года показались вам самыми показательными."
    )
    assert opening(f"{soft_cta}\n\n{NEUTRAL} Первый факт из эфира с проверяемым источником.")


def test_only_cta_and_service_lines_in_the_window_count_as_cta_first() -> None:
    assert opening("Subscribe to the channel.\n\nLinks below")


def test_cta_after_the_hook_or_a_bullet_is_not_cta_first() -> None:
    assert not opening("Tonight we map the sanctions vote.\nSubscribe to the channel.")
    assert not opening(f"{NEUTRAL} Subscribe to the channel point.\nSubscribe to the channel.")


def test_cta_outside_the_three_line_window_is_not_seen() -> None:
    assert not opening("Line one here.\nLine two here.\nLine three here.\nSubscribe to the channel.")
    assert not opening("Hook.\n\nBody.\n\nSubscribe to the channel.")   # третий абзац в окно не входит


def test_no_text_has_no_cta_first() -> None:
    assert not opening("")


def test_service_line_or_bad_hook_as_first_paragraph_is_a_service_hook() -> None:
    assert of("Links below\n\nTonight we map the vote.").hook_is_service_line(BAD_HOOKS, SERVICE_HINTS)
    assert of("Our channel covers the vote tonight.\n\nBody.").hook_is_service_line(BAD_HOOKS, SERVICE_HINTS)
    assert not of("Tonight we map the vote.\n\nBody.").hook_is_service_line(BAD_HOOKS, SERVICE_HINTS)
    assert not of("").hook_is_service_line(BAD_HOOKS, SERVICE_HINTS)
