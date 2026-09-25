from __future__ import annotations

import logging
import random

import pytest

from app.llm.merges import quality as quality_module
from app.llm.merges.description import MergedDescription
from app.llm.merges.quality import (
    BulletNormalization,
    CompactTrim,
    QualityDiagnostics,
    QualityGateStatus,
    QualityNormalization,
    QualityReasonCode,
    QualityRequest,
    QualityRules,
)
from app.llm.merges.rules import COMPACT_BULLET_MAX
from app.tests.conftest import REPO_ROOT
from app.tools.code_standard.source import ModuleSource, SourceTree

RULES: QualityRules = QualityRules.load()
CLEAN_EN: str = (
    "This stream breaks down the budget decision and explains what it means for the regions and for families.\n\n"
    "In this stream you'll see:\n"
    "🔹 budget amendments and the final vote\n"
    "🔹 practical next steps for viewers\n\n"
    "🌐 Official links:\n"
    "https://example.org\n\n"
    "Watch the stream and share your thoughts."
)


def normalized(description: str, language: str, title: str = "", source_count: int = 0) -> QualityNormalization:
    request: QualityRequest = QualityRequest(language=language, title=title, source_count=source_count)
    return MergedDescription(description).quality_normalized(request, RULES)


def bullet_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip().startswith(("🔹 ", "📌 ", "🎤 "))]


# --- донор: test_merge_contract_validation.py::test_short_service_lines_are_normalized_to_expected_language
def test_short_service_lines_are_normalized_to_expected_language() -> None:
    result: QualityNormalization = normalized(
        "Це короткий вступ про головну тему!\n\n"
        "In this stream you'll see:\n"
        "📌 перший акцент\n"
        "🔹 другий пункт\n\n"
        "🌐 Official links:\n"
        "https://example.org\n\n"
        "Watch the stream and share your thoughts. #подія",
        "uk",
    )
    assert "У цьому стрімі ви побачите:" in result.description.text
    assert "🌐 Офіційні ресурси:" in result.description.text
    assert "Дивіться ефір і діліться думками. #подія" in result.description.text
    assert result.diagnostics.semantic_gate_status is QualityGateStatus.NEEDS_NORMALIZATION
    assert result.diagnostics.wrong_language_heading_detected is True
    assert result.diagnostics.official_links_heading_mismatch is True


# --- донор: test_accent_marker_cap_is_enforced_and_overflow_is_logged
def test_accent_marker_cap_is_enforced() -> None:
    result: QualityNormalization = normalized(
        "Focused hook paragraph with enough detail to stay valid!\n\n"
        "In this stream you'll see:\n📌 first\n🎤 second\n🎥 third\n⚖ fourth\n🌐 fifth",
        "en",
    )
    assert result.diagnostics.accent_bullets_count == 3
    assert result.diagnostics.neutral_bullets_count == 2
    assert result.diagnostics.accent_overflow is True
    assert result.diagnostics.accent_marker_types == ("📌", "🎤", "🎥")
    assert "🔹 fourth" in result.description.text
    assert "🔹 fifth" in result.description.text
    assert QualityReasonCode.ACCENT_MARKER_OVERFLOW in result.diagnostics.semantic_gate_reason_codes


# --- донор: test_block_spacing_is_stabilized
def test_block_spacing_is_stabilized() -> None:
    result: QualityNormalization = normalized(
        "This hook stays factual and readable with enough context!\n"
        "In this stream you'll see:\n"
        "🎤 Pastor Vitaliy Orlov comments on the community response\n"
        "🔹 relief updates continue\n"
        "🌐 Official links:\n"
        "https://example.org\n"
        "Watch the stream and share your thoughts. #update",
        "en",
    )
    assert "\n\nIn this stream you'll see:\n" in result.description.text
    assert "\n\n🌐 Official links:\nhttps://example.org\n\n" in result.description.text
    assert "🎤 Pastor Vitaliy Orlov comments on the community response" in result.description.text
    assert result.diagnostics.block_spacing_ok is False
    assert QualityReasonCode.MISSING_BLOCK_SPACING in result.diagnostics.semantic_gate_reason_codes
    assert result.normalization_applied is True


