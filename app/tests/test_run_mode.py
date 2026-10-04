from __future__ import annotations

import pytest

from app.run.flag import CliFlag
from app.run.mode import (
    CHANNEL_SERVICE_NEEDS,
    LINE_ORDER,
    PACKAGES_MET_NEEDS,
    PACKAGES_REQUIRES,
    TABLE_REQUIRES,
    ModeStep,
    Need,
    NeedGap,
    PartReadiness,
    PartState,
    RunMode,
    RunPart,
)
from app.ui import messages_ru as msg

SERVICE_MODES: tuple[RunMode, ...] = (RunMode.SETUP, RunMode.CHECK, RunMode.AUTH, RunMode.STATUS)


def test_the_parts_are_declared_in_work_order() -> None:
    """Порядок работы: вход (таблица или чтение пакетов — основа запуска), превью, нейросеть, пакет, документ и его
    копия, Telegram, эфиры, ключи."""
    assert tuple(RunPart) == (
        RunPart.PLAN,
        RunPart.PACKAGES_IN,
        RunPart.LOCAL_PREVIEWS,
        RunPart.DRIVE_PREVIEWS,
        RunPart.MERGE,
        RunPart.PACKAGE,
        RunPart.DOC,
        RunPart.DOC_COPY,
        RunPart.ANNOUNCE,
        RunPart.BROADCAST,
        RunPart.KEYS,
    )


def test_the_lines_are_every_part_but_the_package_reading_in_the_order_of_the_main_tab() -> None:
    """«Главная» окна (§14 решение 37): таблица, нейросеть, превью на диске и на Google Диске, документ и копия, пакет,
    Telegram, эфиры, ключи; чтение пакетов — не линия."""
    assert LINE_ORDER == (
        RunPart.PLAN,
        RunPart.MERGE,
        RunPart.LOCAL_PREVIEWS,
        RunPart.DRIVE_PREVIEWS,
        RunPart.DOC,
        RunPart.DOC_COPY,
        RunPart.PACKAGE,
        RunPart.ANNOUNCE,
        RunPart.BROADCAST,
        RunPart.KEYS,
    )
    assert set(LINE_ORDER) == set(RunPart) - {RunPart.PACKAGES_IN}


def test_every_line_knows_its_support_from_the_table() -> None:
    """Опоры входа «Таблица» (§14 решения 37, 50): со слотами таблицы работают нейросеть, оба превью, документ и
    Telegram; пакет и эфиры — только с нейросетью; копия документа — с документом; ключи в форму — с эфирами."""
    table: tuple[RunPart, ...] = (
        RunPart.MERGE, RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS, RunPart.DOC, RunPart.ANNOUNCE
    )
    assert all(part.requires_from(RunPart.PLAN) is RunPart.PLAN for part in table)
    assert RunPart.PACKAGE.requires_from(RunPart.PLAN) is RunPart.MERGE
    assert RunPart.BROADCAST.requires_from(RunPart.PLAN) is RunPart.MERGE
    assert RunPart.DOC_COPY.requires_from(RunPart.PLAN) is RunPart.DOC
    assert RunPart.KEYS.requires_from(RunPart.PLAN) is RunPart.BROADCAST
    assert RunPart.PLAN.requires_from(RunPart.PLAN) is None
    assert len(TABLE_REQUIRES) == len(table) + 4


def test_every_line_knows_its_support_from_the_packages() -> None:
    """Опоры входа «Пакеты» (§14 решение 51): нейросети нужна таблица; превью, документ, Telegram, пакет и эфиры
    своей опоры не требуют; копия документа — с документом; ключи в форму — с эфирами."""
    free: tuple[RunPart, ...] = (
        RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS, RunPart.DOC, RunPart.ANNOUNCE, RunPart.PACKAGE,
        RunPart.BROADCAST,
    )
    assert all(part.requires_from(RunPart.PACKAGES_IN) is None for part in free)
    assert RunPart.MERGE.requires_from(RunPart.PACKAGES_IN) is RunPart.PLAN
    assert RunPart.DOC_COPY.requires_from(RunPart.PACKAGES_IN) is RunPart.DOC
    assert RunPart.KEYS.requires_from(RunPart.PACKAGES_IN) is RunPart.BROADCAST
    assert len(PACKAGES_REQUIRES) == 3


def test_the_packages_bring_the_form_and_have_no_table() -> None:
    """При входе «Пакеты» форма ключей — в каждом пакете, а таблицы нет: эти нужды удовлетворены сами."""
    assert PACKAGES_MET_NEEDS == frozenset({Need.FORM, Need.SHEETS_VAULT})


