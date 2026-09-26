"""Рекомендуемые материалы: кандидаты из описаний источников, порядок, порог, проверка языка и блок в описании."""
from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from app.llm.merges.links import SourceDescriptionLines, SourceDescriptionLinks
from app.llm.merges.merge_rules import MergeRules
from app.llm.merges.publication import MergePublication, PublicationSlot
from app.llm.merges.recommended import RecommendedCandidate, RecommendedCandidates, RecommendedMaterials
from app.observability.log_event import LogArea
from app.sources.metadata import SourceMetadata
from app.sources.video import SourceCatalog, SourceVideo
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.merges import merge_video
from app.tests.fixtures.sources import stub_calls, stub_catalog, video_metadata
from app.texts.composer import RecommendedEntry
from app.texts.similarity import StopWords

RULES: MergeRules = MergeRules.load()
STOP_WORDS: StopWords = RULES.lexicons.stop_words
VIDEO_A: str = "https://youtu.be/recommend0A"
VIDEO_B: str = "https://youtu.be/recommend0B"
VIDEO_C: str = "https://youtu.be/recommend0C"
VIDEO_D: str = "https://youtu.be/recommend0D"
VIDEO_E: str = "https://youtu.be/recommend0E"
# Ответ модели: название и тело. Слова темы — climate, budget, vote, council, debates, amendments, tonight.
SUMMARY: str = "Climate budget vote\nCouncil debates climate budget amendments tonight."
NEUTRAL_TITLE: str = "Evening newsroom"
ANSWER_TITLE: str = "Climate budget vote"
ANSWER_BODY: str = (
    "Council debates climate budget amendments tonight, district by district.\n\n"
    "Deputies compare transport, heating and park spending before a final vote."
)
EN_TEXT: str = "A detailed English report on how council budget and climate plans affect every district this year."
UK_TEXT: str = "Детальний український репортаж про бюджет міста та кліматичні плани для кожного району цього року."
DE_TEXT: str = "Ein ausführlicher deutscher Bericht darüber, wie Haushalt und Klimapläne jeden Bezirk in diesem Jahr betreffen."


@pytest.fixture
def llm_log() -> Iterator[LogCapture]:
    with LogCapture.on(LogArea.LLM, logging.INFO) as capture:
        yield capture


def sources_of(*descriptions: str, title: str = NEUTRAL_TITLE, language: str = "en") -> tuple[SourceVideo, ...]:
    """Источники слота с этими описаниями — ряды с первого, ссылка ряда `https://youtu.be/<номер ряда>`."""
    return tuple(merge_video(index + 1, title, text, language) for index, text in enumerate(descriptions))


def candidates_of(sources: tuple[SourceVideo, ...], summary: str = SUMMARY) -> RecommendedCandidates:
    """Кандидаты путём программы: ссылки описаний источников после чистки, затем отбор кандидатов."""
    links: SourceDescriptionLinks = SourceDescriptionLinks.of(SourceDescriptionLines.of_sources(sources))
    return RecommendedCandidates.of(links, sources, summary, STOP_WORDS)


def candidates(*descriptions: str) -> RecommendedCandidates:
    return candidates_of(sources_of(*descriptions))


def by_link(found: RecommendedCandidates) -> dict[str, RecommendedCandidate]:
    return {candidate.link: candidate for candidate in found.candidates}


def en_video(url: str, title: str) -> SourceMetadata:
    return video_metadata(url, title, f"{title}. {EN_TEXT}", "en")


def uk_video(url: str, title: str) -> SourceMetadata:
    return video_metadata(url, title, UK_TEXT, "uk")


def candidate(source_hits: int = 1, overlap: int = 0, occurrences: int = 1, first_seen: int = 0) -> RecommendedCandidate:
    return RecommendedCandidate(VIDEO_A, source_hits, occurrences, overlap, first_seen)


# --- правило 1: кто кандидат


