from __future__ import annotations

import logging

import pytest

from app.texts.source_link import LinkedText, SourceLink


def test_source_link_is_cleaned_and_youtube_is_shortened() -> None:
    assert SourceLink.of("https://example.com/page?utm_medium=email").url == "https://example.com/page"
    assert SourceLink.of("not-a-url").url is None
    assert SourceLink.of("https://[bad").url is None
    youtube: SourceLink = SourceLink.of("https://www.youtube.com/watch?v=abc123def45&si=tracking")
    assert youtube.url == "https://youtu.be/abc123def45" and not youtube.dropped_youtube
    assert youtube.is_youtube and not SourceLink.of("https://example.com").is_youtube


def test_youtube_link_without_an_id_is_dropped_and_logged_by_the_link(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        dropped: SourceLink = SourceLink.of("https://youtube.com/watch?v=short")
    assert dropped.url is None and dropped.dropped_youtube and not dropped.is_youtube
    assert caplog.messages == [
        "non_authoritative_youtube_tail_url_dropped reason=youtube_normalization_failed "
        "raw=https://youtube.com/watch?v=short"
    ]


def test_a_clean_link_writes_no_log_line(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.INFO):
        SourceLink.of("https://example.org")
    assert caplog.messages == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.org/?utm_source=x", "https://example.org"),
        ("https://www.youtube.com/watch?v=abc123def45", "https://youtu.be/abc123def45"),
        ("https://youtube.com/watch?v=short", None),         # YouTube без id — не ссылка видео
        ("example.org", None),
        ("", None),
    ],
)
def test_video_link_is_the_clean_link_or_the_short_youtube_link(raw: str, expected: str | None) -> None:
    assert SourceLink.of_video(raw).url == expected


def test_links_in_text_are_cleaned_and_the_changed_ones_named() -> None:
    text: str = "See https://example.org/?utm_source=x and https://example.org/page, then https://[bad here."
    linked: LinkedText = LinkedText.of(text)
    assert linked.text == "See https://example.org and https://example.org/page, then https://[bad here."
    assert linked.changed_links == ("https://example.org/?utm_source=x",)
    assert linked.change_count == 1
    assert LinkedText.of("") == LinkedText(text="", changed_links=())


def test_curly_braces_around_a_link_in_text_are_kept() -> None:
    assert LinkedText.of("Сайт https://site.org/?utm_source=x} тут").text == "Сайт https://site.org} тут"