# --- донор: test_script_mix_guard_rejects_cyrillic_contamination_inside_english_body
def test_script_mix_in_english_body_is_hard_reject() -> None:
    result: QualityNormalization = normalized(
        "This hook stays factual and readable with enough context about the main topic!\n\n"
        "In this stream you'll see:\n"
        "🔹 budget timeline and mиксed contamination inside the main bullet\n"
        "🔹 verified operational follow-up for the next debate window",
        "en",
    )
    assert result.diagnostics.semantic_gate_status is QualityGateStatus.HARD_REJECT
    assert QualityReasonCode.SCRIPT_MIX_CONTAMINATION in result.diagnostics.semantic_gate_reason_codes
    assert "mиксed" in result.diagnostics.script_mix_suspects


# --- донор: test_script_mix_guard_ignores_allowed_brands_and_urls_in_cyrillic_text
def test_allowed_brands_and_urls_are_not_script_mix() -> None:
    result: QualityNormalization = normalized(
        "Цей вступ лишається фактичним і зрозумілим для глядачів.\n\n"
        "У цьому стрімі ви побачите:\n"
        "🔹 OpenAI та YouTube згадуються як бренди без зайвої мовної кари\n"
        "🔹 NASA і AI залишаються допустимими абревіатурами\n\n"
        "🌐 Офіційні ресурси:\n"
        "https://example.org/openai\n\n"
        "Дивіться ефір і діліться думками. #update",
        "uk",
    )
    assert result.diagnostics.script_mix_detected is False
    assert QualityReasonCode.SCRIPT_MIX_CONTAMINATION not in result.diagnostics.semantic_gate_reason_codes


# --- донор: test_script_mix_guard_ignores_bare_domain_in_cyrillic_text
def test_bare_domain_in_cyrillic_text_is_not_script_mix() -> None:
    result: QualityNormalization = normalized(
        "После решения украинского суда антикультист дал ссылку на lstv.co.uk как ключевой эпизод.\n\n"
        "⚖ Конфликт фактов и манипуляций: что стоит за антикультовой риторикой.\n"
        "🔹 Луиджи Корвальо, член правления ФЕКРИС: реакция на реабилитацию.\n"
        "🔹 Техническая верификация lstv.co.uk: инфраструктура хостинга.\n"
        "🔹 Следы в открытых источниках и вывод расследования.\n\n"
        "Оставляйте комментарии по фактам. #расследование",
        "ru",
    )
    assert result.diagnostics.script_mix_detected is False
    assert QualityReasonCode.SCRIPT_MIX_CONTAMINATION not in result.diagnostics.semantic_gate_reason_codes


# --- донор: test_script_mix_guard_ignores_multi_level_bare_domain
def test_multi_level_bare_domain_is_not_script_mix() -> None:
    result: QualityNormalization = normalized(
        "Ця новина була опублікована на news.bbc.co.uk та підтверджена.\n\n"
        "У цьому стрімі ви побачите:\n🔹 пункт один\n🔹 пункт два\n\nДивіться ефір. #новини",
        "uk",
    )
    assert result.diagnostics.script_mix_detected is False


# --- донор: test_script_mix_guard_catches_mixed_script_token_in_title
def test_mixed_script_token_in_title_is_caught() -> None:
    result: QualityNormalization = normalized(
        "Антикульт под лупой: что стоит за риторикой.\n\n🔹 пункт один\n🔹 пункт два\n\nОставляйте комментарии. #тест",
        "ru",
        title="Антикульт под лупой: сайт lstv.co.uk, FЕКРИС и тени",
    )
    assert result.diagnostics.script_mix_detected is True
    assert QualityReasonCode.SCRIPT_MIX_CONTAMINATION in result.diagnostics.semantic_gate_reason_codes
    assert "FЕКРИС" in result.diagnostics.script_mix_suspects
    assert "lstv" not in result.diagnostics.script_mix_suspects


# --- донор: test_core_wrong_language_hook_is_hard_reject
def test_wrong_language_hook_is_hard_reject() -> None:
    result: QualityNormalization = normalized(
        "This English hook is clearly not in the expected block language and stays unchanged.\n\n"
        "У цьому стрімі ви побачите:\n🔹 пункт один\n🔹 пункт два",
        "uk",
    )
    assert result.diagnostics.semantic_gate_status is QualityGateStatus.HARD_REJECT
    assert QualityReasonCode.INCONSISTENT_BLOCK_LANGUAGE in result.diagnostics.semantic_gate_reason_codes
    assert result.diagnostics.language_consistency_ok is False


# --- донор: test_normalize_merge_description_does_not_double_prefix_bullet_as_lead_in
def test_bullet_is_not_prefixed_twice() -> None:
    result: QualityNormalization = normalized(
        "Hook paragraph with a question?\n\n🔹 First bullet as lead-in\n🔹 Second bullet\n🔹 Third bullet", "en"
    )
    assert all(not line.strip().startswith("🔹 🔹") for line in result.description.text.splitlines())


