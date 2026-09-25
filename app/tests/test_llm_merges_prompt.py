from __future__ import annotations

import dataclasses
import hashlib
import json
import logging
from collections.abc import Iterator
from types import MappingProxyType

import pytest

from app.llm.merges.contract import MergeContractMode
from app.llm.merges.prompt import MergePrompt, MergePromptRefusal, language_full_name
from app.llm.merges.prompt_texts import MergePromptTexts
from app.llm.merges.retry import RetryFacts, RetryProfile, RetrySignal
from app.resources.loader import TextResource
from app.sources.video import SourceVideo
from app.tests.conftest import LogCollector
from app.tests.test_llm_merges_source import merge_video

TEXTS: MergePromptTexts = MergePromptTexts.load()

# sha256 значений `AppTemplates` донора (restreamer 35324e5, загрузчик `template_loader.py`); словари — JSON с
# `sort_keys=True, ensure_ascii=False`. Совпадение значения ресурса с этим хешем и есть «ресурс равен значению донора».
DONOR_VALUE_SHA256: dict[str, str] = {
    "title_description": "d0c2cd30174929146a4ff8dc67e00b0b9dd92550b8e3e93874a0bcc8112e8b73",
    "structural_rules": "04258f1042e52ecf099233b9df4324736c56eb439a4122dc80fce0c0ee9b4ef6",
    "no_description": "d632e251e13956f762ef83e9b96e22b2704e3efdee30fb1990574c8b412803af",
    "contracts": "434122741d7cf921938d0a68eeb876913b9325817415cad02915f2414d308abe",
    "retry_reinforcements": "fd0deda819273e6251418628c55dda70d33c038d69c67f1e71678c4b36fd2076",
}
RESOURCE_SHA256: dict[str, str] = {
    "merge_policy_cross_domain.txt": "49dfbb0110fa1cd8d20b297b02f57efb791806506f278e43d4f689ca97ee34d0",
    "merge_policy_link.txt": "a22fb3c1eac602dd7a4e576dc9be42d4d258ff06a2ad13969f4772754725564a",
    "merge_prompt_contracts.json": "d449ed039623192afd8efc82d119f979e24252fcbfa0e1d32227211728bed32b",
    "merge_prompt_no_description.txt": "aa27232ee5fc76a719beacc74fb70c8b467dda535154826a95e81fb157a945a1",
    "merge_prompt_speaker_anchor.txt": "12665dd348d8e4bfd2a82ae01bdaa67dde308ab5fe8522a324cbd34930c22af9",
    "merge_prompt_structural_rules.txt": "123a4cfe49349a5c3f0e2cb6e85fb73b035f8884b9fd15b13c2b51e6c502ee0e",
    "merge_prompt_title_description.txt": "4dd9552cb82cce599a21d8cfd194dc099a3316d393d03ce55c10905dd60ec3fe",
    "merge_retry_expanded_lines.json": "0ad7d959adea6eb04ea53226902546290e5513b71c73ef1bc310026e57b542ad",
    "merge_retry_fallback_lines.json": "cb931f522265218139641bb84ee148afebbfdde2f8de4297a7c0e51a45ab2f48",
    "merge_retry_reinforcements.json": "7bcda0878b67330d8cc01c179359dffd49b97e1733fd4a1727573489d62df545",
}

