from __future__ import annotations

import logging
from collections.abc import Iterator
from dataclasses import replace

import pytest

from app.llm.merges.check import (
    FormattingRecovery,
    MergeAttemptLabel,
    MergeCheck,
    MergeCheckPassed,
    MergeCheckRequest,
    MergeCheckRules,
    MergeDiagnostics,
)
from app.llm.merges.description import MergedDescription
from app.llm.merges.links import OfficialLinkSelection
from app.llm.merges.quality import QualityGateStatus, QualityNormalization, QualityReasonCode, QualityRequest
from app.llm.merges.reject import MergeReject, MergeRejectCode, MergeRejectStage
from app.sources.video import SourceVideo
from app.tests.conftest import LogCollector
from app.tests.test_llm_merges_source import merge_video

RULES: MergeCheckRules = MergeCheckRules.load()
LABEL: MergeAttemptLabel = MergeAttemptLabel(slot_id="16-10-2026_1900_en", language="en", model="gpt-x", attempt=2)
NEUTRAL: str = chr(0x1F539)
EMOJI: tuple[str, ...] = tuple(
    chr(code) for code in (0x1F525, 0x1F6A8, 0x1F3AF, 0x1F9ED, 0x2728, 0x1F514, 0x1F4A5, 0x1F31F, 0x1F396, 0x1F3F3)
)

# Источники донорских тестов (`test_merge_contract_helpers.py::_expanded_validation_videos`, restreamer 35324e5).
EXPANDED_SOURCES: tuple[tuple[str, str], ...] = (
    (
        "Brussels sanctions vote briefing",
        "In Brussels, Anna Kovalenko tracks the March 18 sanctions vote, budget amendments, and customs delays after "
        "the commission session.",
    ),
    (
        "Kharkiv rail and drone update",
        "In Kharkiv, Oleh Martynenko reports 17 drone strikes, rail hub outages, and evacuation routes for Saltivka "
        "districts.",
    ),
    (
        "Geneva relief corridor desk",
        "From Geneva, Marta Leone outlines the aid corridor timetable, WHO cargo counts, and donor pledges for Odesa "
        "and Mykolaiv hospitals.",
    ),
)
TWO_SOURCES: tuple[tuple[str, str], ...] = (
    ("Source one", "Source one paragraph with concrete facts."),
    ("Source two", "Source two paragraph with concrete facts."),
)
STRONG_BULLETS: tuple[str, ...] = (
    "Brussels sanctions vote, budget amendments, and customs delays after the March 18 commission session",
    "Anna Kovalenko tracks coalition counts and the pressure points before the chamber debate",
    "Kharkiv rail hub outages after 17 drone strikes across Saltivka districts",
    "Oleh Martynenko details evacuation routes, depot damage, and recovery sequencing on the eastern line",
    "Geneva aid corridor timetable, WHO cargo counts, and donor pledges for Odesa hospitals",
    "Marta Leone breaks down how Mykolaiv deliveries depend on the next donor release window",
)
STRONG_HOOK: str = (
    "Tonight we align the Brussels vote, the Kharkiv transport shock, and the Geneva aid timetable into one grounded "
    "briefing. Each source keeps its own factual lane, and the summary stays concrete instead of leaning on editorial "
    "gloss."
)
STRONG_CLOSE: str = (
    "The closing paragraph ties the political vote, frontline logistics, and medical supply chain into a clear "
    "next-step agenda without flattening the sources into one generic thesis."
)
# Перегруженные пункты (длиннее 500 знаков) без общих слов: соседние строки не повтор.
LONG_ALPHA: str = "alpha " * 90
LONG_BETA: str = "beta " * 110
HOOK: str = "Tonight we map the sanctions vote and what it changes for the next operational window."


def bullets(lines: tuple[str, ...] | list[str]) -> str:
    return "\n".join(f"{NEUTRAL} {line}" for line in lines)


def sources_of(pairs: tuple[tuple[str, str], ...]) -> tuple[SourceVideo, ...]:
    return tuple(merge_video(index + 1, title, body) for index, (title, body) in enumerate(pairs))