# --- донор: test_compact_bullet_repair.py
def compact_description(bullet_count: int, lead_in: bool = False) -> tuple[str, list[str]]:
    texts: list[str] = [f"Point {index} stays in original order with concrete detail." for index in range(1, bullet_count + 1)]
    lines: list[str] = ["Tonight we map concrete outcomes from linked source agendas.", ""]
    if lead_in:
        lines.append("In this stream you'll see:")
    lines.extend(f"🔹 {text}" for text in texts)
    return "\n".join(lines), texts


def test_eight_bullets_two_sources_trimmed_to_seven(caplog: pytest.LogCaptureFixture) -> None:
    description, texts = compact_description(8)
    with caplog.at_level(logging.INFO, logger="livecraft.llm"):
        result: QualityNormalization = normalized(description, "en", source_count=2)
    assert len(bullet_lines(result.description.text)) == 7
    assert all(text in result.description.text for text in texts[:7])
    assert texts[7] not in result.description.text
    assert result.normalization_applied is True
    assert [record.getMessage() for record in caplog.records] == [
        "merge_compact_bullet_trimmed source_count=2 bullets_before=8 bullets_after=7 cap=7"
    ]


def test_seven_bullets_two_sources_unchanged() -> None:
    description, texts = compact_description(7)
    result: QualityNormalization = normalized(description, "en", source_count=2)
    assert len(bullet_lines(result.description.text)) == 7
    assert all(text in result.description.text for text in texts)
    assert result.normalization_applied is False


def test_eight_bullets_three_sources_unchanged() -> None:
    description, texts = compact_description(8)
    result: QualityNormalization = normalized(description, "en", source_count=3)
    assert len(bullet_lines(result.description.text)) == 8
    assert all(text in result.description.text for text in texts)


def test_unknown_source_count_does_not_trim() -> None:
    description, texts = compact_description(8)
    result: QualityNormalization = normalized(description, "en")
    assert len(bullet_lines(result.description.text)) == 8


def test_trim_preserves_lead_in_line() -> None:
    description, texts = compact_description(8, lead_in=True)
    result: QualityNormalization = normalized(description, "en", source_count=2)
    assert "In this stream you'll see:" in result.description.text
    assert len(bullet_lines(result.description.text)) == 7
    assert texts[7] not in result.description.text


def test_compact_trim_keeps_non_bullet_lines_in_place() -> None:
    lines: tuple[str, ...] = ("Lead:", *(f"🔹 p{index}" for index in range(9)), "tail line")
    trim: CompactTrim = CompactTrim.of(lines, source_count=1)
    assert trim.applied is True
    assert trim.lines == ("Lead:", *(f"🔹 p{index}" for index in range(COMPACT_BULLET_MAX)), "tail line")
    assert (trim.bullets_before, trim.bullets_after) == (9, 7)


# --- исправление ошибки донора: простой маркер снимается без первого слова
@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("- first point here", "🔹 first point here"),
        ("1) third one", "🔹 third one"),
        ("– sanctions timeline", "🔹 sanctions timeline"),
        ("- word", "🔹 word"),
        ("plain line without marker", "🔹 plain line without marker"),
    ],
)
def test_plain_marker_is_replaced_without_losing_the_first_word(line: str, expected: str) -> None:
    bullets: BulletNormalization = BulletNormalization.of(("Lead-in:", line))
    assert bullets.lines == ("Lead-in:", expected)
    assert bullets.changed is True


def test_first_non_bullet_line_only_collapses_spaces() -> None:
    bullets: BulletNormalization = BulletNormalization.of(("In  this   stream:", "🔹 point"))
    assert bullets.lines == ("In this stream:", "🔹 point")
    assert bullets.changed is False
    assert bullets.neutral_bullets_count == 1


def test_single_cta_paragraph_is_not_repeated_as_hook_and_cta() -> None:
    result: QualityNormalization = normalized("Subscribe to the channel and leave a comment below #stream", "en")
    assert result.description.text == "Subscribe to the channel and leave a comment below #stream"
    assert result.normalization_applied is False


def test_second_paragraph_repeating_the_hook_keeps_one_hook() -> None:
    text: str = "Short single paragraph about the budget vote.\n\nShort single paragraph about the budget vote."
    result: QualityNormalization = normalized(text, "en")
    assert result.description.text == text


