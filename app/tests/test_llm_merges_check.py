from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from app.llm.merges.check import (
    CheckEvent,
    MergeAttemptLabel,
    MergeCheck,
    MergeCheckPassed,
    MergeCheckRequest,
    MergeDiagnostics,
)
from app.llm.merges.description import MergedDescription
from app.llm.merges.links import OfficialLinkSelection
from app.llm.merges.merge_rules import MergeLexicons
from app.llm.merges.quality import QualityGateStatus, QualityReasonCode
from app.llm.merges.reject import MergeReject, MergeRejectCode, MergeRejectStage
from app.observability.log_event import LogArea
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.merges import (
    CHECK_LABEL,
    EMOJI,
    EXPANDED_SOURCES,
    RULES,
    TWO_SOURCES,
    HOOK,
    LONG_ALPHA,
    LONG_BETA,
    STRONG_BULLETS,
    STRONG_CLOSE,
    STRONG_HOOK,
    bullets,
    check_as_is,
    check_request,
    check_with_gate,
    label_in,
    merge_check,
)

LEXICONS: MergeLexicons = RULES.lexicons
LABEL: MergeAttemptLabel = CHECK_LABEL
NEUTRAL: str = chr(0x1F539)


def reject_code(verdict: MergeCheckPassed | MergeReject) -> str:
    assert isinstance(verdict, MergeReject), verdict
    return verdict.reason_code


@pytest.fixture
def llm_log() -> Iterator[LogCapture]:
    with LogCapture.on(LogArea.LLM, logging.INFO) as capture:
        yield capture


# --- сильный и слабый ответ целиком


def test_strong_three_source_answer_passes() -> None:
    answer: str = f"{STRONG_HOOK}\n\nIn this stream you'll see:\n{bullets(STRONG_BULLETS)}\n\n{STRONG_CLOSE}"
    check: MergeCheck = merge_check(answer, title="Brussels, Kharkiv, Geneva: the operational agenda tonight")
    verdict: MergeCheckPassed | MergeReject = check.run()
    assert isinstance(verdict, MergeCheckPassed)
    assert verdict.diagnostics.bullet_points_count == 6
    assert "bullet_points_count=6" in check.diagnostics.events(LABEL)[0].text


def test_dense_two_paragraph_answer_passes() -> None:
    answer: str = f"{STRONG_HOOK}\n\nIn this stream you'll see:\n{bullets(STRONG_BULLETS)}"
    assert isinstance(merge_check(answer).run(), MergeCheckPassed)


def test_overly_generic_three_source_answer_lacks_bullets() -> None:
    answer: str = (
        "Tonight we step back and frame several important developments inside one smooth and readable opening that "
        "sounds strong but stays broad. It keeps attention on the mood and the overall stakes instead of distinct "
        "source facts.\n\nIn this stream you'll see:\n"
        + bullets(["the main context and why it matters", "the broader background and tensions",
                   "how the story fits a larger pattern"])
        + "\n\nA polished closing paragraph keeps the editorial flow consistent for viewers."
    )
    check: MergeCheck = merge_check(answer, title="Why these developments matter tonight")
    assert reject_code(check.run()) == "insufficient_bullet_coverage"
    assert check.diagnostics.bullet_points_count == 3


def test_two_sources_with_eight_bullets_overflow_the_compact_contract() -> None:
    answer: str = (
        "Tonight we map concrete outcomes from two linked source agendas and keep each detail grounded.\n\n"
        "In this stream you'll see:\n" + bullets([f"Concrete point number {n} with timing and consequence." for n in "12345678"])
    )
    assert reject_code(check_as_is(answer, TWO_SOURCES, "Two-source agenda with too many bullets").run()) == (
        "compact_bullet_overflow"
    )


