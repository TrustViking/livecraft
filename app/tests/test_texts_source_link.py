from __future__ import annotations

import logging

import pytest

from app.texts.source_link import SourceLink


def test_source_link_is_cleaned_and_youtube_is_shortened() -> None:
    assert SourceLink.of("https://example.com/page?utm_medium=email").url == "https://example.com/page"
    assert SourceLink.of("not-a-url").url is None
    assert SourceLink.of("https://[bad").url is None
    youtube: SourceLink = SourceLink.of("https://www.youtube.com/watch?v=abc123def45&si=tracking")
    assert youtube.url == "https://youtu.be/abc123def45" and not youtube.dropped_youtube
    assert youtube.is_youtube and not SourceLink.of("https://example.com").is_youtube


@pytest.mark.parametrize(
    ("raw", "url"),
    [
        ("https://www.facebook.com/reel/123456789012..", None),
        ("https://www.facebook.com/groups/1234567890...", None),
        ("https://example.org/page…", None),
        ("(https://example.org/page…)", None),
        ("https://example.org.", "https://example.org"),
        ("https://example.org/page,", "https://example.org/page"),
        ("https://example.org/page;", "https://example.org/page"),
        ("(https://example.org/page?utm_source=x).", "https://example.org/page"),
        ("https://example.org/page", "https://example.org/page"),
        ("https://clinic.example.org/dr-name/", "https://clinic.example.org/dr-name"),
        ("(https://www.instagram.com/example_profile/).", "https://www.instagram.com/example_profile"),
    ],
)
def test_source_link_is_the_bare_address_and_a_truncated_one_is_dropped(raw: str, url: str | None) -> None:
    """В описание уходит сам адрес: без обрамления и знака препинания после него; оборванный многоточием — никуда."""
    assert SourceLink.of(raw).url == url


def test_truncated_youtube_link_is_dropped_before_shortening() -> None:
    link: SourceLink = SourceLink.of("https://www.youtube.com/watch?v=abc123def45...")
    assert link.url is None and not link.dropped_youtube


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

