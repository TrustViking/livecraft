from __future__ import annotations

import io
import json
import logging
import os
import random
import subprocess
from collections.abc import Iterator
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest
import requests
from PIL import Image

from app.core.retry import RetryPolicy
from app.observability.log_event import LogArea
from app.paths import FileName, LivecraftPaths
from app.observability.log_event import LogEvent
from app.sheets.rows import AdmittedRow, PlannedRows, RowSkipReason, SheetRow, SkippedRow
from app.slots.preview import Preview
from app.slots.slot import SlotKey
from app.slots.texts import SourceText
from app.sources.fetcher import MetadataFetcher, SourceFetch
from app.sources.language import LanguageDecision, LanguageResolver, LanguageSource
from app.sources.metadata import SourceFailureReason, SourceMetadata
from app.sources.preview import PreviewDownloader, PreviewNormalizer, PreviewProblem, PreviewResult
from app.sources.video import PreparedSources, SourceCatalog, SourceFacts, SourceVideo, VideoCheck, VideoFit
from app.sources.ytdlp import DETAIL_MAX_CHARS, YTDLP_TIMEOUT_SEC, YtDlpFetcher, YtDlpRefusalMarkers, YtDlpResult
from app.run.progress import StageProgress
from app.runtime.ytdlp_launch import YtDlpLaunch
from app.tests.fixtures.console import ConsoleRecord
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.sources import admitted_row
from app.ui import messages_ru as msg

DATA_DIR: Path = Path(__file__).resolve().parent / "data" / "ytdlp"
KYIV: timezone = timezone(timedelta(hours=3))
START: datetime = datetime(2026, 10, 16, 19, 0, tzinfo=KYIV)
LINK: str = "https://youtu.be/dQw4w9WgXcQ"
OTHER_LINK: str = "https://youtu.be/aB3_-xYz012"
THIRD_LINK: str = "https://youtu.be/Zx9_8yW7v6U"
THUMBNAIL: str = "https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"
RESOLVER: LanguageResolver = LanguageResolver.from_resources()
# video_full.json: язык видео и звук — uk, название и описание langdetect читает как ru → ничья арбитров
FULL_LANGUAGE: str = "language=uk language_source=metadata_arbitration_fallback"
COOKIES_TEXT: bytes =b"# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tvalue\n"


def load_info(name: str) -> dict[str, Any]:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def png_bytes(size: tuple[int, int] = (64, 36), mode: str = "RGBA") -> bytes:
    output: io.BytesIO = io.BytesIO()
    Image.new(mode, size, (200, 30, 30, 128) if mode == "RGBA" else (200, 30, 30)).save(output, format="PNG")
    return output.getvalue()


def noise_image(side: int) -> bytes:
    """Шум без повторов (BMP — быстро пишется): JPEG такой картинки почти не сжимается. Сид — фиксированный."""
    rng: random.Random = random.Random(7)
    output: io.BytesIO = io.BytesIO()
    Image.frombytes("RGB", (side, side), rng.randbytes(side * side * 3)).save(output, format="BMP")
    return output.getvalue()


@pytest.fixture
def log() -> Iterator[LogCapture]:
    with LogCapture.on(LogArea.SOURCES, logging.DEBUG) as capture:
        yield capture


# --- SourceMetadata.from_ytdlp


def test_full_answer_gives_every_field() -> None:
    metadata: SourceMetadata = SourceMetadata.from_ytdlp(LINK, load_info("video_full.json"))
    assert metadata.url == LINK
    assert metadata.video_id == "dQw4w9WgXcQ"
    assert metadata.title == "Тестовый эфир: разбор вопросов | #12"
    assert metadata.description == "Короткое тестовое описание.\nВторая строка."
    assert metadata.thumbnail_url == THUMBNAIL
    assert metadata.youtube_language == "uk"
    assert metadata.channel_language == "ru"
    assert metadata.duration_seconds == 3723
    assert metadata.audio_languages == ("uk", "en")
    assert metadata.subtitle_languages == ("uk", "en")
    assert metadata.auto_caption_languages == ("uk", "ru", "de")
    assert metadata.problem is None


def test_empty_thumbnail_falls_back_to_hqdefault_by_id(log: LogCapture) -> None:
    metadata: SourceMetadata = SourceMetadata.from_ytdlp(OTHER_LINK, load_info("video_no_thumbnail.json"))
    assert metadata.thumbnail_url == "https://i.ytimg.com/vi/aB3_-xYz012/hqdefault.jpg"
    assert metadata.youtube_language is None
    assert metadata.channel_language is None
    assert metadata.duration_seconds is None
    assert metadata.audio_languages == ()
    assert metadata.subtitle_languages == ()
    assert any("source_thumbnail_fallback" in line for line in log.messages(logging.WARNING))


def test_fallback_takes_the_id_from_the_link_when_the_answer_has_none() -> None:
    info: dict[str, Any] = {"title": "Без id", "thumbnail": ""}
    metadata: SourceMetadata = SourceMetadata.from_ytdlp(LINK, info)
    assert metadata.thumbnail_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"


def test_no_id_anywhere_leaves_the_thumbnail_empty() -> None:
    metadata: SourceMetadata = SourceMetadata.from_ytdlp("https://example.org/x", {"title": "Нет id"})
    assert metadata.thumbnail_url == ""
    assert metadata.problem is None


def test_empty_description_is_not_a_problem_but_a_log_line(log: LogCapture) -> None:
    metadata: SourceMetadata = SourceMetadata.from_ytdlp(THIRD_LINK, load_info("video_no_description.json"))
    assert metadata.description == ""
    assert metadata.problem is None
    assert metadata.duration_seconds == 95
    assert any("source_description_empty" in line for line in log.messages(logging.WARNING))


@pytest.mark.parametrize("title", [None, "", "   ", "#только #хештеги"])
def test_empty_title_builds_the_object_and_names_the_problem(title: str | None) -> None:
    info: dict[str, Any] = load_info("video_full.json") | {"title": title}
    metadata: SourceMetadata = SourceMetadata.from_ytdlp(LINK, info)
    assert metadata.title == ""
    assert metadata.problem is SourceFailureReason.NO_TITLE
    assert metadata.video_id == "dQw4w9WgXcQ"


