"""Блоки «🌐 …:» с официальными ссылками в ответе модели (донор: test_merged_publish_payload_sanitation.py)."""
from __future__ import annotations

from app.texts.official_links import OfficialLinksBlocks, official_link_urls

HEADING: str = "\U0001F310 Official links:"


def test_text_without_blocks_is_kept_as_is() -> None:
    blocks: OfficialLinksBlocks = OfficialLinksBlocks.of("Body paragraph.\n\nSecond paragraph.")
    assert blocks == OfficialLinksBlocks(cleaned_text="Body paragraph.\n\nSecond paragraph.")
    assert OfficialLinksBlocks.of("  ") == OfficialLinksBlocks(cleaned_text="")


def test_heading_with_its_own_links_is_taken_out() -> None:
    blocks: OfficialLinksBlocks = OfficialLinksBlocks.of(
        f"Body paragraph.\n\n{HEADING}\nhttps://example.org/official\nhttps://allatra.org/resource\n\nClosing words."
    )
    assert blocks.cleaned_text == "Body paragraph.\n\nClosing words."
    assert blocks.heading_found and blocks.empty_blocks_suppressed == 0
    assert blocks.source_urls == ("https://example.org/official", "https://allatra.org/resource")


def test_heading_takes_the_next_paragraph_of_links() -> None:
    blocks: OfficialLinksBlocks = OfficialLinksBlocks.of(
        f"Body paragraph.\n\n{HEADING}\n\nhttps://example.org/official?utm_source=yt\n\nClosing words."
    )
    assert blocks.cleaned_text == "Body paragraph.\n\nClosing words."
    assert blocks.source_urls == ("https://example.org/official",)


def test_empty_heading_is_suppressed_and_counted() -> None:
    blocks: OfficialLinksBlocks = OfficialLinksBlocks.of(f"Body paragraph.\n\n{HEADING}\n\nJoin us tonight.")
    assert blocks.cleaned_text == "Body paragraph.\n\nJoin us tonight."
    assert blocks.heading_found and blocks.source_urls == () and blocks.empty_blocks_suppressed == 1


def test_youtube_and_incomplete_links_do_not_enter_the_block() -> None:
    blocks: OfficialLinksBlocks = OfficialLinksBlocks.of(
        f"Body.\n\n{HEADING}\nhttps://youtu.be/ccccccccccc\nhttps://[bad\nhttps://example.org\n\n{HEADING}\n\n"
        "https://youtu.be/ddddddddddd"
    )
    # Второй заголовок: в следующем абзаце только YouTube — ссылок блока нет, заголовок подавлен, абзац остаётся в тексте
    # (его ссылку потом снимает хвост), как у донора.
    assert blocks.cleaned_text == "Body.\n\nhttps://youtu.be/ddddddddddd"
    assert blocks.source_urls == ("https://example.org",)
    assert blocks.empty_blocks_suppressed == 1


def test_a_block_with_a_non_link_line_gives_no_links() -> None:
    assert official_link_urls(["https://example.org", "some words"]) == ()
    assert official_link_urls(["", "https://example.org/?utm_source=x", "https://example.org"]) == ("https://example.org",)
    blocks: OfficialLinksBlocks = OfficialLinksBlocks.of(f"Body.\n\n{HEADING}\nhttps://example.org\nsome words")
    assert blocks.cleaned_text == "Body." and blocks.source_urls == () and blocks.empty_blocks_suppressed == 1


def test_a_heading_without_the_globe_is_body_text() -> None:
    blocks: OfficialLinksBlocks = OfficialLinksBlocks.of("Body.\n\nOfficial links:\nhttps://example.org")
    assert blocks.cleaned_text == "Body.\n\nOfficial links:\nhttps://example.org" and not blocks.heading_found