@pytest.mark.parametrize("mode", SERVICE_MODES)
def test_the_service_runs_are_service(mode: RunMode) -> None:
    assert mode.is_service
    assert not RunMode.RUN.is_service


def test_only_the_service_runs_have_a_flag() -> None:
    """Работа по линиям — запуск без ключа (§14 решение 37: ключей режимов нет); у служебных запусков ключ свой."""
    assert RunMode.RUN.flag is None
    flags: dict[RunMode, CliFlag | None] = {mode: mode.flag for mode in SERVICE_MODES}
    assert flags == {
        RunMode.SETUP: CliFlag.SETUP,
        RunMode.CHECK: CliFlag.CHECK,
        RunMode.AUTH: CliFlag.AUTH,
        RunMode.STATUS: CliFlag.STATUS,
    }


def test_every_part_has_a_label() -> None:
    for part in RunPart:
        assert part.human_label == msg.RUN_PART_LABELS[part.value]


def test_the_lines_are_named_as_on_the_main_tab() -> None:
    labels: tuple[str, ...] = tuple(part.human_label for part in LINE_ORDER)
    assert labels == (
        "Таблица плана",
        "Нейросеть",
        "Превью на диске",
        "Превью на Google Диске",
        "Google-документ",
        "Копия документа",
        "Пакет",
        "Telegram",
        "Эфиры YouTube",
        "Ключи в форму",
    )


def test_the_channel_services_need_the_channels_the_settings_and_the_client_secret() -> None:
    """--check, --auth, --status: каналы, настройки и client_secret.json — не сейф и не форма; окну — ничего."""
    assert CHANNEL_SERVICE_NEEDS == (Need.CHANNELS, Need.SETTINGS, Need.CLIENT_SECRET)
    for mode in (RunMode.CHECK, RunMode.AUTH, RunMode.STATUS):
        assert mode.service_needs == CHANNEL_SERVICE_NEEDS
    assert RunMode.SETUP.service_needs == () and RunMode.RUN.service_needs == ()


def test_every_part_names_what_it_needs() -> None:
    """Таблице — сейф таблицы, настройки и вход в Google; превью в папке и копии документа — настройки; нейросети —
    ключ; пакету — настройки и форма; объявлениям в Telegram — бот и чат, форма и настройки; эфирам — каналы,
    настройки и client_secret.json (форма им больше не нужна); ключам в форму — форма и настройки."""
    assert RunPart.PLAN.needs == (Need.SHEETS_VAULT, Need.SETTINGS, Need.CLIENT_SECRET)
    assert RunPart.LOCAL_PREVIEWS.needs == (Need.SETTINGS,)
    assert RunPart.DRIVE_PREVIEWS.needs == (Need.DRIVE_FOLDER, Need.SHEETS_VAULT, Need.SETTINGS, Need.CLIENT_SECRET)
    assert RunPart.MERGE.needs == (Need.OPENAI_VAULT,)
    assert RunPart.PACKAGE.needs == (Need.SETTINGS, Need.FORM)
    assert RunPart.DOC.needs == (Need.DRIVE_FOLDER, Need.FORM, Need.SETTINGS, Need.CLIENT_SECRET)
    assert RunPart.DOC_COPY.needs == (Need.SETTINGS,)
    assert RunPart.ANNOUNCE.needs == (Need.TELEGRAM, Need.FORM, Need.SETTINGS)
    assert RunPart.PACKAGES_IN.needs == (Need.SETTINGS,)
    assert RunPart.BROADCAST.needs == (Need.CHANNELS, Need.SETTINGS, Need.CLIENT_SECRET)
    assert RunPart.KEYS.needs == (Need.FORM, Need.SETTINGS)


def test_the_log_identifiers_are_ascii() -> None:
    assert all(part.value.isascii() for part in RunPart) and all(mode.value.isascii() for mode in RunMode)
    assert all(step.value.isascii() for step in ModeStep)
    assert all(need.value.isascii() for need in Need) and all(state.value.isascii() for state in PartState)


def test_the_state_of_a_part_follows_from_its_gaps() -> None:
    gap: NeedGap = NeedGap(need=Need.SETTINGS, text="настройки не читаются")
    assert PartReadiness(part=RunPart.PLAN, unmet=()).state is PartState.READY
    blocked: PartReadiness = PartReadiness(part=RunPart.PLAN, unmet=(gap,))
    assert blocked.state is PartState.BLOCKED and blocked.lacks(gap.text) and not blocked.lacks("другое")
