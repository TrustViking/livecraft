"""Ссылка http(s): строка адреса, разобранная один раз, и всё, что о ней решает программа (CLAUDE.md §0, §11).

`WebLink` — значение: адрес без краевых пробелов и его разбор. Он сам знает свой хост, схему и query, ведёт ли он
на YouTube (хост из списка `YOUTUBE_HOSTS` — единственное правило) или в соцсеть, полон ли он, как выглядит без
меток слежения, корнем сайта, в блоке официальных ссылок и как ключ повтора. Обрамление ссылки в тексте — один
набор знаков `LINK_EDGE_CHARS` (скобки и уголки) плюс знаки препинания в конце. Негодный адрес (`https://[bad`)
разбора не имеет: он не ссылка, а не ошибка.
"""
from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from functools import cached_property
from typing import Final
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.youtube_video import YOUTUBE_HOSTS

# Ссылка http(s) в тексте и строка, которая целиком — одна ссылка.
URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://\S+", flags=re.IGNORECASE)
URL_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^https?://\S+$", re.IGNORECASE)
HTTPS_SCHEME: Final[str] = "https"     # защищённая схема: ссылки формы и отбор ссылок её требуют
WEB_SCHEMES: Final[frozenset[str]] = frozenset({"http", HTTPS_SCHEME})
# Метки слежения в query: всё, что начинается с `utm_`, и ключи списка.
TRACKING_QUERY_PREFIX: Final[str] = "utm_"
TRACKING_QUERY_KEYS: Final[frozenset[str]] = frozenset(
    {"si", "feature", "pp", "fbclid", "gclid", "igsh", "igshid", "mc_cid", "mc_eid", "ref_src", "ref_url", "spm"}
)
WWW_PREFIX: Final[str] = "www."
# Путь из одного кода языка (`/uk`, `/en/`, `/fr-fr`) — тот же сайт, что и корень.
LANGUAGE_ONLY_PATH_PATTERN: Final[re.Pattern[str]] = re.compile(r"^/[a-z]{2}(?:-[a-z]{2})?/?$", re.IGNORECASE)
ROOT_PATHS: Final[frozenset[str]] = frozenset({"", "/"})
PATH_SLASH: Final[str] = posixpath.sep     # разделитель частей пути ссылки — тот же, что в пути POSIX
ADDRESS_TEMPLATE: Final[str] = "{scheme}://{host}{path}"
# Обрамление ссылки в тексте: скобки и уголки с обеих сторон, знаки препинания — в конце.
LINK_EDGE_CHARS: Final[str] = "<>()[]{}"
LINK_TRAILING_PUNCTUATION: Final[str] = ".,;"
HOST_DOT: Final[str] = "."
HOST_DOUBLE_DOT: Final[str] = ".."
# Соцсети: у их ссылок путь — сам адрес (страница, пост), поэтому в блоке официальных ссылок он сохраняется.
SOCIAL_PLATFORM_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "x.com", "twitter.com", "t.me", "telegram.me", "facebook.com", "fb.com", "instagram.com", "threads.net",
        "linkedin.com", "tiktok.com", "reddit.com", "vk.com",
    }
)
SOCIAL_SUBDOMAIN_MIN_PARTS: Final[int] = 3      # `m.facebook.com` — поддомен соцсети
SOCIAL_DOMAIN_PARTS: Final[int] = 2             # `facebook.com` — имя соцсети из двух частей


def split_url(url: str) -> SplitResult | None:
    """Разбор адреса; негодный (`https://[bad`) — None."""
    try:
        return urlsplit(url)
    except ValueError:
        return None