def request_of(title: str, answer: str, pairs: tuple[tuple[str, str], ...], language: str = "en") -> MergeCheckRequest:
    return MergeCheckRequest.of(replace(LABEL, language=language), title, MergedDescription(answer), sources_of(pairs), RULES)


def normalized_check(
    answer: str, pairs: tuple[tuple[str, str], ...] = EXPANDED_SOURCES, title: str = "Title", language: str = "en"
) -> MergeCheck:
    """Проверка, как у исполнителя донора: ответ → нормализация качества с названием и числом источников."""
    request: MergeCheckRequest = request_of(title, answer, pairs, language)
    normalization: QualityNormalization = MergedDescription(answer).quality_normalized(
        QualityRequest(language=language, title=title, source_count=len(pairs)), RULES.quality
    )
    return MergeCheck.of(request, normalization, RULES)


def raw_check(answer: str, pairs: tuple[tuple[str, str], ...] = (), title: str = "Title") -> MergeCheck:
    """Проверка текста как есть: диагностика качества — от нормализации, текст — не нормализованный."""
    normalization: QualityNormalization = MergedDescription(answer).quality_normalized(
        QualityRequest(language="en", title=title, source_count=len(pairs)), RULES.quality
    )
    request: MergeCheckRequest = request_of(title, answer, pairs)
    return MergeCheck.of(request, replace(normalization, description=MergedDescription(answer)), RULES)


def reject_code(verdict: MergeCheckPassed | MergeReject) -> str:
    assert isinstance(verdict, MergeReject), verdict
    return verdict.reason_code


@pytest.fixture
def llm_log() -> Iterator[LogCollector]:
    collector: LogCollector = LogCollector()
    logger: logging.Logger = logging.getLogger("livecraft.llm")
    logger.addHandler(collector)
    previous: int = logger.level
    logger.setLevel(logging.INFO)
    yield collector
    logger.setLevel(previous)
    logger.removeHandler(collector)


# --- донорские случаи (test_merge_contract_expanded.py, test_compact_bullet_overflow.py, test_audit_run_regressions.py)


def test_strong_three_source_answer_passes() -> None:
    answer: str = f"{STRONG_HOOK}\n\nIn this stream you'll see:\n{bullets(STRONG_BULLETS)}\n\n{STRONG_CLOSE}"
    check: MergeCheck = normalized_check(answer, title="Brussels, Kharkiv, Geneva: the operational agenda tonight")
    verdict: MergeCheckPassed | MergeReject = check.run()
    assert isinstance(verdict, MergeCheckPassed)
    assert verdict.diagnostics.bullet_points_count == 6
    assert "bullet_points_count=6" in check.diagnostics.log_lines(LABEL)[0]


def test_dense_two_paragraph_answer_passes() -> None:
    answer: str = f"{STRONG_HOOK}\n\nIn this stream you'll see:\n{bullets(STRONG_BULLETS)}"
    assert isinstance(normalized_check(answer).run(), MergeCheckPassed)


def test_overly_generic_three_source_answer_lacks_bullets() -> None:
    answer: str = (
        "Tonight we step back and frame several important developments inside one smooth and readable opening that "
        "sounds strong but stays broad. It keeps attention on the mood and the overall stakes instead of distinct "
        "source facts.\n\nIn this stream you'll see:\n"
        + bullets(["the main context and why it matters", "the broader background and tensions",
                   "how the story fits a larger pattern"])
        + "\n\nA polished closing paragraph keeps the editorial flow consistent for viewers."
    )
    check: MergeCheck = normalized_check(answer, title="Why these developments matter tonight")
    assert reject_code(check.run()) == "insufficient_bullet_coverage"
    assert check.diagnostics.bullet_points_count == 3


def test_two_sources_with_eight_bullets_overflow_the_compact_contract() -> None:
    answer: str = (
        "Tonight we map concrete outcomes from two linked source agendas and keep each detail grounded.\n\n"
        "In this stream you'll see:\n" + bullets([f"Concrete point number {n} with timing and consequence." for n in "12345678"])
    )
    assert reject_code(raw_check(answer, TWO_SOURCES, "Two-source agenda with too many bullets").run()) == (
        "compact_bullet_overflow"
    )