# Шаблоны донорских тестов (`test_merge_contract_helpers.py::MergeContractServiceBase._config`).
DONOR_TEST_PROMPT: str = """
Write a YouTube stream title and description in {language_name}.
Generate a new final title, not a copy of any single source title.
Mentally extract key points from each source, preserve all non-trivial source-specific points,
combine overlaps, compress repetition, and produce one coherent final description.
Write a strong native YouTube title no longer than 99 characters.
Do not enumerate sources as 1) 2) 3).
Do not output generic slogans or abstract editorial phrasing.
Do not use emoji in the title.
{merge_contract_block}
Avoid asserting strong person titles or role labels unless they are clearly necessary and well-supported by the sources.
Optional official links block is allowed before the hashtags line with 1 to 3 non-YouTube links from sources.
Always end the description with a final hashtags line.
Return strict JSON with title and description only.

{youtube_candidates_block}

{sources_block}
""".strip()
DONOR_TEST_RULES: str = (
    "MERGE STRUCTURAL RULES\n"
    "RULE 1: Start with a standalone hook paragraph before any bullets.\n"
    "RULE 2: Keep visual paragraph boundaries explicit with one blank line between structural blocks.\n"
    "RULE 3: Keep hashtags only in the final tail position; never write a CTA paragraph anywhere.\n"
    "RULE 4: Do not repeat or paraphrase the hook thesis in the next adjacent line or paragraph.\n"
    "EXAMPLE A (bad): CTA line opens the description and the real hook starts later.\n"
    "EXAMPLE A (good): Hook opens first; no CTA paragraph anywhere.\n"
    "EXAMPLE B (bad): Two adjacent lines restate the same thesis with minor wording changes.\n"
    "EXAMPLE B (good): The second line introduces new facts instead of repeating the opener."
)
DONOR_TEST_COMPACT: str = (
    "Use the compact merge contract for 1 to 2 source items.\n"
    "Write one cohesive stream description in 2 to 3 compact paragraphs.\n"
    "Paragraph 1 (hook): write 1 to 2 sentences grounded in the main tension, risk, or key conflict.\n"
    "Keep the hook editorial and readable, but never clickbait.\n"
    "Paragraph 2 (theses block): open with one short editorial statement that names the central tension, key question, "
    "or main conflict — not a lead-in phrase like 'In this stream you will see'.\n"
    "Then write {compact_bullet_min} to {compact_bullet_max} short thesis bullet lines (target range {compact_bullet_range}).\n"
    "Each bullet line must start with exactly one allowed marker: 🔹 📌 🎤 🎥 ⚖ 🌐 ✅.\n"
    "Most bullets should start with 🔹.\n"
    "Accent markers are rare and optional; use no more than 3 accent markers per theses block.\n"
    "Keep marker usage controlled and readable; do not use dash-only bullets as the sole style.\n"
    "Do not present the agenda as SOURCE 1 / SOURCE 2.\n"
    "Keep agenda points specific and factual, not generic placeholders.\n"
    "The description must still cover all merged source items and preserve key concrete facts from each source."
)
DONOR_TEST_EXPANDED: str = (
    "Use the expanded merge contract for 3 or more source items.\n"
    "Write {expanded_bullet_min} to {expanded_bullet_max} short bullet lines total.\n"
    "You may organize the bullets into 2 to 3 thematic micro-blocks when that improves clarity.\n"
    "Do not combine science or medicine, climate or environment, disasters or catastrophic hazards, psychology or "
    "cognition or behavior, and broad social or moral conclusions into one bullet or one cause-and-effect chain unless "
    "the sources explicitly require that connection.\n"
    "Thematic grouping is encouraged when useful: research, hazards, human behavior, practical risk, public meaning, or "
    "response can be separated into different bullets or micro-blocks.\n"
    "{speaker_anchor_line}"
)
DONOR_TEST_NARRATIVE: str = (
    "This stream covers a single unified event or case. Write the description as connected prose, not a bullet list. "
    "Hook paragraph first, then 2-3 prose paragraphs. No bullets."
)


def donor_test_texts(
    prompt: str = DONOR_TEST_PROMPT,
    rules: str = DONOR_TEST_RULES,
    compact: str = DONOR_TEST_COMPACT,
    expanded: str = DONOR_TEST_EXPANDED,
    narrative: str = DONOR_TEST_NARRATIVE,
) -> MergePromptTexts:
    return dataclasses.replace(
        TEXTS,
        title_description=prompt,
        structural_rules=rules,
        contracts=MappingProxyType(
            {MergeContractMode.COMPACT: compact, MergeContractMode.EXPANDED: expanded, MergeContractMode.NARRATIVE: narrative}
        ),
        retry_reinforcements=MappingProxyType({}),
        no_description="no description",
    )


def two_videos() -> tuple[SourceVideo, ...]:
    return (
        merge_video(2, "Title 1", "Paragraph one.\n\nParagraph two."),
        merge_video(3, "Title 2", "Paragraph three.\n\nParagraph four."),
    )


def three_videos() -> tuple[SourceVideo, ...]:
    return (*two_videos(), merge_video(4, "Title 3", "Paragraph five.\n\nParagraph six."))


