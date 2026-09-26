from __future__ import annotations

import logging
from collections.abc import Iterator

import pytest

from app.llm.merges.links import (
    AuthoritativeLinks,
    LinkCandidate,
    OfficialLinkHints,
    OfficialLinkSelection,
    RankedLinks,
    SourceDescriptionLines,
    TextLinks,
)
from app.observability.log_event import LogArea
from app.sources.video import SourceVideo
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.merges import merge_video

HINTS: OfficialLinkHints = OfficialLinkHints.load()


def select(*descriptions: str) -> OfficialLinkSelection:
    return OfficialLinkSelection.of(SourceDescriptionLines.of(descriptions), HINTS)


def test_the_hints_of_the_answer_check_name_official_pages() -> None:
    assert "official" in HINTS.hints.phrases and "сайт" in HINTS.hints.phrases


def test_context_is_a_lowercase_substring_of_the_line() -> None:
    assert HINTS.has_context("  OFFICIAL Website: https://example.org")
    assert HINTS.has_context("Офіційний сайт ініціативи")
    assert not HINTS.has_context("Read more https://example.org")
    assert not HINTS.has_context("   ")


def test_publish_context_is_the_links_heading_or_its_own_hint() -> None:
    assert HINTS.publish_hints.phrases == ("official", "resource", "resources", "details", "site", "website")
    assert HINTS.has_publish_context("More DETAILS https://example.org")
    assert HINTS.has_publish_context("\U0001F310 Links:")
    assert not HINTS.has_publish_context("Офіційний сайт https://example.org")     # подсказки проверки ответа — не эти


def test_the_description_lines_keep_the_source_of_each_line() -> None:
    lines: SourceDescriptionLines = SourceDescriptionLines.of(("one\r\n  two  ", "three"))
    assert [(line.text, line.source_index) for line in lines.lines] == [("one", 0), ("two", 0), ("three", 1)]


def test_ranking_is_by_score_and_then_by_order() -> None:
    ranked: RankedLinks = RankedLinks(
        (
            LinkCandidate("http://alpha.org/p", has_context=False, index=0),
            LinkCandidate("https://bravo.org/p", has_context=False, index=1),
            LinkCandidate("https://charlie.org/p", has_context=False, index=2),
            LinkCandidate("https://delta.org/p", has_context=True, index=3),
        )
    )
    assert ranked.urls == ("https://delta.org/p", "https://bravo.org/p", "https://charlie.org/p", "http://alpha.org/p")


def test_no_links_gives_an_empty_selection() -> None:
    assert select("", "Just text without links.") == OfficialLinkSelection(found_in_sources=0, kept_links=())


def test_youtube_links_are_not_candidates() -> None:
    selection: OfficialLinkSelection = select(
        "https://youtu.be/aaaaaaaaaaa https://www.youtube.com/watch?v=bbbbbbbbbbb https://m.youtube.com/live/x"
    )
    assert selection == OfficialLinkSelection(found_in_sources=0, kept_links=())


def test_links_are_cleaned_before_counting_and_bad_ones_skipped() -> None:
    selection: OfficialLinkSelection = select("(https://example.org/about?utm_source=x). ftp://files.org https://[bad")
    assert selection == OfficialLinkSelection(found_in_sources=1, kept_links=("https://example.org/about",))


def test_https_beats_http() -> None:
    selection: OfficialLinkSelection = select("http://alpha.org/page\nhttps://bravo.org/page")
    assert selection.kept_links == ("https://bravo.org/page", "http://alpha.org/page")


def test_official_context_in_the_line_raises_the_score() -> None:
    selection: OfficialLinkSelection = select("Read https://alpha.org/page\nOfficial website: https://bravo.org/page")
    assert selection.kept_links[0] == "https://bravo.org/page"


def test_frequent_domain_raises_the_score() -> None:
    selection: OfficialLinkSelection = select(
        "https://alpha.org/one https://bravo.org/x1\nhttps://bravo.org/x2 https://bravo.org/x3"
    )
    assert selection.found_in_sources == 4
    assert selection.kept_links[0] == "https://bravo.org/x1"
    assert "https://alpha.org/one" not in selection.kept_links


def test_query_lowers_the_score() -> None:
    selection: OfficialLinkSelection = select("https://alpha.org/page?id=1\nhttps://bravo.org/page")
    assert selection.kept_links == ("https://bravo.org/page", "https://alpha.org/page?id=1")


def test_shorter_link_wins_on_length() -> None:
    long_link: str = "https://alpha.org/" + "segment/" * 12
    selection: OfficialLinkSelection = select(f"{long_link}\nhttps://bravo.org/p")
    assert selection.kept_links[0] == "https://bravo.org/p"


def test_equal_score_keeps_the_earlier_link_first() -> None:
    selection: OfficialLinkSelection = select("https://alpha.org/p\nhttps://bravo.org/p")
    assert selection.kept_links == ("https://alpha.org/p", "https://bravo.org/p")


def test_duplicates_by_key_are_kept_once() -> None:
    selection: OfficialLinkSelection = select("https://www.alpha.org/uk https://alpha.org/ https://alpha.org/en/")
    assert selection.found_in_sources == 3
    assert len(selection.kept_links) == 1


