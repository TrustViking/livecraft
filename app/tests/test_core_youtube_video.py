from __future__ import annotations

import pytest

from app.core.youtube_video import YouTubeVideoId

VIDEO_ID: str = "dQw4w9WgXcQ"
OTHER_ID: str = "aB3_-xYz012"


def video_id_of(text: str) -> str | None:
    video: YouTubeVideoId | None = YouTubeVideoId.of(text)
    return video.value if video is not None else None


@pytest.mark.parametrize(
    "text",
    [
        f"https://youtu.be/{VIDEO_ID}",
        f"youtu.be/{VIDEO_ID}?si=abc",
        f"https://www.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/watch?v={VIDEO_ID}&t=42s",
        f"https://www.youtube.com/watch?feature=share&v={VIDEO_ID}",
        f"https://www.youtube.com/watch?feature=share&v={VIDEO_ID}&list=PL1",
        f"https://m.youtube.com/watch?v={VIDEO_ID}",
        f"https://www.youtube.com/shorts/{VIDEO_ID}",
        f"https://www.youtube.com/embed/{VIDEO_ID}",
        f"https://www.youtube.com/live/{VIDEO_ID}?feature=shared",
        f"HTTPS://WWW.YOUTUBE.COM/watch?v={VIDEO_ID}",
        VIDEO_ID,
        f"  {VIDEO_ID}  ",
        f"Стрим тут: https://youtu.be/{VIDEO_ID} — не пропустите",
    ],
)
def test_every_link_kind_gives_the_id_and_the_short_link(text: str) -> None:
    video: YouTubeVideoId | None = YouTubeVideoId.of(text)
    assert video == YouTubeVideoId(VIDEO_ID)
    assert video is not None and video.short_url == f"https://youtu.be/{VIDEO_ID}"


def test_the_watch_link_is_built_from_the_id() -> None:
    assert YouTubeVideoId(VIDEO_ID).watch_url == f"https://www.youtube.com/watch?v={VIDEO_ID}"


def test_of_two_links_the_earliest_wins_whatever_its_kind() -> None:
    first_watch: str = f"https://www.youtube.com/watch?v={VIDEO_ID} и https://youtu.be/{OTHER_ID}"
    first_short: str = f"https://youtu.be/{OTHER_ID} и https://www.youtube.com/watch?v={VIDEO_ID}"
    assert video_id_of(first_watch) == VIDEO_ID
    assert video_id_of(first_short) == OTHER_ID


@pytest.mark.parametrize(
    "link",
    [f"https://youtu.be/{VIDEO_ID}", f"https://www.youtube.com/watch?v={VIDEO_ID}", f"https://youtube.com/live/{VIDEO_ID}"],
)
def test_a_link_wins_over_an_earlier_bare_id(link: str) -> None:
    assert video_id_of(f"{OTHER_ID} {link}") == VIDEO_ID


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "https://youtu.be/dQw4w9WgXc",
        "https://youtu.be/short",
        f"x{VIDEO_ID}x",
        f"{VIDEO_ID}Q",
        "https://vimeo.com/123456789",
        "просто текст без ссылки",
    ],
)
def test_no_id_is_none(text: str) -> None:
    assert YouTubeVideoId.of(text) is None


def test_eleven_characters_inside_a_link_to_another_site_are_not_an_id() -> None:
    """Id берётся только из ссылки YouTube или из ячейки, которая целиком — id."""
    assert YouTubeVideoId.of("https://example.com/abcdefghijk") is None
    assert YouTubeVideoId.of("смотрите abcdefghijk сегодня") is None
    assert YouTubeVideoId.of("abcdefghijk") == YouTubeVideoId("abcdefghijk")