@pytest.mark.parametrize("duration", [True, "3600", -5, None])
def test_duration_that_is_not_a_positive_number_is_none(duration: Any) -> None:
    info: dict[str, Any] = {"title": "t", "duration": duration}
    assert SourceMetadata.from_ytdlp(LINK, info).duration_seconds is None


def test_malformed_lists_do_not_break_the_object() -> None:
    info: dict[str, Any] = {"title": "t", "formats": "none", "subtitles": ["uk"], "automatic_captions": None}
    metadata: SourceMetadata = SourceMetadata.from_ytdlp(LINK, info)
    assert metadata.audio_languages == ()
    assert metadata.subtitle_languages == ()
    assert metadata.auto_caption_languages == ()


def test_log_fields_have_no_title_or_description() -> None:
    metadata: SourceMetadata = SourceMetadata.from_ytdlp(LINK, load_info("video_full.json"))
    line: str = LogEvent.of("probe", **metadata.log_fields).text
    assert "Тестовый" not in line
    assert "описание" not in line
    assert "id=dQw4w9WgXcQ" in line


def test_the_fetch_log_fields_are_the_summary_or_the_reason() -> None:
    ok: SourceFetch = SourceFetch.from_metadata(LINK, SourceMetadata.from_ytdlp(LINK, load_info("video_full.json")))
    assert LogEvent.of("fetch", **ok.log_fields).text.startswith("fetch result=ok id=dQw4w9WgXcQ ")
    failed: SourceFetch = SourceFetch.failed(LINK, SourceFailureReason.TIMEOUT, "timeout_sec=30")
    assert LogEvent.of("fetch", **failed.log_fields).text == "fetch result=timeout detail=timeout_sec=30"


# --- YtDlpFetcher


class _FakeRun:
    """Подделка subprocess.run: запоминает команду и ключи, видит копию cookies во время вызова."""

    def __init__(
        self,
        stdout: str = "",
        stderr: str = "",
        returncode: int = 0,
        error: BaseException | None = None,
        write_to_cookies: bool = False,
    ) -> None:
        self.stdout: str = stdout
        self.stderr: str = stderr
        self.returncode: int = returncode
        self.error: BaseException | None = error
        self.write_to_cookies: bool = write_to_cookies
        self.commands: list[list[str]] = []
        self.kwargs: list[dict[str, Any]] = []
        self.cookies_seen: list[bytes] = []

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        self.commands.append(list(command))
        self.kwargs.append(kwargs)
        if "--cookies" in command:
            copy: Path = Path(command[command.index("--cookies") + 1])
            self.cookies_seen.append(copy.read_bytes())
            if self.write_to_cookies:
                copy.write_bytes(b"# rewritten by yt-dlp\n")
        if self.error is not None:
            raise self.error
        return subprocess.CompletedProcess(command, self.returncode, stdout=self.stdout, stderr=self.stderr)

    @property
    def cookies_copy(self) -> Path:
        command: list[str] = self.commands[-1]
        return Path(command[command.index("--cookies") + 1])


@pytest.fixture
def ytdlp_paths(livecraft_paths: LivecraftPaths) -> LivecraftPaths:
    """Корень, где лежит tools\\yt-dlp.exe (пустой файл: настоящий вызов подменяется)."""
    livecraft_paths.file(FileName.YTDLP).write_bytes(b"")
    return livecraft_paths


def fetcher_for(paths: LivecraftPaths, run: _FakeRun) -> YtDlpFetcher:
    return YtDlpFetcher(launch=YtDlpLaunch.of(paths), deno_exe=paths.file(FileName.DENO), run=run)


def full_json() -> str:
    return (DATA_DIR / "video_full.json").read_text(encoding="utf-8")


def launch_head(paths: LivecraftPaths) -> list[str]:
    """Начало каждой команды yt-dlp: exe и папка кэша в state\\ (§14 решение 56)."""
    return [str(paths.file(FileName.YTDLP)), "--cache-dir", str(paths.file(FileName.YTDLP_CACHE))]


def test_from_paths_takes_the_tools_and_cookies_of_the_root(livecraft_paths: LivecraftPaths) -> None:
    fetcher: YtDlpFetcher = YtDlpFetcher.from_paths(livecraft_paths)
    assert fetcher.launch == YtDlpLaunch.of(livecraft_paths)
    assert fetcher.deno_exe == livecraft_paths.file(FileName.DENO)
    assert fetcher.timeout_sec == YTDLP_TIMEOUT_SEC
    assert fetcher.run is subprocess.run


def test_command_without_cookies_and_deno(ytdlp_paths: LivecraftPaths) -> None:
    run: _FakeRun = _FakeRun(stdout=full_json())
    fetched: SourceFetch = fetcher_for(ytdlp_paths, run).fetch(LINK)
    assert fetched.is_ok
    assert run.commands == [
        [*launch_head(ytdlp_paths), "--dump-single-json", "--no-warnings", "--skip-download", "--no-playlist", LINK]
    ]
    assert run.kwargs[0] == {
        "capture_output": True,
        "text": True,
        "check": False,
        "timeout": YTDLP_TIMEOUT_SEC,
        "encoding": "utf-8",
        "errors": "replace",
        "env": YtDlpLaunch.of(ytdlp_paths).env,
    }
    assert run.kwargs[0]["env"]["DENO_DIR"] == str(ytdlp_paths.file(FileName.DENO_CACHE))


def test_command_with_cookies_copy_and_deno(ytdlp_paths: LivecraftPaths) -> None:
    ytdlp_paths.file(FileName.COOKIES).write_bytes(COOKIES_TEXT)
    ytdlp_paths.file(FileName.DENO).write_bytes(b"")
    run: _FakeRun = _FakeRun(stdout=full_json())
    fetcher_for(ytdlp_paths, run).fetch(LINK)
    command: list[str] = run.commands[0]
    copy: Path = run.cookies_copy
    assert command == [
        *launch_head(ytdlp_paths),
        "--dump-single-json",
        "--no-warnings",
        "--skip-download",
        "--no-playlist",
        "--cookies",
        str(copy),
        "--js-runtimes",
        f"deno:{ytdlp_paths.file(FileName.DENO)}",
        LINK,
    ]
    assert copy != ytdlp_paths.file(FileName.COOKIES)
    assert copy.parent == ytdlp_paths.file(FileName.COOKIES).parent      # копия — в secrets\, не в %TEMP%
    assert run.cookies_seen == [COOKIES_TEXT]


