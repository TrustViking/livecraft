from __future__ import annotations

import logging
import re
import shutil
import warnings
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from app.core.clock import Clock
from app.core.dates import FILE_STAMP_FORMAT
from app.observability.log_event import LogArea, get_logger
from app.observability.logging_setup import RunLog, mask_stream_key
from app.tests.fixtures.clock import StoppedClock
from app.version import APP_NAME

THIRD_PARTY_LOGGER: str = "googleapiclient.discovery_cache"
STREAM_KEY: str = "abcd-efgh-ijkl-mnop-qrst"
CLOCK: Clock = Clock(timezone.utc)
# Пояс программы, заведомо не совпадающий с поясом машины: по нему видно, чьё время попало в лог.
FAR_ZONE: timezone = timezone(timedelta(hours=14))
RECORD_STAMP_PATTERN: re.Pattern[str] = re.compile(r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}),\d{3} \| ")
RECORD_STAMP_FORMAT: str = "%Y-%m-%d %H:%M:%S"
LOG_NAME_PATTERN: re.Pattern[str] = re.compile(r"^\d{2}-\d{2}-\d{4}_\d{6}_livecraft\.log$")


class _DropMarked(logging.Filter):
    """Фильтр-метка: выбрасывает записи со словом «secret» — по нему видно, на каких обработчиках он висит."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "secret" not in record.getMessage()


def _emit() -> None:
    get_logger(LogArea.MAIN).warning("broadcast_not_found slot_id=16-09-2026_1900_uk")
    get_logger(LogArea.MAIN).info("run_report mode=full")
    logging.getLogger(THIRD_PARTY_LOGGER).warning("file_cache is only supported with oauth2client<4.0.0")
    logging.getLogger(THIRD_PARTY_LOGGER).info("third party chatter")


def test_log_file_is_date_time_livecraft(tmp_path: Path) -> None:
    """logs\\{DD-MM-YYYY}_{HHMMSS}_livecraft.log (CLAUDE.md §5)."""
    log: RunLog = RunLog.open(tmp_path, debug=False, started=CLOCK.now())
    log.close()
    assert log.path.parent == tmp_path
    assert LOG_NAME_PATTERN.fullmatch(log.path.name), log.path.name
    stamp: str = log.path.name.split("_livecraft.log")[0]
    assert datetime.strptime(stamp, FILE_STAMP_FORMAT) is not None


def test_a_start_without_a_zone_is_a_programming_error(tmp_path: Path) -> None:
    """Без пояса нельзя сказать, по чьим часам писать время: это ошибка программы, а не догадка."""
    with pytest.raises(ValueError):
        RunLog.open(tmp_path, debug=False, started=datetime(2026, 9, 20, 12, 0))


def test_log_file_name_follows_the_program_zone_not_the_machine(tmp_path: Path) -> None:
    """20-09-2026 23:30 UTC — в поясе программы (+03:00) это уже 21-09-2026 02:30: имя файла — по программе."""
    moment: datetime = datetime(2026, 9, 20, 23, 30, tzinfo=timezone.utc)
    started: datetime = StoppedClock.at(moment, zone=timezone(timedelta(hours=3))).now()
    log: RunLog = RunLog.open(tmp_path, debug=False, started=started)
    log.close()
    assert log.path.name == "21-09-2026_023000_livecraft.log"


def test_record_time_follows_the_program_zone_not_the_machine(tmp_path: Path) -> None:
    """Время каждой записи — по поясу программы: часы машины (её пояс не +14:00) дали бы другой час."""
    log: RunLog = RunLog.open(tmp_path, debug=False, started=Clock(FAR_ZONE).now())
    before: datetime = datetime.now(FAR_ZONE).replace(tzinfo=None, microsecond=0)
    get_logger(LogArea.MAIN).info("run_started version=0.1.0")
    after: datetime = datetime.now(FAR_ZONE).replace(tzinfo=None, microsecond=0)
    log.close()
    match: re.Match[str] | None = RECORD_STAMP_PATTERN.match(log.path.read_text(encoding="utf-8"))
    assert match is not None
    assert before <= datetime.strptime(match.group(1), RECORD_STAMP_FORMAT) <= after


def test_without_debug_nothing_goes_to_the_terminal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Терминал — только тексты оператора: ни WARNING livecraft, ни чужой WARNING, ни lastResort."""
    log: RunLog = RunLog.open(tmp_path, debug=False, started=CLOCK.now())
    _emit()
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        logging.captureWarnings(True)      # catch_warnings вернул свой showwarning — повторяем то, что делает open
        warnings.warn("library deprecation", DeprecationWarning, stacklevel=1)
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    assert captured.err == "" and captured.out == ""
    log.close()
    text: str = log.path.read_text(encoding="utf-8")
    assert " | WARNING | livecraft.main | broadcast_not_found" in text
    assert " | INFO | livecraft.main | run_report" in text        # файл livecraft — DEBUG
    assert f" | WARNING | {THIRD_PARTY_LOGGER} | file_cache" in text
    assert "third party chatter" not in text                        # чужие — от WARNING
    assert "library deprecation" in text