# --- статусы и коды
def test_clean_description_is_ok_and_unchanged() -> None:
    result: QualityNormalization = normalized(CLEAN_EN, "en")
    assert result.description.text == CLEAN_EN
    assert result.normalization_applied is False
    assert result.diagnostics.semantic_gate_status is QualityGateStatus.OK
    assert result.diagnostics.semantic_gate_reason_codes == ()


def test_every_reason_code_and_status_is_reachable() -> None:
    samples: list[QualityDiagnostics] = [
        normalized(CLEAN_EN, "en").diagnostics,
        normalized("Hook paragraph long enough here!\n\nWhat we cover:\n📌 a\n🎤 b\n🎥 c\n✅ d", "en").diagnostics,
        normalized(CLEAN_EN.replace("🌐 Official links:", "🌐 Links:"), "en").diagnostics,
        normalized(CLEAN_EN.replace("In this stream you'll see:", "В этом стриме вы увидите:"), "en").diagnostics,
        normalized(CLEAN_EN.replace("budget amendments", "бюджетні поправки"), "en").diagnostics,
        normalized(CLEAN_EN, "uk").diagnostics,
    ]
    codes: set[QualityReasonCode] = {code for sample in samples for code in sample.semantic_gate_reason_codes}
    statuses: set[QualityGateStatus] = {sample.semantic_gate_status for sample in samples}
    assert codes == set(QualityReasonCode)
    assert statuses == set(QualityGateStatus)


def test_reason_codes_keep_donor_order() -> None:
    result: QualityNormalization = normalized(
        "This English hook is clearly not in the expected block language and stays unchanged.\n\n"
        "In this stream you'll see:\n📌 a\n🎤 b\n🎥 c\n✅ d\n\n🌐 Links:\nhttps://example.org",
        "uk",
    )
    assert result.diagnostics.semantic_gate_reason_codes == tuple(QualityReasonCode)


def test_empty_description_is_not_normalized_but_title_is_checked() -> None:
    result: QualityNormalization = normalized(" \r\n ", "ru", title="Проверка FЕКРИС")
    assert result.description.text == ""
    assert result.normalization_applied is False
    assert result.diagnostics.block_spacing_ok is True
    assert result.diagnostics.hook_language_detected == "none"
    assert result.diagnostics.script_mix_suspects == ("FЕКРИС",)


def test_windows_line_breaks_are_normalized() -> None:
    result: QualityNormalization = normalized(CLEAN_EN.replace("\n", "\r\n"), "en")
    assert result.description.text == CLEAN_EN


def test_log_line_has_donor_keys_and_no_description_text() -> None:
    result: QualityNormalization = normalized(CLEAN_EN.replace("budget amendments", "бюджетні поправки"), "en")
    line: str = result.diagnostics.log_line
    assert "semantic_gate_status=hard_reject" in line
    assert "semantic_gate_reason_codes=script_mix_contamination" in line
    assert "block_language_expected=en" in line
    for text_line in CLEAN_EN.splitlines():
        if len(text_line) > 12:
            assert text_line not in line
    assert "script_mix_suspects=none" in normalized(CLEAN_EN, "en").diagnostics.log_line


def test_normalization_never_raises_on_arbitrary_text() -> None:
    rng: random.Random = random.Random(3110)
    alphabet: str = "abcXYZабвіїєЁ 🔹📌🌐#@.:-–—*•1)\n\r\t/"
    for _ in range(300):
        text: str = "".join(rng.choice(alphabet) for _ in range(rng.randint(0, 160)))
        language: str = rng.choice(["uk", "ru", "en", "de", ""])
        result: QualityNormalization = normalized(text, language, title=text[:20], source_count=rng.randint(0, 4))
        assert isinstance(result.diagnostics.semantic_gate_status, QualityGateStatus)


def test_merge_patterns_have_no_literal_range_characters() -> None:
    """Диапазоны и символы в шаблонах merge записаны экранированием: литеральный символ не виден глазом."""
    package: str = quality_module.__name__.rpartition(".")[0]
    modules: list[ModuleSource] = [module for module in SourceTree.from_root(REPO_ROOT).modules if module.key.package == package]
    assert modules
    offenders: list[tuple[str, int]] = [
        (module.key.parts[-1], number)
        for module in modules
        for number, line in enumerate(module.text.splitlines(), 1)
        if ("compile(" in line or line.lstrip().startswith(('r"', "r'")))
        and any(0x2000 <= ord(char) <= 0x2BFF or ord(char) >= 0x1F000 for char in line)
    ]
    assert offenders == []
