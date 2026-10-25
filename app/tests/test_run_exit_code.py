from __future__ import annotations

import pytest

from app.run.exit_code import ExitCode, RunOutcome


def test_exit_codes_are_the_ones_section_ten_names() -> None:
    assert (ExitCode.OK, ExitCode.ERRORS, ExitCode.CONFIG, ExitCode.NO_FUTURE_SLOTS) == (0, 1, 2, 3)


def test_weight_orders_the_codes_by_importance() -> None:
    """Конфигурация важнее «нет будущих слотов», «нет будущих слотов» — ошибок, ошибки — «всё сделано» (§10)."""
    ordered: list[ExitCode] = sorted(ExitCode, key=lambda code: code.weight)
    assert ordered == [ExitCode.OK, ExitCode.ERRORS, ExitCode.NO_FUTURE_SLOTS, ExitCode.CONFIG]


@pytest.mark.parametrize(
    ("first", "second", "combined"),
    [
        (ExitCode.OK, ExitCode.OK, ExitCode.OK),
        (ExitCode.OK, ExitCode.ERRORS, ExitCode.ERRORS),
        (ExitCode.ERRORS, ExitCode.NO_FUTURE_SLOTS, ExitCode.NO_FUTURE_SLOTS),
        (ExitCode.NO_FUTURE_SLOTS, ExitCode.CONFIG, ExitCode.CONFIG),
        (ExitCode.CONFIG, ExitCode.ERRORS, ExitCode.CONFIG),
        (ExitCode.NO_FUTURE_SLOTS, ExitCode.OK, ExitCode.NO_FUTURE_SLOTS),
    ],
)
def test_exit_codes_combine_by_importance(first: ExitCode, second: ExitCode, combined: ExitCode) -> None:
    """2 важнее 3, 3 важнее 1, 1 важнее 0 (§10) — в любом порядке."""
    assert first.combined(second) is combined
    assert second.combined(first) is combined


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        (RunOutcome.DONE, ExitCode.OK),
        (RunOutcome.FAILED, ExitCode.ERRORS),
        (RunOutcome.NOT_CONFIGURED, ExitCode.CONFIG),
        (RunOutcome.NOTHING_PLANNED, ExitCode.NO_FUTURE_SLOTS),
    ],
)
def test_every_outcome_has_its_exit_code(outcome: RunOutcome, code: ExitCode) -> None:
    assert outcome.exit_code is code


def test_the_outcome_identifiers_are_ascii() -> None:
    assert all(outcome.value.isascii() for outcome in RunOutcome)