@pytest.mark.parametrize("outcome", ["ok", "refused", "timeout", "start_failed"])
def test_cookies_copy_is_removed_and_the_original_is_untouched(ytdlp_paths: LivecraftPaths, outcome: str) -> None:
    ytdlp_paths.file(FileName.COOKIES).write_bytes(COOKIES_TEXT)
    old_time: float = 1_700_000_000.0
    os.utime(ytdlp_paths.file(FileName.COOKIES), (old_time, old_time))
    runs: dict[str, _FakeRun] = {
        "ok": _FakeRun(stdout=full_json(), write_to_cookies=True),
        "refused": _FakeRun(returncode=1, stderr="ERROR: Private video", write_to_cookies=True),
        "timeout": _FakeRun(error=subprocess.TimeoutExpired(["yt-dlp"], YTDLP_TIMEOUT_SEC), write_to_cookies=True),
        "start_failed": _FakeRun(error=PermissionError("denied"), write_to_cookies=True),
    }
    run: _FakeRun = runs[outcome]
    fetcher_for(ytdlp_paths, run).fetch(LINK)
    assert not run.cookies_copy.exists()
    assert ytdlp_paths.file(FileName.COOKIES).read_bytes() == COOKIES_TEXT
    assert ytdlp_paths.file(FileName.COOKIES).stat().st_mtime == old_time


def test_unreadable_cookies_mean_a_call_without_cookies(
    ytdlp_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch
) -> None:
    ytdlp_paths.file(FileName.COOKIES).write_bytes(COOKIES_TEXT)

    def _deny(source: Path, target: Path) -> None:
        raise PermissionError("locked")

    monkeypatch.setattr("app.runtime.ytdlp_launch.shutil.copyfile", _deny)
    run: _FakeRun = _FakeRun(stdout=full_json())
    assert fetcher_for(ytdlp_paths, run).fetch(LINK).is_ok
    assert "--cookies" not in run.commands[0]


@pytest.mark.parametrize(
    ("stderr", "reason"),
    [
        ("ERROR: [youtube] x: Private video. Sign in if you've been granted access", SourceFailureReason.PRIVATE),
        ("ERROR: [youtube] x: Sign in to confirm you're not a bot", SourceFailureReason.PRIVATE),
        ("ERROR: [youtube] dQw4w9WgXcQ: Video unavailable", SourceFailureReason.UNAVAILABLE),
        ("ERROR: This video has been removed by the uploader", SourceFailureReason.UNAVAILABLE),
        ("ERROR: Unable to download webpage: HTTP Error 500", SourceFailureReason.FAILED),
    ],
)
def test_refusal_is_named_by_stderr(ytdlp_paths: LivecraftPaths, stderr: str, reason: SourceFailureReason) -> None:
    run: _FakeRun = _FakeRun(returncode=1, stderr=f"WARNING: first\n{stderr}")
    fetched: SourceFetch = fetcher_for(ytdlp_paths, run).fetch(LINK)
    assert fetched.failure is reason
    assert fetched.metadata is None
    assert not fetched.is_ok
    assert fetched.detail == "WARNING: first"


def test_detail_is_the_first_line_cut_and_full_stderr_goes_only_to_debug(
    ytdlp_paths: LivecraftPaths, log: LogCapture
) -> None:
    long_line: str = "ERROR: " + "x" * 500
    tail: str = "SECOND-LINE-ONLY-IN-DEBUG"
    run: _FakeRun = _FakeRun(returncode=1, stderr=f"\n  {long_line}\n{tail}\n")
    fetched: SourceFetch = fetcher_for(ytdlp_paths, run).fetch(LINK)
    assert fetched.detail == long_line[:DETAIL_MAX_CHARS]
    debug_lines: list[str] = log.messages(logging.DEBUG)
    other_lines: list[str] = [record.getMessage() for record in log.records if record.levelno > logging.DEBUG]
    assert any(tail in line for line in debug_lines)
    assert not any(tail in line for line in other_lines)


def test_refusal_markers_are_the_resource_files() -> None:
    assert YtDlpRefusalMarkers.load() == YtDlpRefusalMarkers(
        private=("Private video", "Sign in to confirm", "Sign in if you"),
        unavailable=("Video unavailable", "removed by the uploader"),
    )


def test_empty_stderr_on_failure_gives_the_exit_code() -> None:
    result: YtDlpResult = YtDlpResult(returncode=2, stdout="", stderr="")
    assert result.refusal is SourceFailureReason.FAILED
    assert result.detail == "exit_code=2"


