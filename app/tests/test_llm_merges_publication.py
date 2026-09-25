"""Санация принятого merge перед публикацией (донор: test_merged_publish_payload_sanitation.py,
test_post_llm_sanitation_tail.py, test_no_cta_in_published_output.py, test_sanitizer_quality_gate.py)."""
from __future__ import annotations

import dataclasses
import logging
from collections.abc import Iterator

import pytest

from app.llm.merges.attempt import MergeRules
from app.llm.merges.publication import PRIMARY_SOURCE_LABEL, MergePublication, PublishGate, SanitizedDescription
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.sources.video import SourceVideo
from app.tests.conftest import LogCollector
from app.tests.test_llm_merges_source import merge_video
from app.texts.description_marks import CtaLexicon

RULES: MergeRules = MergeRules.load()
CTA: CtaLexicon = RULES.check.quality.cta
GATE: PublishGate = PublishGate(bad_hooks=RULES.check.bad_hooks, cta=CTA)
HEADING: str = "\U0001F310 Official links:"
TITLE: str = "Merged title"


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


def source(metadata_url: str = "", description: str = "", row: int = 2) -> SourceVideo:
    """Источник как `_video` донорских тестов: без ссылки ряда; ссылка метаданных — своя."""
    video: SourceVideo = merge_video(row, "Source title", description)
    assert video.metadata is not None
    return dataclasses.replace(
        video, row=dataclasses.replace(video.row, link=""), metadata=dataclasses.replace(video.metadata, url=metadata_url)
    )


def publish(description: str, sources: tuple[SourceVideo, ...] | None = None, language: str = "en") -> MergePublication:
    return MergePublication.of(TITLE, description, (source(),) if sources is None else sources, language, RULES)


def sanitize(text: str, language: str = "en") -> SanitizedDescription:
    return SanitizedDescription.of(text, language, "merge", CTA)


def applied_line(log: LogCollector) -> str:
    lines: list[str] = [line for line in log.messages() if line.startswith("publish_sanitation_applied=yes ")]
    assert len(lines) == 1
    return lines[0]


# --- санация текста


def test_embedded_hashtags_are_split_from_the_cta(llm_log: LogCollector) -> None:
    sanitized: SanitizedDescription = sanitize(
        "Scientists compare nanoplastics data across multiple studies.\n\n"
        "Join us tonight and share if you find these scientific findings important. #nanoplastics #microplastics"
    )
    assert sanitized.body == "Scientists compare nanoplastics data across multiple studies."
    assert sanitized.cta_text == "Join us tonight and share if you find these scientific findings important."
    assert sanitized.hashtags_line == "#nanoplastics #microplastics" and sanitized.hashtags_split_from_cta
    assert llm_log.messages() == [
        "tail_parse lang=en source=merge cta_found=yes hashtags_found=yes hashtags_split_from_cta=yes",
        "tail_layout lang=en source=merge layout=body_blank_cta_blank_hashtags",
        "publish_cta_gate_dropped lang=en source=merge cta_chars=74",
        "post_llm_sanitation lang=en source=merge urls_normalized=0 tail_separated=yes tail_cta_found=yes "
        "hashtags_found=yes source_urls_found=0 malformed_source_urls_dropped=0",
    ]


@pytest.mark.parametrize(
    ("text", "layout"),
    [
        ("Body.\n\nJoin us tonight for the full discussion.\n\n#nano #micro", "body_blank_cta_blank_hashtags"),
        ("Body.\n\n#nano #micro", "body_blank_hashtags"),
        ("Body.\n\nJoin us tonight for the full discussion.", "body_blank_cta"),
        ("Body.\n\nhttps://example.org/?utm_source=x\nhttps://youtu.be/aaaaaaaaaaa", "body_blank_recommended_materials_blank_official_links"),
        ("", "empty"),
    ],
)
def test_tail_layout_names_what_the_tail_had(text: str, layout: str) -> None:
    assert sanitize(text).tail_layout == layout


def test_links_in_the_body_are_cleaned_and_counted() -> None:
    sanitized: SanitizedDescription = sanitize(
        "Body with https://example.org/?utm_source=x inside.\n\nMore https://example.org/page?fbclid=1 words."
    )
    assert sanitized.body == "Body with https://example.org inside.\n\nMore https://example.org/page words."
    assert sanitized.url_change_count == 2 and sanitized.source_urls == ()


def test_double_bullet_markers_and_broken_tail_links() -> None:
    sanitized: SanitizedDescription = sanitize(
        "Hook paragraph.\n\n\U0001F539 \U0001F539 First point\n\U0001F539 \U0001F4CC Second point\n\nhttps://[bad\nhttps://localhost"
    )
    assert sanitized.body == "Hook paragraph.\n\n\U0001F539 First point\n\U0001F539 Second point"
    assert sanitized.malformed_source_urls_dropped == 2 and sanitized.source_urls == ()


