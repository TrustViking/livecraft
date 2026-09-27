from __future__ import annotations

import pytest

from app.run.exit_code import RunOutcome
from app.run.flag import CliFlag
from app.run.mode import (
    NOT_BUILT_PARTS,
    ModeReadiness,
    ModeStep,
    Need,
    NeedGap,
    PartReadiness,
    PartState,
    RunMode,
    RunPart,
)
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


def test_announce_broadcast_and_package_reading_are_not_built_yet_and_merge_is() -> None:
    assert NOT_BUILT_PARTS == {RunPart.ANNOUNCE, RunPart.BROADCAST, RunPart.PACKAGES_IN}
    assert RunPart.MERGE.is_built
    for part in RunPart:
        assert part.is_built is (part not in NOT_BUILT_PARTS)


def test_every_part_has_a_label_and_every_missing_part_a_stage() -> None:
    for part in RunPart:
        assert part.human_label == msg.RUN_PART_LABELS[part.value]
    for part in NOT_BUILT_PARTS:
        expected: str = msg.RUN_PART_NOT_BUILT.format(part=part.human_label, stage=msg.RUN_PART_STAGES[part.value])
        assert part.not_built_line == expected


def test_every_part_names_what_it_needs() -> None:
    """Таблице — сейф таблицы, настройки и вход в Google; нейросети — ключ; пакету — настройки и форма."""
    assert RunPart.PLAN.needs == (Need.SHEETS_VAULT, Need.SETTINGS, Need.CLIENT_SECRET)
    assert RunPart.MERGE.needs == (Need.OPENAI_VAULT,)
    assert RunPart.PACKAGE.needs == (Need.SETTINGS, Need.FORM)
    assert RunPart.BROADCAST.needs == (Need.CHANNELS, Need.SETTINGS, Need.FORM)
    assert RunPart.ANNOUNCE.needs == () and RunPart.PACKAGES_IN.needs == ()


def test_the_log_identifiers_are_ascii() -> None:
    assert all(part.value.isascii() for part in RunPart) and all(mode.value.isascii() for mode in RunMode)
    assert all(step.value.isascii() for step in ModeStep)
    assert all(need.value.isascii() for need in Need) and all(state.value.isascii() for state in PartState)


# --- готовность режима по частям: что делает запуск и каков исход


SETTINGS_GAP: NeedGap = NeedGap(need=Need.SETTINGS, text="настройки не читаются")
FORM_GAP: NeedGap = NeedGap(need=Need.FORM, text="нет ссылки на форму")


def ready(part: RunPart) -> PartReadiness:
    return PartReadiness(part=part, unmet=())


def blocked(part: RunPart, *gaps: NeedGap) -> PartReadiness:
    return PartReadiness(part=part, unmet=gaps or (SETTINGS_GAP,))


def not_built(part: RunPart) -> PartReadiness:
    return PartReadiness(part=part, unmet=())


def test_the_state_of_a_part_follows_from_its_gaps() -> None:
    assert ready(RunPart.PLAN).state is PartState.READY
    assert blocked(RunPart.PLAN).state is PartState.BLOCKED
    assert not_built(RunPart.ANNOUNCE).state is PartState.NOT_BUILT
    assert PartReadiness(part=RunPart.ANNOUNCE, unmet=(SETTINGS_GAP,)).state is PartState.NOT_BUILT


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
    assert mode_of(ready(RunPart.PLAN), not_built(RunPart.ANNOUNCE)).outcome is RunOutcome.DONE


def test_the_event_names_the_parts_by_state() -> None:
    mode: ModeReadiness = mode_of(
        ready(RunPart.PLAN), ready(RunPart.MERGE), blocked(RunPart.PACKAGE), not_built(RunPart.ANNOUNCE)
    )
    assert mode.event.text == "mode_readiness mode=all ready=plan,merge blocked=package not_built=announce"


# --- нейросеть: часть реализована, без ключа она не готова


OPENAI_GAP: NeedGap = NeedGap(need=Need.OPENAI_VAULT, text="ключ OpenAI — вкладка «Ключи и ссылки»")