class _TimeoutsFirst(_FakeRun):
    """Подделка subprocess.run: первые `timeouts` вызовов — таймаут, дальше — ответ."""

    def __init__(self, timeouts: int, stdout: str = "") -> None:
        super().__init__(stdout=stdout)
        self.timeouts: int = timeouts

    def __call__(self, command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        if len(self.commands) < self.timeouts:
            self.commands.append(list(command))
            self.kwargs.append(kwargs)
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return super().__call__(command, **kwargs)


def test_a_timeout_is_tried_once_more_with_the_timeout_doubled(ytdlp_paths: LivecraftPaths, log: LogCapture) -> None:
    """Машина под нагрузкой: первый вызов упёрся в 30 с — второй сразу, с 60 с, и видео прочитано."""
    run: _TimeoutsFirst = _TimeoutsFirst(timeouts=1, stdout=full_json())
    fetched: SourceFetch = fetcher_for(ytdlp_paths, run).fetch(LINK)
    assert fetched.is_ok
    assert [kwargs["timeout"] for kwargs in run.kwargs] == [30.0, 60.0]
    assert any(line.startswith("ytdlp_timeout_retry") and "timeout_sec=60" in line for line in log.messages())


def test_two_timeouts_are_a_timeout_after_the_longer_wait(ytdlp_paths: LivecraftPaths) -> None:
    run: _TimeoutsFirst = _TimeoutsFirst(timeouts=2)
    fetched: SourceFetch = fetcher_for(ytdlp_paths, run).fetch(LINK)
    assert fetched.failure is SourceFailureReason.TIMEOUT
    assert fetched.detail == "timeout_sec=60"
    assert len(run.commands) == 2


def test_a_refusal_is_not_tried_again(ytdlp_paths: LivecraftPaths) -> None:
    run: _FakeRun = _FakeRun(returncode=1, stderr="ERROR: [youtube] x: Private video")
    fetched: SourceFetch = fetcher_for(ytdlp_paths, run).fetch(LINK)
    assert fetched.failure is SourceFailureReason.PRIVATE
    assert len(run.commands) == 1


def test_exe_that_does_not_start_is_failed(ytdlp_paths: LivecraftPaths) -> None:
    run: _FakeRun = _FakeRun(error=PermissionError("denied"))
    fetched: SourceFetch = fetcher_for(ytdlp_paths, run).fetch(LINK)
    assert fetched.failure is SourceFailureReason.FAILED
    assert fetched.detail == "PermissionError"


def test_missing_exe_is_tool_missing_without_a_call(livecraft_paths: LivecraftPaths) -> None:
    run: _FakeRun = _FakeRun(stdout=full_json())
    fetched: SourceFetch = fetcher_for(livecraft_paths, run).fetch(LINK)
    assert fetched.failure is SourceFailureReason.TOOL_MISSING
    assert run.commands == []


@pytest.mark.parametrize("stdout", ["not json at all", "", "[1, 2]", "null"])
def test_garbage_in_stdout_is_bad_output(ytdlp_paths: LivecraftPaths, stdout: str) -> None:
    fetched: SourceFetch = fetcher_for(ytdlp_paths, _FakeRun(stdout=stdout)).fetch(LINK)
    assert fetched.failure is SourceFailureReason.BAD_OUTPUT
    assert fetched.metadata is None


def test_answer_without_title_is_no_title_but_keeps_the_object(ytdlp_paths: LivecraftPaths) -> None:
    info: dict[str, Any] = load_info("video_full.json") | {"title": ""}
    fetched: SourceFetch = fetcher_for(ytdlp_paths, _FakeRun(stdout=json.dumps(info))).fetch(LINK)
    assert fetched.failure is SourceFailureReason.NO_TITLE
    assert fetched.metadata is not None
    assert fetched.metadata.video_id == "dQw4w9WgXcQ"
    assert not fetched.is_ok


def test_every_failure_reason_has_a_russian_text() -> None:
    for reason in SourceFailureReason:
        assert reason.human == msg.SOURCE_FAILURE_REASONS[reason.value]
    for problem in PreviewProblem:
        assert problem.human == msg.PREVIEW_PROBLEMS[problem.value]


# --- PreviewNormalizer: скачанная картинка → обложка


def test_small_png_becomes_a_jpeg() -> None:
    result: PreviewResult = PreviewNormalizer().normalized(png_bytes((64, 36)))
    assert result.is_ok and result.problem is None
    preview: Preview | None = result.preview
    assert preview is not None
    assert preview.data.startswith(b"\xff\xd8\xff")
    assert (preview.width, preview.height) == (64, 36)
    assert preview.mime_type == "image/jpeg"
    with Image.open(io.BytesIO(preview.data)) as image:
        assert image.format == "JPEG" and image.mode == "RGB"


@pytest.mark.parametrize("raw", [b"", b"not an image", png_bytes()[:40]])
def test_garbage_is_not_an_image(raw: bytes) -> None:
    result: PreviewResult = PreviewNormalizer().normalized(raw)
    assert result.preview is None
    assert result.problem is PreviewProblem.NOT_IMAGE


def test_large_noisy_image_is_squeezed_by_lower_quality() -> None:
    """1600×1600 шума: при quality 90 больше 2 МБ, при 80 — меньше (замер Pillow 12)."""
    raw: bytes = noise_image(1600)
    with Image.open(io.BytesIO(raw)) as image:
        at_90: io.BytesIO = io.BytesIO()
        image.convert("RGB").save(at_90, format="JPEG", quality=90)
    assert len(at_90.getvalue()) > Preview.MAX_BYTES
    result: PreviewResult = PreviewNormalizer().normalized(raw)
    assert result.preview is not None
    assert result.preview.size_bytes <= Preview.MAX_BYTES


def test_image_too_large_even_at_the_lowest_quality_is_a_problem() -> None:
    result: PreviewResult = PreviewNormalizer().normalized(noise_image(2000))
    assert result.preview is None
    assert result.problem is PreviewProblem.TOO_LARGE


# --- PreviewDownloader


class _Response:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code: int = status_code
        self.content: bytes = content


class _FakeGet:
    """Подделка requests.get: отдаёт заданные ответы или исключения по очереди."""

    def __init__(self, *outcomes: _Response | requests.RequestException) -> None:
        self.outcomes: list[_Response | requests.RequestException] = list(outcomes)
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, timeout: float) -> _Response:
        self.calls.append((url, timeout))
        outcome: _Response | requests.RequestException = self.outcomes.pop(0)
        if isinstance(outcome, requests.RequestException):
            raise outcome
        return outcome


class _ZeroRandom(random.Random):
    def uniform(self, a: float, b: float) -> float:
        return a


def downloader_for(get: _FakeGet, sleeps: list[float]) -> PreviewDownloader:
    return PreviewDownloader(session_get=get, policy=RetryPolicy(), rng=_ZeroRandom(0), sleep=sleeps.append)


def test_503_then_200_is_one_retry() -> None:
    get: _FakeGet = _FakeGet(_Response(503), _Response(200, png_bytes()))
    sleeps: list[float] = []
    result: PreviewResult = downloader_for(get, sleeps).preview(THUMBNAIL)
    assert result.is_ok
    assert get.calls == [(THUMBNAIL, 20.0), (THUMBNAIL, 20.0)]
    assert sleeps == [2.0]