def test_a_candidate_is_a_youtube_video_of_a_description_but_never_a_video_of_the_slot() -> None:
    """Видео самого источника эфир и так показывает; канал, плейлист и чужой сайт — не видео YouTube."""
    found: RecommendedCandidates = candidates(
        f"Climate budget {VIDEO_A}\nChannel https://www.youtube.com/@newsroom\n"
        "Playlist https://www.youtube.com/playlist?list=PL0123456789\nSite https://example.org",
        "Previous part https://www.youtube.com/watch?v=00000000001&t=5s",
    )
    assert [item.link for item in found.candidates] == [VIDEO_A]
    assert found.raw_youtube == 2


# --- правило 2: контекст и слова


def test_the_context_is_the_cleaned_line_or_the_source_title_and_stop_words_do_not_count() -> None:
    sources: tuple[SourceVideo, ...] = sources_of(
        f"{VIDEO_A}\nWatch this stream #climate {VIDEO_B}\nClimate talks recap: {VIDEO_C} #budget", title="Budget hearing"
    )
    found: dict[str, RecommendedCandidate] = by_link(candidates_of(sources, SUMMARY + " stream"))
    assert found[VIDEO_A].overlap == 1          # строка — одна ссылка: контекст — название источника, «budget»
    assert found[VIDEO_B].overlap == 0          # watch, this, stream — частые слова; хештег не контекст
    assert found[VIDEO_C].overlap == 1          # climate; хештег #budget не контекст


def test_the_words_of_a_candidate_are_all_its_mentions() -> None:
    found: RecommendedCandidates = candidates(
        f"Climate recap {VIDEO_A}", f"Council vote {VIDEO_A}\n{VIDEO_A} amendments"
    )
    only: RecommendedCandidate = found.candidates[0]
    assert (only.source_hits, only.occurrences, only.overlap, only.first_seen) == (2, 3, 4, 0)
    assert found.summary_words == 7


def test_the_answer_words_are_its_title_and_body() -> None:
    sources: tuple[SourceVideo, ...] = sources_of(f"Heating spending {VIDEO_A}")
    assert candidates_of(sources, "Heating\nPark spending").candidates[0].overlap == 2
    assert candidates_of(sources, "Park").candidates[0].overlap == 0


# --- правило 3: порядок


def test_more_sources_then_more_words_then_more_mentions_then_earlier() -> None:
    found: RecommendedCandidates = candidates(
        f"Climate budget {VIDEO_A}\nCooking {VIDEO_B}\nClimate budget {VIDEO_C}\nCouncil climate budget {VIDEO_D}\n"
        f"Climate budget {VIDEO_E}\nClimate budget again {VIDEO_C}",
        f"Cooking {VIDEO_B}",
    )
    assert [item.link for item in found.candidates] == [VIDEO_B, VIDEO_D, VIDEO_C, VIDEO_A, VIDEO_E]
    assert [item.first_seen for item in found.candidates] == [1, 3, 2, 0, 4]


# --- правило 4: порог


@pytest.mark.parametrize(
    ("few_sources", "item", "expected"),
    [
        (True, candidate(overlap=1), True),
        (True, candidate(source_hits=2, overlap=0), False),
        (False, candidate(source_hits=2, overlap=0), True),
        (False, candidate(overlap=2), True),
        (False, candidate(overlap=1), False),
    ],
)
def test_the_threshold_depends_on_the_number_of_sources(
    few_sources: bool, item: RecommendedCandidate, expected: bool
) -> None:
    assert item.passes(few_sources) is expected


def test_two_sources_are_few_three_are_not() -> None:
    assert candidates("a", "b").few_sources
    assert not candidates("a", "b", "c").few_sources


# --- правило 5: проверка языка и первые два годных