def test_a_final_cta_paragraph_left_by_the_tail_is_removed(llm_log: LogCollector) -> None:
    """Абзац из одной строки с хештегом без подсказки призыва хвост не снимает — его снимает проверка тела."""
    sanitized: SanitizedDescription = sanitize("Budget decision and what it means for the regions.\n \n#stream \U0001F3AF")
    assert sanitized.body == "Budget decision and what it means for the regions."
    assert "removed_final_body_cta=yes lang=en source=merge removed_chars=9" in llm_log.messages()


def test_a_bullet_block_with_a_cta_word_is_kept() -> None:
    sanitized: SanitizedDescription = sanitize(
        "A judge ruled that expert opinions are inadmissible evidence.\n\n"
        "\U0001F539 Watch how the court rejected the witnesses statement.\n\U0001F539 Legal timeline and appeal context.\n\n"
        "#Justice #Court"
    )
    assert "Watch how the court" in sanitized.body and "Legal timeline" in sanitized.body


# --- проверка перед публикацией


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("First paragraph with enough words.\n\nSecond paragraph with different words.", False),
        ("Same long text here with enough tokens for check.\n\nSame long text here with enough tokens for check.", True),
        ("Hi.\n\nHi.", False),
    ],
)
def test_gate_duplicate_paragraphs(text: str, expected: bool) -> None:
    assert GATE.has_duplicate_paragraphs(text) is expected


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
    assert GATE.has_opener_cta(text) is expected


# --- публикация целиком


def test_embedded_hashtags_are_split_in_the_publication(llm_log: LogCollector) -> None:
    publication: MergePublication = publish(
        "Body paragraph.\n\nJoin us tonight and share your thoughts. #nanoplastics #microplastics"
    )
    assert publication.description == "Body paragraph.\n\n#nanoplastics #microplastics"
    assert publication.layout == "body_blank_hashtags" and not publication.is_blocked
    line: str = applied_line(llm_log)
    assert f"lang=en source={PRIMARY_SOURCE_LABEL} " in line
    assert "hashtags_split_from_cta=yes tail_layout=body_blank_hashtags " in line
    assert [message for message in llm_log.messages() if message.startswith("publish_cta_gate_dropped")] == [
        "publish_cta_gate_dropped lang=en source=primary_success cta_chars=40"
    ] * 2


@pytest.mark.parametrize(
    "text",
    [
        "Body paragraph.\n\nJoin us tonight and share your thoughts.\n\n#nanoplastics #microplastics",
        "Body paragraph.\n\n#nanoplastics #microplastics",
    ],
)
def test_separate_hashtags_stay_stable(text: str) -> None:
    assert publish(text).description == "Body paragraph.\n\n#nanoplastics #microplastics"


def test_a_closing_cta_is_never_published() -> None:
    assert publish("Body paragraph.\n\nJoin us tonight and share your thoughts.").description == "Body paragraph."
    russian: MergePublication = publish(
        "Свидетельства жертв звучат на фоне следствия.\n\n"
        "⚖ Дело открыто и находится на стадии следствия.\n\U0001F539 Встреча с послом: правительство ознакомлено.\n\n"
        "Напишите в комментариях, какие вопросы вы считаете ключевыми.\n\n#Танзания #ЗащитаДетей",
        language="ru",
    )
    assert "Напишите в комментариях" not in russian.description
    assert "#Танзания" in russian.description and "Свидетельства жертв" in russian.description


def test_an_empty_official_links_heading_is_suppressed(llm_log: LogCollector) -> None:
    publication: MergePublication = publish(f"Body paragraph.\n\n{HEADING}\n\nJoin us tonight and share your thoughts.")
    assert HEADING not in publication.description
    line: str = applied_line(llm_log)
    assert "official_links_final_count=0 official_links_block=suppressed " in line


def test_a_non_empty_official_links_block_stays_cohesive(llm_log: LogCollector) -> None:
    publication: MergePublication = publish(
        f"Body paragraph.\n\n{HEADING}\n\nhttps://example.org/official\nhttps://allatra.org/resource\n\n"
        "Join us tonight and share your thoughts. #nanoplastics #microplastics"
    )
    assert publication.description == (
        f"Body paragraph.\n\n{HEADING}\nhttps://example.org\nhttps://allatra.org\n\n#nanoplastics #microplastics"
    )
    line: str = applied_line(llm_log)
    for fragment in ("official_links_heading_found=yes", "official_links_text_links=2", "official_links_final_count=2",
                     "official_links_block=emitted", "tail_layout=body_blank_official_links_blank_hashtags"):
        assert fragment in line