def test_404_is_not_retried() -> None:
    get: _FakeGet = _FakeGet(_Response(404))
    sleeps: list[float] = []
    assert downloader_for(get, sleeps).download(THUMBNAIL) is PreviewProblem.NOT_FOUND
    assert len(get.calls) == 1
    assert sleeps == []


def test_403_is_rejected_without_retries() -> None:
    get: _FakeGet = _FakeGet(_Response(403))
    assert downloader_for(get, []).download(THUMBNAIL) is PreviewProblem.REJECTED
    assert len(get.calls) == 1


def test_connection_errors_and_timeouts_are_retried_until_the_policy_ends() -> None:
    policy: RetryPolicy = RetryPolicy()
    errors: list[requests.RequestException] = [
        requests.ConnectionError("down") if index % 2 else requests.Timeout("slow")
        for index in range(policy.max_attempts)
    ]
    get: _FakeGet = _FakeGet(*errors)
    sleeps: list[float] = []
    assert downloader_for(get, sleeps).download(THUMBNAIL) is PreviewProblem.UNAVAILABLE
    assert len(get.calls) == policy.max_attempts
    assert sleeps == [2.0, 4.0, 8.0, 16.0]


def test_other_request_errors_are_rejected_at_once() -> None:
    get: _FakeGet = _FakeGet(requests.exceptions.InvalidURL("bad"))
    assert downloader_for(get, []).download(THUMBNAIL) is PreviewProblem.REJECTED
    assert len(get.calls) == 1


def test_empty_url_is_no_url_without_a_request() -> None:
    get: _FakeGet = _FakeGet()
    result: PreviewResult = downloader_for(get, []).preview("")
    assert result.problem is PreviewProblem.NO_URL
    assert get.calls == []


def test_downloaded_garbage_is_not_an_image() -> None:
    get: _FakeGet = _FakeGet(_Response(200, b"<html>not an image</html>"))
    assert downloader_for(get, []).preview(THUMBNAIL).problem is PreviewProblem.NOT_IMAGE


# --- SourceFacts, SourceVideo, PreparedSources, SourceCatalog


def admitted(row_number: int, link: str) -> AdmittedRow:
    return admitted_row(row_number, link, START)


def rows_of(*rows: AdmittedRow, skipped: tuple[SkippedRow, ...] = ()) -> PlannedRows:
    return PlannedRows(admitted=rows, skipped=skipped)


def video_of(
    row: AdmittedRow, fetched: SourceFetch, language: LanguageDecision | None, preview: PreviewResult | None = None
) -> SourceVideo:
    return SourceVideo(row=row, facts=SourceFacts(fetch=fetched, language=language, preview=preview))


class _FakeFetcher:
    """Получатель без yt-dlp: итог по ссылке из словаря, счётчик обращений."""

    def __init__(self, fetches: dict[str, SourceFetch]) -> None:
        self.fetches: dict[str, SourceFetch] = fetches
        self.calls: list[str] = []

    def fetch(self, url: str) -> SourceFetch:
        self.calls.append(url)
        return self.fetches[url]


def ok_fetch(link: str, info_name: str = "video_full.json") -> SourceFetch:
    return SourceFetch.from_metadata(link, SourceMetadata.from_ytdlp(link, load_info(info_name)))


def catalog_for(fetcher: MetadataFetcher, get: _FakeGet, resolver: LanguageResolver = RESOLVER) -> SourceCatalog:
    return SourceCatalog(fetcher=fetcher, downloader=downloader_for(get, []), resolver=resolver)


def language_decisions(log: LogCapture) -> list[str]:
    """Строки решений языка: LanguageResolver пишет одну на каждое решение."""
    return [line for line in log.messages() if line.startswith("language_decision ")]


def no_language_fetch(link: str) -> SourceFetch:
    """Видео, язык которого не определить: нет языка видео, короткие название и описание."""
    info: dict[str, Any] = load_info("video_full.json") | {
        "language": None, "title": "Эфир", "description": "", "formats": [], "automatic_captions": {},
    }
    return SourceFetch.from_metadata(link, SourceMetadata.from_ytdlp(link, info))


def decision_for(fetched: SourceFetch) -> LanguageDecision:
    metadata: SourceMetadata | None = fetched.ready_metadata
    assert metadata is not None
    return RESOLVER.resolve(metadata)


def test_fake_fetcher_is_a_metadata_fetcher() -> None:
    fetcher: MetadataFetcher = _FakeFetcher({})
    assert callable(fetcher.fetch)


def test_two_rows_with_one_link_are_one_fetch_one_language_and_one_download(log: LogCapture) -> None:
    fetcher: _FakeFetcher = _FakeFetcher({LINK: ok_fetch(LINK)})
    get: _FakeGet = _FakeGet(_Response(200, png_bytes()))
    catalog: SourceCatalog = catalog_for(fetcher, get)
    videos: tuple[SourceVideo, ...] = catalog.prepare(rows_of(admitted(2, LINK), admitted(5, LINK))).videos
    assert [video.row_number for video in videos] == [2, 5]
    assert all(video.is_ready and video.preview is not None for video in videos)
    assert fetcher.calls == [LINK]
    assert len(get.calls) == 1
    assert videos[0].facts is videos[1].facts
    assert len(language_decisions(log)) == 1
    assert list(catalog.known) == [LINK]
    info: list[str] = log.messages(logging.INFO)
    assert f"source row=2 link={LINK} result=ok preview=ok {FULL_LANGUAGE}" in info
    assert f"source row=5 link={LINK} result=ok preview=ok {FULL_LANGUAGE}" in info
    assert any("sources_prepared sources=2 links=1 ready=2 failed=0" in line for line in info)
    assert any(line.endswith("languages=uk:2") for line in info)


