"""Вход в канал и проверка всех каналов без окна (app\\setup\\panels\\channels_check.py, CLAUDE.md §8.2, §10): тот же
код, что у --auth и --check, на подделке площадки; строки окна — те же, что печатает консоль служебного запуска."""
from __future__ import annotations

import pytest

from app.broadcasts.service import ChannelService
from app.broadcasts.services import BroadcastServices
from app.config.channel import ConfiguredChannels
from app.config.settings import LivecraftSettings
from app.paths import FileName, LivecraftPaths
from app.platforms.error import PlatformError
from app.run.exit_code import RunOutcome
from app.run.mode import RunMode
from app.setup.panels.channels_check import ChannelsCheck, ChannelsVerdict, CheckTranscript
from app.setup.readiness import Readiness, ServiceReadiness
from app.tests.fixtures.broadcasts import BroadcastBench
from app.tests.fixtures.platform import FAKE_TOKEN_TEXT, token_path
from app.ui import messages_ru as msg
from app.ui.console import Console


@pytest.fixture
def bench(ready_paths: LivecraftPaths) -> BroadcastBench:
    """Каналы yt_ua и yt_ru в channels.json и с токенами."""
    return BroadcastBench.with_tokens(ready_paths)


def _check(bench: BroadcastBench, opened: list[int] | None = None) -> ChannelsCheck:
    """Проверка каналов на зависимостях стенда; строки — на консоль проверки."""

    def _open(paths: LivecraftPaths, settings: LivecraftSettings, console: Console) -> BroadcastServices:
        (opened if opened is not None else []).append(1)
        return bench.services_on(console)

    return ChannelsCheck(paths=bench.paths, open_services=_open)


def _console_run(bench: BroadcastBench, handle: str | None) -> RunOutcome:
    """Тот же служебный запуск в консоль оператора — как .\\livecraft.bat --check или --auth."""
    return ChannelService(bench.services(), ConfiguredChannels(bench.channels), bench.record.console).run(handle)


def test_check_all_says_the_lines_of_the_console_check(bench: BroadcastBench) -> None:
    said: list[str] = []
    verdict: ChannelsVerdict = _check(bench).check_all(said.append)
    assert _console_run(bench, None) is RunOutcome.DONE
    assert verdict.is_ok
    assert verdict.text.splitlines()[:-1] == bench.record.lines[:-1]
    assert verdict.text.splitlines()[-1] == msg.CHECK_OK_LINE.format(line=msg.CHECK_ALL_OK)   # итог консоли — со знаком
    assert said[0] == msg.CHECK_HEADER.format(path=bench.paths.file(FileName.CHANNELS))
    assert said[-1].splitlines() == bench.record.lines      # по ходу проверки окно видит всё сказанное до сих пор


def test_a_failing_channel_makes_the_check_not_ok(bench: BroadcastBench) -> None:
    error: PlatformError = PlatformError("liveStreamingNotEnabled", "выключены")
    bench.platform.fail_list["yt_ua"] = error
    verdict: ChannelsVerdict = _check(bench).check_all(lambda text: None)
    assert _console_run(bench, None) is RunOutcome.FAILED
    assert not verdict.is_ok
    assert verdict.text.splitlines()[:-1] == bench.record.lines[:-1]
    assert msg.CHECK_CHANNEL_FAILED.format(account_name="yt_ua", handle="@yt_ua", reason=error.human) in verdict.text
    assert verdict.text.splitlines()[-1] == msg.CHECK_PROBLEM_LINE.format(line=msg.CHECK_HAS_PROBLEMS)


def test_log_in_logs_in_the_channel_again(bench: BroadcastBench) -> None:
    verdict: ChannelsVerdict = _check(bench).log_in("@yt_ru", lambda text: None)
    assert verdict.is_ok
    assert bench.platform.logins == ["yt_ru"]
    assert token_path(bench.paths, "@yt_ru").read_text(encoding="utf-8") == FAKE_TOKEN_TEXT


def test_log_in_to_an_unknown_handle_lists_the_handles(bench: BroadcastBench) -> None:
    verdict: ChannelsVerdict = _check(bench).log_in("@nobody", lambda text: None)
    assert _console_run(bench, "@nobody") is RunOutcome.FAILED
    assert not verdict.is_ok and verdict.text.splitlines()[:-1] == bench.record.lines[:-1]
    assert verdict.text.splitlines()[-1] == msg.CHECK_PROBLEM_LINE.format(line=bench.record.lines[-1])
    assert bench.platform.logins == []


def test_missing_needs_are_named_and_youtube_is_not_opened(bench: BroadcastBench) -> None:
    bench.paths.file(FileName.CLIENT_SECRET).unlink()
    opened: list[int] = []
    verdict: ChannelsVerdict = _check(bench, opened).check_all(lambda text: None)
    service: ServiceReadiness = ServiceReadiness(Readiness.check(bench.paths), RunMode.CHECK)
    assert service.lines
    marked: tuple[str, ...] = tuple(msg.CHECK_PROBLEM_LINE.format(line=line) for line in service.lines)
    assert verdict == ChannelsVerdict(is_ok=False, text="\n".join(marked))     # каждая нужда — проблема
    assert opened == []


def test_the_transcript_tells_every_finished_line() -> None:
    told: list[str] = []
    transcript: CheckTranscript = CheckTranscript(told.append)
    transcript.write("первая")
    assert told == []
    transcript.write("\n")
    transcript.write("вторая\n")
    assert told == ["первая", "первая\nвторая"]
    assert transcript.text == "первая\nвторая"
