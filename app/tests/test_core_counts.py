from __future__ import annotations

from enum import Enum

from app.core.counts import CountItem, Counts
from app.observability.log_event import LogEvent


class Reason(str, Enum):
    FIRST = "first"
    SECOND = "second"
    THIRD = "third"


def test_without_an_order_keys_go_in_the_order_of_first_appearance() -> None:
    counts: Counts[str] = Counts.of(["en", "uk", "en", "de", "uk", "en"])
    assert counts.items == (CountItem("en", 3), CountItem("uk", 2), CountItem("de", 1))
    assert counts.total == 6


def test_a_given_order_wins_and_keys_with_zero_are_left_out() -> None:
    counts: Counts[Reason] = Counts.of([Reason.THIRD, Reason.FIRST, Reason.THIRD], order=tuple(Reason))
    assert counts.items == (CountItem(Reason.FIRST, 1), CountItem(Reason.THIRD, 2))


def test_count_of_a_missing_key_is_zero() -> None:
    counts: Counts[str] = Counts.of(["uk"])
    assert (counts.count("uk"), counts.count("en")) == (1, 0)


def test_the_log_value_writes_an_enum_member_by_its_value_and_nothing_as_a_dash() -> None:
    counts: Counts[Reason] = Counts.of([Reason.SECOND, Reason.SECOND, Reason.FIRST])
    assert counts.log_value == ("second:2", "first:1")
    assert LogEvent.of("probe", failures=counts.log_value).text == "probe failures=second:2,first:1"
    assert LogEvent.of("probe", failures=Counts.of([]).log_value).text == "probe failures=-"


def test_joined_and_wrapped_build_the_console_part_from_the_templates_given() -> None:
    counts: Counts[str] = Counts.of(["uk", "en", "uk"])
    assert counts.joined("{name}: {count}", "; ", str.upper) == "UK: 2; EN: 1"
    assert counts.wrapped(" ({items})", "{name}: {count}", ", ", str) == " (uk: 2, en: 1)"
    assert Counts.of([]).wrapped(" ({items})", "{name}: {count}", ", ", str) == ""