def test_skipped_rows_are_not_processed() -> None:
    fetcher: _FakeFetcher = _FakeFetcher({LINK: ok_fetch(LINK)})
    get: _FakeGet = _FakeGet(_Response(200, png_bytes()))
    past: SkippedRow = SkippedRow(SheetRow(2, OTHER_LINK, "01.09.2026", "19:00"), RowSkipReason.IN_PAST)
    prepared: PreparedSources = catalog_for(fetcher, get).prepare(rows_of(admitted(3, LINK), skipped=(past,)))
    assert [video.row_number for video in prepared.videos] == [3]
    assert fetcher.calls == [LINK]


def test_one_failed_source_does_not_stop_the_next(log: LogCapture) -> None:
    failed: SourceFetch = SourceFetch.failed(OTHER_LINK, SourceFailureReason.PRIVATE, "ERROR: Private video")
    fetcher: _FakeFetcher = _FakeFetcher({OTHER_LINK: failed, LINK: ok_fetch(LINK)})
    get: _FakeGet = _FakeGet(_Response(200, png_bytes()))
    catalog: SourceCatalog = catalog_for(fetcher, get)
    videos: tuple[SourceVideo, ...] = catalog.prepare(rows_of(admitted(2, OTHER_LINK), admitted(3, LINK))).videos
    assert [video.is_ready for video in videos] == [False, True]
    assert videos[0].refusal is SourceFailureReason.PRIVATE
    assert videos[0].preview is None and videos[0].facts.preview is None
    assert videos[0].facts.language is None          # язык отказавшего источника не решаем
    assert len(language_decisions(log)) == 1
    assert len(get.calls) == 1                       # обложку отказавшего источника не качаем
    assert (
        f"source row=2 link={OTHER_LINK} result=private preview=- language=- language_source=- "
        "detail=ERROR: Private video"
    ) in log.messages(logging.WARNING)
    assert any("failed=1 failures=private:1" in line for line in log.messages(logging.INFO))


def test_source_without_preview_is_still_ready(log: LogCapture) -> None:
    fetcher: _FakeFetcher = _FakeFetcher({LINK: ok_fetch(LINK)})
    get: _FakeGet = _FakeGet(_Response(404))
    prepared: PreparedSources = catalog_for(fetcher, get).prepare(rows_of(admitted(2, LINK)))
    video: SourceVideo = prepared.videos[0]
    assert video.is_ready
    assert video.preview is None
    assert video.facts.preview == PreviewResult.failed(PreviewProblem.NOT_FOUND)
    assert prepared.no_preview == 1
    assert f"source row=2 link={LINK} result=ok preview=not_found {FULL_LANGUAGE}" in log.messages(logging.INFO)


def test_source_without_title_is_not_ready_and_gets_no_language_and_no_preview(log: LogCapture) -> None:
    info: dict[str, Any] = load_info("video_full.json") | {"title": ""}
    no_title: SourceFetch = SourceFetch.from_metadata(LINK, SourceMetadata.from_ytdlp(LINK, info))
    get: _FakeGet = _FakeGet()
    prepared: PreparedSources = catalog_for(_FakeFetcher({LINK: no_title}), get).prepare(rows_of(admitted(2, LINK)))
    video: SourceVideo = prepared.videos[0]
    assert not video.is_ready
    assert video.facts.fetch.metadata is not None and video.facts.fetch.metadata.url == LINK
    assert video.refusal is SourceFailureReason.NO_TITLE
    assert video.facts.language is None
    assert language_decisions(log) == []
    assert get.calls == []


def test_source_whose_language_is_undetected_is_not_ready(log: LogCapture) -> None:
    get: _FakeGet = _FakeGet()
    catalog: SourceCatalog = catalog_for(_FakeFetcher({LINK: no_language_fetch(LINK)}), get)
    video: SourceVideo = catalog.prepare(rows_of(admitted(2, LINK))).videos[0]
    assert video.facts.fetch.failure is None
    assert video.facts.language is not None and not video.facts.language.is_resolved
    assert video.facts.language.source is LanguageSource.UNDETECTED
    assert video.language_code is None
    assert not video.is_ready
    assert video.refusal is SourceFailureReason.NO_LANGUAGE
    assert get.calls == []                           # источник дальше не идёт — обложка ему не нужна
    warnings: list[str] = log.messages(logging.WARNING)
    assert any(line.startswith(f"language_decision url={LINK} final_language=unknown") for line in warnings)
    assert (
        f"source row=2 link={LINK} result=no_language preview=- language=- language_source=undetected detail=-"
    ) in warnings
    assert any("failures=no_language:1" in line and line.endswith("languages=-") for line in log.messages(logging.INFO))


def test_refusal_order_is_ytdlp_then_title_then_language() -> None:
    undetected: LanguageDecision = decision_for(no_language_fetch(LINK))
    info: dict[str, Any] = load_info("video_full.json") | {"title": ""}
    no_title: SourceFetch = SourceFetch.from_metadata(LINK, SourceMetadata.from_ytdlp(LINK, info))
    assert SourceFacts(SourceFetch.failed(LINK, SourceFailureReason.TIMEOUT), undetected, None).refusal is (
        SourceFailureReason.TIMEOUT
    )
    assert SourceFacts(no_title, undetected, None).refusal is SourceFailureReason.NO_TITLE
    assert SourceFacts(no_language_fetch(LINK), undetected, None).refusal is SourceFailureReason.NO_LANGUAGE
    assert SourceFacts(no_language_fetch(LINK), None, None).refusal is SourceFailureReason.NO_LANGUAGE


def test_the_slot_key_of_a_fit_source_is_its_start_in_the_program_zone_and_its_language() -> None:
    video: SourceVideo = video_of(admitted(2, LINK), ok_fetch(LINK), decision_for(ok_fetch(LINK)))
    kyiv: ZoneInfo = ZoneInfo("Europe/Kyiv")
    key: SlotKey | None = video.slot_key(kyiv)
    assert key == SlotKey(start=START.astimezone(kyiv), language="uk")
    assert key is not None and key.slot_id == "16-10-2026_1900_uk"


