from __future__ import annotations

import pytest

from app.core.url_text import (
    TRACKING_QUERY_KEYS,
    YOUTUBE_HOSTS,
    canonical_link_key,
    is_youtube_host,
    normalize_display_url,
    normalize_link_candidate,
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
