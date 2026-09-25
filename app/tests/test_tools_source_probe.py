from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from app.paths import LivecraftPaths, ROOT_ENV_VAR
from app.sources.fetcher import SourceFailureReason, SourceFetch
from app.sources.language import LanguageResolver
from app.sources.metadata import SourceMetadata
from app.sources.preview import PreviewDownloader, PreviewProblem
from app.tools import source_probe
from app.tools.source_probe import ProbeExit, SourceProbe
from app.ui import messages_ru as msg

DATA_DIR: Path = Path(__file__).resolve().parent / "data" / "ytdlp"
LINK: str = "https://youtu.be/dQw4w9WgXcQ"
WATCH_LINK: str = "https://www.youtube.com/watch?v=dQw4w9WgXcQ&t=10"
OTHER_LINK: str = "https://youtu.be/aB3_-xYz012"
RESOLVER: LanguageResolver = LanguageResolver.from_resources()


def load_info(name: str) -> dict[str, Any]:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


def png_bytes(size: tuple[int, int]) -> bytes:
    output: io.BytesIO = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(output, format="PNG")
    return output.getvalue()


class _FakeFetcher:
    def __init__(self, fetches: dict[str, SourceFetch]) -> None:
        self.fetches: dict[str, SourceFetch] = fetches
        self.calls: list[str] = []

    def fetch(self, url: str) -> SourceFetch:
        self.calls.append(url)
        return self.fetches[url]


class _Response:
    def __init__(self, status_code: int, content: bytes = b"") -> None:
        self.status_code: int = status_code
        self.content: bytes = content


class _FakeGet:
    def __init__(self, *responses: _Response) -> None:
        self.responses: list[_Response] = list(responses)
        self.urls: list[str] = []

    def __call__(self, url: str, timeout: float) -> _Response:
        self.urls.append(url)
        return self.responses.pop(0)


def ok_fetch(link: str, name: str = "video_full.json") -> SourceFetch:
    return SourceFetch.from_metadata(link, SourceMetadata.from_ytdlp(link, load_info(name)))


def run_probe(fetcher: _FakeFetcher, get: _FakeGet, links: list[str]) -> tuple[int, list[str]]:
    lines: list[str] = []
    downloader: PreviewDownloader = PreviewDownloader(session_get=get, sleep=lambda _: None)
    code: int = SourceProbe(fetcher=fetcher, downloader=downloader, resolver=RESOLVER, say=lines.append).run(links)
    return code, lines


def test_probe_prints_the_fields_and_the_preview() -> None:
    fetcher: _FakeFetcher = _FakeFetcher({LINK: ok_fetch(LINK)})
    get: _FakeGet = _FakeGet(_Response(200, png_bytes((1280, 720))))
    code, lines = run_probe(fetcher, get, [WATCH_LINK])
    assert code == ProbeExit.OK == 0
    assert fetcher.calls == [LINK]                           # ссылка нормализована, как ссылка ряда
    assert get.urls == ["https://i.ytimg.com/vi/dQw4w9WgXcQ/maxresdefault.jpg"]
    assert lines[0] == msg.SOURCE_PROBE_TITLE
    assert msg.SOURCE_PROBE_SOURCE.format(link=LINK) in lines
    assert msg.SOURCE_PROBE_ID.format(value="dQw4w9WgXcQ") in lines
    assert msg.SOURCE_PROBE_NAME.format(value="Тестовый эфир: разбор вопросов | #12") in lines
    assert msg.SOURCE_PROBE_DURATION.format(value="1:02:03") in lines
    assert msg.SOURCE_PROBE_LANGUAGE.format(video="uk", channel="ru") in lines
    assert msg.SOURCE_PROBE_AUDIO.format(value="uk, en") in lines
    assert msg.SOURCE_PROBE_SUBTITLES.format(value="uk, en") in lines
    assert msg.SOURCE_PROBE_AUTO_CAPTIONS.format(value="uk, ru, de") in lines
    language: str = msg.SOURCE_PROBE_SOURCE_LANGUAGE.format(code="uk", source="metadata_arbitration_fallback")
    assert language in lines
    assert any(line.startswith("  обложка: 1280×720, ") and "годится" in line for line in lines)
    assert lines.index(language) < len(lines) - 2                  # язык — перед строкой обложки и итогом
    assert lines[-1] == msg.SOURCE_PROBE_SUMMARY.format(total=1, ok=1, failed=0)


def test_probe_shows_only_ten_languages_and_how_many_more() -> None:
    info: dict[str, Any] = load_info("video_full.json")
    info["automatic_captions"] = {f"l{index:02d}": [] for index in range(13)}
    fetch: SourceFetch = SourceFetch.from_metadata(LINK, SourceMetadata.from_ytdlp(LINK, info))
    code, lines = run_probe(_FakeFetcher({LINK: fetch}), _FakeGet(_Response(200, png_bytes((64, 36)))), [LINK])
    shown: str = ", ".join(f"l{index:02d}" for index in range(10))
    assert code == ProbeExit.OK
    assert msg.SOURCE_PROBE_AUTO_CAPTIONS.format(value=msg.SOURCE_PROBE_MORE.format(shown=shown, more=3)) in lines


def test_probe_names_the_preview_problem_and_still_succeeds() -> None:
    fetcher: _FakeFetcher = _FakeFetcher({OTHER_LINK: ok_fetch(OTHER_LINK, "video_no_thumbnail.json")})
    code, lines = run_probe(fetcher, _FakeGet(_Response(404)), [OTHER_LINK])
    assert code == ProbeExit.OK
    assert msg.SOURCE_PROBE_PREVIEW_BAD.format(reason=PreviewProblem.NOT_FOUND.human) in lines
    assert msg.SOURCE_PROBE_DURATION.format(value=msg.SOURCE_PROBE_NONE) in lines