def test_no_more_than_three_links_are_kept() -> None:
    selection: OfficialLinkSelection = select("https://a.org/1 https://b.org/1 https://c.org/1", "https://d.org/1")
    assert selection.found_in_sources == 4
    assert len(selection.kept_links) == 3


def test_context_is_taken_only_from_the_line_of_the_link() -> None:
    selection: OfficialLinkSelection = select("Official site\rhttps://alpha.org/p\r\nOfficial: https://bravo.org/p")
    assert selection.kept_links == ("https://bravo.org/p", "https://alpha.org/p")


def test_selection_for_slot_sources_reads_raw_video_descriptions() -> None:
    sources = [merge_video(1, "One", "Official site: https://alpha.org"), merge_video(2, "Two", "")]
    assert OfficialLinkSelection.for_sources(sources, HINTS) == select("Official site: https://alpha.org", "")


# --- официальные ссылки описания эфира после санации


def source_with(description: str, row: int = 2, title: str = "Source title") -> SourceVideo:
    return merge_video(row, title, description)


@pytest.fixture
def llm_log() -> Iterator[LogCapture]:
    with LogCapture.on(LogArea.LLM, logging.INFO) as capture:
        yield capture


def authoritative(*descriptions: str, tail: tuple[str, ...] = (), malformed: int = 0) -> AuthoritativeLinks:
    sources: tuple[SourceVideo, ...] = tuple(source_with(text, index + 2) for index, text in enumerate(descriptions))
    return AuthoritativeLinks.of("en", sources, TextLinks(tail, malformed), HINTS)


def test_root_and_language_path_of_one_site_are_one_link() -> None:
    links: AuthoritativeLinks = authoritative("Stream content here.\nhttps://allatra.org/\nhttps://allatra.org/uk")
    assert links.urls == ("https://allatra.org",) and links.duplicate_urls_removed == 1


def test_context_https_domain_frequency_query_and_length_rank_the_links() -> None:
    links: AuthoritativeLinks = authoritative(
        "Watch http://plain.example/a\nOfficial site https://ctx.example/page\nhttps://freq.example/1 https://freq.example/2\n"
        "https://query.example/?id=1"
    )
    assert links.urls[0] == "https://ctx.example"
    assert links.urls[1] == "https://freq.example"
    assert len(links.urls) == 3 and links.emitted_source_video_urls == 3


def test_at_most_three_source_links_then_every_new_tail_link() -> None:
    links: AuthoritativeLinks = authoritative(
        "https://a.example https://b.example https://c.example https://d.example",
        tail=("https://e.example/x", "https://f.example", "https://a.example/uk", "https://youtu.be/aaaaaaaaaaa", "https://[bad"),
        malformed=2,
    )
    assert links.urls[3:] == ("https://e.example", "https://f.example")
    assert links.emitted_source_video_urls == 3 and len(links.urls) == 5
    assert len(links.text.preserved) == 3 and links.duplicate_urls_removed == 1
    assert links.text.youtube_count == 1 and links.text.malformed_dropped == 3


def test_the_own_video_link_of_a_source_is_youtube_and_never_an_official_link() -> None:
    """Ссылка ряда — всегда видео YouTube: ссылка самого видео в официальные не идёт."""
    links: AuthoritativeLinks = AuthoritativeLinks.of("en", (source_with("", title="Official conference"),), TextLinks(()), HINTS)
    assert links.urls == () and links.emitted_source_video_urls == 0


def test_youtube_links_of_descriptions_are_counted_for_recommended_materials() -> None:
    links: AuthoritativeLinks = authoritative(
        "https://youtu.be/aaaaaaaaaaa\nhttps://youtu.be/ccccccccccc",
        "https://www.youtube.com/watch?v=aaaaaaaaaaa&feature=share\nhttps://youtu.be/bbbbbbbbbbb",
    )
    assert (links.raw_youtube_urls_found, links.deduped_youtube_candidates, links.repeated_youtube_candidates) == (4, 3, 1)
    assert links.urls == ()


def test_the_log_lines_name_what_was_selected(llm_log: LogCapture) -> None:
    links: AuthoritativeLinks = authoritative("https://example.org", tail=("https://[bad",), malformed=1)
    texts: tuple[str, ...] = tuple(event.text for event in links.events)
    assert llm_log.messages() == list(texts)
    assert texts == (
        "merged_source_urls_built lang=en inspected=1 emitted=1 selected_youtube_urls=0 deduped=0 "
        "preserved_non_youtube_tail_urls=0 raw_youtube_urls_found=0 deduped_youtube_candidates=0 "
        "repeated_youtube_candidates=0 ignored_llm_youtube_urls=0 "
        "source_urls_mode=authoritative_non_youtube_from_inputs_plus_script_selected_recommended_materials",
        "merged_source_urls_cleaned lang=en malformed_tail_urls_dropped=2",
    )
    assert len(authoritative("text").events) == 1


def test_a_bad_address_in_a_source_description_is_not_a_link() -> None:
    assert authoritative("See https://[bad and https://example.org").urls == ("https://example.org",)
