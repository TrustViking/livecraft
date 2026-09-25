"""Ссылки в тексте: хосты YouTube, снятие меток слежения, ключ сравнения ссылок (CLAUDE.md §0 — чистые преобразования).

Перенесено из restreamer как есть по поведению: `app\\core\\text_utils.py::is_youtube_host` (`_YOUTUBE_HOSTS`),
`app\\core\\url_utils.py` (`strip_tracking_params`, `TRACKING_QUERY_KEYS`, `_canonical_domain_key`, `_LANG_ONLY_PATH_RE`),
`app\\core\\url_normalizer.py::normalize_display_url`, `app\\llm\\merges\\merge_links.py::_normalize_link_candidate`.
Функции не знают ни об описаниях, ни об источниках: правила над ними живут в `app\\llm\\merges\\`.

Одно отличие от донора — исправление его ошибки: `urlsplit` отвергает негодный адрес (`https://[bad`) исключением
`ValueError`. Донор ловил его в `strip_tracking_params` и `normalize_display_url`, но не в `_normalize_link_candidate`:
такая строка в описании источника или в ответе модели роняла весь merge слота. Здесь негодный адрес — не ссылка.
"""
from __future__ import annotations

import re
from typing import Final
from urllib.parse import SplitResult, parse_qsl, urlencode, urlsplit, urlunsplit

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
