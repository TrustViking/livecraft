from __future__ import annotations

import pytest

from app.setup.run_mode import NOT_BUILT_PARTS, ExitCode, RunMode, RunPart
from app.ui import messages_ru as msg

TABLE_PARTS: tuple[RunPart, ...] = (RunPart.PLAN, RunPart.MERGE, RunPart.PACKAGE)
TABLE_PARTS_NO_LLM: tuple[RunPart, ...] = (RunPart.PLAN, RunPart.PACKAGE)


@pytest.mark.parametrize(
    ("mode", "no_llm", "parts"),
    [
        (RunMode.ANNOUNCE, False, (*TABLE_PARTS, RunPart.ANNOUNCE)),
        (RunMode.ANNOUNCE, True, (*TABLE_PARTS_NO_LLM, RunPart.ANNOUNCE)),
        (RunMode.BROADCAST, False, (*TABLE_PARTS, RunPart.BROADCAST)),
        (RunMode.BROADCAST, True, (*TABLE_PARTS_NO_LLM, RunPart.BROADCAST)),
        (RunMode.ALL, False, (*TABLE_PARTS, RunPart.ANNOUNCE, RunPart.BROADCAST)),
        (RunMode.ALL, True, (*TABLE_PARTS_NO_LLM, RunPart.ANNOUNCE, RunPart.BROADCAST)),
        (RunMode.FROM_PACKAGE, False, (RunPart.PACKAGES_IN, RunPart.BROADCAST)),
        (RunMode.FROM_PACKAGE, True, (RunPart.PACKAGES_IN, RunPart.BROADCAST)),
    ],
)
def test_every_mode_has_its_parts_in_work_order(mode: RunMode, no_llm: bool, parts: tuple[RunPart, ...]) -> None:
    """Режим А: таблица, нейросеть (кроме --no-llm), пакет, затем выводы; режим Б: пакеты и эфиры (§14 решения 17, 18)."""
    assert mode.parts(no_llm) == parts


@pytest.mark.parametrize(
    ("announce", "broadcast", "from_package", "mode"),
    [
        (False, False, False, RunMode.ALL),
        (True, False, False, RunMode.ANNOUNCE),
        (False, True, False, RunMode.BROADCAST),
        (False, False, True, RunMode.FROM_PACKAGE),
    ],
)
def test_the_mode_comes_from_the_flags(announce: bool, broadcast: bool, from_package: bool, mode: RunMode) -> None:
    assert RunMode.of(announce=announce, broadcast=broadcast, from_package=from_package) is mode


def test_only_the_package_mode_skips_the_table() -> None:
    assert [mode for mode in RunMode if not mode.is_from_table] == [RunMode.FROM_PACKAGE]


def test_merge_announce_broadcast_and_package_reading_are_not_built_yet() -> None:
    assert NOT_BUILT_PARTS == {RunPart.MERGE, RunPart.ANNOUNCE, RunPart.BROADCAST, RunPart.PACKAGES_IN}
    for part in RunPart:
        assert part.is_built is (part not in NOT_BUILT_PARTS)


def test_every_part_has_a_label_and_every_missing_part_a_stage() -> None:
    for part in RunPart:
        assert part.human_label == msg.RUN_PART_LABELS[part.value]
        line: str | None = part.not_built_line
        if part.is_built:
            assert line is None
            continue
        template: str = msg.RUN_PART_NOT_BUILT_TEXTS.get(part.value, msg.RUN_PART_NOT_BUILT)
        assert line == template.format(part=part.human_label, stage=msg.RUN_PART_STAGES[part.value])


def test_the_merge_line_says_the_texts_come_from_the_videos() -> None:
    """Без нейросети запуск идёт на текстах видео — строка говорит именно это, а не «не выполняется»."""
    line: str | None = RunPart.MERGE.not_built_line
    assert line is not None and "из видео" in line and msg.RUN_PART_STAGES["merge"] in line


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


def test_main_reexports_the_exit_codes() -> None:
    from app import main

    assert main.ExitCode is ExitCode


def test_the_log_identifiers_are_ascii() -> None:
    assert all(part.value.isascii() for part in RunPart) and all(mode.value.isascii() for mode in RunMode)