def test_hook_echo_is_repaired_and_logged(llm_log: LogCollector) -> None:
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
    check: MergeCheck = normalized_check(answer, pairs=(), title="Итоговый заголовок", language="ru")
    verdict: MergeCheckPassed | MergeReject = check.run()
    assert isinstance(verdict, MergeCheckPassed)
    assert verdict.description.text != check.description.text
    assert verdict.description.paragraphs[1].startswith(NEUTRAL)
    assert verdict.diagnostics is check.diagnostics                 # диагностика — до починки, как у донора
    assert f"hook_echo_repair_applied=yes {replace(LABEL, language='ru').prefix}" in llm_log.messages()


# --- каждая причина отказа отдельно


def test_per_source_dump_is_rejected() -> None:
    assert reject_code(raw_check("SOURCE 1: Point one.\n\nSOURCE 2: Point two.", TWO_SOURCES).run()) == (
        "per_source_enumeration"
    )


def test_duplicate_paragraphs_are_rejected() -> None:
    paragraph: str = "The same paragraph with enough words to be compared by the duplicate rule."
    assert reject_code(raw_check(f"{HOOK}\n\n{paragraph}\n\n{paragraph}").run()) == "duplicate_paragraph"


def test_unrepairable_hook_echo_is_rejected() -> None:
    body: str = HOOK[:50] + " but tonight we also look at seven regional budget lines and hospitals"
    answer: str = f"{HOOK}\n\n{body}\n\nClosing words without bullets."
    assert reject_code(raw_check(answer).run()) == "hook_echo_in_body"


def test_adjacent_repeated_lines_are_rejected() -> None:
    line: str = "Brussels sanctions vote and budget amendments after the March 18 commission session"
    answer: str = f"{HOOK}\n\n{NEUTRAL} {line}\n{NEUTRAL} {line} again"
    assert reject_code(raw_check(answer).run()) == "duplicate_paragraph"


def test_cta_before_the_hook_is_rejected() -> None:
    assert reject_code(raw_check(f"Subscribe to the channel.\n{HOOK}\n\n{bullets(STRONG_BULLETS[:2])}").run()) == (
        "cta_as_first_paragraph"
    )


def test_service_line_as_hook_is_rejected() -> None:
    assert reject_code(raw_check(f"Links below\n\n{HOOK}\n\n{bullets(STRONG_BULLETS[:2])}").run()) == "cta_in_hook"


def test_bad_hook_as_first_paragraph_is_rejected() -> None:
    answer: str = f"This video is part of our coverage of the vote.\n{HOOK}\n\n{bullets(STRONG_BULLETS[:2])}"
    assert reject_code(raw_check(answer).run()) in {"cta_as_first_paragraph", "cta_in_hook"}
    answer_after_hook: str = f"{HOOK}\nThis video is part of our coverage.\n\n{bullets(STRONG_BULLETS[:2])}"
    assert reject_code(raw_check(answer_after_hook).run()) == "cta_in_hook"


@pytest.mark.parametrize(("source_count", "bullet_count"), [(2, 4), (3, 4), (4, 4), (5, 5)])
def test_too_few_bullets_for_the_sources(source_count: int, bullet_count: int) -> None:
    pairs: tuple[tuple[str, str], ...] = tuple((f"Source {n}", "Body.") for n in range(source_count))
    answer: str = f"{HOOK}\n\n{bullets([f'Point {n} with its own detail' for n in range(bullet_count)])}"
    assert reject_code(raw_check(answer, pairs).run()) == "insufficient_bullet_coverage"


def test_enough_bullets_for_the_sources_pass_the_count() -> None:
    pairs: tuple[tuple[str, str], ...] = tuple((f"Source {n}", "Body.") for n in range(5))
    answer: str = f"{HOOK}\n\n{bullets([f'Point {n} with its own detail' for n in range(6)])}"
    assert isinstance(raw_check(answer, pairs).run(), MergeCheckPassed)


def test_one_source_has_no_bullet_minimum() -> None:
    assert isinstance(raw_check(f"{HOOK}\n\nBody paragraph.", (("One", "Body."),)).run(), MergeCheckPassed)


