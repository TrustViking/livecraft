from __future__ import annotations

import pytest

from app.core.url_text import (
    SOCIAL_PLATFORM_HOSTS,
    TRACKING_QUERY_KEYS,
    YOUTUBE_HOSTS,
    SourceUrl,
    canonical_link_key,
    dedupe_nonempty,
    is_complete_source_url,
    is_social_platform_host,
    is_youtube_host,
    is_youtube_url,
    normalize_display_url,
    normalize_link_candidate,
    normalize_official_link_display,
    sanitize_url,
    sanitize_urls_in_text,
    split_url,
    strip_tracking_params,
)


@pytest.mark.parametrize("host", ["youtu.be", "www.youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"])
def test_youtube_hosts_are_recognized_in_any_case(host: str) -> None:
    assert is_youtube_host(host)
    assert is_youtube_host(f"  {host.upper()} ")


@pytest.mark.parametrize("host", ["music.youtube.com", "youtube.org", "example.org", "", "youtu.be:443"])
def test_other_hosts_are_not_youtube(host: str) -> None:
    assert not is_youtube_host(host)


def test_hosts_and_tracking_keys_are_the_donor_sets() -> None:
    assert len(YOUTUBE_HOSTS) == 5
    assert TRACKING_QUERY_KEYS == (
        "si", "feature", "pp", "fbclid", "gclid", "igsh", "igshid", "mc_cid", "mc_eid", "ref_src", "ref_url", "spm",
    )


def test_bad_address_splits_to_none() -> None:
    assert split_url("https://[bad") is None
    assert split_url("https://example.org") is not None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.org/page?utm_source=x&id=5", "https://example.org/page?id=5"),
        ("https://example.org/page?id=5&FBCLID=abc&Si=1", "https://example.org/page?id=5"),
        ("https://example.org/page?utm_campaign=1#frag", "https://example.org/page#frag"),
        ("https://example.org/page?a=&b=2", "https://example.org/page?a=&b=2"),
        ("  https://example.org  ", "https://example.org"),
        ("ftp://example.org/?utm_source=x", "ftp://example.org/?utm_source=x"),
        ("https://[bad?utm_source=x", "https://[bad?utm_source=x"),
        ("", ""),
    ],
)
def test_tracking_params_are_removed_only_from_web_links(url: str, expected: str) -> None:
    assert strip_tracking_params(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.org/", "https://example.org"),
        ("HTTPS://Example.ORG/", "https://Example.ORG"),
        ("https://example.org/page", "https://example.org/page"),
        ("https://example.org/?a=1", "https://example.org/?a=1"),
        ("https://example.org/#top", "https://example.org/#top"),
        ("mailto:team@example.org", "mailto:team@example.org"),
        ("https://[bad/", "https://[bad/"),
    ],
)
def test_display_url_drops_only_the_bare_root_slash(url: str, expected: str) -> None:
    assert normalize_display_url(url) == expected


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("https://www.example.org/", "https://example.org"),
        ("https://example.org/uk", "https://example.org"),
        ("https://example.org/fr-fr/", "https://EXAMPLE.org"),
        ("https://example.org/page/", "https://example.org/page"),
        ("https://example.org/page?id=1", "https://example.org/page?id=2"),
    ],
)
def test_same_site_links_share_a_key(first: str, second: str) -> None:
    assert canonical_link_key(first) == canonical_link_key(second)


def test_scheme_and_real_paths_keep_keys_apart() -> None:
    assert canonical_link_key("http://example.org") != canonical_link_key("https://example.org")
    assert canonical_link_key("https://example.org/news") != canonical_link_key("https://example.org")
    assert canonical_link_key("https://example.org/ukr") != canonical_link_key("https://example.org")


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(https://example.org/about)", "https://example.org/about"),
        ("(https://example.org/about).", "https://example.org/about)"),   # донор: скобка перед точкой остаётся
        ("<https://example.org/>", "https://example.org"),
        ("https://example.org/page;", "https://example.org/page"),
        ("https://example.org/page?utm_source=x&id=5#frag", "https://example.org/page?id=5"),
        ("https://example.org/#frag", "https://example.org"),
        ("ftp://example.org", None),
        ("https://", None),
        ("   ", None),
        ("https://[bad", None),
    ],
)
def test_link_candidate_is_unwrapped_cleaned_and_validated(raw: str, expected: str | None) -> None:
    assert normalize_link_candidate(raw) == expected


# --- ссылки санации после LLM (донор: test_sanitizer_url_selector.py, test_canonical_url_dedup.py)