def test_debug_prints_the_log_to_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    log: RunLog = RunLog.open(tmp_path, debug=True, started=CLOCK.now())
    _emit()
    err: str = capsys.readouterr().err
    log.close()
    assert " | WARNING | livecraft.main | broadcast_not_found" in err
    assert " | INFO | livecraft.main | run_report" in err
    assert f" | WARNING | {THIRD_PARTY_LOGGER} | file_cache" in err


def test_close_removes_only_own_handlers_from_the_python_root(tmp_path: Path) -> None:
    python_root: logging.Logger = logging.getLogger()
    before: list[logging.Handler] = list(python_root.handlers)
    log: RunLog = RunLog.open(tmp_path, debug=False, started=CLOCK.now())
    assert len(python_root.handlers) == len(before) + 1
    log.close()
    assert python_root.handlers == before
    assert not any(handler in logging.getLogger(APP_NAME).handlers for handler in log.handlers)


def test_close_releases_the_log_file(tmp_path: Path) -> None:
    """На Windows открытый файл лога не даёт удалить папку: close обязан его закрыть."""
    logs_dir: Path = tmp_path / "logs"
    logs_dir.mkdir()
    log: RunLog = RunLog.open(logs_dir, debug=False, started=CLOCK.now())
    get_logger(LogArea.MAIN).info("run_started version=0.1.0")
    log.close()
    shutil.rmtree(logs_dir)
    assert not logs_dir.exists()


def test_each_log_closes_only_its_own_handlers(tmp_path: Path) -> None:
    """Лог знает свои обработчики сам, без общего списка: закрытый лог не трогает обработчики другого."""
    first_dir: Path = tmp_path / "first"
    first_dir.mkdir()
    first: RunLog = RunLog.open(first_dir, debug=False, started=CLOCK.now())
    second: RunLog = RunLog.open(tmp_path, debug=False, started=CLOCK.now())
    first.close()
    assert all(handler in logging.getLogger(APP_NAME).handlers for handler in second.handlers)
    assert not any(handler in logging.getLogger(APP_NAME).handlers for handler in first.handlers)
    get_logger(LogArea.MAIN).info("run_started version=0.1.0")
    second.close()
    assert "run_started" in second.path.read_text(encoding="utf-8")
    assert "run_started" not in first.path.read_text(encoding="utf-8")


def test_the_handlers_are_fields_of_the_log(tmp_path: Path) -> None:
    """Обработчики на логгере livecraft и на корневом логгере Python — одни и те же объекты этого лога."""
    log: RunLog = RunLog.open(tmp_path, debug=True, started=CLOCK.now())
    assert len(log.handlers) == 2
    assert all(handler in logging.getLogger(APP_NAME).handlers for handler in log.handlers)
    assert all(handler in logging.getLogger().handlers for handler in log.handlers)
    log.close()


def test_protect_hangs_the_filter_on_every_handler_of_the_run(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Фильтр лога — на файл и на терминал (--debug), в том числе для записей чужих библиотек."""
    log: RunLog = RunLog.open(tmp_path, debug=True, started=CLOCK.now())
    log.protect(_DropMarked())
    get_logger(LogArea.SHEETS).info("sheet_read secret=1")
    logging.getLogger(THIRD_PARTY_LOGGER).warning("URL being requested: secret")
    get_logger(LogArea.SHEETS).info("sheet_read done")
    err: str = capsys.readouterr().err
    log.close()
    text: str = log.path.read_text(encoding="utf-8")
    assert "secret" not in text and "secret" not in err
    assert "sheet_read done" in text and "sheet_read done" in err


def test_close_takes_the_filter_away_with_the_handlers(tmp_path: Path) -> None:
    """Фильтр живёт на обработчиках лога: следующий лог его не наследует и ставит свой сам."""
    first: RunLog = RunLog.open(tmp_path, debug=False, started=CLOCK.now())
    first.protect(_DropMarked())
    first.close()
    second: RunLog = RunLog.open(tmp_path, debug=False, started=CLOCK.now())
    get_logger(LogArea.SHEETS).info("sheet_read secret=1")
    second.close()
    assert "secret=1" in second.path.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "-"), ("", "****"), ("ab", "****"), ("abc", "****"), ("abcd", "****-abcd"), (STREAM_KEY, "****-qrst")],
)
def test_mask_stream_key_shows_at_most_the_last_four_characters(value: str | None, expected: str) -> None:
    """Ключ потока в логе — только маской; полностью он есть только в keys.txt (§6, инвариант 6)."""
    assert mask_stream_key(value) == expected


def test_masked_key_does_not_contain_the_key(tmp_path: Path) -> None:
    log: RunLog = RunLog.open(tmp_path, debug=False, started=CLOCK.now())
    get_logger(LogArea.MAIN).info("stream_key=%s", mask_stream_key(STREAM_KEY))
    log.close()
    text: str = log.path.read_text(encoding="utf-8")
    assert STREAM_KEY not in text and "stream_key=****-qrst" in text
