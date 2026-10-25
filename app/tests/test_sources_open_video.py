"""Данные видео без входа в YouTube (CLAUDE.md §14 решение 80): yt-dlp с `--ignore-no-formats-error`, при его отказе —
открытые данные (oEmbed и обложка по id). yt-dlp и HTTP подменены; разбор, язык и строки — боевые."""
from __future__ import annotations

import json
import logging
import subprocess
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
import requests

from app.core.retry import RetryPolicy
from app.observability.log_event import LogArea
from app.paths import FileName, LivecraftPaths
from app.sheets.rows import PlannedRows
from app.sources.fetcher import SourceFetch
from app.sources.language import LanguageResolver
from app.sources.metadata import SourceFailureReason
from app.sources.open_video import OEMBED_URL, OpenVideoData, VideoData
from app.sources.preview import PreviewDownloader
from app.sources.video import PreparedSources, SourceCatalog, SourceVideo
from app.sources.ytdlp import YtDlpFetcher
from app.runtime.ytdlp_launch import YtDlpLaunch
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.sources import admitted_row

KYIV: timezone = timezone(timedelta(hours=3))
START: datetime = datetime(2026, 10, 26, 19, 0, tzinfo=KYIV)
AGE_ID: str = "kyaoIA58xOQ"
AGE_LINK: str = f"https://youtu.be/{AGE_ID}"
AGE_TITLE: str = "The Victims of the Expedition in Africa | Abridged Version"
AGE_STDERR: str = f"ERROR: [youtube] {AGE_ID}: Sign in to confirm your age. This video may be inappropriate for some users."
BOT_STDERR: str = f"ERROR: [youtube] {AGE_ID}: Sign in to confirm you’re not a bot. Use --cookies-from-browser"
PRIVATE_STDERR: str = f"ERROR: [youtube] {AGE_ID}: Private video. Sign in if you've been granted access to this video"


