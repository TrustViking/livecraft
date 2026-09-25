"""Ссылки в тексте: хосты YouTube, снятие меток слежения, ключ сравнения ссылок (CLAUDE.md §0 — чистые преобразования).

Перенесено из restreamer как есть по поведению: `app\\core\\text_utils.py::is_youtube_host` (`_YOUTUBE_HOSTS`),
`app\\core\\url_utils.py` (`strip_tracking_params`, `TRACKING_QUERY_KEYS`, `_canonical_domain_key`, `_LANG_ONLY_PATH_RE`),
`app\\core\\url_normalizer.py::normalize_display_url`, `app\\llm\\merges\\merge_links.py::_normalize_link_candidate`.
Функции не знают ни об описаниях, ни об источниках: правила над ними живут в `app\\llm\\merges\\`.

Одно отличие от донора — исправление его ошибки: `urlsplit` отвергает негодный адрес (`https://[bad`) исключением
`ValueError`. Донор ловил его в `strip_tracking_params` и `normalize_display_url`, но не в `_normalize_link_candidate`:
такая строка в описании источника или в ответе модели роняла весь merge слота. Здесь негодный адрес — не ссылка.

Для санации после LLM (задача 3.14) перенесены `app\\publish\\sanitizers\\url_selector.py` (`_sanitize_url` → `sanitize_url`,
`_is_complete_source_url` → `is_complete_source_url`, `_sanitize_source_url` → `SourceUrl.of`, `_sanitize_urls_in_text`
→ `sanitize_urls_in_text`, `_dedupe_nonempty` → `dedupe_nonempty`), `app\\core\\url_utils.py`
(`normalize_official_link_display`, `is_social_platform_host`, `SOCIAL_PLATFORM_HOSTS`) и `text_utils.py::is_youtube_url`.
`SourceUrl` — значение, а не правило: строку лога о ссылке YouTube без id пишет вызывающий объект. Шаблоны ссылок
`URL_PATTERN` и `URL_LINE_PATTERN` (`app\\core\\constants.py` донора) — единственные в программе и объявлены здесь:
`app\\core` не зависит от других пакетов `app`, разметка описания и чистка текста берут шаблоны отсюда.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit

from app.core.sheet_text import normalize_youtube_link

# Ссылка http(s) в тексте и строка, которая целиком — одна ссылка.
URL_PATTERN: Final[re.Pattern[str]] = re.compile(r"https?://\S+", flags=re.IGNORECASE)
URL_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^https?://\S+$", re.IGNORECASE)
YOUTUBE_HOSTS: Final[frozenset[str]] = frozenset(
    {"youtu.be", "www.youtu.be", "youtube.com", "www.youtube.com", "m.youtube.com"}
)
WEB_SCHEMES: Final[frozenset[str]] = frozenset({"http", "https"})
# Метки слежения в query: всё, что начинается с `utm_`, и ключи списка.
TRACKING_QUERY_PREFIX: Final[str] = "utm_"
TRACKING_QUERY_KEYS: Final[tuple[str, ...]] = (
    "si",
    "feature",
    "pp",
    "fbclid",
    "gclid",
    "igsh",
    "igshid",
    "mc_cid",
    "mc_eid",
    "ref_src",
    "ref_url",
    "spm",
)
WWW_PREFIX: Final[str] = "www."
# Путь из одного кода языка (`/uk`, `/en/`, `/fr-fr`) — тот же сайт, что и корень.
LANGUAGE_ONLY_PATH_PATTERN: Final[re.Pattern[str]] = re.compile(r"^/[a-z]{2}(?:-[a-z]{2})?/?$", re.IGNORECASE)
ROOT_PATHS: Final[tuple[str, ...]] = ("", "/")
# Ссылка в тексте: снаружи — скобки и кавычки-уголки, в конце — знаки препинания.
LINK_EDGE_CHARS: Final[str] = "<>()[]{}"
LINK_TRAILING_PUNCTUATION: Final[str] = ".,;"


def split_url(url: str) -> SplitResult | None:
    """Разбор адреса; негодный (`https://[bad`) — None."""
    try:
        return urlsplit(url)
    except ValueError:
        return None


def is_youtube_host(host: str) -> bool:
    """Хост — YouTube (`youtu.be`, `youtube.com`, `www.`, `m.`)."""
    return str(host or "").strip().lower() in YOUTUBE_HOSTS


def strip_tracking_params(url: str) -> str:
    """Адрес http(s) без меток слежения в query; прочее — как есть (без краевых пробелов)."""
    raw_url: str = str(url or "").strip()
    if not raw_url:
        return raw_url
    parts: SplitResult | None = split_url(raw_url)
    if parts is None or parts.scheme not in WEB_SCHEMES or not parts.netloc:
        return raw_url
    kept_items: list[tuple[str, str]] = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not _is_tracking_key(key)
    ]
    query: str = urlencode(kept_items, doseq=True)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))


def _is_tracking_key(key: str) -> bool:
    normalized_key: str = key.lower().strip()
    return normalized_key.startswith(TRACKING_QUERY_PREFIX) or normalized_key in TRACKING_QUERY_KEYS


def normalize_display_url(url: str) -> str:
    """Корень сайта без пути, query и фрагмента — без завершающего `/`; прочее — как есть."""
    raw_url: str = str(url or "")
    if not raw_url:
        return raw_url
    parts: SplitResult | None = split_url(raw_url)
    if parts is None or str(parts.scheme or "").lower() not in WEB_SCHEMES or not parts.netloc:
        return raw_url
    if parts.path not in ROOT_PATHS or parts.query or parts.fragment:
        return raw_url
    return urlunsplit((parts.scheme, parts.netloc, "", "", ""))


def canonical_link_key(url: str) -> str:
    """Ключ повтора ссылок: схема и хост в нижнем регистре без `www.`, путь без `/` в конце, путь из кода языка —
    как корень; query и фрагмент не учитываются."""
    parts: SplitResult | None = split_url(str(url or "").strip())
    if parts is None:
        return ""
    domain: str = parts.netloc.lower()
    if domain.startswith(WWW_PREFIX):
        domain = domain[len(WWW_PREFIX) :]
    path: str = "" if LANGUAGE_ONLY_PATH_PATTERN.match(parts.path) else parts.path.rstrip("/")
    return f"{parts.scheme.lower()}://{domain}{path}"


def normalize_link_candidate(url: str) -> str | None:
    """Ссылка из текста в виде для сравнения: без обрамления, меток слежения и фрагмента, корень — без `/`.
    Не http(s), без хоста или негодный адрес — None."""
    raw_url: str = str(url or "").strip().strip(LINK_EDGE_CHARS).rstrip(LINK_TRAILING_PUNCTUATION)
    if not raw_url:
        return None
    parts: SplitResult | None = split_url(raw_url)
    if parts is None or parts.scheme not in WEB_SCHEMES or not parts.netloc:
        return None
    stripped: SplitResult | None = split_url(strip_tracking_params(raw_url))
    if stripped is None:
        return None
    return normalize_display_url(urlunsplit((stripped.scheme, stripped.netloc, stripped.path, stripped.query, "")))


# --- ссылки санации после LLM (restreamer `app\publish\sanitizers\url_selector.py`, `app\core\url_utils.py`)

# Соцсети: у их ссылок путь — сам адрес (страница, пост), поэтому в блоке официальных ссылок он сохраняется.
SOCIAL_PLATFORM_HOSTS: Final[frozenset[str]] = frozenset(
    {
        "x.com",
        "twitter.com",
        "t.me",
        "telegram.me",
        "facebook.com",
        "fb.com",
        "instagram.com",
        "threads.net",
        "linkedin.com",
        "tiktok.com",
        "reddit.com",
        "vk.com",
    }
)
SOCIAL_SUBDOMAIN_MIN_PARTS: Final[int] = 3
# Обёртка ссылки в тексте: открывающие знаки слева, закрывающие и знаки препинания справа — сохраняются при чистке.
URL_WRAP_OPENERS: Final[str] = "<(["
URL_WRAP_CLOSERS: Final[str] = ">)].,;"
HOST_DOT: Final[str] = "."
HOST_DOUBLE_DOT: Final[str] = ".."
WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s")
YOUTUBE_DROP_LOG: Final[str] = "non_authoritative_youtube_tail_url_dropped reason=youtube_normalization_failed raw={raw!r}"


def is_youtube_url(url: str) -> bool:
    """Ссылка (без обрамления) ведёт на YouTube; негодный адрес — нет (`text_utils.py::is_youtube_url` донора)."""
    cleaned: str = str(url or "").strip().strip(LINK_EDGE_CHARS).rstrip(LINK_TRAILING_PUNCTUATION)
    if not cleaned:
        return False
    parts: SplitResult | None = split_url(cleaned)
    return parts is not None and is_youtube_host(parts.netloc)


def is_social_platform_host(host: str) -> bool:
    """Хост — соцсеть из списка, в том числе поддомен (`m.facebook.com`, `mobile.twitter.com`)."""
    normalized_host: str = str(host or "").strip().lower()
    if normalized_host.startswith(WWW_PREFIX):
        normalized_host = normalized_host[len(WWW_PREFIX) :]
    if normalized_host in SOCIAL_PLATFORM_HOSTS:
        return True
    parts: list[str] = normalized_host.split(HOST_DOT)
    return len(parts) >= SOCIAL_SUBDOMAIN_MIN_PARTS and HOST_DOT.join(parts[-2:]) in SOCIAL_PLATFORM_HOSTS


def normalize_official_link_display(url: str) -> str:
    """Вид ссылки в блоке официальных ссылок: сайт — схема и хост без `www.`; соцсеть — адрес без меток слежения;
    не http(s), без хоста или негодный адрес — как есть."""
    raw_url: str = str(url or "").strip()
    if not raw_url:
        return raw_url
    parts: SplitResult | None = split_url(raw_url)
    if parts is None or parts.scheme not in WEB_SCHEMES or not parts.netloc:
        return raw_url
    host: str = parts.netloc.lower().strip()
    if host.startswith(WWW_PREFIX):
        host = host[len(WWW_PREFIX) :]
    if not host:
        return raw_url
    if is_social_platform_host(host):
        return strip_tracking_params(raw_url)
    return f"{parts.scheme}://{host}"


def sanitize_url(url: str) -> str:
    """Ссылка из текста без меток слежения, корень — без `/`; обёртка (`<([`, `>)].,;`) сохраняется; не ссылка — как есть.
    Негодный адрес (`https://[bad`) — как есть, как любая не-ссылка (у донора — исключение)."""
    raw_url: str = str(url or "").strip()
    if not raw_url:
        return ""
    prefix: str = ""
    suffix: str = ""
    while raw_url and raw_url[0] in URL_WRAP_OPENERS:
        prefix += raw_url[0]
        raw_url = raw_url[1:]
    while raw_url and raw_url[-1] in URL_WRAP_CLOSERS:
        suffix = raw_url[-1] + suffix
        raw_url = raw_url[:-1]
    if not raw_url:
        return prefix + suffix
    parts: SplitResult | None = split_url(raw_url)
    if parts is None or parts.scheme not in WEB_SCHEMES or not parts.netloc:
        return prefix + raw_url + suffix
    return prefix + normalize_display_url(strip_tracking_params(raw_url)) + suffix


def is_complete_source_url(url: str) -> bool:
    """Полная ссылка http(s): одна строка без пробелов, хост с точкой, без пустых частей имени; негодный адрес — нет."""
    cleaned_url: str = str(url or "").strip().strip(LINK_EDGE_CHARS).rstrip(LINK_TRAILING_PUNCTUATION)
    if not cleaned_url or not URL_LINE_PATTERN.fullmatch(cleaned_url):
        return False
    parts: SplitResult | None = split_url(cleaned_url)
    if parts is None or parts.scheme not in WEB_SCHEMES or not parts.netloc:
        return False
    host: str = parts.netloc.strip().lower()
    if HOST_DOT not in host or host.endswith(HOST_DOT) or HOST_DOUBLE_DOT in host:
        return False
    return not WHITESPACE_PATTERN.search(cleaned_url)


@dataclass(frozen=True)
class SourceUrl:
    """Ссылка источника после чистки (`_sanitize_source_url` донора): `url` None — не ссылка или неполная.
    `youtube_dropped` — ссылка YouTube, из которой не извлёкся id: вызывающий пишет `log_line`."""

    raw: str
    url: str | None
    youtube_dropped: bool = False

    @classmethod
    def of(cls, raw: str) -> SourceUrl:
        sanitized: str = sanitize_url(raw).strip()
        if not sanitized or not is_complete_source_url(sanitized):
            return cls(raw=raw, url=None)
        if not is_youtube_url(sanitized):
            return cls(raw=raw, url=sanitized)
        youtube: str | None = normalize_youtube_link(sanitized)
        if youtube is None:
            return cls(raw=sanitized, url=None, youtube_dropped=True)
        return cls(raw=raw, url=youtube)

    @property
    def log_line(self) -> str:
        return YOUTUBE_DROP_LOG.format(raw=self.raw)


def sanitize_urls_in_text(text: str) -> tuple[str, int]:
    """Каждая ссылка текста — через `sanitize_url`; вместе с текстом — сколько ссылок изменилось."""
    changes: list[str] = []

    def replace(match: re.Match[str]) -> str:
        raw_url: str = match.group(0)
        sanitized: str = sanitize_url(raw_url)
        if sanitized != raw_url:
            changes.append(raw_url)
        return sanitized

    return URL_PATTERN.sub(replace, str(text or "")), len(changes)


def dedupe_nonempty(values: Iterable[str]) -> tuple[str, ...]:
    """Значения без краёв, без пустых и без повторов — в порядке первого появления."""
    kept: dict[str, None] = {}
    for value in values:
        cleaned: str = str(value or "").strip()
        if cleaned:
            kept.setdefault(cleaned, None)
    return tuple(kept)