def build(language: str, videos: tuple[SourceVideo, ...], texts: MergePromptTexts, retry: RetryProfile | None = None) -> MergePrompt:
    prompt: MergePrompt | MergePromptRefusal = MergePrompt.of(language, videos, texts, retry)
    assert isinstance(prompt, MergePrompt)
    return prompt


@pytest.fixture
def llm_log() -> Iterator[LogCollector]:
    logger: logging.Logger = logging.getLogger("livecraft.llm")
    collector: LogCollector = LogCollector()
    previous: int = logger.level
    logger.addHandler(collector)
    logger.setLevel(logging.DEBUG)
    yield collector
    logger.removeHandler(collector)
    logger.setLevel(previous)


# --- ресурсы


@pytest.mark.parametrize(("name", "digest"), sorted(RESOURCE_SHA256.items()))
def test_resource_file_is_the_transferred_one(name: str, digest: str) -> None:
    assert hashlib.sha256(TextResource(name).path.read_bytes()).hexdigest() == digest


def test_template_values_equal_the_donor_values() -> None:
    def sha(value: object) -> str:
        text: str = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(text.encode("utf-8")).hexdigest()

    contracts: dict[str, str] = {mode.value: text for mode, text in TEXTS.contracts.items()}
    reinforcements: dict[str, list[str]] = {signal: list(lines) for signal, lines in TEXTS.retry_reinforcements.items()}
    assert {
        "title_description": sha(TEXTS.title_description),
        "structural_rules": sha(TEXTS.structural_rules),
        "no_description": sha(TEXTS.no_description),
        "contracts": sha(contracts),
        "retry_reinforcements": sha(reinforcements),
    } == DONOR_VALUE_SHA256


def test_texts_cover_every_contract_and_every_retry_signal() -> None:
    assert set(TEXTS.contracts) == set(MergeContractMode)
    assert set(TEXTS.retry_reinforcements) == {signal.value for signal in RetrySignal}
    assert set(TEXTS.retry_fallbacks) == {signal.value for signal in RetrySignal}
    assert TEXTS.link_policy.startswith("SYSTEM LINK POLICY\n")
    assert TEXTS.cross_domain_policy.startswith("CROSS-DOMAIN SENTENCE POLICY\n")
    assert not TEXTS.title_description.startswith("#")


# --- донорские тесты промта (test_merge_contract_prompt.py)


def test_prompt_targets_youtube_title_and_description_only() -> None:
    text: str = build("en", two_videos(), donor_test_texts()).text
    for fragment in (
        "YouTube stream title and description",
        "99 characters",
        "title and description only",
        "must still cover all merged source items and preserve key concrete facts from each source",
        "Do not output generic slogans",
        "Use the compact merge contract for 1 to 2 source items.",
        "2 to 3 compact paragraphs",
        "Then write 4 to 7 short thesis bullet lines",
        "allowed marker",
        "Most bullets should start with 🔹",
        "no more than 3 accent markers",
        "Avoid asserting strong person titles",
        "If the sources touch different semantic domains, do not compress them into one sentence.",
        "These topics may stay in one final description, but present them as separate lines of discussion in separate sentences.",
        "Do not build one long cause-and-effect chain across all of those domains in a single sentence.",
        "Do not include any URLs in the output.",
        "Link blocks will be assembled later by the system.",
        "Do not use emoji in the title.",
        "Paragraph one.\n\nParagraph two.",
    ):
        assert fragment in text
    assert "always end the description with a final hashtags line" in text.lower()
    assert "never write a cta paragraph anywhere" in text.lower()
    assert "URL:" not in text


def test_prompt_uses_expanded_contract_for_three_or_more_sources(llm_log: LogCollector) -> None:
    text: str = build("en", three_videos(), donor_test_texts()).text
    assert "Use the expanded merge contract for 3 or more source items." in text
    assert "Write 4 to 6 short bullet lines total." in text
    assert "2 to 3 thematic micro-blocks" in text
    assert "Do not combine science or medicine, climate or environment, disasters or catastrophic hazards, psychology or cognition or behavior, and broad social or moral conclusions into one bullet" in text
    assert "Thematic grouping is encouraged when useful" in text
    assert (
        "merge_prompt_contract_selected language=en source_count=3 contract_mode=expanded expected_bullet_range=4-6 "
        "expanded_structure_enabled=yes"
    ) in "\n".join(llm_log.messages(logging.INFO))


