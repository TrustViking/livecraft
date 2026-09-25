from __future__ import annotations

import pytest

from app.llm.merges.layout import DescriptionLayout, LayoutRecovery, TailBlock
from app.llm.merges.reject import MergeRejectCode

REALISTIC: str = (
    "Tonight we track the conference agenda and initiative updates with concrete facts.\n\n"
    "In this stream you'll see:\n🔹 conference timeline and priorities\n🎤 speaker remarks and context\n"
    "✅ practical next steps for viewers\n\n"
    "The second body paragraph keeps the legal and organizational context tied to the sources.\n\n"
    "The third body paragraph highlights what changed since the previous stream and why it matters.\n\n"
    "https://youtu.be/aaaaaaaaaaa\n\n"
    "https://www.youtube.com/watch?v=bbbbbbbbbbb\n\n"
    "🌐 Official links:\nhttps://interfaithconf.org/about\nhttps://spiritualdiplomats.org/resources\n\n"
    "#conference #initiative"
)


# --- донор: test_merge_contract_parser.py::test_tail_separation_recognizes_multiple_allowed_tail_blocks_in_order
def test_tail_blocks_are_recognized_in_order() -> None:
    layout: DescriptionLayout = DescriptionLayout.of(
        "Hook paragraph.\n\n"
        "In this stream you'll see:\n🔹 main point\n✅ practical follow-up\n\n"
        "https://youtu.be/aaaaaaaaaaa\n\n"
        "🌐 Official links:\nhttps://example.org\n\n"
        "#topic #update",
        max_body_paragraphs=4,
    )
    assert layout.body_paragraph_count_after_recovery == 2
    assert layout.tail_blocks == (TailBlock.YOUTUBE_LINKS, TailBlock.OFFICIAL_LINKS, TailBlock.HASHTAGS)


# --- донор: test_merge_contract_parser.py::test_realistic_merge_output_with_five_service_tail_paragraphs_is_accepted
def test_realistic_output_with_five_tail_paragraphs() -> None:
    layout: DescriptionLayout = DescriptionLayout.of(REALISTIC, max_body_paragraphs=4)
    assert layout.raw_paragraph_count == 8
    assert layout.body_paragraph_count_after_recovery == 4
    assert [block.value for block in layout.tail_blocks] == ["youtube_links", "youtube_links", "official_links", "hashtags"]
    assert layout.recovery is LayoutRecovery.NOT_NEEDED
    assert layout.full_text == REALISTIC


def test_tail_is_taken_only_from_the_end() -> None:
    layout: DescriptionLayout = DescriptionLayout.of("#tag\n\nBody one.\n\nBody two.", max_body_paragraphs=4)
    assert layout.tail_blocks == ()
    assert layout.body_paragraph_count == 3
    assert not layout.tail_detected


@pytest.mark.parametrize(
    ("paragraph", "block"),
    [
        ("#stream #topic", TailBlock.HASHTAGS),
        ("#a#b", None),
        ("# not", None),
        ("🌐 Official links:", TailBlock.OFFICIAL_LINKS),
        ("🌐 Official links:\nhttps://example.org\nhttp://x.org", TailBlock.OFFICIAL_LINKS),
        ("🌐 Official links:\nhttps://example.org\ntext", None),
        ("https://youtu.be/a\nhttps://www.youtube.com/watch?v=b", TailBlock.YOUTUBE_LINKS),
        ("https://youtu.be/a\nhttps://example.org", None),
        ("Plain paragraph.", None),
    ],
)
def test_tail_block_of_paragraph(paragraph: str, block: TailBlock | None) -> None:
    assert TailBlock.of(paragraph) is block


# --- донор: test_merge_contract_parser.py::test_body_only_recovery_accepts_near_good_body
def test_five_body_paragraphs_collapse_to_four() -> None:
    layout: DescriptionLayout = DescriptionLayout.of(
        "Paragraph one.\n\nParagraph two.\n\nParagraph three.\n\nParagraph four.\n\nParagraph five.\n\n#topic", 4
    )
    assert layout.recovery is LayoutRecovery.COLLAPSED
    assert layout.recovery_applied
    assert layout.body_paragraphs == ("Paragraph one.\nParagraph two.", "Paragraph three.", "Paragraph four.", "Paragraph five.")
    assert layout.full_text.endswith("\n\n#topic")


def test_more_than_four_extra_paragraphs_cannot_be_collapsed() -> None:
    text: str = "\n\n".join(f"Paragraph {index}." for index in range(1, 10))
    layout: DescriptionLayout = DescriptionLayout.of(text, 4)
    assert layout.recovery is LayoutRecovery.NOT_POSSIBLE
    assert layout.body_paragraph_count_after_recovery == 9
    assert not layout.recovery_applied


def test_single_paragraph_of_four_sentences_is_split_in_half() -> None:
    layout: DescriptionLayout = DescriptionLayout.of("One. Two! Three? Four… Five.", 4)
    assert layout.recovery is LayoutRecovery.SPLIT_SINGLE
    assert layout.body_paragraphs == ("One. Two!", "Three? Four… Five.")


def test_single_paragraph_of_three_sentences_stays() -> None:
    layout: DescriptionLayout = DescriptionLayout.of("One. Two. Three.", 4)
    assert layout.recovery is LayoutRecovery.NOT_NEEDED
    assert layout.body_paragraph_count_after_recovery == 1


def test_recovery_is_blocked_by_duplicate_paragraphs() -> None:
    repeated: str = "Same long text here with enough tokens to count."
    text: str = "\n\n".join([repeated, "Two.", "Three.", "Four.", repeated])
    layout: DescriptionLayout = DescriptionLayout.of(text, 4)
    assert layout.recovery is LayoutRecovery.BLOCKED
    assert layout.blocked_reason is MergeRejectCode.DUPLICATE_PARAGRAPH
    assert layout.body_paragraph_count_after_recovery == 5


def test_recovery_is_blocked_by_hook_echo() -> None:
    hook: str = "Tonight we map how the sanctions vote changes transport risk windows for the next 48 hours."
    text: str = "\n\n".join([hook, hook + " Extra.", "Three.", "Four.", "Five."])
    assert DescriptionLayout.of(text, 4).blocked_reason is MergeRejectCode.DUPLICATE_PARAGRAPH


def test_duplicates_within_a_valid_body_do_not_block() -> None:
    repeated: str = "Same long text here with enough tokens to count."
    layout: DescriptionLayout = DescriptionLayout.of(f"{repeated}\n\n{repeated}", 4)
    assert layout.blocked_reason is None
    assert layout.recovery is LayoutRecovery.NOT_NEEDED


def test_only_tail_leaves_an_empty_body() -> None:
    layout: DescriptionLayout = DescriptionLayout.of("#a #b", 4)
    assert layout.body_text == "" and layout.full_text == "#a #b"
    assert layout.body_paragraph_count == 0


def test_crlf_is_normalized() -> None:
    layout: DescriptionLayout = DescriptionLayout.of("One.\r\n\r\nTwo.\r\n\r\n#t", 4)
    assert layout.full_text == "One.\n\nTwo.\n\n#t"


def test_log_fields_have_the_donor_keys_and_no_text() -> None:
    layout: DescriptionLayout = DescriptionLayout.of(REALISTIC, 4)
    assert layout.log_fields == (
        "raw_paragraph_count=8 tail_separated=yes tail_blocks=youtube_links,youtube_links,official_links,hashtags "
        "body_paragraph_count=4 recovery_applied=no body_paragraph_count_after_recovery=4"
    )
    assert "conference" not in repr(layout)