def test_a_refusal_is_code_1_and_other_links_still_go() -> None:
    failed: SourceFetch = SourceFetch.failed(OTHER_LINK, SourceFailureReason.PRIVATE, "ERROR: Private video")
    fetcher: _FakeFetcher = _FakeFetcher({OTHER_LINK: failed, LINK: ok_fetch(LINK)})
    code, lines = run_probe(fetcher, _FakeGet(_Response(200, png_bytes((64, 36)))), [OTHER_LINK, LINK])
    assert code == ProbeExit.ERRORS == 1
    assert fetcher.calls == [OTHER_LINK, LINK]
    assert msg.SOURCE_PROBE_FAILED.format(reason=SourceFailureReason.PRIVATE.human) in lines
    assert msg.SOURCE_PROBE_DETAIL.format(detail="ERROR: Private video") in lines
    assert lines[-1] == msg.SOURCE_PROBE_SUMMARY.format(total=2, ok=1, failed=1)
    assert sum(line.startswith("  язык источника:") for line in lines) == 1   # у отказа языка нет


def _undetected_language_fetch() -> SourceFetch:
    info: dict[str, Any] = load_info("video_full.json") | {
        "language": None, "title": "Эфир", "description": "", "formats": [], "automatic_captions": {},
    }
    return SourceFetch.from_metadata(LINK, SourceMetadata.from_ytdlp(LINK, info))


def test_undetected_language_is_named_and_counts_as_a_refusal() -> None:
    code, lines = run_probe(
        _FakeFetcher({LINK: _undetected_language_fetch()}), _FakeGet(_Response(200, png_bytes((64, 36)))), [LINK]
    )
    assert code == ProbeExit.ERRORS
    assert msg.SOURCE_PROBE_SOURCE_LANGUAGE_NONE in lines
    assert lines[-1] == msg.SOURCE_PROBE_SUMMARY.format(total=1, ok=0, failed=1)


def test_undetected_language_skips_the_preview_as_the_run_does() -> None:
    """Боевой путь (SourceCatalog) не качает обложку источнику без языка — пробник тоже."""
    get: _FakeGet = _FakeGet(_Response(200, png_bytes((64, 36))))
    code, lines = run_probe(_FakeFetcher({LINK: _undetected_language_fetch()}), get, [LINK])
    assert code == ProbeExit.ERRORS
    assert get.urls == []                                    # загрузчик обложки не вызывался
    assert msg.SOURCE_PROBE_PREVIEW_SKIPPED in lines
    assert not any(line.startswith("  обложка: ") and line != msg.SOURCE_PROBE_PREVIEW_SKIPPED for line in lines)
    assert lines.index(msg.SOURCE_PROBE_SOURCE_LANGUAGE_NONE) < lines.index(msg.SOURCE_PROBE_PREVIEW_SKIPPED)


def test_a_resolved_language_still_downloads_the_preview() -> None:
    get: _FakeGet = _FakeGet(_Response(200, png_bytes((64, 36))))
    code, lines = run_probe(_FakeFetcher({LINK: ok_fetch(LINK)}), get, [LINK])
    assert code == ProbeExit.OK
    assert len(get.urls) == 1
    assert msg.SOURCE_PROBE_PREVIEW_SKIPPED not in lines


def test_a_link_that_is_not_youtube_is_a_refusal() -> None:
    fetcher: _FakeFetcher = _FakeFetcher({})
    code, lines = run_probe(fetcher, _FakeGet(), ["https://example.org/page"])
    assert code == ProbeExit.ERRORS
    assert fetcher.calls == []
    assert msg.SOURCE_PROBE_BAD_LINK.format(raw="https://example.org/page") in lines


def test_no_links_is_code_2() -> None:
    code, lines = run_probe(_FakeFetcher({}), _FakeGet(), [])
    assert code == ProbeExit.NOT_READY == 2
    assert lines == [msg.SOURCE_PROBE_TITLE, msg.SOURCE_PROBE_USAGE]


def test_without_ytdlp_exe_is_code_2(livecraft_paths: LivecraftPaths) -> None:
    lines: list[str] = []
    probe: SourceProbe = SourceProbe.from_paths(livecraft_paths, say=lines.append)
    assert probe.resolver.detector.service_hints == RESOLVER.detector.service_hints
    code: int = probe.run([LINK, OTHER_LINK])
    assert code == ProbeExit.NOT_READY
    assert msg.SOURCE_PROBE_FAILED.format(reason=SourceFailureReason.TOOL_MISSING.human) in lines
    assert msg.SOURCE_PROBE_SOURCE.format(link=OTHER_LINK) not in lines   # дальше не идём


def test_main_runs_on_the_root_from_the_environment(
    livecraft_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ROOT_ENV_VAR, str(livecraft_paths.root))
    assert source_probe.main([LINK]) == ProbeExit.NOT_READY
    out: str = capsys.readouterr().out
    assert msg.SOURCE_PROBE_TITLE in out
    assert SourceFailureReason.TOOL_MISSING.human in out
    log_text: str = "\n".join(
        path.read_text(encoding="utf-8") for path in livecraft_paths.logs_dir.glob("*_livecraft.log")
    )
    assert "ytdlp_missing" in log_text


def test_main_without_links_is_code_2(
    livecraft_paths: LivecraftPaths, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv(ROOT_ENV_VAR, str(livecraft_paths.root))
    monkeypatch.setattr("sys.argv", ["source_probe"])
    assert source_probe.main() == ProbeExit.NOT_READY
    assert msg.SOURCE_PROBE_USAGE in capsys.readouterr().out