def test_merge_without_the_key_is_blocked_the_table_runs_and_the_outcome_is_a_failure() -> None:
    """Нет ключа OpenAI: строка «Не готово — нейросеть: …», таблица всё равно прогоняется, исход — ошибка (код 1);
    merge в прогоне нет."""
    mode: ModeReadiness = mode_of(ready(RunPart.PLAN), blocked(RunPart.MERGE, OPENAI_GAP), ready(RunPart.PACKAGE))
    assert mode.step is ModeStep.RUN_PLAN and mode.outcome is RunOutcome.FAILED
    assert mode.lines == (msg.RUN_NEED_BLOCKED.format(parts=RunPart.MERGE.human_label, gap=OPENAI_GAP.text),)
    assert not mode.is_part_ready(RunPart.MERGE)


def test_merge_with_the_key_is_ready() -> None:
    mode: ModeReadiness = mode_of(ready(RunPart.PLAN), ready(RunPart.MERGE), ready(RunPart.PACKAGE))
    assert mode.is_part_ready(RunPart.MERGE) and mode.outcome is RunOutcome.DONE and mode.lines == ()


# --- одна строка на нужду с перечнем частей


def test_one_need_of_several_parts_is_one_line_naming_them_all() -> None:
    """Сломанные настройки нужны таблице и пакету — одна строка, в ней обе части (а не две строки)."""
    mode: ModeReadiness = mode_of(blocked(RunPart.PLAN), blocked(RunPart.PACKAGE), not_built(RunPart.BROADCAST))
    parts: str = msg.LIST_JOINER.join((RunPart.PLAN.human_label, RunPart.PACKAGE.human_label))
    assert mode.lines == (
        msg.RUN_NEED_BLOCKED.format(parts=parts, gap=SETTINGS_GAP.text),
        RunPart.BROADCAST.not_built_line,
    )


def test_needs_are_said_in_work_order_and_not_built_parts_stay_in_place() -> None:
    mode: ModeReadiness = mode_of(
        ready(RunPart.PLAN), not_built(RunPart.ANNOUNCE), blocked(RunPart.PACKAGE, SETTINGS_GAP, FORM_GAP)
    )
    package: str = RunPart.PACKAGE.human_label
    assert mode.lines == (
        RunPart.ANNOUNCE.not_built_line,
        msg.RUN_NEED_BLOCKED.format(parts=package, gap=SETTINGS_GAP.text),
        msg.RUN_NEED_BLOCKED.format(parts=package, gap=FORM_GAP.text),
    )


VAULT_BROKEN: str = "файл ключей и ссылок не читается"


def test_one_text_of_different_needs_is_one_line_naming_all_their_parts() -> None:
    """Разные нужды с одним текстом (сломанный сейф) — одна строка со всеми частями, а не строка на нужду."""
    mode: ModeReadiness = mode_of(
        blocked(RunPart.PLAN, NeedGap(need=Need.SHEETS_VAULT, text=VAULT_BROKEN)),
        blocked(RunPart.PACKAGE, NeedGap(need=Need.SETTINGS, text=VAULT_BROKEN)),
    )
    parts: str = msg.LIST_JOINER.join((RunPart.PLAN.human_label, RunPart.PACKAGE.human_label))
    assert mode.lines == (msg.RUN_NEED_BLOCKED.format(parts=parts, gap=VAULT_BROKEN),)


def test_a_broken_vault_for_the_plan_and_the_merge_is_one_line() -> None:
    """Сломанный сейф не даёт ни таблицы, ни ключа OpenAI — одна строка."""
    mode: ModeReadiness = mode_of(
        blocked(RunPart.PLAN, NeedGap(need=Need.SHEETS_VAULT, text=VAULT_BROKEN)),
        blocked(RunPart.MERGE, NeedGap(need=Need.OPENAI_VAULT, text=VAULT_BROKEN)),
    )
    parts: str = msg.LIST_JOINER.join((RunPart.PLAN.human_label, RunPart.MERGE.human_label))
    assert mode.lines == (msg.RUN_NEED_BLOCKED.format(parts=parts, gap=VAULT_BROKEN),)


def test_a_ready_mode_says_nothing() -> None:
    assert mode_of(ready(RunPart.PLAN), ready(RunPart.PACKAGE)).lines == ()
