from __future__ import annotations

from app.llm.merges.blocks import DescriptionBlocks
from app.texts.description_marks import CtaLexicon

CTA: CtaLexicon = CtaLexicon.load()


def blocks(text: str) -> DescriptionBlocks:
    return DescriptionBlocks.of(text, CTA)


def test_full_description_splits_into_hook_theses_links_and_cta() -> None:
    parsed: DescriptionBlocks = blocks(
        "Hook sentence one.\n\n"
        "In this stream you'll see:\n🔹 first\n📌 second\n\n"
        "🌐 Official links:\nhttps://example.org\nhttps://example.com/\n\n"
        "Watch the stream and share your thoughts. #tag"
    )
    assert parsed.hook == "Hook sentence one."
    assert parsed.lead_in == "In this stream you'll see:"
    assert parsed.theses_lines == ("In this stream you'll see:", "🔹 first", "📌 second")
    assert parsed.links_heading == "🌐 Official links:"
    assert parsed.links_urls == ("https://example.org", "https://example.com/")
    assert parsed.cta == "Watch the stream and share your thoughts. #tag"


def test_hook_lead_in_bullets_links_and_cta_in_one_paragraph() -> None:
    parsed: DescriptionBlocks = blocks(
        "Hook line.\nLead in:\n🔹 one\n- two\n🌐 Links:\nhttps://a.org\nsome trailing words\nmore"
    )
    assert parsed.hook == "Hook line."
    assert parsed.lead_in == "Lead in:"
    assert parsed.theses_lines == ("Lead in:", "🔹 one", "- two")
    assert parsed.links_heading == "🌐 Links:"
    assert parsed.links_urls == ("https://a.org",)
    assert parsed.cta == "some trailing words more"


def test_lines_after_bullets_without_heading_become_cta() -> None:
    parsed: DescriptionBlocks = blocks("Hook.\n\n🔹 one\n🔹 two\nClosing   words here")
    assert parsed.theses_lines == ("🔹 one", "🔹 two")
    assert parsed.lead_in == ""
    assert parsed.cta == "Closing words here"


def test_second_bullets_paragraph_extends_theses() -> None:
    parsed: DescriptionBlocks = blocks("Hook.\n\nLead:\n🔹 one\n\nMore:\n🔹 two")
    assert parsed.theses_lines == ("Lead:", "🔹 one", "🔹 two")
    assert parsed.lead_in == "Lead:"


def test_without_bullets_second_paragraph_becomes_theses() -> None:
    parsed: DescriptionBlocks = blocks("First paragraph.\n\nSecond line one\nSecond line two\n\nThird paragraph.")
    assert parsed.hook == "First paragraph."
    assert parsed.theses_lines == ("Second line one", "Second line two")
    assert parsed.lead_in == "Second line one"
    assert parsed.cta == "Second line one Second line two"


def test_cta_paragraph_is_recognized_and_hook_falls_back_to_first_paragraph() -> None:
    parsed: DescriptionBlocks = blocks("Subscribe and leave a comment #tag")
    assert parsed.cta == "Subscribe and leave a comment #tag"
    assert parsed.hook == "Subscribe and leave a comment #tag"
    assert parsed.is_single_echo_cta is True


def test_empty_text_gives_empty_blocks() -> None:
    parsed: DescriptionBlocks = blocks("")
    assert parsed == DescriptionBlocks("", "", (), "", (), "")
    assert parsed.render() == ""


def test_render_joins_blocks_and_strips_the_root_url_slash() -> None:
    parsed: DescriptionBlocks = DescriptionBlocks(
        hook="Hook   with\nspaces",
        lead_in="",
        theses_lines=("Lead:", " ", "🔹 one "),
        links_heading="🌐 Links:",
        links_urls=("https://site.org/", "https://site.org/page/", " "),
        cta="Watch  now",
    )
    assert parsed.render() == (
        "Hook with spaces\n\nLead:\n🔹 one\n\n🌐 Links:\nhttps://site.org\nhttps://site.org/page/\n\nWatch now"
    )
