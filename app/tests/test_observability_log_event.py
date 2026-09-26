from __future__ import annotations

import logging
from enum import Enum

import pytest

from app.observability.log_event import LogArea, LogEvent, LogField, LogValue, get_logger
from app.tests.fixtures.logs import LogCapture
from app.version import APP_NAME


class _Kind(str, Enum):
    MERGED = "merged"


class _Event(str, Enum):
    DONE = "probe_done"


# --- области и логгеры


def test_every_area_logger_lives_under_the_program_root() -> None:
    """Логгер области — `livecraft.<область>`: так их все ловит один обработчик корня программы."""
    for area in LogArea:
        assert get_logger(area).name == f"{APP_NAME}.{area.value}"


def test_the_areas_keep_the_logger_names_of_the_modules() -> None:
    assert {area.value for area in LogArea} == {
        "auth", "intake", "llm", "main", "packages", "runtime", "setup", "sheets", "slots", "sources",
        "sources.preview", "sources.ytdlp", "texts", "tools.llm_probe", "tools.sheets_probe", "tools.source_probe",
        "vault",
    }


# --- одно правило записи значения


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, "yes"),
        (False, "no"),
        (None, "-"),
        ("", "-"),
        ((), "-"),
        ([], "-"),
        (_Kind.MERGED, "merged"),
        (("uk", "en"), "uk,en"),
        ([_Kind.MERGED, None, True], "merged,-,yes"),
        (0, "0"),
        (2.5, "2.5"),
        ("plan(9c2b)", "plan(9c2b)"),
    ],
)
def test_a_field_value_is_written_by_one_rule(value: object, expected: str) -> None:
    assert LogField("key", value).text == f"key={expected}"


def test_empty_is_written_the_same_way_everywhere() -> None:
    """«Пусто» в строке лога — одно написание на всю программу."""
    assert LogValue.EMPTY.value == "-"
    assert LogField("a", None).rendered == LogField("b", "").rendered == LogValue.EMPTY.value


# --- событие


def test_fields_keep_the_order_of_the_arguments() -> None:
    event: LogEvent = LogEvent.of(_Event.DONE, rows=2, sheet="plan", ok=True)
    assert event.text == "probe_done rows=2 sheet=plan ok=yes"


def test_the_name_may_be_a_member_or_a_text() -> None:
    assert LogEvent.of("probe_done").text == LogEvent.of(_Event.DONE).text == "probe_done"


def test_extended_adds_fields_at_the_end_and_leaves_the_event_as_it_was() -> None:
    event: LogEvent = LogEvent.of(_Event.DONE, rows=2)
    longer: LogEvent = event.extended(attempts=1, retry=None)
    assert longer.text == "probe_done rows=2 attempts=1 retry=-"
    assert event.text == "probe_done rows=2"


def test_emit_writes_the_text_at_the_given_level() -> None:
    with LogCapture.on(LogArea.MAIN) as capture:
        LogEvent.of(_Event.DONE, rows=0).emit(get_logger(LogArea.MAIN), logging.WARNING)
        LogEvent.of(_Event.DONE, rows=1).emit(get_logger(LogArea.MAIN))
    assert capture.messages(logging.WARNING) == ["probe_done rows=0"]
    assert capture.messages(logging.INFO) == ["probe_done rows=1"]
