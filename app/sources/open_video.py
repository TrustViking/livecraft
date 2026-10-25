"""Данные видео без входа в YouTube (CLAUDE.md §3 шаг 2.4, §14 решение 80).

Работа программы не зависит от входа в YouTube: ей нужны название, описание, превью и язык видео, а их YouTube
отдаёт и без входа. yt-dlp читает видео с ключом `--ignore-no-formats-error` (app\\sources\\ytdlp.py) — и видео с
проверкой возраста приходит с названием, описанием и обложкой. Когда yt-dlp всё же отказал (YouTube просит войти,
подтвердить, что запрос не от бота, yt-dlp не ответил вовремя), данные спрашиваются открыто:

- `OpenVideoData` — название открытым запросом oEmbed YouTube (`https://www.youtube.com/oembed?url=<ссылка>&format=json`,
  без входа и без yt-dlp), обложка — по id видео (`hqdefault.jpg`), описания нет; язык решается прежним правилом по
  названию (app\\sources\\language.py). oEmbed названия не отдал (видео приватное или удалено) — открытых данных нет;
- `VideoData` — получатель данных видео запуска (`MetadataFetcher`): сначала yt-dlp, при его отказе — открытые данные;
  открытых данных нет — прежний отказ yt-dlp с его причиной: человеку она говорит, что делать.

Запрос oEmbed — один, без повторов: это запасной путь после отказа yt-dlp, а не основной.
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from http import HTTPStatus
from typing import Final

import requests

from app.core.youtube_video import YouTubeVideoId
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.paths import LivecraftPaths
from app.sources.fetcher import MetadataFetcher, SourceFetch
from app.sources.metadata import SourceMetadata
from app.sources.ytdlp import YtDlpFetcher

LOGGER = get_logger(LogArea.SOURCES)

OEMBED_URL: Final[str] = "https://www.youtube.com/oembed"
OEMBED_TIMEOUT_SEC: Final[float] = 20.0


class OembedKey(str, Enum):
    """Параметры запроса oEmbed и поле ответа, которое читает программа."""

    URL = "url"
    FORMAT = "format"
    JSON = "json"
    TITLE = "title"


class OpenDataEvent(str, Enum):
    """События открытых данных видео в логе."""

    USED = "source_open_data"
    REFUSED = "source_open_data_refused"


@dataclass(frozen=True)
class OpenVideoData:
    """Открытые данные видео: `get` — `requests.get` или подделка, `timeout_sec` — таймаут запроса oEmbed."""

    get: Callable[..., requests.Response] = requests.get
    timeout_sec: float = OEMBED_TIMEOUT_SEC

    def metadata(self, url: str) -> SourceMetadata | None:
        """Название из oEmbed и обложка по id видео ссылки `url`; id нет или названия oEmbed не дал — None."""
        video: YouTubeVideoId | None = YouTubeVideoId.of(url)
        if video is None:
            return None
        title: str = self._title(url)
        return SourceMetadata.of_open(video, url, title) if title else None

    def _title(self, url: str) -> str:
        """Название видео из oEmbed; сбой сети, не 200 или ответ без названия — пустая строка, причина — в лог."""
        params: dict[str, str] = {OembedKey.URL.value: url, OembedKey.FORMAT.value: OembedKey.JSON.value}
        try:
            response: requests.Response = self.get(OEMBED_URL, params=params, timeout=self.timeout_sec)
            answer: object = response.json() if response.status_code == HTTPStatus.OK else None
        except requests.RequestException as error:
            LogEvent.of(OpenDataEvent.REFUSED, url=url, error=type(error).__name__).emit(LOGGER, logging.WARNING)
            return ""
        title: object = answer.get(OembedKey.TITLE.value) if isinstance(answer, dict) else None
        if not isinstance(title, str) or not title.strip():
            LogEvent.of(OpenDataEvent.REFUSED, url=url, status=response.status_code).emit(LOGGER, logging.WARNING)
            return ""
        return title.strip()


@dataclass(frozen=True)
class VideoData:
    """Данные видео запуска: yt-dlp (`ytdlp`), при его отказе — открытые данные (`open_data`). Реализует
    `MetadataFetcher`."""

    ytdlp: MetadataFetcher
    open_data: OpenVideoData

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> VideoData:
        return cls(ytdlp=YtDlpFetcher.from_paths(paths), open_data=OpenVideoData())

    def fetch(self, url: str) -> SourceFetch:
        """yt-dlp; отказал после ответа YouTube — открытые данные, их нет — отказ yt-dlp как есть."""
        fetched: SourceFetch = self.ytdlp.fetch(url)
        if fetched.failure is None or not fetched.failure.is_answer_from_youtube:
            return fetched
        metadata: SourceMetadata | None = self.open_data.metadata(url)
        if metadata is None:
            return fetched
        used: LogEvent = LogEvent.of(OpenDataEvent.USED, url=url, ytdlp_failure=fetched.failure)
        used.extended(detail=fetched.detail).emit(LOGGER, logging.WARNING)
        return SourceFetch.from_metadata(url, metadata)