def test_hook_echo_is_repaired_and_logged(llm_log: LogCapture) -> None:
    hook: str = (
        "Февральский эфир показал, как один тезис многократно повторяется в разных формулировках, и это требует "
        "аккуратной проверки фактов перед выводами о последствиях."
    )
    echo: str = (
        "Февральский эфир показал, как один тезис многократно повторяется в разных формулировках, но ниже идут новые "
        "подтверждения из источников без рекламного тона.\n"
        + bullets(["Первый подтвержденный факт с датой и участниками обсуждения.",
                   "Второй подтвержденный факт с последствиями для повестки."])
    )
    answer: str = f"{hook}\n\n{echo}\n\nТретий абзац добавляет отдельный контекст и не повторяет открывающий тезис."
    check: MergeCheck = merge_check(answer, pairs=(), title="Итоговый заголовок", language="ru")
    verdict: MergeCheckPassed | MergeReject = check.run()
    assert isinstance(verdict, MergeCheckPassed)
    assert verdict.description.text != check.description.text
    assert verdict.description.paragraphs[1].startswith(NEUTRAL)
    assert verdict.diagnostics is check.diagnostics                 # диагностика — до починки
    assert label_in("ru").event(CheckEvent.HOOK_ECHO_REPAIRED).text in llm_log.messages()
    assert llm_log.messages()[-1].startswith("hook_echo_repair_applied=yes slot=16-10-2026_1900_en language=ru ")


# --- каждая причина отказа отдельно


def test_per_source_dump_is_rejected() -> None:
    assert reject_code(check_as_is("SOURCE 1: Point one.\n\nSOURCE 2: Point two.", TWO_SOURCES).run()) == (
        "per_source_enumeration"
    )


def test_duplicate_paragraphs_are_rejected() -> None:
    paragraph: str = "The same paragraph with enough words to be compared by the duplicate rule."
    assert reject_code(check_as_is(f"{HOOK}\n\n{paragraph}\n\n{paragraph}").run()) == "duplicate_paragraph"


def test_unrepairable_hook_echo_is_rejected() -> None:
    body: str = HOOK[:50] + " but tonight we also look at seven regional budget lines and hospitals"
    answer: str = f"{HOOK}\n\n{body}\n\nClosing words without bullets."
    assert reject_code(check_as_is(answer).run()) == "hook_echo_in_body"


def test_adjacent_repeated_lines_are_rejected() -> None:
    line: str = "Brussels sanctions vote and budget amendments after the March 18 commission session"
    answer: str = f"{HOOK}\n\n{NEUTRAL} {line}\n{NEUTRAL} {line} again"
    assert reject_code(check_as_is(answer).run()) == "duplicate_paragraph"


def test_cta_before_the_hook_is_rejected() -> None:
    assert reject_code(check_as_is(f"Subscribe to the channel.\n{HOOK}\n\n{bullets(STRONG_BULLETS[:2])}").run()) == (
        "cta_as_first_paragraph"
    )


def test_service_line_as_hook_is_rejected() -> None:
    assert reject_code(check_as_is(f"Links below\n\n{HOOK}\n\n{bullets(STRONG_BULLETS[:2])}").run()) == "cta_in_hook"


def test_bad_hook_as_first_paragraph_is_rejected() -> None:
    answer: str = f"This video is part of our coverage of the vote.\n{HOOK}\n\n{bullets(STRONG_BULLETS[:2])}"
    assert reject_code(check_as_is(answer).run()) in {"cta_as_first_paragraph", "cta_in_hook"}
    answer_after_hook: str = f"{HOOK}\nThis video is part of our coverage.\n\n{bullets(STRONG_BULLETS[:2])}"
    assert reject_code(check_as_is(answer_after_hook).run()) == "cta_in_hook"


@pytest.mark.parametrize(("source_count", "bullet_count"), [(2, 4), (3, 4), (4, 4), (5, 5)])
def test_too_few_bullets_for_the_sources(source_count: int, bullet_count: int) -> None:
    pairs: tuple[tuple[str, str], ...] = tuple((f"Source {n}", "Body.") for n in range(source_count))
    answer: str = f"{HOOK}\n\n{bullets([f'Point {n} with its own detail' for n in range(bullet_count)])}"
    assert reject_code(check_as_is(answer, pairs).run()) == "insufficient_bullet_coverage"