def test_more_than_ten_emoji_are_rejected() -> None:
    answer: str = f"{HOOK} {' '.join(EMOJI)} {EMOJI[0]}\n\n{bullets(STRONG_BULLETS[:2])}"
    check: MergeCheck = raw_check(answer, (("One", "Body."),))
    assert check.diagnostics.emoji_count == 11
    assert reject_code(check.run()) == "excessive_emoji_usage"
    assert isinstance(raw_check(f"{HOOK} {' '.join(EMOJI)}\n\nBody.", (("One", "Body."),)).run(), MergeCheckPassed)


def test_two_overloaded_bullets_in_a_list_of_four_are_rejected() -> None:
    answer: str = f"{HOOK}\n\n{bullets([LONG_ALPHA, LONG_BETA, 'short one', 'short two'])}"
    verdict: MergeCheckPassed | MergeReject = raw_check(answer).run()
    assert reject_code(verdict) == "overloaded_bullet"
    assert isinstance(verdict, MergeReject) and verdict.detail == "count=2"
    three_bullets: str = f"{HOOK}\n\n{bullets([LONG_ALPHA, LONG_BETA, 'short one'])}"
    assert isinstance(raw_check(three_bullets).run(), MergeCheckPassed)


@pytest.mark.parametrize("title", ["Budget 1) and sanctions", "Тема 1) бюджет", "Part 2) now"])
def test_numbered_title_is_rejected(title: str) -> None:
    assert reject_code(raw_check(f"{HOOK}\n\nBody paragraph.", title=title).run()) == "numbered_title_dump"


@pytest.mark.parametrize("title", ["A1) x", "Part 2)", "(1)intro", "1.) x"])
def test_title_without_a_numbered_item_passes(title: str) -> None:
    assert isinstance(raw_check(f"{HOOK}\n\nBody paragraph.", title=title).run(), MergeCheckPassed)


def test_paragraphs_with_the_same_long_start_are_rejected() -> None:
    start: str = "Brussels sanctions vote and the budget amendments after the March 18 commission session "
    answer: str = (
        f"{HOOK}\n\nSecond paragraph about Kharkiv rail outages.\n\n"
        f"{start}with customs delays for traders.\n\n{start}bring a different set of consequences for hospitals."
    )
    check: MergeCheck = raw_check(answer)
    assert not check.description.has_duplicate_paragraphs
    assert reject_code(check.run()) == "duplicate_paragraph"


def test_semantic_gate_rejects_with_normalized_gate_codes() -> None:
    check: MergeCheck = raw_check(f"{HOOK}\n\nBody paragraph.")
    hard = replace(
        check.quality,
        semantic_gate_status=QualityGateStatus.HARD_REJECT,
        semantic_gate_reason_codes=(QualityReasonCode.MISSING_BLOCK_SPACING, QualityReasonCode.SCRIPT_MIX_CONTAMINATION),
    )
    verdict: MergeCheckPassed | MergeReject = replace(check, quality=hard).run()
    assert isinstance(verdict, MergeReject)
    assert verdict.code is MergeRejectCode.SEMANTIC_GATE
    assert verdict.reason_codes == ("missing_block_spacing", "script_mix_contamination")
    assert verdict.reason_code == "missing_block_spacing"


def test_needs_normalization_status_does_not_reject() -> None:
    check: MergeCheck = raw_check(f"{HOOK}\n\nBody paragraph.")
    soft = replace(check.quality, semantic_gate_status=QualityGateStatus.NEEDS_NORMALIZATION)
    assert isinstance(replace(check, quality=soft).run(), MergeCheckPassed)


def test_mixed_script_description_is_rejected_by_the_gate() -> None:
    answer: str = f"{HOOK}\n\nIn this stream you'll see:\n{bullets(['budget timeline and m' + chr(0x438) + 'xed contamination inside the main bullet', 'verified operational follow-up'])}"
    verdict: MergeCheckPassed | MergeReject = normalized_check(answer, pairs=(("One", "Body."),)).run()
    assert isinstance(verdict, MergeReject) and verdict.code is MergeRejectCode.SEMANTIC_GATE
    assert "script_mix_contamination" in verdict.reason_codes


