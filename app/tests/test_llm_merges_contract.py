from __future__ import annotations

import dataclasses
from types import MappingProxyType

import pytest

from app.llm.merges import rules
from app.llm.merges.contract import MergeContract, MergeContractMode, SourceTextSet, capitalized_runs
from app.llm.merges.prompt_texts import MergePromptTexts
from app.texts.description_marks import extract_named_entities

TEXTS: MergePromptTexts = MergePromptTexts.load()
# Пять цепочек имён: John Smith, Mary Jones, Alex Brown, Nina White, Oleg Ivanov.
SHARED_EVENT: str = "John Smith met Mary Jones while Alex Brown and Nina White and Oleg Ivanov reported from the event."


def lowercase_texts(count: int) -> tuple[str, ...]:
    return tuple(f"low overlap lowercase text {index}" for index in range(count))


def with_contracts(compact: str, expanded: str, narrative: str) -> MergePromptTexts:
    return dataclasses.replace(
        TEXTS,
        contracts=MappingProxyType(
            {MergeContractMode.COMPACT: compact, MergeContractMode.EXPANDED: expanded, MergeContractMode.NARRATIVE: narrative}
        ),
    )


# --- выбор режима


def test_two_unrelated_sources_get_the_compact_contract() -> None:
    contract: MergeContract = MergeContract.select(lowercase_texts(2), TEXTS)
    assert contract.mode is MergeContractMode.COMPACT
    assert (contract.bullet_range_min, contract.bullet_range_max) == (rules.COMPACT_BULLET_MIN, rules.COMPACT_BULLET_MAX)
    assert contract.bullet_range_label == "4-7"
    assert contract.max_body_paragraphs == 4
    assert contract.expanded_structure_enabled is False
    assert "Use the compact merge contract for 1 to 2 source items." in contract.block
    assert "Then write 4 to 7 short thesis bullet lines (target range 4-7)." in contract.block
    assert "{" not in contract.block


@pytest.mark.parametrize(
    ("count", "label"),
    [(3, "4-6"), (4, "5-7"), (5, "5-7"), (6, "6-9"), (7, "6-9"), (8, "6-9")],
)
def test_three_or_more_sources_get_the_expanded_contract_with_growing_range(count: int, label: str) -> None:
    contract: MergeContract = MergeContract.select(lowercase_texts(count), TEXTS)
    assert contract.mode is MergeContractMode.EXPANDED
    assert contract.bullet_range_label == label
    assert contract.max_body_paragraphs == 7
    assert contract.expanded_structure_enabled is True
    assert contract.source_count == count
    minimum, maximum = label.split("-")
    assert f"Write {minimum} to {maximum} short bullet lines total." in contract.block


def test_two_sources_about_one_event_get_the_narrative_contract() -> None:
    contract: MergeContract = MergeContract.select((SHARED_EVENT, SHARED_EVENT), TEXTS)
    assert contract.mode is MergeContractMode.NARRATIVE
    assert contract.bullet_range_label is None
    assert (contract.bullet_range_min, contract.bullet_range_max) == (0, 0)
    assert contract.max_body_paragraphs == 5
    assert contract.block.startswith("This stream covers a single unified event or case.")


def test_four_shared_names_are_not_enough_for_one_event() -> None:
    """Имена через запятую сливаются в одну цепочку («Alex Brown Nina White»): у донора здесь четыре цепочки, не пять."""
    four: str = "John Smith met Mary Jones while Alex Brown, Nina White, and Oleg Ivanov reported from the same event."
    assert MergeContract.select((four, four), TEXTS).mode is MergeContractMode.COMPACT


def test_names_shared_by_three_sources_do_not_make_them_narrative() -> None:
    assert MergeContract.select((SHARED_EVENT,) * 3, TEXTS).mode is MergeContractMode.EXPANDED


# --- два разных поиска имён донора


def test_single_event_runs_drop_punctuation_and_accept_all_caps_words() -> None:
    """Внутренний поиск донора: цепочки слов с заглавной буквы, знаки сняты; «NATO EU» — тоже цепочка."""
    assert capitalized_runs("Talk: NATO EU, then Anna-Maria Kovalenko, and O'Brien Kelly.") == {
        "Talk NATO EU", "AnnaMaria Kovalenko", "OBrien Kelly"
    }
    assert "nato eu" not in extract_named_entities("Talk: NATO EU")