def test_enough_bullets_for_the_sources_pass_the_count() -> None:
    pairs: tuple[tuple[str, str], ...] = tuple((f"Source {n}", "Body.") for n in range(5))
    answer: str = f"{HOOK}\n\n{bullets([f'Point {n} with its own detail' for n in range(6)])}"
    assert isinstance(check_as_is(answer, pairs).run(), MergeCheckPassed)


def test_one_source_has_no_bullet_minimum() -> None:
    assert isinstance(check_as_is(f"{HOOK}\n\nBody paragraph.", (("One", "Body."),)).run(), MergeCheckPassed)


def test_more_than_ten_emoji_are_rejected() -> None:
    answer: str = f"{HOOK} {' '.join(EMOJI)} {EMOJI[0]}\n\n{bullets(STRONG_BULLETS[:2])}"
    check: MergeCheck = check_as_is(answer, (("One", "Body."),))
    assert check.diagnostics.emoji_count == 11
    assert reject_code(check.run()) == "excessive_emoji_usage"
    assert isinstance(check_as_is(f"{HOOK} {' '.join(EMOJI)}\n\nBody.", (("One", "Body."),)).run(), MergeCheckPassed)


def test_two_overloaded_bullets_in_a_list_of_four_are_rejected() -> None:
    answer: str = f"{HOOK}\n\n{bullets([LONG_ALPHA, LONG_BETA, 'short one', 'short two'])}"
    verdict: MergeCheckPassed | MergeReject = check_as_is(answer).run()
    assert reject_code(verdict) == "overloaded_bullet"
    assert isinstance(verdict, MergeReject) and verdict.detail == "count=2"
    three_bullets: str = f"{HOOK}\n\n{bullets([LONG_ALPHA, LONG_BETA, 'short one'])}"
    assert isinstance(check_as_is(three_bullets).run(), MergeCheckPassed)


@pytest.mark.parametrize("title", ["Budget 1) and sanctions", "Тема 1) бюджет", "Part 2) now"])
def test_numbered_title_is_rejected(title: str) -> None:
    assert reject_code(check_as_is(f"{HOOK}\n\nBody paragraph.", title=title).run()) == "numbered_title_dump"


@pytest.mark.parametrize("title", ["A1) x", "Part 2)", "(1)intro", "1.) x"])
def test_title_without_a_numbered_item_passes(title: str) -> None:
    assert isinstance(check_as_is(f"{HOOK}\n\nBody paragraph.", title=title).run(), MergeCheckPassed)


def test_paragraphs_with_the_same_long_start_are_rejected() -> None:
    start: str = "Brussels sanctions vote and the budget amendments after the March 18 commission session "
    answer: str = (
        f"{HOOK}\n\nSecond paragraph about Kharkiv rail outages.\n\n"
        f"{start}with customs delays for traders.\n\n{start}bring a different set of consequences for hospitals."
    )
    check: MergeCheck = check_as_is(answer)
    assert not check.description.has_duplicate_paragraphs
    assert reject_code(check.run()) == "duplicate_paragraph"


def test_semantic_gate_rejects_with_normalized_gate_codes() -> None:
    check: MergeCheck = check_as_is(f"{HOOK}\n\nBody paragraph.")
    codes: tuple[QualityReasonCode, ...] = (
        QualityReasonCode.MISSING_BLOCK_SPACING, QualityReasonCode.SCRIPT_MIX_CONTAMINATION
    )
    verdict: MergeCheckPassed | MergeReject = check_with_gate(check, QualityGateStatus.HARD_REJECT, codes).run()
    assert isinstance(verdict, MergeReject)
    assert verdict.code is MergeRejectCode.SEMANTIC_GATE
    assert verdict.reason_codes == ("missing_block_spacing", "script_mix_contamination")
    assert verdict.reason_code == "missing_block_spacing"