def test_compact_contract_is_read_from_templates_and_exposes_4_7_range() -> None:
    texts: MergePromptTexts = donor_test_texts(
        compact="TEMPLATE COMPACT CONTRACT\nUse compact bullet range {compact_bullet_range} for compact mode.",
        expanded="Expanded template {expanded_bullet_min}-{expanded_bullet_max}",
        narrative="Narrative template",
    )
    text: str = build("en", two_videos(), texts).text
    assert "TEMPLATE COMPACT CONTRACT" in text
    assert "compact bullet range 4-7" in text


def test_compact_prompt_ignores_expanded_retry_profile() -> None:
    retry: RetryProfile = RetryProfile.expanded(3, ("insufficient_expanded_body",), TEXTS)
    text: str = build("en", two_videos(), donor_test_texts(), retry).text
    assert "EXPANDED RETRY FOCUS" not in text
    assert "Use the compact merge contract for 1 to 2 source items." in text


def test_merge_prompt_uses_clean_full_source_text_without_urls_hashtags_or_truncation(llm_log: LogCollector) -> None:
    videos: tuple[SourceVideo, ...] = (
        merge_video(
            1,
            "Source 1",
            "Hook paragraph with concrete facts and named people. " + "A" * 2600 + "\n\n"
            "Main stream link https://youtu.be/aaaaaaaaaaa\n"
            "Official links:\nhttps://example.org/details\n\n"
            "Join and follow updates. #topic #update",
        ),
        merge_video(2, "Source 2", "Second source keeps the semantic context intact without extra links."),
    )
    text: str = build("en", videos, donor_test_texts()).text
    for absent in ("https://youtu.be/aaaaaaaaaaa", "https://example.org/details", "#topic", "Official links:",
                   "Join and follow updates.", "YOUTUBE CANDIDATES"):
        assert absent not in text
    assert "Hook paragraph with concrete facts and named people." in text
    assert "Second source keeps the semantic context intact without extra links." in text
    assert "Do not add a recommended materials block" in text
    assert "A" * 2400 in text
    logs: str = "\n".join(llm_log.messages(logging.INFO))
    assert "hard_truncation=disabled" in logs
    assert "merge_source_text_prepared language=en source_index=1" in logs
    assert "urls_removed=" in logs
    assert "hashtags_removed=" in logs


# --- донорские тесты правил структуры (test_merge_structural_rules.py)


STRUCTURAL_RULES: str = (
    "STRUCTURAL RULES — APPLY TO EVERY MERGE OUTPUT\n\n"
    "RULE 1 — NO CTA AS OPENER:\nThe first paragraph MUST be the editorial hook.\n\n"
    "RULE 2 — HOOK UNIQUENESS:\nThe hook paragraph appears exactly ONCE — as the first paragraph.\n\n"
    "RULE 3 — BULLET COUNT DISCIPLINE:\nThe number of bullets must stay within the range specified by the contract.\n\n"
    "RULE 4 — PARAGRAPH 2 STARTS WITH A BULLET:\nImmediately after the hook, the next content must be the bullet block.\n\n"
    "EXAMPLE — CORRECT structure (uk):\nHook paragraph here.\n\n"
    "EXAMPLE — WRONG structure (3 violations):\nCTA as first paragraph."
)


def structural_texts() -> MergePromptTexts:
    return donor_test_texts(
        prompt="Write in {language_name}.\n{merge_contract_block}\n\n{youtube_candidates_block}\n\n{sources_block}",
        rules=STRUCTURAL_RULES,
        compact="COMPACT CONTRACT {compact_bullet_range}",
        expanded="EXPANDED CONTRACT {expanded_bullet_min}-{expanded_bullet_max}",
        narrative="NARRATIVE CONTRACT",
    )


def assert_structural_rules_present(text: str) -> None:
    for fragment in (
        "STRUCTURAL RULES", "RULE 1 — NO CTA AS OPENER", "RULE 2 — HOOK UNIQUENESS", "RULE 3 — BULLET COUNT DISCIPLINE",
        "RULE 4 — PARAGRAPH 2 STARTS WITH A BULLET", "EXAMPLE — CORRECT structure", "EXAMPLE — WRONG structure",
    ):
        assert fragment in text


