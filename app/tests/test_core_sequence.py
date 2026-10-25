from __future__ import annotations

from app.core.sequence import unique_in_order


def test_repeats_are_dropped_and_the_first_order_is_kept() -> None:
    assert unique_in_order(["b", "a", "b", "c", "a"]) == ("b", "a", "c")


def test_values_are_compared_as_they_are() -> None:
    assert unique_in_order([" a", "a", "A"]) == (" a", "a", "A")


def test_empty_input_and_any_iterable() -> None:
    assert unique_in_order([]) == ()
    assert unique_in_order(code for code in ("uk", "en", "uk")) == ("uk", "en")