def test_needs_normalization_status_does_not_reject() -> None:
    check: MergeCheck = check_as_is(f"{HOOK}\n\nBody paragraph.")
    assert isinstance(check_with_gate(check, QualityGateStatus.NEEDS_NORMALIZATION).run(), MergeCheckPassed)


def test_mixed_script_description_is_rejected_by_the_gate() -> None:
    answer: str = f"{HOOK}\n\nIn this stream you'll see:\n{bullets(['budget timeline and m' + chr(0x438) + 'xed contamination inside the main bullet', 'verified operational follow-up'])}"
    verdict: MergeCheckPassed | MergeReject = merge_check(answer, pairs=(("One", "Body."),)).run()
    assert isinstance(verdict, MergeReject) and verdict.code is MergeRejectCode.SEMANTIC_GATE
    assert "script_mix_contamination" in verdict.reason_codes


# --- порядок проверок: первая сработавшая побеждает


def test_per_source_dump_wins_over_emoji_and_bullets() -> None:
    answer: str = f"Source 1: {' '.join(EMOJI)} {EMOJI[0]}\nSource 2: point"
    assert reject_code(check_as_is(answer, EXPANDED_SOURCES).run()) == "per_source_enumeration"


def test_cta_first_wins_over_missing_bullets_and_numbered_title() -> None:
    answer: str = f"Subscribe to the channel.\n{HOOK}\n\nBody."
    assert reject_code(check_as_is(answer, EXPANDED_SOURCES, "Budget 1) vote").run()) == "cta_as_first_paragraph"


def test_bullet_count_wins_over_emoji() -> None:
    answer: str = f"{HOOK} {' '.join(EMOJI)} {EMOJI[0]}\n\n{bullets(STRONG_BULLETS[:3])}"
    assert reject_code(check_as_is(answer, EXPANDED_SOURCES).run()) == "insufficient_bullet_coverage"


def test_emoji_win_over_overloaded_bullets_and_numbered_title() -> None:
    answer: str = f"{HOOK} {' '.join(EMOJI)} {EMOJI[0]}\n\n{bullets([LONG_ALPHA, LONG_BETA, 'a', 'b'])}"
    assert reject_code(check_as_is(answer, (("One", "Body."),), "Budget 1) vote").run()) == "excessive_emoji_usage"


def test_numbered_title_wins_over_similar_paragraphs_and_the_gate() -> None:
    start: str = "Brussels sanctions vote and the budget amendments after the March 18 commission session "
    answer: str = f"{HOOK}\n\nSecond.\n\n{start}one ending here.\n\n{start}another ending with more words."
    check: MergeCheck = check_as_is(answer, title="Vote 1) now")
    assert reject_code(check_with_gate(check, QualityGateStatus.HARD_REJECT).run()) == "numbered_title_dump"


# --- диагностика и строки лога


def test_attempt_label_starts_the_log_line_and_names_the_request() -> None:
    assert LABEL.event(CheckEvent.STYLE).text == "merge_style_coverage slot=16-10-2026_1900_en language=en model=gpt-x attempt=2"
    assert LABEL.request_label == "merge_en_primary_2"


def test_diagnostics_count_bullets_markers_entities_and_links() -> None:
    pairs: tuple[tuple[str, str], ...] = (
        ("Anna Kovalenko briefing", "Official site: https://example.org/ and https://youtu.be/aaaaaaaaaaa"),
        ("Oleh Martynenko update", "Details https://news.example.com/story?utm_source=x"),
    )
    answer: str = (
        f"{HOOK} Anna Kovalenko opens: why now?\n\n{NEUTRAL} first point\n- second point\n1) third point\n"
        f"{chr(0x1F4CC)} fourth point\n\nSee https://example.org and https://www.example.org/uk and https://youtu.be/bbbbbbbbbbb"
    )
    request: MergeCheckRequest = check_request("Title", answer, pairs)
    diagnostics: MergeDiagnostics = MergeDiagnostics.of(
        request, MergedDescription(answer), check_as_is(answer, pairs).quality, LEXICONS
    )
    assert diagnostics.bullet_points_count == 4
    assert diagnostics.semantic_bullets_count == diagnostics.bullets_with_emoji_count == 2
    assert diagnostics.bullets_with_plain_marker_count == 2
    assert diagnostics.bullet_marker_types == (NEUTRAL, "-", "1)", chr(0x1F4CC))
    assert diagnostics.hook_present and diagnostics.agenda_block_present
    assert diagnostics.named_entities_preserved == 1
    assert diagnostics.source_named_entities_total == 2
    assert (diagnostics.links.found_in_sources, len(diagnostics.links.kept_links)) == (2, 2)
    assert diagnostics.official_links_in_output == 1


