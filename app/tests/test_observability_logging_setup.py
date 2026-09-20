from __future__ import annotations

import logging
import re
import shutil
import warnings
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path

import pytest

from app.core.dates import FILE_STAMP_FORMAT
from app.observability.logging_setup import (
    ROOT_LOGGER_NAME,
    close_logging,
    get_logger,
    mask_stream_key,
    setup_logging,
)

THIRD_PARTY_LOGGER: str = "googleapiclient.discovery_cache"
STREAM_KEY: str = "abcd-efgh-ijkl-mnop-qrst"
LOG_NAME_PATTERN: re.Pattern[str] = re.compile(r"^\d{2}-\d{2}-\d{4}_\d{6}_livecraft\.log$")


@pytest.fixture(autouse=True)
def _closed_logging() -> Iterator[None]:
    yield
    close_logging()


def _emit() -> None:
    get_logger("youtube").warning("broadcast_not_found slot_id=16-09-2026_1900_uk")
    get_logger("youtube").info("run_report mode=full")
    logging.getLogger(THIRD_PARTY_LOGGER).warning("file_cache is only supported with oauth2client<4.0.0")
    logging.getLogger(THIRD_PARTY_LOGGER).info("third party chatter")


def test_root_logger_is_named_livecraft() -> None:
    """Имя корневого логгера — константа, дочерние — livecraft.<домен> (CLAUDE.md §11)."""
    assert ROOT_LOGGER_NAME == "livecraft"
    assert get_logger("sheets").name == "livecraft.sheets"


def test_log_file_is_date_time_livecraft(tmp_path: Path) -> None:
    """logs\\{DD-MM-YYYY}_{HHMMSS}_livecraft.log (CLAUDE.md §5)."""
    log_path: Path = setup_logging(tmp_path, debug=False)
    assert log_path.parent == tmp_path
    assert LOG_NAME_PATTERN.fullmatch(log_path.name), log_path.name
    stamp: str = log_path.name.split("_livecraft.log")[0]
    assert datetime.strptime(stamp, FILE_STAMP_FORMAT) is not None


def test_without_debug_nothing_goes_to_the_terminal(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """Терминал — только тексты оператора: ни WARNING livecraft, ни чужой WARNING, ни lastResort."""
    log_path: Path = setup_logging(tmp_path, debug=False)
    _emit()
    with warnings.catch_warnings():
        warnings.simplefilter("always")
        logging.captureWarnings(True)      # catch_warnings вернул свой showwarning — повторяем то, что делает setup
        warnings.warn("library deprecation", DeprecationWarning, stacklevel=1)
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    assert captured.err == "" and captured.out == ""
    close_logging()
    text: str = log_path.read_text(encoding="utf-8")
    assert " | WARNING | livecraft.youtube | broadcast_not_found" in text
    assert " | INFO | livecraft.youtube | run_report" in text        # файл livecraft — DEBUG
    assert f" | WARNING | {THIRD_PARTY_LOGGER} | file_cache" in text
    assert "third party chatter" not in text                        # чужие — от WARNING
    assert "library deprecation" in text


def test_debug_prints_the_log_to_stderr(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    setup_logging(tmp_path, debug=True)
    _emit()
    err: str = capsys.readouterr().err
    assert " | WARNING | livecraft.youtube | broadcast_not_found" in err
    assert " | INFO | livecraft.youtube | run_report" in err
    assert f" | WARNING | {THIRD_PARTY_LOGGER} | file_cache" in err


def test_close_removes_only_own_handlers_from_the_python_root(tmp_path: Path) -> None:
    python_root: logging.Logger = logging.getLogger()
    before: list[logging.Handler] = list(python_root.handlers)
    setup_logging(tmp_path, debug=False)
    assert len(python_root.handlers) == len(before) + 1
    close_logging()
    assert python_root.handlers == before
    assert logging.getLogger(ROOT_LOGGER_NAME).handlers == []


def test_close_releases_the_log_file(tmp_path: Path) -> None:
    """На Windows открытый файл лога не даёт удалить папку: close_logging обязан его закрыть."""
    logs_dir: Path = tmp_path / "logs"
    logs_dir.mkdir()
    setup_logging(logs_dir, debug=False)
    get_logger("main").info("run_started version=0.1.0")
    close_logging()
    shutil.rmtree(logs_dir)
    assert not logs_dir.exists()


def test_setup_twice_leaves_one_set_of_handlers(tmp_path: Path) -> None:
    """Повторный setup сначала закрывает прежний: строка не двоится в двух файлах."""
    setup_logging(tmp_path, debug=False)
    second: Path = setup_logging(tmp_path, debug=False)
    assert len(logging.getLogger(ROOT_LOGGER_NAME).handlers) == 1
    get_logger("main").info("run_started version=0.1.0")
    close_logging()
    assert "run_started" in second.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    ("value", "expected"),
    [(None, "-"), ("", "****"), ("ab", "****"), ("abc", "****"), ("abcd", "****-abcd"), (STREAM_KEY, "****-qrst")],
)
def test_mask_stream_key_shows_at_most_the_last_four_characters(value: str | None, expected: str) -> None:
    """Ключ потока в логе — только маской; полностью он есть только в keys.txt (§6, инвариант 6)."""
    assert mask_stream_key(value) == expected


def test_masked_key_does_not_contain_the_key(tmp_path: Path) -> None:
    log_path: Path = setup_logging(tmp_path, debug=False)
    get_logger("youtube").info("stream_key=%s", mask_stream_key(STREAM_KEY))
    close_logging()
    text: str = log_path.read_text(encoding="utf-8")
    assert STREAM_KEY not in text and "stream_key=****-qrst" in text