def test_an_unfit_source_has_no_slot_key() -> None:
    """Негодный источник в слот не идёт: у него нет ключа слота, а не исключение."""
    failed: SourceFetch = SourceFetch.failed(LINK, SourceFailureReason.TIMEOUT)
    undetected: LanguageDecision = decision_for(no_language_fetch(LINK))
    assert video_of(admitted(2, LINK), failed, None).slot_key(ZoneInfo("Europe/Kyiv")) is None
    assert video_of(admitted(2, LINK), no_language_fetch(LINK), undetected).slot_key(ZoneInfo("Europe/Kyiv")) is None


def test_the_source_text_and_links_come_from_the_video_and_the_row() -> None:
    fetched: SourceFetch = ok_fetch(LINK)
    assert fetched.metadata is not None
    row: AdmittedRow = admitted_row(2, f"https://www.youtube.com/watch?v={LINK[-11:]}&t=5s", START)
    video: SourceVideo = video_of(row, fetched, None)
    assert video.text == SourceText(title=fetched.metadata.title, description=fetched.metadata.description)
    assert (video.link, video.watch_url) == (LINK, f"https://www.youtube.com/watch?v={LINK[-11:]}")
    failed: SourceFetch = SourceFetch.failed(LINK, SourceFailureReason.TIMEOUT)
    empty: SourceVideo = video_of(row, failed, None)
    assert empty.text == SourceText(title="", description="")


def test_prepared_sources_count_by_reason_and_by_language() -> None:
    failed: SourceFetch = SourceFetch.failed(OTHER_LINK, SourceFailureReason.UNAVAILABLE)
    uk: LanguageDecision = decision_for(ok_fetch(LINK))
    ru: LanguageDecision = decision_for(ok_fetch(OTHER_LINK, "video_no_thumbnail.json"))
    en: LanguageDecision = decision_for(ok_fetch(THIRD_LINK, "video_no_description.json"))
    prepared: PreparedSources = PreparedSources((
        video_of(admitted(2, OTHER_LINK), failed, None),
        video_of(admitted(3, OTHER_LINK), failed, None),
        video_of(admitted(4, LINK), ok_fetch(LINK), uk, PreviewResult.failed(PreviewProblem.NO_URL)),
        video_of(admitted(5, THIRD_LINK), ok_fetch(THIRD_LINK, "video_no_description.json"), en),
        video_of(admitted(6, OTHER_LINK), ok_fetch(OTHER_LINK, "video_no_thumbnail.json"), ru),
        video_of(admitted(7, LINK), ok_fetch(LINK), uk),
    ))
    assert (uk.language, ru.language, en.language) == ("uk", "ru", "en")
    assert prepared.ready == 4 and prepared.has_ready
    assert prepared.no_preview == 4
    assert [(item.key, item.count) for item in prepared.failures.items] == [(SourceFailureReason.UNAVAILABLE, 2)]
    assert [(item.key, item.count) for item in prepared.languages.items] == [("uk", 2), ("en", 1), ("ru", 1)]
    assert prepared.has_errors
    assert prepared.event.text == (
        "sources_prepared sources=6 links=3 ready=4 failed=2 failures=unavailable:2 no_preview=4 "
        "languages=uk:2,en:1,ru:1"
    )
    unavailable: str = msg.INTAKE_COUNT_ITEM.format(name=SourceFailureReason.UNAVAILABLE.human, count=2)
    assert prepared.console_line == msg.INTAKE_SOURCES_LINE.format(
        ready=4, total=6, no_preview=4, failures=msg.INTAKE_SOURCES_FAILURES.format(items=unavailable)
    )


def test_prepared_sources_without_refusals_have_no_errors_and_no_failures_part() -> None:
    uk: LanguageDecision = decision_for(ok_fetch(LINK))
    prepared: PreparedSources = PreparedSources((video_of(admitted(2, LINK), ok_fetch(LINK), uk),))
    assert not prepared.has_errors
    assert prepared.console_line == msg.INTAKE_SOURCES_LINE.format(ready=1, total=1, no_preview=1, failures="")


def test_catalog_from_paths_uses_ytdlp_and_the_resource_resolver(livecraft_paths: LivecraftPaths) -> None:
    catalog: SourceCatalog = SourceCatalog.from_paths(livecraft_paths)
    assert isinstance(catalog.fetcher, YtDlpFetcher)
    assert catalog.fetcher.launch.exe == livecraft_paths.file(FileName.YTDLP)
    assert catalog.resolver.detector.service_hints == RESOLVER.detector.service_hints
    videos: tuple[SourceVideo, ...] = catalog.prepare(rows_of(admitted(2, LINK))).videos
    assert videos[0].refusal is SourceFailureReason.TOOL_MISSING
    assert videos[0].facts.language is None


@pytest.mark.parametrize(
    ("status", "problem"),
    [
        (429, PreviewProblem.UNAVAILABLE),
        (503, PreviewProblem.UNAVAILABLE),
        (404, PreviewProblem.NOT_FOUND),
        (403, PreviewProblem.REJECTED),
    ],
)
def test_the_problem_of_a_preview_status_is_one_rule(status: int, problem: PreviewProblem) -> None:
    """429 и 5xx — временно недоступно (повторяется), 404 — картинки нет, прочие 4xx — отказ."""
    assert PreviewProblem.for_status(status) is problem


# --- VideoCheck: годится ли видео в рекомендуемые материалы слота


def check_of(fetched: SourceFetch) -> VideoCheck:
    """Проверка видео путём программы: данные видео и решение языка по ним."""
    return catalog_for(_FakeFetcher({fetched.url: fetched}), _FakeGet()).check(fetched.url)


def test_a_video_in_the_slot_language_without_dispute_fits_and_gives_its_title() -> None:
    check: VideoCheck = check_of(ok_fetch(THIRD_LINK, "video_no_description.json"))
    assert check.language is not None and not check.language.is_conflict
    assert check.fit("en") is VideoFit.FITS
    assert check.title == "Эфир без описания" and check.language_code == "en"


def test_a_video_in_another_language_does_not_fit() -> None:
    assert check_of(ok_fetch(THIRD_LINK, "video_no_description.json")).fit("uk") is VideoFit.OTHER_LANGUAGE