class _Run:
    """Подделка subprocess.run: один ответ yt-dlp на любой вызов; команды запоминаются."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode: int = returncode
        self.stdout: str = stdout
        self.stderr: str = stderr
        self.commands: list[list[str]] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        return subprocess.CompletedProcess(command, self.returncode, stdout=self.stdout, stderr=self.stderr)


class _Response:
    """Ответ HTTP: код, тело JSON (oEmbed) и байты (обложка)."""

    def __init__(self, status_code: int, payload: object = None, content: bytes = b"") -> None:
        self.status_code: int = status_code
        self.payload: object = payload
        self.content: bytes = content

    def json(self) -> object:
        if self.payload is None:
            raise requests.JSONDecodeError("no json", "", 0)
        return self.payload


class _Web:
    """Подделка requests.get: oEmbed отвечает `oembed`, обложка — картинкой или 404; адреса запоминаются."""

    def __init__(self, oembed: _Response | requests.RequestException, cover: bytes = b"") -> None:
        self.oembed: _Response | requests.RequestException = oembed
        self.cover: bytes = cover
        self.calls: list[tuple[str, dict[str, str] | None]] = []

    def __call__(self, url: str, params: dict[str, str] | None = None, timeout: float = 0.0) -> _Response:
        self.calls.append((url, params))
        if url != OEMBED_URL:
            return _Response(200, content=self.cover) if self.cover else _Response(404)
        if isinstance(self.oembed, requests.RequestException):
            raise self.oembed
        return self.oembed


@pytest.fixture
def log() -> Iterator[LogCapture]:
    with LogCapture.on(LogArea.SOURCES, logging.DEBUG) as capture:
        yield capture


@pytest.fixture
def ytdlp_paths(livecraft_paths: LivecraftPaths) -> LivecraftPaths:
    """Корень с tools\\yt-dlp.exe (пустой файл: вызов подменяется)."""
    livecraft_paths.file(FileName.YTDLP).write_bytes(b"")
    return livecraft_paths


def _catalog(paths: LivecraftPaths, run: _Run, web: _Web) -> SourceCatalog:
    """Каталог запуска на боевых объектах: yt-dlp и открытые данные (`VideoData`), обложки, язык ресурсов."""
    ytdlp: YtDlpFetcher = YtDlpFetcher(launch=YtDlpLaunch.of(paths), deno_exe=paths.file(FileName.DENO), run=run)
    return SourceCatalog(
        fetcher=VideoData(ytdlp=ytdlp, open_data=OpenVideoData(get=web)),
        downloader=PreviewDownloader(session_get=web, policy=RetryPolicy(max_retries=0), sleep=lambda _s: None),
        resolver=LanguageResolver.from_resources(),
    )


def _prepared(catalog: SourceCatalog, row: int = 16) -> PreparedSources:
    return catalog.prepare(PlannedRows(admitted=(admitted_row(row, AGE_LINK, START),), skipped=()))


def test_ytdlp_reads_an_age_restricted_video_without_formats(ytdlp_paths: LivecraftPaths) -> None:
    """Проба 24-10-2026: с `--ignore-no-formats-error` видео 18+ приходит с названием, описанием и обложкой, без форматов
    и языка — язык решается по тексту, открытые данные не нужны."""
    answer: dict[str, Any] = {
        "id": AGE_ID, "title": AGE_TITLE, "description": "A documentary about the expedition and its victims in Africa.",
        "thumbnail": f"https://i.ytimg.com/vi/{AGE_ID}/maxresdefault.jpg", "formats": [], "age_limit": 18,
    }
    run: _Run = _Run(0, stdout=json.dumps(answer))
    web: _Web = _Web(_Response(500))
    video: SourceVideo = _prepared(_catalog(ytdlp_paths, run, web)).videos[0]
    assert "--ignore-no-formats-error" in run.commands[0]
    assert video.is_ready and video.language_code == "en" and video.has_description
    assert all(url != OEMBED_URL for url, _params in web.calls)


def test_an_age_refusal_takes_the_open_data_and_the_video_goes_without_a_description(
    ytdlp_paths: LivecraftPaths, log: LogCapture
) -> None:
    """yt-dlp отказал по возрасту — название из oEmbed, обложка по id, описания нет, язык — по названию."""
    web: _Web = _Web(_Response(200, {"title": AGE_TITLE, "author_name": "Channel"}))
    prepared: PreparedSources = _prepared(_catalog(ytdlp_paths, _Run(1, stderr=AGE_STDERR), web))
    video: SourceVideo = prepared.videos[0]
    assert video.is_ready and video.refusal is None
    assert (video.text.title, video.text.description, video.language_code) == (AGE_TITLE, "", "en")
    assert video.facts.fetch.metadata is not None
    assert video.facts.fetch.metadata.thumbnail_url == f"https://i.ytimg.com/vi/{AGE_ID}/hqdefault.jpg"
    assert web.calls[0] == (OEMBED_URL, {"url": AGE_LINK, "format": "json"})
    assert web.calls[1][0] == f"https://i.ytimg.com/vi/{AGE_ID}/hqdefault.jpg"
    assert prepared.console_line == "Видео: годных 1 из 1, без превью 1, без описания 1."
    assert prepared.refusal_lines == () and not prepared.has_errors
    assert any(line.startswith("source_open_data ") and "ytdlp_failure=age" in line for line in log.messages())


def test_a_private_video_is_refused_with_an_attention_line_and_an_action(ytdlp_paths: LivecraftPaths) -> None:
    """Приватное: oEmbed названия не отдаёт (401) — видео негодно, ВНИМАНИЕ называет ряд, ссылку, причину и действие."""
    web: _Web = _Web(_Response(401))
    prepared: PreparedSources = _prepared(_catalog(ytdlp_paths, _Run(1, stderr=PRIVATE_STDERR), web))
    assert prepared.videos[0].refusal is SourceFailureReason.PRIVATE
    assert prepared.console_line == "Видео: годных 0 из 1, без превью 0; не годны — приватное: 1."
    assert prepared.refusal_lines == (
        f"ВНИМАНИЕ — ряд 16, {AGE_LINK}: видео приватное — откройте к нему доступ по ссылке или замените ссылку в "
        "таблице",
    )


@pytest.mark.parametrize("oembed", [_Response(404), _Response(200, {"title": "  "}), requests.ConnectionError()])
def test_a_bot_check_without_open_data_is_its_own_line(
    ytdlp_paths: LivecraftPaths, oembed: _Response | requests.RequestException
) -> None:
    """«Не бот» и открытых данных нет (не 200, пустое название, сбой сети) — своя причина и своё действие."""
    prepared: PreparedSources = _prepared(_catalog(ytdlp_paths, _Run(1, stderr=BOT_STDERR), _Web(oembed)))
    assert prepared.videos[0].refusal is SourceFailureReason.BOT
    assert prepared.refusal_lines == (
        f"ВНИМАНИЕ — ряд 16, {AGE_LINK}: YouTube просит подтвердить, что запрос не от бота — запустите снова позже",
    )


def test_without_ytdlp_the_open_data_is_not_asked(livecraft_paths: LivecraftPaths) -> None:
    """Нет yt-dlp — не отказ YouTube: его чинит загрузка yt-dlp, открытых данных не спрашивают."""
    web: _Web = _Web(_Response(200, {"title": AGE_TITLE}))
    fetched: SourceFetch = _catalog(livecraft_paths, _Run(0), web).fetcher.fetch(AGE_LINK)
    assert fetched.failure is SourceFailureReason.TOOL_MISSING and web.calls == []


def test_a_link_without_a_video_id_has_no_open_data() -> None:
    web: _Web = _Web(_Response(200, {"title": AGE_TITLE}))
    assert OpenVideoData(get=web).metadata("https://example.org/watch") is None and web.calls == []