def test_structural_rules_are_appended_for_compact_mode() -> None:
    videos = (merge_video(2, "One", "low overlap lowercase text one"), merge_video(3, "Two", "low overlap lowercase text two"))
    text: str = build("en", videos, structural_texts()).text
    assert "COMPACT CONTRACT 4-7" in text
    assert_structural_rules_present(text)


def test_structural_rules_are_appended_for_expanded_mode() -> None:
    videos = tuple(merge_video(row, title, f"source text {title.lower()}") for row, title in ((2, "One"), (3, "Two"), (4, "Three")))
    text: str = build("en", videos, structural_texts()).text
    assert "EXPANDED CONTRACT 4-6" in text
    assert_structural_rules_present(text)


def test_structural_rules_are_appended_for_narrative_mode() -> None:
    """У донора «одно событие» подменялось; здесь описание само даёт пять общих цепочек имён."""
    description: str = "John Smith met Mary Jones while Alex Brown and Nina White and Oleg Ivanov reported from the same event."
    videos = (merge_video(2, "One", description), merge_video(3, "Two", description))
    prompt: MergePrompt = build("en", videos, structural_texts())
    assert prompt.contract.mode is MergeContractMode.NARRATIVE
    assert "NARRATIVE CONTRACT" in prompt.text
    assert_structural_rules_present(prompt.text)


def test_structural_rules_come_before_the_contract() -> None:
    block: str = build("en", two_videos(), structural_texts()).contract_block
    assert block == f"{STRUCTURAL_RULES}\n\nCOMPACT CONTRACT 4-7"


def repo_videos(count: int) -> tuple[SourceVideo, ...]:
    return tuple(
        merge_video(
            index + 1,
            f"Title {index}",
            f"Source {index} paragraph one with concrete facts and names.\n\nSource {index} paragraph two with extra details and timing.",
        )
        for index in range(1, count + 1)
    )


def test_prompt_contains_hook_sharpness_examples() -> None:
    text: str = build("uk", repo_videos(3), TEXTS).text
    assert "HOOK SHARPNESS" in text
    assert "STRONG" in text
    assert "WEAK" in text


def test_prompt_contains_multilingual_hook_sharpness_examples() -> None:
    text: str = build("ru", repo_videos(3), TEXTS).text
    for fragment in ("MEDIUM (ru)", "WEAK (ru)", "MEDIUM (en)", "WEAK (en)"):
        assert fragment in text


# --- боевой промт и повтор


def test_production_prompt_writes_language_contract_and_policies_in_order() -> None:
    prompt: MergePrompt = build("uk", repo_videos(2), TEXTS)
    text: str = prompt.text
    assert "Write output only in Ukrainian." in text
    assert "{" not in text
    assert text.index(TEXTS.structural_rules) < text.index("Use the compact merge contract") < text.index("SOURCE 1\nTITLE: Title 1")
    assert text.endswith(f"{TEXTS.cross_domain_policy}\n\n{TEXTS.link_policy}")


def test_retry_instruction_goes_last_and_keeps_the_prefix() -> None:
    first: MergePrompt = build("en", three_videos(), TEXTS)
    retry: RetryProfile = RetryProfile.targeted(
        RetrySignal.INSUFFICIENT_BULLET_COVERAGE, RetryFacts(source_count=3, actual_bullets=2, required_bullets=5), TEXTS
    )
    again: str = first.with_retry(retry).text
    assert again == f"{first.text}\n\n{retry.instruction_block}"
    assert "RETRY INSTRUCTION:" not in first.text
    assert again.endswith("Spread bullets across all 3 sources. Do not collapse multiple sources into one generic lane.")
    assert build("en", three_videos(), TEXTS, retry).text == again


def test_disabled_retry_changes_nothing() -> None:
    prompt: MergePrompt = build("en", two_videos(), TEXTS)
    assert prompt.with_retry(RetryProfile.standard(("paragraph_underflow",))).text == prompt.text


def test_contract_block_with_retry_appends_the_instruction() -> None:
    prompt: MergePrompt = build("en", two_videos(), TEXTS)
    retry: RetryProfile = RetryProfile.targeted(RetrySignal.PARAGRAPH_UNDERFLOW, RetryFacts(), TEXTS)
    assert prompt.contract_block_with(retry) == f"{prompt.contract_block}\n\n{retry.instruction_block}"
    assert prompt.contract_block_with(None) == prompt.contract_block


