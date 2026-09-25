from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.llm.merges.prompt_texts import MergePromptTexts
from app.llm.merges.source import MergeSource, PreparedSourceDescription
from app.sheets.plan import SheetRow
from app.sheets.rows import PlanRow
from app.sources.video import SourceVideo
from app.tests.conftest import ready_source

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
START: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
TEXTS: MergePromptTexts = MergePromptTexts.load()
HINTS: tuple[str, ...] = TEXTS.service_hints


def merge_video(row_number: int, title: str, description: str, language: str = "en") -> SourceVideo:
    """Годный источник слота без сети; ссылка своя на каждый ряд."""
    link: str = f"https://youtu.be/{row_number:011d}"
    row: SheetRow = SheetRow(row_number=row_number, link=link, date_raw="16.10.2026", time_raw="19:00")
    return ready_source(PlanRow.admitted(row, START, link), title, description, language)


# --- подготовка описания


def test_empty_description_prepares_to_nothing() -> None:
    assert PreparedSourceDescription.of("  \r\n ", HINTS) == PreparedSourceDescription(
        text="", raw_chars=0, urls_removed=0, hashtags_removed=0, service_paragraphs_dropped=0
    )


def test_description_keeps_full_text_without_links_hashtags_or_truncation() -> None:
    """Донор: test_merge_prompt_uses_clean_full_source_text_without_urls_hashtags_or_truncation (подготовка)."""
    text: str = (
        "Hook paragraph with concrete facts and named people. " + "A" * 2600 + "\n\n"
        "Main stream link https://youtu.be/aaaaaaaaaaa\n"
        "Official links:\nhttps://example.org/details\n\n"
        "Join and follow updates. #topic #update"
    )
    prepared: PreparedSourceDescription = PreparedSourceDescription.of(text, HINTS)
    assert "A" * 2600 in prepared.text
    assert "https://" not in prepared.text
    assert "#topic" not in prepared.text
    assert "Join and follow updates." not in prepared.text
    assert prepared.raw_chars == len(text)
    assert prepared.urls_removed == 2
    assert prepared.hashtags_removed == 2
    assert prepared.service_paragraphs_dropped == 1
    assert prepared.cleaned_chars == len(prepared.text)


def test_line_breaks_are_normalized_before_counting() -> None:
    prepared: PreparedSourceDescription = PreparedSourceDescription.of("First.\r\n\r\n\r\n\r\nSecond.", HINTS)
    assert prepared.text == "First.\n\nSecond."
    assert prepared.raw_chars == len("First.\n\nSecond.")


def test_paragraph_of_only_links_counts_as_dropped() -> None:
    prepared: PreparedSourceDescription = PreparedSourceDescription.of("Body text.\n\nhttps://a.example #tag", HINTS)
    assert prepared.text == "Body text."
    assert (prepared.urls_removed, prepared.hashtags_removed, prepared.service_paragraphs_dropped) == (1, 1, 1)


# --- источник в промте


def test_source_takes_title_row_and_prepared_description() -> None:
    source: MergeSource = MergeSource.of(merge_video(7, "  Title 1  ", "Paragraph one.\n\nParagraph two."), TEXTS)
    assert source.title == "Title 1"
    assert source.row_number == 7
    assert source.prompt_description == "Paragraph one.\n\nParagraph two."
    assert source.prompt_block(2) == "SOURCE 2\nTITLE: Title 1\nDESCRIPTION: Paragraph one.\n\nParagraph two."


def test_empty_description_becomes_no_description_in_prompt_but_not_in_quality_text() -> None:
    source: MergeSource = MergeSource.of(merge_video(2, "Title", "   "), TEXTS)
    assert source.prompt_description == TEXTS.no_description
    assert source.has_description is False
    assert source.quality_text == "Title"


def test_description_that_cleans_to_nothing_falls_back_in_prompt_only() -> None:
    source: MergeSource = MergeSource.of(merge_video(2, "Title", "https://only.link #tag"), TEXTS)
    assert source.description.text == ""
    assert source.prompt_description == TEXTS.no_description
    assert source.quality_text == "Title"


def test_quality_text_is_title_and_cleaned_description() -> None:
    source: MergeSource = MergeSource.of(merge_video(2, "Title", "Body https://x.example text."), TEXTS)
    assert source.quality_text == "Title\nBody text."


def test_log_line_has_counters_and_no_source_text() -> None:
    source: MergeSource = MergeSource.of(merge_video(9, "Secret title", "Private body https://x.example #tag"), TEXTS)
    line: str = source.log_line(1, "en")
    assert line == (
        "merge_source_text_prepared language=en source_index=1 row=9 raw_chars=35 cleaned_chars=12 "
        "urls_removed=1 hashtags_removed=1 service_paragraphs_dropped=0 hard_truncation=disabled"
    )
    assert "Private" not in line and "Secret" not in line