def test_social_hosts_are_the_donor_set() -> None:
    assert SOCIAL_PLATFORM_HOSTS == {
        "x.com", "twitter.com", "t.me", "telegram.me", "facebook.com", "fb.com", "instagram.com", "threads.net",
        "linkedin.com", "tiktok.com", "reddit.com", "vk.com",
    }


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("m.facebook.com", True),
        ("mobile.twitter.com", True),
        ("l.instagram.com", True),
        ("facebook.com", True),
        ("www.x.com", True),
        ("api.example.com", False),
        ("example.com", False),
    ],
)
def test_social_platform_hosts_include_subdomains(host: str, expected: bool) -> None:
    assert is_social_platform_host(host) is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://x.com/pastormarkburns/status/123456", "https://x.com/pastormarkburns/status/123456"),
        ("https://www.facebook.com/SomePage", "https://www.facebook.com/SomePage"),
        ("https://t.me/somechannel/12345", "https://t.me/somechannel/12345"),
        ("https://www.instagram.com/user/?utm_source=ig", "https://www.instagram.com/user/"),
        ("https://m.facebook.com/page/123", "https://m.facebook.com/page/123"),
        ("https://www.spiritualdiplomats.org/ukraine", "https://spiritualdiplomats.org"),
        ("https://allatra.org/uk", "https://allatra.org"),
        ("https://x.com", "https://x.com"),
        ("https://example.com", "https://example.com"),
        ("https://example.com/", "https://example.com"),
        ("https://www.example.org?ref=123", "https://example.org"),
        ("not-a-url", "not-a-url"),
        ("", ""),
        ("https://[bad", "https://[bad"),
    ],
)
def test_official_link_display_keeps_social_paths_and_cuts_sites_to_the_host(url: str, expected: str) -> None:
    assert normalize_official_link_display(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com/page?utm_source=twitter&id=123", "https://example.com/page?id=123"),
        ("https://example.com/?fbclid=abc123", "https://example.com"),
        ("https://example.com/about", "https://example.com/about"),
        ("https://example.com/", "https://example.com"),
        ("(https://example.org/about).", "(https://example.org/about)."),
        ("<https://example.org/?utm_source=x>", "<https://example.org>"),
        ("[https://example.org/];", "[https://example.org];"),
        ("ftp://example.org/?utm_source=x", "ftp://example.org/?utm_source=x"),
        ("https://[bad", "https://[bad"),
        ("", ""),
        ("().", "()."),
    ],
)
def test_sanitize_url_cleans_the_link_and_keeps_its_wrapping(url: str, expected: str) -> None:
    assert sanitize_url(url) == expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://example.com", True),
        ("http://example.com/page", True),
        ("(https://example.com).", True),
        ("example.com", False),
        ("", False),
        ("https://localhost", False),
        ("https://x..y/z", False),
        ("https://example.", False),
        ("https://exa mple.org", False),
        ("ftp://example.org/file", False),
        ("https://[bad", False),
    ],
)
def test_complete_source_url_needs_a_dotted_host(url: str, expected: bool) -> None:
    assert is_complete_source_url(url) is expected


def test_youtube_url_is_recognized_through_its_wrapping_and_never_on_a_bad_address() -> None:
    assert is_youtube_url("(https://www.youtube.com/watch?v=abc123def45).")
    assert is_youtube_url("https://youtu.be/abc123def45")
    assert not is_youtube_url("https://example.org")
    assert not is_youtube_url("https://[bad")
    assert not is_youtube_url("")


def test_source_url_is_cleaned_and_youtube_is_shortened() -> None:
    assert SourceUrl.of("https://example.com/page?utm_medium=email").url == "https://example.com/page"
    assert SourceUrl.of("not-a-url").url is None
    assert SourceUrl.of("https://[bad").url is None
    youtube: SourceUrl = SourceUrl.of("https://www.youtube.com/watch?v=abc123def45&si=tracking")
    assert youtube.url == "https://youtu.be/abc123def45" and not youtube.youtube_dropped


def test_youtube_link_without_an_id_is_dropped_with_the_donor_log_line() -> None:
    dropped: SourceUrl = SourceUrl.of("https://youtube.com/watch?v=short")
    assert dropped.url is None and dropped.youtube_dropped
    assert dropped.log_line == (
        "non_authoritative_youtube_tail_url_dropped reason=youtube_normalization_failed "
        "raw='https://youtube.com/watch?v=short'"
    )


def test_urls_in_text_are_cleaned_and_changes_counted() -> None:
    text: str = "See https://example.org/?utm_source=x and https://example.org/page, then https://[bad here."
    assert sanitize_urls_in_text(text) == (
        "See https://example.org and https://example.org/page, then https://[bad here.", 1
    )
    assert sanitize_urls_in_text("") == ("", 0)


def test_dedupe_keeps_first_nonempty_values_in_order() -> None:
    assert dedupe_nonempty([" b", "a", "", "b", "  ", "a "]) == ("b", "a")