# --- порядок проверок: первая сработавшая побеждает


def test_per_source_dump_wins_over_emoji_and_bullets() -> None:
    answer: str = f"Source 1: {' '.join(EMOJI)} {EMOJI[0]}\nSource 2: point"
    assert reject_code(raw_check(answer, EXPANDED_SOURCES).run()) == "per_source_enumeration"


def test_cta_first_wins_over_missing_bullets_and_numbered_title() -> None:
    answer: str = f"Subscribe to the channel.\n{HOOK}\n\nBody."
    assert reject_code(raw_check(answer, EXPANDED_SOURCES, "Budget 1) vote").run()) == "cta_as_first_paragraph"


def test_bullet_count_wins_over_emoji() -> None:
    answer: str = f"{HOOK} {' '.join(EMOJI)} {EMOJI[0]}\n\n{bullets(STRONG_BULLETS[:3])}"
    assert reject_code(raw_check(answer, EXPANDED_SOURCES).run()) == "insufficient_bullet_coverage"


def test_emoji_win_over_overloaded_bullets_and_numbered_title() -> None:
    answer: str = f"{HOOK} {' '.join(EMOJI)} {EMOJI[0]}\n\n{bullets([LONG_ALPHA, LONG_BETA, 'a', 'b'])}"
    assert reject_code(raw_check(answer, (("One", "Body."),), "Budget 1) vote").run()) == "excessive_emoji_usage"


def test_numbered_title_wins_over_similar_paragraphs_and_the_gate() -> None:
    start: str = "Brussels sanctions vote and the budget amendments after the March 18 commission session "
    answer: str = f"{HOOK}\n\nSecond.\n\n{start}one ending here.\n\n{start}another ending with more words."
    check: MergeCheck = raw_check(answer, title="Vote 1) now")
    hard = replace(check.quality, semantic_gate_status=QualityGateStatus.HARD_REJECT)
    assert reject_code(replace(check, quality=hard).run()) == "numbered_title_dump"


# --- восстановление форматирования


def emoji_heavy_answer() -> str:
    hook: str = (
        f"{EMOJI[0]} Tonight we align the Brussels vote {EMOJI[1]}, the Kharkiv transport shock {EMOJI[2]}, and the "
        f"Geneva aid timetable {EMOJI[3]} into one grounded briefing {EMOJI[4]} that stays source-specific {EMOJI[5]} "
        f"without losing clarity {EMOJI[6]} while keeping the agenda concrete {EMOJI[7]} and readable {EMOJI[8]} for "
        f"every viewer {EMOJI[9]}."
    )
    return (
        f"{hook}\n\nIn this stream you'll see:\n{bullets(STRONG_BULLETS)}\n\n"
        f"Watch live {chr(0x2705)} and share updates {chr(0x1F4E3)} #briefing"
    )


def test_three_source_emoji_overflow_is_salvaged(llm_log: LogCollector) -> None:
    """Донор: test_expanded_three_source_merge_salvages_formatting_only_emoji_overflow."""
    check: MergeCheck = normalized_check(emoji_heavy_answer(), title="Brussels, Kharkiv, Geneva: the operational agenda")
    reject: MergeCheckPassed | MergeReject = check.run()
    assert reject_code(reject) == "excessive_emoji_usage"
    assert isinstance(reject, MergeReject)
    recovery: FormattingRecovery = FormattingRecovery.of(check, reject)
    assert recovery.passed is not None and recovery.reject is None
    assert recovery.outcome == "applied"
    assert "reduced_non_structural_emoji" in recovery.actions
    text: str = recovery.passed.description.text
    assert all(emoji not in text for emoji in EMOJI[:4]) and chr(0x1F4E3) not in text
    assert f"{NEUTRAL} Brussels sanctions vote" in text
    line: str = next(message for message in llm_log.messages() if message.startswith("merge_llm_validation_salvage"))
    assert line.startswith(f"merge_llm_validation_salvage {LABEL.prefix} outcome=applied reason_codes=excessive_emoji_usage")
    assert "actions=reduced_non_structural_emoji" in line
    assert f"emoji_before={check.diagnostics.emoji_count} emoji_after=" in line
    assert "replacement_reason_codes" not in line
    assert check.run_with_recovery() == recovery.verdict