def test_speaker_names_use_the_named_entity_rule_longest_first() -> None:
    sources: SourceTextSet = SourceTextSet(texts=("Anna Kovalenko spoke.", "Oleh Martynenko and Ian Li", "Iryna Melnyk"))
    assert sources.speaker_names == ("oleh martynenko", "anna kovalenko", "iryna melnyk")


def test_speaker_names_are_capped_at_eight() -> None:
    names: str = " ".join(f"Name{chr(97 + index)}x Surname{chr(97 + index)}x," for index in range(10))
    assert len(SourceTextSet(texts=(names.replace(",", " and"),)).speaker_names) <= rules.SPEAKER_NAMES_MAX


# --- строка-якорь спикеров


def test_three_sources_get_no_speaker_anchor() -> None:
    texts: tuple[str, ...] = ("Anna Kovalenko spoke.", "Oleh Martynenko too.", "Marta Leone as well.")
    assert "named speakers" not in MergeContract.select(texts, TEXTS).block


def test_four_sources_get_speaker_anchor_in_place_of_the_placeholder() -> None:
    texts: tuple[str, ...] = (
        "In Brussels, Anna Kovalenko tracks the vote.",
        "In Kharkiv, Oleh Martynenko reports strikes.",
        "From Geneva, Marta Leone outlines aid.",
        "In Lviv, Iryna Melnyk details repairs.",
    )
    block: str = MergeContract.select(texts, TEXTS).block
    assert block.endswith(
        "For 4 sources surface at least 3 distinct named speakers or participants from the list below, covering as many "
        "sources as possible. Do not drop any speaker from this list without clear overlap reason. Known names from "
        "sources: oleh martynenko, anna kovalenko, iryna melnyk, from geneva, marta leone."
    )   # «From Geneva» — тоже имя по правилу донора: два слова с заглавной, в каждом не меньше трёх букв
    assert "{speaker_anchor_line}" not in block


def test_minimum_names_is_limited_by_the_names_found() -> None:
    texts: tuple[str, ...] = ("Anna Kovalenko spoke.", "x", "y", "z", "w")
    assert "at least 1 distinct named speakers" in MergeContract.select(texts, TEXTS).block


def test_four_sources_without_names_get_no_anchor_and_an_empty_placeholder() -> None:
    block: str = MergeContract.select(lowercase_texts(4), TEXTS).block
    assert "named speakers" not in block
    assert block.endswith("rewrite it with a sharper angle.")


def test_anchor_is_appended_when_the_template_has_no_placeholder() -> None:
    texts: MergePromptTexts = with_contracts("C", "Expanded template {expanded_bullet_min}-{expanded_bullet_max}", "N")
    sources: tuple[str, ...] = ("Anna Kovalenko spoke.", "Oleh Martynenko too.", "x", "y")
    block: str = MergeContract.select(sources, texts).block
    assert block.startswith("Expanded template 5-7\nFor 4 sources surface at least 2 distinct named speakers")


# --- шаблоны


def test_compact_contract_is_read_from_the_template_and_exposes_the_range() -> None:
    """Донор: test_compact_contract_is_read_from_templates_and_exposes_4_7_range (контракт)."""
    texts: MergePromptTexts = with_contracts(
        "TEMPLATE COMPACT CONTRACT\nUse compact bullet range {compact_bullet_range} for compact mode.",
        "Expanded template {expanded_bullet_min}-{expanded_bullet_max}",
        "Narrative template",
    )
    block: str = MergeContract.select(lowercase_texts(2), texts).block
    assert block == "TEMPLATE COMPACT CONTRACT\nUse compact bullet range 4-7 for compact mode."


def test_placeholders_are_replaced_by_name_and_other_braces_stay() -> None:
    texts: MergePromptTexts = with_contracts("  {source_count} of {compact_bullet_max} {unknown} {}  \n", "E", "N")
    assert MergeContract.select(lowercase_texts(2), texts).block == "2 of 7 {unknown} {}"
