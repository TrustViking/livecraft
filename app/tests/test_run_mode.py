from __future__ import annotations

import pytest

from app.run.exit_code import RunOutcome
from app.run.flag import CliFlag
from app.run.mode import NOT_BUILT_PARTS, ModeReadiness, ModeStep, PartReadiness, RunMode, RunPart
from app.ui import messages_ru as msg

TABLE_PARTS: tuple[RunPart, ...] = (RunPart.PLAN, RunPart.MERGE, RunPart.PACKAGE)
TABLE_PARTS_NO_LLM: tuple[RunPart, ...] = (RunPart.PLAN, RunPart.PACKAGE)
SERVICE_MODES: tuple[RunMode, ...] = (RunMode.SETUP, RunMode.CHECK, RunMode.AUTH, RunMode.STATUS)


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


@pytest.mark.parametrize("mode", SERVICE_MODES)
def test_service_runs_have_no_parts_and_are_not_the_table(mode: RunMode) -> None:
    assert mode.is_service and not mode.is_from_table
    assert mode.parts(False) == () and mode.parts(True) == ()


def test_only_the_three_table_modes_read_the_table() -> None:
    assert [mode for mode in RunMode if mode.is_from_table] == [RunMode.ANNOUNCE, RunMode.BROADCAST, RunMode.ALL]


def test_every_mode_but_all_has_its_flag() -> None:
    """Режим «всё» — запуск без ключа; у остальных режимов и служебных запусков ключ свой."""
    assert RunMode.ALL.flag is None
    flags: dict[RunMode, CliFlag | None] = {mode: mode.flag for mode in RunMode if mode is not RunMode.ALL}
    assert flags == {
        RunMode.ANNOUNCE: CliFlag.ANNOUNCE,
        RunMode.BROADCAST: CliFlag.BROADCAST,
        RunMode.FROM_PACKAGE: CliFlag.FROM_PACKAGE,
        RunMode.SETUP: CliFlag.SETUP,
        RunMode.CHECK: CliFlag.CHECK,
        RunMode.AUTH: CliFlag.AUTH,
        RunMode.STATUS: CliFlag.STATUS,
    }


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


def test_the_log_identifiers_are_ascii() -> None:
    assert all(part.value.isascii() for part in RunPart) and all(mode.value.isascii() for mode in RunMode)
    assert all(step.value.isascii() for step in ModeStep)


# --- готовность режима по частям: что делает запуск и каков исход


def ready(part: RunPart) -> PartReadiness:
    return PartReadiness(part=part, is_ready=True, is_built=True, action=None)


def blocked(part: RunPart) -> PartReadiness:
    return PartReadiness(part=part, is_ready=False, is_built=True, action=f"не готово: {part.value}")


def not_built(part: RunPart) -> PartReadiness:
    return PartReadiness(part=part, is_ready=False, is_built=False, action=part.not_built_line)


def mode_of(*parts: PartReadiness, fixable: bool = True) -> ModeReadiness:
    return ModeReadiness(mode=RunMode.ALL, parts=parts, is_fixable_in_setup=fixable)


def test_a_blocked_base_opens_the_window_or_refuses_when_the_window_cannot_help() -> None:
    """Не готова таблица — не готово ничего: окно настройщика; повреждённый поставочный файл окно не заменит."""
    assert mode_of(blocked(RunPart.PLAN), ready(RunPart.PACKAGE)).step is ModeStep.OPEN_SETUP
    assert mode_of(blocked(RunPart.PLAN), ready(RunPart.PACKAGE), fixable=False).step is ModeStep.REFUSE


def test_a_ready_table_runs_the_plan() -> None:
    assert mode_of(ready(RunPart.PLAN), blocked(RunPart.PACKAGE)).step is ModeStep.RUN_PLAN


def test_a_mode_without_the_table_only_reports() -> None:
    """Режим Б этой версии — одни «пока нет»: окно не открывается, прогона таблицы нет."""
    assert mode_of(not_built(RunPart.PACKAGES_IN), not_built(RunPart.BROADCAST)).step is ModeStep.REPORT


def test_a_blocked_part_makes_the_outcome_a_failure() -> None:
    """Не настроенная реализованная часть — ошибка (код 1); нереализованная — «появится позже», не ошибка."""
    assert mode_of(ready(RunPart.PLAN), blocked(RunPart.PACKAGE)).outcome is RunOutcome.FAILED
    assert mode_of(ready(RunPart.PLAN), not_built(RunPart.MERGE)).outcome is RunOutcome.DONE


def test_the_event_names_the_parts_by_state() -> None:
    mode: ModeReadiness = mode_of(ready(RunPart.PLAN), not_built(RunPart.MERGE), blocked(RunPart.PACKAGE))
    assert mode.event.text == "mode_readiness mode=all ready=plan blocked=package not_built=merge"