def test_salvage_reveals_a_non_formatting_issue(llm_log: LogCollector) -> None:
    points: list[str] = [LONG_ALPHA, LONG_BETA, *STRONG_BULLETS[:4]]
    answer: str = f"{HOOK} {' '.join(EMOJI)} {EMOJI[0]}\n\n{bullets(points)}"
    check: MergeCheck = raw_check(answer, EXPANDED_SOURCES)
    reject: MergeCheckPassed | MergeReject = check.run()
    assert reject_code(reject) == "excessive_emoji_usage"
    assert isinstance(reject, MergeReject)
    recovery: FormattingRecovery = FormattingRecovery.of(check, reject)
    assert recovery.passed is None and recovery.reject is not None
    assert recovery.reject.reason_code == "overloaded_bullet"
    assert recovery.outcome == "revealed_non_formatting_issue"
    line: str = next(message for message in llm_log.messages() if message.startswith("merge_llm_validation_salvage"))
    assert "outcome=revealed_non_formatting_issue reason_codes=excessive_emoji_usage" in line
    assert "replacement_reason_codes=overloaded_bullet" in line


def test_salvage_is_not_tried_below_three_sources(llm_log: LogCollector) -> None:
    answer: str = f"{HOOK} {' '.join(EMOJI)} {EMOJI[0]}\n\n{bullets(STRONG_BULLETS[:5])}"
    check: MergeCheck = raw_check(answer, TWO_SOURCES)
    reject: MergeCheckPassed | MergeReject = check.run()
    assert reject_code(reject) == "excessive_emoji_usage"
    assert isinstance(reject, MergeReject)
    recovery: FormattingRecovery = FormattingRecovery.of(check, reject)
    assert recovery.verdict is reject and recovery.actions == ()
    assert check.run_with_recovery() is not None and reject_code(check.run_with_recovery()) == "excessive_emoji_usage"
    assert not any(message.startswith("merge_llm_validation_salvage") for message in llm_log.messages())


def test_salvage_is_only_for_emoji_overflow() -> None:
    check: MergeCheck = raw_check(f"{HOOK}\n\n{bullets(STRONG_BULLETS[:3])}", EXPANDED_SOURCES)
    reject: MergeCheckPassed | MergeReject = check.run()
    assert isinstance(reject, MergeReject)
    recovery: FormattingRecovery = FormattingRecovery.of(check, reject)
    assert recovery.verdict is reject and recovery.actions == ()


def test_salvage_without_any_change_keeps_the_reject() -> None:
    check: MergeCheck = raw_check(f"{HOOK}\n\n{bullets(STRONG_BULLETS)}", EXPANDED_SOURCES)
    reject: MergeReject = MergeReject(MergeRejectCode.EXCESSIVE_EMOJI_USAGE)
    recovery: FormattingRecovery = FormattingRecovery.of(check, reject)
    assert recovery.verdict is reject and recovery.actions == ()


# --- диагностика и строки лога


def test_attempt_label_prefix() -> None:
    assert LABEL.prefix == "slot=16-10-2026_1900_en language=en model=gpt-x attempt=2"


def test_diagnostics_count_bullets_markers_entities_and_links() -> None:
    pairs: tuple[tuple[str, str], ...] = (
        ("Anna Kovalenko briefing", "Official site: https://example.org/ and https://youtu.be/aaaaaaaaaaa"),
        ("Oleh Martynenko update", "Details https://news.example.com/story?utm_source=x"),
    )
    answer: str = (
        f"{HOOK} Anna Kovalenko opens: why now?\n\n{NEUTRAL} first point\n- second point\n1) third point\n"
        f"{chr(0x1F4CC)} fourth point\n\nSee https://example.org and https://www.example.org/uk and https://youtu.be/bbbbbbbbbbb"
    )
    request: MergeCheckRequest = request_of("Title", answer, pairs)
    diagnostics: MergeDiagnostics = MergeDiagnostics.of(
        request, MergedDescription(answer), raw_check(answer, pairs).quality, RULES
    )
    assert diagnostics.bullet_points_count == 4
    assert diagnostics.semantic_bullets_count == diagnostics.bullets_with_emoji_count == 2
    assert diagnostics.bullets_with_plain_marker_count == 2
    assert diagnostics.bullet_marker_types == (NEUTRAL, "-", "1)", chr(0x1F4CC))
    assert diagnostics.hook_present and diagnostics.agenda_block_present
    assert diagnostics.named_entities_preserved == 1
    assert diagnostics.source_named_entities_total == 2
    assert (diagnostics.official_links_found_in_sources, diagnostics.official_links_kept) == (2, 2)
    assert diagnostics.official_links_in_output == 1
    assert diagnostics.official_links_fill_applied is False