def test_text_and_source_links_are_deduped_into_one_block(llm_log: LogCollector) -> None:
    publication: MergePublication = publish(
        f"Body paragraph.\n\n{HEADING}\n\nhttps://example.org/official?utm_source=yt\n\n"
        "Join us tonight and share your thoughts.\n\n#nanoplastics #microplastics",
        sources=(source("https://example.org/official"), source("https://example.org/second-source", row=3)),
    )
    assert publication.description == f"Body paragraph.\n\n{HEADING}\nhttps://example.org\n\n#nanoplastics #microplastics"
    line: str = applied_line(llm_log)
    for fragment in ("official_links_text_links=1", "official_links_source_links=1", "official_links_final_count=1",
                     "official_links_dedup_applied=yes"):
        assert fragment in line


def test_youtube_links_of_the_answer_are_ignored_and_not_recommended(llm_log: LogCollector) -> None:
    publication: MergePublication = publish(
        f"Body paragraph.\n\n{HEADING}\n\nhttps://example.org/official?utm_source=yt\n\n{HEADING}\n"
        f"https://example.org/official\nhttps://example.org/second\n\n{HEADING}\n\nhttps://youtu.be/ccccccccccc\n\n"
        "Join us tonight and share your thoughts.\n\n#nanoplastics #microplastics",
        sources=(source("https://example.org/second"), source(row=3)),
    )
    assert publication.description.count(HEADING) == 1 and publication.description.count("https://example.org") == 1
    assert "youtu" not in publication.description and "Recommended materials:" not in publication.description
    line: str = applied_line(llm_log)
    for fragment in ("official_links_text_links=2", "official_links_final_count=1", "recommended_materials_final_count=0",
                     "recommended_materials_block=skipped", "ignored_llm_youtube_urls=1", "official_links_dedup_applied=yes"):
        assert fragment in line


def test_without_sources_the_body_is_not_normalized_again() -> None:
    publication: MergePublication = publish(
        f"Body paragraph.\n\n{HEADING}\nhttps://example.org/official\nhttps://example.org/second\n\n{HEADING}\n\n"
        "Join us tonight and share your thoughts.\n\n#nanoplastics #microplastics",
        sources=(),
    )
    assert publication.description == f"Body paragraph.\n\n{HEADING}\nhttps://example.org\n\n#nanoplastics #microplastics"


def test_source_youtube_links_are_not_injected() -> None:
    publication: MergePublication = publish(
        "Body paragraph.\n\nJoin us tonight and share your thoughts.",
        sources=(source("https://youtu.be/aaaaaaaaaaa"), source("https://www.youtube.com/watch?v=bbbbbbbbbbb", row=3)),
    )
    assert "youtu" not in publication.description


@pytest.mark.parametrize(("language", "heading"), [("uk", "\U0001F310 Офіційні ресурси:"), ("de", HEADING), ("", HEADING)])
def test_the_links_heading_follows_the_language(language: str, heading: str) -> None:
    publication: MergePublication = publish("Body paragraph.\n\nhttps://example.org/page", language=language)
    assert publication.description == f"Body paragraph.\n\n{heading}\nhttps://example.org"


def test_the_title_is_collapsed_to_single_spaces() -> None:
    publication: MergePublication = MergePublication.of("  Title \t with\n spaces ", "Body.", (source(),), "en", RULES)
    assert publication.title == "Title with spaces"
    assert publication.slot_texts == SlotTexts(title="Title with spaces", description="Body.", origin=SlotTextOrigin.MERGED)


def test_a_duplicate_paragraph_blocks_the_publication(llm_log: LogCollector) -> None:
    """Без источников тело не нормализуется повторно (правило донора) — повтор доходит до проверки как есть."""
    paragraph: str = "Budget amendments passed after the long commission session in Brussels today."
    publication: MergePublication = publish(f"{paragraph}\n\nMiddle facts.\n\n{paragraph}", sources=())
    assert publication.has_duplicate and publication.is_blocked and publication.slot_texts is None
    errors: list[str] = llm_log.messages(logging.ERROR)
    assert errors == [
        f"publish_duplicate_paragraph_detected lang=en source=primary_success description_chars={len(publication.description)}"
    ]


def test_a_cta_opener_blocks_the_publication(llm_log: LogCollector) -> None:
    """Призыв первым предложением абзаца из нескольких предложений хвост не снимает — его ловит проверка."""
    publication: MergePublication = publish(
        "Subscribe to our channel for updates and facts. Budget amendments passed.\n\nFacts about the vote.", sources=()
    )
    assert publication.has_opener_cta and publication.slot_texts is None
    assert llm_log.messages(logging.ERROR)[0].startswith("publish_opener_cta_detected lang=en source=primary_success ")


def test_no_description_text_reaches_the_log(llm_log: LogCollector) -> None:
    publish(
        f"Unique hook words about Brussels.\n\n\U0001F539 Distinct bullet about Kharkiv\n\n{HEADING}\nhttps://example.org\n\n"
        "Join us tonight and share. #tag"
    )
    joined: str = "\n".join(llm_log.messages())
    for fragment in ("Unique hook words", "Distinct bullet", "Join us tonight", "#tag"):
        assert fragment not in joined
