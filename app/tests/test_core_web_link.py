from __future__ import annotations

import pytest

from app.core.web_link import SOCIAL_PLATFORM_HOSTS, TRACKING_QUERY_KEYS, WebLink, split_url
from app.core.youtube_video import YOUTUBE_HOSTS
from app.tests.conftest import REPO_ROOT
from app.tools.code_standard.imports import ImportedModules
from app.tools.code_standard.source import ModuleSource, SourceKey, SourceTree
from app.tools.code_standard.standard import AppName
from app.tools.code_standard.usage import ModuleImports

CORE_KEY: SourceKey = SourceKey.of("app/core")
CORE_PACKAGE: str = "app.core"


@pytest.mark.parametrize("host", ["youtu.be", "www.youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"])
def test_youtube_hosts_are_recognized_in_any_case(host: str) -> None:
    assert WebLink.of(f"https://{host}/watch").is_youtube
    assert WebLink.of(f"  https://{host.upper()}/watch ").is_youtube


@pytest.mark.parametrize(
    "url",
    [
        "https://music.youtube.com/x", "https://youtube.org/x", "https://example.org", "", "https://youtu.be:443/x",
        "https://youtube-like.example.com/watch?v=abc", "https://[bad",
    ],
)
def test_other_hosts_are_not_youtube(url: str) -> None:
    """«Ссылка YouTube» — только хост из списка: похожее имя сайта или подстрока «youtu» — не YouTube."""
    assert not WebLink.of(url).is_youtube


def test_hosts_and_tracking_keys_are_fixed_sets() -> None:
    assert len(YOUTUBE_HOSTS) == 5
    assert TRACKING_QUERY_KEYS == {
        "si", "feature", "pp", "fbclid", "gclid", "igsh", "igshid", "mc_cid", "mc_eid", "ref_src", "ref_url", "spm",
    }


def test_bad_address_splits_to_none() -> None:
    assert split_url("https://[bad") is None
    assert split_url("https://example.org") is not None
    assert WebLink.of("https://[bad").parts is None


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
    assert WebLink.of(url).without_tracking == expected


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
def test_display_root_drops_only_the_bare_root_slash(url: str, expected: str) -> None:
    assert WebLink.of(url).display_root == expected


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
    assert WebLink.of(first).key == WebLink.of(second).key


def test_scheme_and_real_paths_keep_keys_apart() -> None:
    assert WebLink.of("http://example.org").key != WebLink.of("https://example.org").key
    assert WebLink.of("https://example.org/news").key != WebLink.of("https://example.org").key
    assert WebLink.of("https://example.org/ukr").key != WebLink.of("https://example.org").key
    assert WebLink.of("https://[bad").key == ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("(https://example.org/about)", "https://example.org/about"),
        ("(https://example.org/about).", "https://example.org/about)"),   # скобка перед точкой остаётся в адресе
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
    assert WebLink.of(raw).candidate == expected


def test_social_hosts_are_a_fixed_set() -> None:
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
    assert WebLink.of(f"https://{host}/page").is_social is expected


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
def test_official_display_keeps_social_paths_and_cuts_sites_to_the_host(url: str, expected: str) -> None:
    assert WebLink.of(url).official_display == expected


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
def test_sanitized_cleans_the_link_and_keeps_its_wrapping(url: str, expected: str) -> None:
    assert WebLink.of(url).sanitized == expected


def test_curly_braces_wrap_a_link_like_any_other_brackets() -> None:
    """Обрамление ссылки — один набор знаков и для чистки: фигурные скобки сохраняются, метки слежения снимаются."""
    assert WebLink.of("{https://site.org/?utm_source=x}").sanitized == "{https://site.org}"
    assert WebLink.of("{https://site.org/page}.").sanitized == "{https://site.org/page}."


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
def test_complete_link_needs_a_dotted_host(url: str, expected: bool) -> None:
    assert WebLink.of(url).is_complete is expected


def test_youtube_link_is_recognized_through_its_wrapping_and_never_on_a_bad_address() -> None:
    assert WebLink.of("(https://www.youtube.com/watch?v=abc123def45).").unwrapped.is_youtube
    assert WebLink.of("https://youtu.be/abc123def45").unwrapped.is_youtube
    assert not WebLink.of("https://example.org").unwrapped.is_youtube
    assert not WebLink.of("https://[bad").unwrapped.is_youtube
    assert not WebLink.of("").unwrapped.is_youtube


def test_scheme_query_and_host_are_read_from_one_parse() -> None:
    link: WebLink = WebLink.of("https://WWW.Example.org/page?id=1")
    assert (link.host, link.bare_host, link.is_https, link.has_query, link.is_web) == (
        "www.example.org", "example.org", True, True, True,
    )
    assert not WebLink.of("http://example.org").is_https
    assert not WebLink.of("mailto:team@example.org").is_web


def _outside_core(module: ModuleSource, tree: SourceTree) -> list[str]:
    """Модули app вне core, которые называют импорты модуля (разбор импортов замка, E16)."""
    return [
        origin for origin in ImportedModules(module, tree).origins
        if ModuleImports.is_app(origin) and not AppName(origin).within(CORE_PACKAGE)
    ]


def test_core_modules_import_nothing_from_app_outside_core() -> None:
    tree: SourceTree = SourceTree.from_root(REPO_ROOT)
    modules: tuple[ModuleSource, ...] = tree.under(CORE_KEY)
    assert modules
    offenders: list[str] = [f"{module.key.text}: {origin}" for module in modules for origin in _outside_core(module, tree)]
    assert offenders == []


def test_import_check_sees_nested_and_relative_imports() -> None:
    source: str = """
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from app.texts.tail import TailReader
def later():
    import app.sources.video
from . import dates
from ..texts import paragraphs
from .retry import RetryPolicy
"""
    tree: SourceTree = SourceTree.from_texts({"app/core/sample.py": source})
    module: ModuleSource = tree.modules[0]
    modules: tuple[str, ...] = ImportedModules(module, tree).origins
    assert sorted(_outside_core(module, tree)) == [
        "app.sources.video", "app.texts", "app.texts.tail"
    ]
    assert "app.core" in modules and "app.core.retry" in modules
    assert SourceKey.of("app/core/web_link.py").package == CORE_PACKAGE
