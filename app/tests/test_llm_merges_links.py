from __future__ import annotations

import hashlib
import pathlib

from app.llm.merges.links import OFFICIAL_LINK_HINTS_RESOURCE, OfficialLinkHints, OfficialLinkSelection
from app.resources.loader import TextResource
from app.tests.test_llm_merges_source import merge_video

HINTS: OfficialLinkHints = OfficialLinkHints.load()
# Отпечаток файла restreamer `app\resources\text\lexicon_official_link_hints.txt` (35324e5): ресурс перенесён побайтно.
DONOR_HINTS_SHA256: str = "d000eb4738f32cffc387235315fe254857dd7fb03535a7479e7ef570d705e4d8"


def select(*descriptions: str) -> OfficialLinkSelection:
    return OfficialLinkSelection.of(list(descriptions), HINTS)


def test_hints_resource_is_the_donor_file_byte_for_byte() -> None:
    path: pathlib.Path = TextResource(OFFICIAL_LINK_HINTS_RESOURCE).path
    assert hashlib.sha256(path.read_bytes()).hexdigest() == DONOR_HINTS_SHA256
    assert "official" in HINTS.hints and "сайт" in HINTS.hints


def test_context_is_a_lowercase_substring_of_the_line() -> None:
    assert HINTS.has_context("  OFFICIAL Website: https://example.org")
    assert HINTS.has_context("Офіційний сайт ініціативи")
    assert not HINTS.has_context("Read more https://example.org")
    assert not HINTS.has_context("   ")


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