@dataclass(frozen=True)
class WebLink:
    """Адрес без краевых пробелов; разбор — один раз, по первому обращению."""

    text: str

    @classmethod
    def of(cls, text: str) -> WebLink:
        return cls((text or "").strip())

    @property
    def unwrapped(self) -> WebLink:
        """Ссылка из текста без обрамления: скобок и уголков по краям, знаков препинания в конце."""
        return WebLink(self.text.strip(LINK_EDGE_CHARS).rstrip(LINK_TRAILING_PUNCTUATION))

    @cached_property
    def parts(self) -> SplitResult | None:
        return split_url(self.text)

    @property
    def host(self) -> str:
        """Хост в нижнем регистре; негодный адрес — пусто."""
        return self.parts.netloc.lower().strip() if self.parts is not None else ""

    @property
    def bare_host(self) -> str:
        """Хост без `www.`."""
        return self.host.removeprefix(WWW_PREFIX)

    @property
    def is_web(self) -> bool:
        """Адрес http(s) с хостом."""
        return self.parts is not None and self.parts.scheme in WEB_SCHEMES and bool(self.parts.netloc)

    @property
    def is_https(self) -> bool:
        return self.parts is not None and self.parts.scheme == HTTPS_SCHEME

    @property
    def has_query(self) -> bool:
        return self.parts is not None and bool(self.parts.query)

    @property
    def is_youtube(self) -> bool:
        """Хост — YouTube из списка `YOUTUBE_HOSTS`; похожее имя (`youtube-like.example.com`) — нет."""
        return self.host in YOUTUBE_HOSTS

    @property
    def is_social(self) -> bool:
        """Хост — соцсеть из списка, в том числе её поддомен (`m.facebook.com`, `mobile.twitter.com`)."""
        host: str = self.bare_host
        labels: list[str] = host.split(HOST_DOT)
        is_subdomain: bool = len(labels) >= SOCIAL_SUBDOMAIN_MIN_PARTS
        return host in SOCIAL_PLATFORM_HOSTS or (
            is_subdomain and HOST_DOT.join(labels[-SOCIAL_DOMAIN_PARTS:]) in SOCIAL_PLATFORM_HOSTS
        )

    @property
    def is_complete(self) -> bool:
        """Полная ссылка http(s) без обрамления: одна строка без пробелов, хост с точкой и без пустых частей имени."""
        link: WebLink = self.unwrapped
        if not URL_LINE_PATTERN.fullmatch(link.text) or not link.is_web:
            return False
        host: str = link.host
        return HOST_DOT in host and not host.endswith(HOST_DOT) and HOST_DOUBLE_DOT not in host

    @property
    def without_tracking(self) -> str:
        """Адрес http(s) без меток слежения в query; не http(s) — как есть."""
        if self.parts is None or not self.is_web:
            return self.text
        kept: list[tuple[str, str]] = [
            (key, value)
            for key, value in parse_qsl(self.parts.query, keep_blank_values=True)
            if not self._is_tracking_key(key)
        ]
        parts: SplitResult = self.parts
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept, doseq=True), parts.fragment))

    def _is_tracking_key(self, key: str) -> bool:
        """Ключ query — метка слежения: `utm_…` или ключ из списка (без учёта регистра)."""
        normalized: str = key.lower().strip()
        return normalized.startswith(TRACKING_QUERY_PREFIX) or normalized in TRACKING_QUERY_KEYS

    @property
    def display_root(self) -> str:
        """Корень сайта — схема и хост без `/`, query и фрагмента; ссылка не на корень и не http(s) — как есть."""
        if self.parts is None or not self.is_web:
            return self.text
        if self.parts.path not in ROOT_PATHS or self.parts.query or self.parts.fragment:
            return self.text
        return urlunsplit((self.parts.scheme, self.parts.netloc, "", "", ""))

    @property
    def key(self) -> str:
        """Ключ повтора ссылок: схема и хост в нижнем регистре без `www.`, путь без `/` в конце, путь из кода языка —
        как корень; query и фрагмент не учитываются. Негодный адрес — пусто."""
        if self.parts is None:
            return ""
        path: str = "" if LANGUAGE_ONLY_PATH_PATTERN.match(self.parts.path) else self.parts.path.rstrip(PATH_SLASH)
        return ADDRESS_TEMPLATE.format(scheme=self.parts.scheme.lower(), host=self.bare_host, path=path)

    @property
    def candidate(self) -> str | None:
        """Ссылка из текста в виде для сравнения: без обрамления, меток слежения и фрагмента, корень — без `/`.
        Не http(s), без хоста или негодный адрес — None."""
        link: WebLink = self.unwrapped
        if not link.is_web:
            return None
        clean: SplitResult | None = split_url(link.without_tracking)
        if clean is None:
            return None
        return WebLink(urlunsplit((clean.scheme, clean.netloc, clean.path, clean.query, ""))).display_root

    @property
    def official_display(self) -> str:
        """Вид ссылки в блоке официальных ссылок: сайт — схема и хост без `www.`; соцсеть — адрес без меток слежения;
        не http(s) или без хоста — как есть."""
        if self.parts is None or not self.is_web or not self.bare_host:
            return self.text
        if self.is_social:
            return self.without_tracking
        return ADDRESS_TEMPLATE.format(scheme=self.parts.scheme, host=self.bare_host, path="")

    @property
    def sanitized(self) -> str:
        """Ссылка из текста без меток слежения, корень — без `/`; обрамление по краям сохраняется; не ссылка — как есть."""
        core: str = self.text.lstrip(LINK_EDGE_CHARS)
        prefix: str = self.text[: len(self.text) - len(core)]
        bare: str = core.rstrip(LINK_EDGE_CHARS + LINK_TRAILING_PUNCTUATION)
        suffix: str = core[len(bare) :]
        link: WebLink = WebLink(bare)
        if not bare or not link.is_web:
            return prefix + bare + suffix
        return prefix + WebLink(link.without_tracking).display_root + suffix