def test_links_in_output_are_counted_on_the_answer_before_normalization() -> None:
    request: MergeCheckRequest = check_request("Title", "Body https://a.org https://b.org", (("One", "Body."),))
    diagnostics: MergeDiagnostics = MergeDiagnostics.of(request, MergedDescription("Body"), check_as_is("Body").quality, LEXICONS)
    assert diagnostics.official_links_in_output == 2
    assert diagnostics.links == OfficialLinkSelection(found_in_sources=0, kept_links=())


def test_short_first_paragraph_is_not_a_hook_and_few_bullets_are_not_an_agenda() -> None:
    diagnostics: MergeDiagnostics = check_as_is(f"Short hook: yes\n\n{bullets(['a', 'b'])}").diagnostics
    assert not diagnostics.hook_present
    assert not diagnostics.agenda_block_present
    assert check_as_is(f"{HOOK}\n\nIn this stream: budget\n{bullets(['a'])}").diagnostics.agenda_block_present


def test_log_lines_name_the_diagnostics_and_have_no_description_text() -> None:
    secret_word: str = "Zanzibarquux"
    answer: str = f"{HOOK} {secret_word}!\n\n{bullets([secret_word + ' point', 'second point'])}"
    diagnostics: MergeDiagnostics = merge_check(answer, pairs=(("One", "Body."),), title=f"{secret_word} title").diagnostics
    style, gate = (event.text for event in diagnostics.events(LABEL))
    assert secret_word not in style and secret_word not in gate
    assert style.startswith(f"{LABEL.event(CheckEvent.STYLE).text} style_contract_version=v4_merge_quality_hardening ")
    style_keys: list[str] = [part.split("=")[0] for part in style.split(" ")[5:]]
    assert style_keys == [
        "style_contract_version", "hook_present", "agenda_block_present", "bullet_points_count", "semantic_bullets_count",
        "bullets_with_emoji_count", "bullets_with_plain_marker_count", "bullet_marker_types", "neutral_bullets_count",
        "accent_bullets_count", "accent_marker_types", "accent_overflow", "block_spacing_ok", "named_entities_preserved",
        "source_named_entities_total", "named_entities_metric", "emoji_count", "official_links_found_in_sources",
        "official_links_kept", "official_links_in_output", "official_links_fill_applied",
    ]
    gate_keys: list[str] = [part.split("=")[0] for part in gate.split(" ")[5:]]
    assert gate_keys == [
        "block_language_expected", "hook_language_detected", "lead_in_language_detected",
        "links_heading_language_detected", "cta_language_detected", "language_consistency_ok",
        "wrong_language_heading_detected", "script_mix_detected", "script_mix_suspects", "semantic_gate_status",
        "semantic_gate_reason_codes",
    ]
    assert "official_links_fill_applied=no" in style and "named_entities_metric=informational" in style