def test_template_without_contract_placeholder_gets_the_block_appended() -> None:
    texts: MergePromptTexts = donor_test_texts(prompt="Head in {language_name}.\n{sources_block}", rules="RULES")
    text: str = build("en", two_videos(), texts).text
    assert text.startswith("Head in English.\nSOURCE 1\n")
    assert "Paragraph four.\n\nRULES\n\nUse the compact merge contract" in text


def test_braces_in_source_text_do_not_break_the_template() -> None:
    videos = (merge_video(2, "A {title}", "Body {language_name} {0}"), merge_video(3, "B", "Other body"))
    text: str = build("en", videos, TEXTS).text
    assert "TITLE: A {title}\nDESCRIPTION: Body {language_name} {0}" in text


def test_source_texts_for_quality_follow_the_sources() -> None:
    videos = (merge_video(2, "One", "Body https://x.example"), merge_video(3, "Two", ""))
    assert build("en", videos, TEXTS).source_texts_for_quality == ("One\nBody", "Two")


def test_contract_is_chosen_by_the_prompt_descriptions() -> None:
    """Пустое после чистки описание идёт в выбор контракта текстом «нет описания», как у донора."""
    prompt: MergePrompt = build("en", (merge_video(2, "A", ""), merge_video(3, "B", "")), TEXTS)
    assert prompt.contract.mode is MergeContractMode.COMPACT
    assert prompt.contract.max_body_paragraphs == 4


# --- лог и отказ


def test_log_lines_have_counters_and_no_source_text(llm_log: LogCollector) -> None:
    videos = (merge_video(5, "Secret one", "Private https://x.example"), merge_video(6, "Secret two", ""))
    prompt: MergePrompt = build("en", videos, TEXTS)
    assert llm_log.messages(logging.INFO) == list(prompt.log_lines)
    assert prompt.log_lines == (
        "merge_source_text_prepared language=en source_index=1 row=5 raw_chars=25 cleaned_chars=7 urls_removed=1 "
        "hashtags_removed=0 service_paragraphs_dropped=0 hard_truncation=disabled",
        "merge_source_text_prepared language=en source_index=2 row=6 raw_chars=16 cleaned_chars=16 urls_removed=0 "
        "hashtags_removed=0 service_paragraphs_dropped=0 hard_truncation=disabled",
        "merge_prompt_sources_ready language=en source_count=2 raw_source_chars_total=41 cleaned_source_chars_total=23 "
        "hard_truncation=disabled",
        "merge_prompt_contract_selected language=en source_count=2 contract_mode=compact expected_bullet_range=4-7 "
        "expanded_structure_enabled=no narrative_trigger=no",
    )
    assert not any("Secret" in line or "Private" in line for line in prompt.log_lines)


def test_narrative_log_line_has_no_bullet_range() -> None:
    description: str = "John Smith met Mary Jones while Alex Brown and Nina White and Oleg Ivanov reported."
    prompt: MergePrompt = build("en", (merge_video(2, "A", description), merge_video(3, "B", description)), TEXTS)
    assert prompt.log_lines[-1].endswith("contract_mode=narrative expected_bullet_range=None expanded_structure_enabled=no narrative_trigger=yes")


@pytest.mark.parametrize("count", [0, 1])
def test_fewer_than_two_sources_is_a_refusal_value(count: int, llm_log: LogCollector) -> None:
    result: MergePrompt | MergePromptRefusal = MergePrompt.of("uk", two_videos()[:count], TEXTS)
    assert result == MergePromptRefusal(language="uk", source_count=count)
    assert llm_log.messages(logging.WARNING) == [f"merge_prompt_refused language=uk source_count={count} min_sources=2"]
    assert llm_log.messages(logging.INFO) == []


# --- название языка


@pytest.mark.parametrize(
    ("code", "name"),
    [("uk", "Ukrainian"), ("ru", "Russian"), ("en", "English"), ("de", "German"), (" EN ", "English"),
     ("xx", "XX"), (" zz ", "ZZ"), ("", "Unknown"), ("   ", "Unknown")],
)
def test_language_full_name(code: str, name: str) -> None:
    assert language_full_name(code) == name
