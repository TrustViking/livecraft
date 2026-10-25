"""Файл cookies YouTube в формате Netscape — secrets\\cookies.txt (CLAUDE.md §14 решения 54, 73).

Cookies — по желанию каждого человека, своим файлом: программа их не несёт (решение 54). Файл выгружает человек
расширением браузера и загружает на вкладке «Cookies YouTube» окна настройки (`place_from`): годный файл встаёт на
место secrets\\cookies.txt копией со временем изменения источника — это и есть дата выгрузки (`exported`); файл не
Netscape не копируется, прежний остаётся. Правила файла:

- вид — первая непустая строка — заголовок Netscape (BOM в начале не мешает): иначе yt-dlp файл не примет;
- cookies входа в аккаунт YouTube — cookies домена youtube.com с именами из ресурса cookies_login_names.txt: по ним
  yt-dlp решает, вошёл ли он (`login_cookies`); строка cookie — поля через табуляцию, у cookie только для HTTP перед
  доменом стоит `#HttpOnly_`;
- срок cookies входа — самый поздний срок среди них (`login_expires`); сеансовый cookie (срок 0) срока не даёт.
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, tzinfo
from enum import Enum, IntEnum
from pathlib import Path
from typing import Final

from app.paths import AtomicFile
from app.resources.loader import COMMENT_PREFIX, TextResource
from app.ui.console import EncodingErrors
from app.ui.messages import msg

NETSCAPE_HEADER: Final[str] = "# Netscape HTTP Cookie File"
BOM_TOLERANT_ENCODING: Final[str] = "utf-8-sig"     # файл, выгруженный с BOM, — тоже Netscape
LOGIN_NAMES_RESOURCE: Final[str] = "cookies_login_names.txt"
SESSION_EXPIRES: Final[int] = 0                     # сеансовый cookie: срока нет


class NetscapeMark(str, Enum):
    """Разметка строки cookie Netscape и домен cookies YouTube."""

    HTTP_ONLY = "#HttpOnly_"      # перед доменом cookie, доступного только HTTP
    SEPARATOR = "\t"
    YOUTUBE_DOMAIN = "youtube.com"


class NetscapeField(IntEnum):
    """Поля строки cookie Netscape по номеру: домен, …, срок (секунды эпохи), имя, значение."""

    DOMAIN = 0
    EXPIRES = 4
    NAME = 5
    VALUE = 6


class CookiesPlaceProblem(str, Enum):
    """Почему файл не встал на место secrets\\cookies.txt. Значение — ключ `msg.COOKIES_PLACE_PROBLEMS`."""

    NOT_NETSCAPE = "not_netscape"    # не тот вид: yt-dlp его не примет
    UNREADABLE = "unreadable"        # выбранный файл не читается
    NOT_WRITTEN = "not_written"      # копия не встала на место: сбой диска, файл занят

    @property
    def human(self) -> str:
        return msg.COOKIES_PLACE_PROBLEMS[self.value]


@dataclass(frozen=True)
class NetscapeCookie:
    """Cookie из строки файла: домен, имя и срок в секундах эпохи (0 — сеансовый)."""

    domain: str
    name: str
    expires: int

    @classmethod
    def of_line(cls, line: str) -> NetscapeCookie | None:
        """Cookie строки; комментарий, пустая или неполная строка — None."""
        text: str = line.strip()
        if text.startswith(NetscapeMark.HTTP_ONLY.value):
            text = text.removeprefix(NetscapeMark.HTTP_ONLY.value)
        elif not text or text.startswith(COMMENT_PREFIX):
            return None
        fields: list[str] = text.split(NetscapeMark.SEPARATOR.value)
        if len(fields) <= NetscapeField.VALUE or not fields[NetscapeField.EXPIRES].isdigit():
            return None
        return cls(fields[NetscapeField.DOMAIN], fields[NetscapeField.NAME], int(fields[NetscapeField.EXPIRES]))

    @property
    def is_login(self) -> bool:
        """Cookie входа в аккаунт YouTube: домен youtube.com и имя из ресурса имён."""
        is_youtube: bool = self.domain.endswith(NetscapeMark.YOUTUBE_DOMAIN.value)
        return is_youtube and self.name in TextResource(LOGIN_NAMES_RESOURCE).lines


@dataclass(frozen=True)
class CookiesFile:
    """Файл cookies `path`; даты — в поясе программы `zone`."""

    path: Path
    zone: tzinfo

    @property
    def exists(self) -> bool:
        return self.path.is_file()

    @property
    def is_netscape(self) -> bool:
        """Первая непустая строка — заголовок Netscape."""
        first: str = next((line.strip() for line in self._lines() if line.strip()), "")
        return first.startswith(NETSCAPE_HEADER)

    @property
    def exported(self) -> datetime:
        """Дата выгрузки — время изменения файла: программа его не пишет, yt-dlp получает копию."""
        return datetime.fromtimestamp(self.path.stat().st_mtime, self.zone)

    @property
    def login_cookies(self) -> tuple[NetscapeCookie, ...]:
        """Cookies входа в аккаунт YouTube в файле по порядку."""
        cookies: tuple[NetscapeCookie | None, ...] = tuple(NetscapeCookie.of_line(line) for line in self._lines())
        return tuple(cookie for cookie in cookies if cookie is not None and cookie.is_login)

    @property
    def login_expires(self) -> datetime | None:
        """Самый поздний срок cookies входа; у них только сеансовые сроки или их нет — None."""
        latest: int = max((cookie.expires for cookie in self.login_cookies), default=SESSION_EXPIRES)
        return None if latest == SESSION_EXPIRES else datetime.fromtimestamp(latest, self.zone)

    def place_from(self, source: Path) -> CookiesPlaceProblem | None:
        """Файл `source` — на место этого: не Netscape — прежний файл не тронут; годный — копией со временем изменения
        источника (дата выгрузки), целиком или никак. Источник и есть этот файл — без копии. Не вышло — причина."""
        loaded: CookiesFile = CookiesFile(source, self.zone)
        try:
            if not loaded.is_netscape:
                return CookiesPlaceProblem.NOT_NETSCAPE
        except OSError:
            return CookiesPlaceProblem.UNREADABLE
        if source.resolve() == self.path.resolve():
            return None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            AtomicFile.at(self.path).write(lambda temp: shutil.copy2(source, temp))
        except OSError:
            return CookiesPlaceProblem.NOT_WRITTEN
        return None

    def _lines(self) -> list[str]:
        """Строки файла; BOM и неверные байты не мешают."""
        return self.path.read_bytes().decode(BOM_TOLERANT_ENCODING, errors=EncodingErrors.REPLACE.value).splitlines()
