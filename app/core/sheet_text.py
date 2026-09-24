"""Чистые преобразования текста таблицы плана (CLAUDE.md §2, контур A; §5 — `core\\sheet_text.py`).

Перенесено из restreamer как есть по поведению: `planning\\sheet_parser.py` (дата и время ряда, буквы
колонок), `google\\sheets_client.py::_normalize_header_name` (имя колонки шапки),
`ingest\\youtube_metadata.py` (id видео и короткая ссылка). Логирования здесь нет — это чистые функции.

Ни одна функция не знает о рядах, плане и слотах: это разрешённое §0 исключение «чистое преобразование
без знания о предметных объектах». Правила над рядами живут в `app\\sheets\\`.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone, tzinfo
from typing import Final
from zoneinfo import ZoneInfo

# Форматы донора, порядок важен: берётся первый подошедший.
SHEET_DATE_FORMATS: Final[tuple[str, ...]] = (
    "%d.%m.%Y",
    "%d.%m.%y",
    "%d/%m/%Y",
    "%d/%m/%y",
    "%Y-%m-%d",
    "%d%m%y",
    "%d%m%Y",
)
SHEET_TIME_FORMATS: Final[tuple[str, ...]] = (
    "%H:%M",
    "%H.%M",
    "%H%M",
    "%H:%M:%S",
    "%I:%M %p",
    "%I %p",
)

COLUMN_LETTERS_PATTERN: Final[re.Pattern[str]] = re.compile(r"[A-Z]+")
ALPHABET_SIZE: Final[int] = 26
HEADER_JUNK_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^a-zа-я0-9]+", flags=re.IGNORECASE)

YOUTUBE_ID_CHARS: Final[str] = r"[A-Za-z0-9_-]"
YOUTUBE_ID_LENGTH: Final[int] = 11
_ID: Final[str] = rf"({YOUTUBE_ID_CHARS}{{{YOUTUBE_ID_LENGTH}}})"
_ID_END: Final[str] = r"(?:[^A-Za-z0-9_-]|$)"
# Ссылки с контекстом: из всех совпадений берётся самое раннее по позиции id в тексте.
# У донора `watch\?[^#\s]*?(?:[?&]v=|&v=)` не ловил `watch?v=` первым параметром (`?` уже съеден), и такая
# ссылка находилась только запасным поиском голого id — проигрывая более поздней `youtu.be`. Здесь исправлено.
YOUTUBE_LINK_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(rf"(?:https?://)?(?:www\.)?youtu\.be/{_ID}{_ID_END}", flags=re.IGNORECASE),
    re.compile(
        rf"(?:https?://)?(?:www\.)?(?:m\.)?youtube\.com/watch\?(?:[^#\s]*?&)?v={_ID}{_ID_END}",
        flags=re.IGNORECASE,
    ),
    re.compile(
        rf"(?:https?://)?(?:www\.)?(?:m\.)?youtube\.com/(?:shorts|embed|live)/{_ID}{_ID_END}",
        flags=re.IGNORECASE,
    ),
)
# Голый id: 11 символов, по краям — не символы id.
YOUTUBE_BARE_ID_PATTERN: Final[re.Pattern[str]] = re.compile(
    rf"(?<![A-Za-z0-9_-]){_ID}(?![A-Za-z0-9_-])"
)
YOUTUBE_SHORT_LINK_TEMPLATE: Final[str] = "https://youtu.be/{video_id}"


def parse_sheet_datetime(date_raw: str, time_raw: str, zone: ZoneInfo) -> datetime:
    """Дата и время ряда → момент в зоне `zone`; секунды отбрасываются; негодное — ValueError."""
    parsed_date: datetime = _parse_first(date_raw.strip(), SHEET_DATE_FORMATS, "date", date_raw)
    parsed_time: datetime = _parse_first(time_raw.strip(), SHEET_TIME_FORMATS, "time", time_raw)
    return datetime(
        year=parsed_date.year,
        month=parsed_date.month,
        day=parsed_date.day,
        hour=parsed_time.hour,
        minute=parsed_time.minute,
        tzinfo=zone,
    )


def _parse_first(text: str, formats: tuple[str, ...], kind: str, raw: str) -> datetime:
    for pattern in formats:
        try:
            return datetime.strptime(text, pattern)
        except ValueError:
            continue
    raise ValueError(f"unsupported {kind} format: {raw!r}")


def is_real_local_time(value: datetime) -> bool:
    """Существует ли такое местное время в зоне момента: в час перехода на летнее время его нет.

    Момент переводится в UTC и обратно; если часы и минуты не вернулись — местного времени не было.
    Повторяющийся час осени существует (берётся первое наступление, fold=0).
    """
    zone: tzinfo | None = value.tzinfo
    if zone is None:
        raise ValueError("naive datetime has no zone")
    back: datetime = value.astimezone(timezone.utc).astimezone(zone)
    return back.replace(tzinfo=None, fold=0) == value.replace(tzinfo=None, fold=0)


def column_letters_to_index(text: str) -> int | None:
    """Буквы колонки → номер с 1 (A → 1, AA → 27); не буквы — None."""
    cleaned: str = str(text or "").strip().upper()
    if not COLUMN_LETTERS_PATTERN.fullmatch(cleaned):
        return None
    index: int = 0
    for symbol in cleaned:
        index = index * ALPHABET_SIZE + (ord(symbol) - ord("A") + 1)
    return index


def normalize_header_name(text: str) -> str:
    """Имя колонки шапки для сравнения: нижний регистр, только латиница, кириллица и цифры."""
    return HEADER_JUNK_PATTERN.sub("", text.strip().lower())


def extract_youtube_video_id(text: str) -> str | None:
    """Id видео YouTube из ссылки или текста: сначала ссылки (самая ранняя), затем голый id; нет — None."""
    cleaned: str = str(text or "").strip()
    if not cleaned:
        return None
    earliest: re.Match[str] | None = None
    for pattern in YOUTUBE_LINK_PATTERNS:
        for match in pattern.finditer(cleaned):
            if earliest is None or match.start(1) < earliest.start(1):
                earliest = match
    if earliest is not None:
        return earliest.group(1)
    bare: re.Match[str] | None = YOUTUBE_BARE_ID_PATTERN.search(cleaned)
    return bare.group(1) if bare is not None else None


def normalize_youtube_link(text: str) -> str | None:
    """Ссылка или текст → `https://youtu.be/<id>`; id не найден — None."""
    video_id: str | None = extract_youtube_video_id(text)
    if video_id is None:
        return None
    return YOUTUBE_SHORT_LINK_TEMPLATE.format(video_id=video_id)