def test_the_first_two_fitting_videos_are_taken_and_a_video_under_the_threshold_is_never_fetched(
    llm_log: LogCapture,
) -> None:
    found: RecommendedCandidates = candidates(
        f"Climate budget {VIDEO_A}\nCouncil climate budget {VIDEO_B}\nClimate budget {VIDEO_C}\nClimate budget {VIDEO_D}\n"
        f"Cooking {VIDEO_E}",
        "Second source",
        "Third source",
    )
    catalog: SourceCatalog = stub_catalog(
        en_video(VIDEO_A, "Budget explained"), uk_video(VIDEO_B, "Бюджет міста"), en_video(VIDEO_C, "Climate plan"),
        en_video(VIDEO_D, "Council vote"), en_video(VIDEO_E, "Cooking show"),
    )
    materials: RecommendedMaterials = RecommendedMaterials.select(found, "en", catalog)
    assert materials.entries == (
        RecommendedEntry("Budget explained", VIDEO_A), RecommendedEntry("Climate plan", VIDEO_C)
    )
    assert stub_calls(catalog) == [VIDEO_B, VIDEO_A, VIDEO_C]
    assert (materials.checked, materials.fallback_applied) == (3, False)
    assert (
        f"recommended_candidate_language_filtered url={VIDEO_B} target=en fit=other_language detected=uk"
        in llm_log.messages()
    )


def test_a_video_without_data_is_filtered_with_no_detected_language(llm_log: LogCapture) -> None:
    materials: RecommendedMaterials = RecommendedMaterials.select(candidates(f"Climate {VIDEO_A}"), "en", stub_catalog())
    assert materials.entries == () and materials.checked == 1
    assert llm_log.messages()[0] == (
        f"recommended_candidate_language_filtered url={VIDEO_A} target=en fit=no_data detected=-"
    )


def test_a_video_with_disputed_language_is_not_taken(llm_log: LogCapture) -> None:
    """Язык видео en, а текст украинский: сигналы спорят — такое видео не рекомендуется даже слоту en."""
    disputed: SourceMetadata = video_metadata(VIDEO_A, "Бюджет міста", UK_TEXT, "en")
    materials: RecommendedMaterials = RecommendedMaterials.select(candidates(f"Climate {VIDEO_A}"), "en", stub_catalog(disputed))
    assert materials.entries == ()
    assert any(" fit=ambiguous " in line for line in llm_log.messages())


# --- правило 6: запасное видео из двух источников


def test_without_a_taken_video_the_first_fitting_video_of_both_sources_is_the_fallback(llm_log: LogCapture) -> None:
    found: RecommendedCandidates = candidates(f"Cooking {VIDEO_B}\nClimate {VIDEO_A}", f"Recipes {VIDEO_B}")
    catalog: SourceCatalog = stub_catalog(uk_video(VIDEO_A, "Бюджет міста"), en_video(VIDEO_B, "Kitchen talk"))
    materials: RecommendedMaterials = RecommendedMaterials.select(found, "en", catalog)
    assert [item.link for item in found.passing] == [VIDEO_A]
    assert materials.entries == (RecommendedEntry("Kitchen talk", VIDEO_B),) and materials.fallback_applied
    assert stub_calls(catalog) == [VIDEO_A, VIDEO_B]
    assert f"recommended_materials_fallback_applied url={VIDEO_B} source_hits=2 overlap=0" in llm_log.messages()


def test_the_fallback_does_not_check_a_video_again() -> None:
    found: RecommendedCandidates = candidates(f"Climate {VIDEO_A}", f"Budget {VIDEO_A}")
    catalog: SourceCatalog = stub_catalog(uk_video(VIDEO_A, "Бюджет міста"))
    materials: RecommendedMaterials = RecommendedMaterials.select(found, "en", catalog)
    assert materials.entries == () and not materials.fallback_applied
    assert stub_calls(catalog) == [VIDEO_A]


# --- правило 7: запись и строки лога


def test_the_candidates_line_counts_every_stage(llm_log: LogCapture) -> None:
    found: RecommendedCandidates = candidates(f"Climate {VIDEO_A}\nCooking {VIDEO_B}", f"Cooking {VIDEO_B}")
    materials: RecommendedMaterials = RecommendedMaterials.select(found, "en", stub_catalog(en_video(VIDEO_A, "Budget")))
    assert materials.entries == (RecommendedEntry("Budget", VIDEO_A),)
    assert llm_log.messages() == [
        "recommended_materials_candidates_built lang=en summary_words=7 raw_youtube_urls_found=3 candidates=2 "
        "repeated=1 passing=1 checked=1 selected=1 fallback=no"
    ]


def publish(
    sources: tuple[SourceVideo, ...], catalog: SourceCatalog, language: str = "en", body: str = ANSWER_BODY
) -> MergePublication:
    return MergePublication.of(ANSWER_TITLE, body, PublicationSlot(language, sources, RULES, catalog))