def test_gate_line_carries_the_gate_verdict() -> None:
    mixed: str = f"{HOOK}\n\n{bullets(['budget amendments', 'бюджетні поправки'])}"
    _, gate = (event.text for event in merge_check(mixed, pairs=(("One", "Body."),)).diagnostics.events(LABEL))
    assert "block_language_expected=en " in gate and "script_mix_detected=yes " in gate
    assert gate.endswith("semantic_gate_status=hard_reject semantic_gate_reason_codes=script_mix_contamination")
    clean_check: MergeCheck = merge_check(f"{HOOK}\n\n{bullets(['budget amendments'])}", pairs=(("One", "Body."),))
    _, clean = (event.text for event in clean_check.diagnostics.events(LABEL))
    assert "script_mix_suspects=- " in clean and clean.endswith("semantic_gate_reason_codes=-")


# --- каждый код шага CHECK достижим проверкой на своём входе
CHECK_REACHABILITY_CASES: list[tuple[str, MergeRejectCode]] = [
    ("per_source", MergeRejectCode.PER_SOURCE_ENUMERATION),
    ("duplicate", MergeRejectCode.DUPLICATE_PARAGRAPH),
    ("echo", MergeRejectCode.HOOK_ECHO_IN_BODY),
    ("cta_first", MergeRejectCode.CTA_AS_FIRST_PARAGRAPH),
    ("cta_hook", MergeRejectCode.CTA_IN_HOOK),
    ("few_bullets", MergeRejectCode.INSUFFICIENT_BULLET_COVERAGE),
    ("compact", MergeRejectCode.COMPACT_BULLET_OVERFLOW),
    ("emoji", MergeRejectCode.EXCESSIVE_EMOJI_USAGE),
    ("overloaded", MergeRejectCode.OVERLOADED_BULLET),
    ("numbered", MergeRejectCode.NUMBERED_TITLE_DUMP),
    ("gate", MergeRejectCode.SEMANTIC_GATE),
]


def reachability_check(case: str) -> MergeCheck:
    """Вход, на котором проверка отвергает ответ ровно этим кодом."""
    one: tuple[tuple[str, str], ...] = (("One", "Body."),)
    paragraph: str = "The same paragraph with enough words to be compared by the duplicate rule."
    inputs: dict[str, MergeCheck] = {
        "per_source": check_as_is("SOURCE 1: Point one.\n\nSOURCE 2: Point two.", TWO_SOURCES),
        "duplicate": check_as_is(f"{HOOK}\n\n{paragraph}\n\n{paragraph}"),
        "echo": check_as_is(f"{HOOK}\n\n{HOOK[:50]} but tonight we also look at seven regional budget lines\n\nClosing."),
        "cta_first": check_as_is(f"Subscribe to the channel.\n{HOOK}\n\nBody."),
        "cta_hook": check_as_is(f"Links below\n\n{HOOK}\n\nBody."),
        "few_bullets": check_as_is(f"{HOOK}\n\n{bullets(STRONG_BULLETS[:3])}", EXPANDED_SOURCES),
        "compact": check_as_is(f"{HOOK}\n\n{bullets([f'Point {n} with its own detail' for n in range(8)])}", TWO_SOURCES),
        "emoji": check_as_is(f"{HOOK} {' '.join(EMOJI)} {EMOJI[0]}\n\nBody.", one),
        "overloaded": check_as_is(f"{HOOK}\n\n{bullets([LONG_ALPHA, LONG_BETA, 'a', 'b'])}"),
        "numbered": check_as_is(f"{HOOK}\n\nBody.", title="Budget 1) vote"),
        "gate": merge_check(
            f"{HOOK}\n\n{bullets(['budget timeline and m' + chr(0x438) + 'xed contamination', 'verified follow-up'])}", one
        ),
    }
    return inputs[case]


@pytest.mark.parametrize(("case", "code"), CHECK_REACHABILITY_CASES)
def test_every_check_code_is_reachable(case: str, code: MergeRejectCode) -> None:
    verdict: MergeCheckPassed | MergeReject = reachability_check(case).run()
    assert isinstance(verdict, MergeReject)
    assert verdict.code is code


def test_check_cases_cover_exactly_the_check_codes() -> None:
    assert {code for _, code in CHECK_REACHABILITY_CASES} == {
        code for code in MergeRejectCode if MergeRejectStage.CHECK in code.stages
    }