def test_a_video_whose_language_signals_dispute_is_ambiguous_even_in_the_slot_language() -> None:
    """Язык решён спором сигналов — зритель может получить ролик не на своём языке: такое видео не берётся."""
    check: VideoCheck = check_of(ok_fetch(LINK))
    assert check.language is not None and check.language.is_conflict and check.language_code == "uk"
    assert check.fit("uk") is VideoFit.AMBIGUOUS


def test_a_video_whose_language_is_undetected_is_ambiguous() -> None:
    check: VideoCheck = check_of(no_language_fetch(LINK))
    assert check.language_code is None and check.fit("uk") is VideoFit.AMBIGUOUS


def test_a_video_without_fit_data_does_not_fit_and_has_no_title() -> None:
    info: dict[str, Any] = load_info("video_full.json") | {"title": ""}
    no_title: SourceFetch = SourceFetch.from_metadata(LINK, SourceMetadata.from_ytdlp(LINK, info))
    for fetched in (SourceFetch.failed(LINK, SourceFailureReason.UNAVAILABLE), no_title):
        check: VideoCheck = check_of(fetched)
        assert check.language is None and check.title == ""
        assert check.fit("uk") is VideoFit.NO_DATA


def test_a_check_downloads_no_cover_and_asks_ytdlp_once_per_link(log: LogCapture) -> None:
    fetcher: _FakeFetcher = _FakeFetcher({LINK: ok_fetch(LINK)})
    get: _FakeGet = _FakeGet()
    catalog: SourceCatalog = catalog_for(fetcher, get)
    first: VideoCheck = catalog.check(LINK)
    assert catalog.check(LINK) is first
    assert fetcher.calls == [LINK] and get.calls == []
    assert len(language_decisions(log)) == 1


def test_a_link_checked_and_then_prepared_as_a_source_is_one_ytdlp_call(log: LogCapture) -> None:
    """Видео и рекомендуемое, и источник: одно обращение к yt-dlp и одно решение языка; итог и строки источника прежние."""
    fetcher: _FakeFetcher = _FakeFetcher({LINK: ok_fetch(LINK)})
    get: _FakeGet = _FakeGet(_Response(200, png_bytes()))
    catalog: SourceCatalog = catalog_for(fetcher, get)
    check: VideoCheck = catalog.check(LINK)
    video: SourceVideo = catalog.prepare(rows_of(admitted(2, LINK))).videos[0]
    assert fetcher.calls == [LINK] and len(get.calls) == 1
    assert len(language_decisions(log)) == 1
    assert video.is_ready and video.preview is not None
    assert (video.facts.fetch, video.facts.language) == (check.fetch, check.language)
    assert f"source row=2 link={LINK} result=ok preview=ok {FULL_LANGUAGE}" in log.messages(logging.INFO)


def test_a_prepared_source_is_not_fetched_again_when_checked() -> None:
    fetcher: _FakeFetcher = _FakeFetcher({LINK: ok_fetch(LINK)})
    catalog: SourceCatalog = catalog_for(fetcher, _FakeGet(_Response(200, png_bytes())))
    facts: SourceFacts = catalog.facts(LINK)
    assert catalog.check(LINK).fetch is facts.fetch
    assert fetcher.calls == [LINK]


# --- строки хода в консоли (CLAUDE.md §13 задача 9.5)


class _WatchingFetcher(_FakeFetcher):
    """Получатель, который при каждом обращении запоминает, сколько строк уже на консоли."""

    def __init__(self, fetches: dict[str, SourceFetch], record: ConsoleRecord) -> None:
        super().__init__(fetches)
        self.record: ConsoleRecord = record
        self.seen: list[int] = []

    def fetch(self, url: str) -> SourceFetch:
        self.seen.append(len(self.record.lines))
        return super().fetch(url)


def test_a_progress_line_names_each_row_before_its_video_is_read() -> None:
    """Три ряда — три строки хода с местом ряда и ссылкой; строка ряда на консоли раньше, чем yt-dlp спрошен о его
    видео: строки идут по ходу, а не пачкой в конце."""
    record: ConsoleRecord = ConsoleRecord()
    links: tuple[str, ...] = (LINK, OTHER_LINK, THIRD_LINK)
    fetcher: _WatchingFetcher = _WatchingFetcher({link: ok_fetch(link) for link in links}, record)
    catalog: SourceCatalog = catalog_for(fetcher, _FakeGet(*(_Response(200, png_bytes()) for _ in links)))
    rows: PlannedRows = rows_of(*(admitted(place + 1, link) for place, link in enumerate(links, start=1)))
    prepared: PreparedSources = catalog.prepare(rows, StageProgress(record.console))
    assert prepared.ready == 3
    assert record.lines == [
        f"Чтение видео 1 из 3: {LINK}", f"Чтение видео 2 из 3: {OTHER_LINK}", f"Чтение видео 3 из 3: {THIRD_LINK}",
    ]
    assert fetcher.seen == [1, 2, 3]


def test_a_row_of_a_known_link_is_counted_too() -> None:
    """Счёт строк хода — по рядам таблицы: ряд с уже прочитанным видео свою строку получает, yt-dlp не спрошен."""
    record: ConsoleRecord = ConsoleRecord()
    fetcher: _WatchingFetcher = _WatchingFetcher({LINK: ok_fetch(LINK)}, record)
    catalog: SourceCatalog = catalog_for(fetcher, _FakeGet(_Response(200, png_bytes())))
    catalog.prepare(rows_of(admitted(2, LINK), admitted(5, LINK)), StageProgress(record.console))
    assert record.lines == [f"Чтение видео 1 из 2: {LINK}", f"Чтение видео 2 из 2: {LINK}"]
    assert fetcher.seen == [1]


def test_without_a_console_the_sources_say_nothing(capsys: pytest.CaptureFixture[str]) -> None:
    fetcher: _FakeFetcher = _FakeFetcher({LINK: ok_fetch(LINK)})
    catalog: SourceCatalog = catalog_for(fetcher, _FakeGet(_Response(200, png_bytes())))
    catalog.prepare(rows_of(admitted(2, LINK)))
    catalog.prepare(rows_of(admitted(2, LINK)), StageProgress())
    assert capsys.readouterr().out == ""