def applied_line(log: LogCapture) -> str:
    return next(line for line in log.messages() if line.startswith("publish_sanitation_applied=yes "))


def test_the_sanitation_line_names_the_recommended_block(llm_log: LogCapture) -> None:
    sources: tuple[SourceVideo, ...] = sources_of(f"Climate budget {VIDEO_A}\nCooking {VIDEO_B}", f"Cooking {VIDEO_B}")
    publish(sources, stub_catalog(en_video(VIDEO_A, "Budget explained")))
    line: str = applied_line(llm_log)
    assert (
        "raw_youtube_urls_found=3 deduped_youtube_candidates=2 repeated_youtube_candidates=1 "
        "recommended_materials_final_count=1 recommended_materials_block=emitted"
    ) in line
    built: str = next(line for line in llm_log.messages() if line.startswith("merged_source_urls_built "))
    assert "youtube_urls_found" not in built and "source_urls_mode" not in built and "selected_youtube" not in built


def test_without_a_fitting_video_there_is_no_block(llm_log: LogCapture) -> None:
    publication: MergePublication = publish(sources_of(f"Climate budget {VIDEO_A}"), stub_catalog())
    assert "Recommended materials:" not in publication.description
    assert "recommended_materials_final_count=0 recommended_materials_block=absent" in applied_line(llm_log)


# --- правило 8: место и заголовок блока


def test_the_block_goes_after_the_body_and_before_the_official_links() -> None:
    sources: tuple[SourceVideo, ...] = sources_of(f"Climate budget {VIDEO_A}")
    publication: MergePublication = publish(
        sources, stub_catalog(en_video(VIDEO_A, "Budget explained")), body=f"{ANSWER_BODY}\n\nhttps://example.org/page"
    )
    assert publication.description == (
        f"{publication.body.text}\n\nRecommended materials:\n\n✅ Budget explained\n👉 {VIDEO_A}\n\n"
        "\U0001F310 Official links:\nhttps://example.org"
    )
    assert publication.layout == "body_blank_recommended_materials_blank_official_links"


def test_the_heading_is_in_the_slot_language() -> None:
    sources: tuple[SourceVideo, ...] = sources_of(f"Бюджет {VIDEO_A}", language="uk")
    publication: MergePublication = publish(
        sources, stub_catalog(uk_video(VIDEO_A, "Бюджет міста")), "uk", "Бюджет міста та кліматичні плани.\n\nДепутати голосують."
    )
    assert "Рекомендовані матеріали:\n\n✅ Бюджет міста\n👉 " + VIDEO_A in publication.description


def test_a_language_outside_the_headings_gets_the_english_heading_and_a_log_line() -> None:
    sources: tuple[SourceVideo, ...] = sources_of(f"Haushalt Klima {VIDEO_A}", language="de")
    german: SourceMetadata = video_metadata(VIDEO_A, "Haushalt und Klima", DE_TEXT, "de")
    with LogCapture.on(LogArea.TEXTS, logging.INFO) as texts_log:
        publication: MergePublication = publish(
            sources, stub_catalog(german), "de", "Haushalt und Klima im Stadtrat.\n\nDie Abgeordneten stimmen ab."
        )
    assert "Recommended materials:\n\n✅ Haushalt und Klima\n👉 " + VIDEO_A in publication.description
    assert "heading_fallback_en kind=recommended_materials language=de" in texts_log.messages()


# --- правило 9: ссылки YouTube ответа модели


def test_youtube_links_of_the_answer_are_neither_published_nor_checked(llm_log: LogCapture) -> None:
    catalog: SourceCatalog = stub_catalog(en_video(VIDEO_A, "Budget explained"))
    publication: MergePublication = publish(sources_of("Plain description"), catalog, body=f"{ANSWER_BODY}\n\n{VIDEO_A}")
    assert "youtu" not in publication.description and stub_calls(catalog) == []
    assert publication.body.sanitized.tail_layout == "body"
    assert "ignored_llm_youtube_urls=1" in applied_line(llm_log)