def test_links_in_output_are_counted_on_the_answer_before_normalization() -> None:
    request: MergeCheckRequest = request_of("Title", "Body https://a.org https://b.org", (("One", "Body."),))
    diagnostics: MergeDiagnostics = MergeDiagnostics.of(request, MergedDescription("Body"), raw_check("Body").quality, RULES)
    assert diagnostics.official_links_in_output == 2
    assert request.links == OfficialLinkSelection(found_in_sources=0, kept_links=())


def test_short_first_paragraph_is_not_a_hook_and_few_bullets_are_not_an_agenda() -> None:
    diagnostics: MergeDiagnostics = raw_check(f"Short hook: yes\n\n{bullets(['a', 'b'])}").diagnostics
    assert not diagnostics.hook_present
    assert not diagnostics.agenda_block_present
    assert raw_check(f"{HOOK}\n\nIn this stream: budget\n{bullets(['a'])}").diagnostics.agenda_block_present


def test_log_lines_have_donor_keys_and_no_description_text() -> None:
    secret_word: str = "Zanzibarquux"
    answer: str = f"{HOOK} {secret_word}!\n\n{bullets([secret_word + ' point', 'second point'])}"
    style, gate = normalized_check(answer, pairs=(("One", "Body."),), title=f"{secret_word} title").diagnostics.log_lines(LABEL)
    assert secret_word not in style and secret_word not in gate
    assert style.startswith(f"merge_style_coverage {LABEL.prefix} style_contract_version=v4_merge_quality_hardening ")
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
    _, gate = normalized_check(mixed, pairs=(("One", "Body."),)).diagnostics.log_lines(LABEL)
    assert "block_language_expected=en " in gate and "script_mix_detected=yes " in gate
    assert gate.endswith("semantic_gate_status=hard_reject semantic_gate_reason_codes=script_mix_contamination")
    _, clean = normalized_check(f"{HOOK}\n\n{bullets(['budget amendments'])}", pairs=(("One", "Body."),)).diagnostics.log_lines(
        LABEL
    )
    assert "script_mix_suspects=none " in clean and "semantic_gate_reason_codes=" in clean


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
        "per_source": raw_check("SOURCE 1: Point one.\n\nSOURCE 2: Point two.", TWO_SOURCES),
        "duplicate": raw_check(f"{HOOK}\n\n{paragraph}\n\n{paragraph}"),
        "echo": raw_check(f"{HOOK}\n\n{HOOK[:50]} but tonight we also look at seven regional budget lines\n\nClosing."),
        "cta_first": raw_check(f"Subscribe to the channel.\n{HOOK}\n\nBody."),
        "cta_hook": raw_check(f"Links below\n\n{HOOK}\n\nBody."),
        "few_bullets": raw_check(f"{HOOK}\n\n{bullets(STRONG_BULLETS[:3])}", EXPANDED_SOURCES),
        "compact": raw_check(f"{HOOK}\n\n{bullets([f'Point {n} with its own detail' for n in range(8)])}", TWO_SOURCES),
        "emoji": raw_check(f"{HOOK} {' '.join(EMOJI)} {EMOJI[0]}\n\nBody.", one),
        "overloaded": raw_check(f"{HOOK}\n\n{bullets([LONG_ALPHA, LONG_BETA, 'a', 'b'])}"),
        "numbered": raw_check(f"{HOOK}\n\nBody.", title="Budget 1) vote"),
        "gate": normalized_check(
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
