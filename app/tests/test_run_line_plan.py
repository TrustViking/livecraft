from __future__ import annotations

from app.run.exit_code import RunOutcome
from app.run.line_plan import LinePlan, LineState, LineStatus, ModeReadiness, RunScope, RunTexts, RunTextSource
from app.run.mode import LINE_ORDER, ModeStep, Need, NeedGap, PartReadiness, RunPart
from app.ui import messages_ru as msg

ALL_ON: frozenset[RunPart] = frozenset(LINE_ORDER)


def plan_of(*parts: RunPart) -> LinePlan:
    return LinePlan(frozenset(parts))


def without(*parts: RunPart) -> LinePlan:
    return LinePlan(ALL_ON - set(parts))


# --- линии: работает ли линия и чего ей не хватает


def test_every_line_works_when_all_are_on() -> None:
    plan: LinePlan = LinePlan(ALL_ON)
    assert all(line.state is LineState.WORKS for line in plan.lines)
    assert plan.working == tuple(part for part in RunPart if part is not RunPart.PACKAGES_IN)
    assert plan.unsupported == ()


def test_a_line_without_its_support_does_not_work_and_names_the_switched_off_line() -> None:
    """Вход «Таблица», документ выключен: копии документа не хватает документа; эфиры выключены — ключам не хватает
    эфиров; прочие линии работают."""
    plan: LinePlan = without(RunPart.DOC, RunPart.BROADCAST)
    copy: LineStatus = plan.status(RunPart.DOC_COPY)
    assert copy.state is LineState.NO_SUPPORT and copy.missing is RunPart.DOC
    assert plan.status(RunPart.KEYS).missing is RunPart.BROADCAST
    assert plan.working == (
        RunPart.PLAN, RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS, RunPart.MERGE, RunPart.PACKAGE, RunPart.ANNOUNCE
    )


def test_a_switched_off_line_is_off_whatever_its_support() -> None:
    plan: LinePlan = without(RunPart.MERGE, RunPart.PLAN)
    assert plan.status(RunPart.MERGE).state is LineState.OFF
    assert plan.status(RunPart.PLAN).state is LineState.OFF


def test_without_the_table_the_broadcasts_read_the_packages_first() -> None:
    """Таблица выключена, эфиры включены — режим Б: чтение пакетов перед эфирами (§14 решение 37)."""
    plan: LinePlan = plan_of(RunPart.BROADCAST, RunPart.KEYS)
    assert plan.working == (RunPart.PACKAGES_IN, RunPart.BROADCAST, RunPart.KEYS)
    assert not plan.works(RunPart.PLAN) and plan.works(RunPart.PACKAGES_IN)


def test_with_the_table_the_packages_are_not_read() -> None:
    plan: LinePlan = plan_of(RunPart.PLAN, RunPart.MERGE, RunPart.BROADCAST)
    assert plan.source is RunPart.PLAN
    assert plan.working == (RunPart.PLAN, RunPart.MERGE, RunPart.BROADCAST)
    assert not plan.works(RunPart.PACKAGES_IN)


def test_from_the_table_without_the_ai_the_package_and_the_broadcasts_do_not_work() -> None:
    """Вход «Таблица» без нейросети (§14 решение 50): вывод для людей идёт, пакет, эфиры и ключи — нет: им не хватает
    нейросети, и сводка называет причину."""
    plan: LinePlan = without(RunPart.MERGE)
    assert plan.status(RunPart.PACKAGE).missing is RunPart.MERGE
    assert plan.status(RunPart.BROADCAST).missing is RunPart.MERGE
    assert plan.status(RunPart.KEYS).missing is RunPart.MERGE
    assert plan.working == (
        RunPart.PLAN, RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS, RunPart.DOC, RunPart.DOC_COPY, RunPart.ANNOUNCE
    )
    assert plan.summary_lines[-1] == (
        "  не работают без «Нейросеть»: Пакет, Эфиры YouTube, Ключи в форму — от таблицы плана они работают только с "
        "нейросетью: тексты «по номерам» на YouTube и в пакет не идут"
    )


def test_from_the_packages_every_output_works_and_the_ai_waits_for_the_table() -> None:
    """Вход «Пакеты» (§14 решение 51): превью, документ и копия, пакет, Telegram, эфиры и ключи работают от пакетов,
    первым — чтение пакетов; нейросети не хватает таблицы."""
    plan: LinePlan = without(RunPart.PLAN)
    assert plan.source is RunPart.PACKAGES_IN
    assert plan.working == (
        RunPart.PACKAGES_IN, RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS, RunPart.PACKAGE, RunPart.DOC,
        RunPart.DOC_COPY, RunPart.ANNOUNCE, RunPart.BROADCAST, RunPart.KEYS,
    )
    assert plan.status(RunPart.MERGE).missing is RunPart.PLAN
    assert plan.summary_lines[-1] == "  не работают без «Таблица плана»: Нейросеть"


def test_the_packages_are_read_for_any_working_line() -> None:
    """Пакеты читаются, когда таблица выключена и работает хоть одна линия — не только эфиры."""
    assert plan_of(RunPart.DOC).works(RunPart.PACKAGES_IN)
    assert plan_of(RunPart.PACKAGE).working == (RunPart.PACKAGES_IN, RunPart.PACKAGE)
    assert not plan_of(RunPart.MERGE).works(RunPart.PACKAGES_IN)
    assert not plan_of().works(RunPart.PACKAGES_IN)


def test_without_the_table_no_part_needs_the_form_of_the_settings() -> None:
    """Вход «Пакеты»: форма ключей — в каждом пакете, таблицы нет: ни форма настроек, ни таблица не нужны никому; с
    таблицей — нужны."""
    packages: LinePlan = plan_of(RunPart.DRIVE_PREVIEWS, RunPart.DOC, RunPart.BROADCAST, RunPart.KEYS)
    assert packages.needs_of(RunPart.KEYS) == (Need.SETTINGS,)
    assert packages.needs_of(RunPart.DOC) == (Need.DRIVE_FOLDER, Need.SETTINGS, Need.CLIENT_SECRET)
    assert packages.needs_of(RunPart.DRIVE_PREVIEWS) == (Need.DRIVE_FOLDER, Need.SETTINGS, Need.CLIENT_SECRET)
    table: LinePlan = plan_of(RunPart.PLAN, RunPart.MERGE, RunPart.DRIVE_PREVIEWS, RunPart.BROADCAST, RunPart.KEYS)
    assert table.needs_of(RunPart.KEYS) == (Need.FORM, Need.SETTINGS)
    assert Need.SHEETS_VAULT in table.needs_of(RunPart.DRIVE_PREVIEWS)


def test_a_line_without_support_is_not_an_error_but_a_summary_line() -> None:
    """Линия без опоры не работает и ошибкой не считается (§14 решение 37): строки консоли нет, в сводке — одна строка
    на опору."""
    plan: LinePlan = plan_of(RunPart.PLAN, RunPart.DOC_COPY)
    assert plan.console_lines == ()
    assert plan.summary_lines[-1] == "  не работают без «Google-документ»: Копия документа"


def test_the_lines_without_support_are_grouped_by_the_missing_line() -> None:
    """Таблица выключена: нейросеть ждёт таблицу; копия документа ждёт документ, а не таблицу, пока документ
    выключен; пакет, Telegram и эфиры работают от пакетов."""
    plan: LinePlan = plan_of(RunPart.MERGE, RunPart.PACKAGE, RunPart.ANNOUNCE, RunPart.DOC_COPY, RunPart.BROADCAST)
    assert plan.summary_lines[-2:] == (
        "  не работают без «Таблица плана»: Нейросеть",
        "  не работают без «Google-документ»: Копия документа",
    )


def test_no_line_on_is_one_line_to_the_setup_window() -> None:
    assert plan_of().console_lines == (msg.LINES_NONE_WORKING,)
    assert msg.LINES_NONE_WORKING == (
        "Не включено ни одной линии работы: включите их в окне настройки (.\\livecraft.bat --setup)."
    )


def test_the_summary_names_the_working_and_the_switched_off_lines() -> None:
    plan: LinePlan = without(RunPart.ANNOUNCE, RunPart.DOC_COPY)
    assert plan.summary_lines == (
        "  линии работы: Таблица плана, Нейросеть, Превью на диске, Превью на Google Диске, Google-документ, Пакет, "
        "Эфиры YouTube, Ключи в форму",
        "  выключены: Копия документа, Telegram",
    )
    assert LinePlan(ALL_ON).summary_lines == (msg.READINESS_LINES_WORKING.format(lines=msg.LIST_JOINER.join(
        part.human_label for part in LINE_ORDER
    )),)


# --- готовность работающих линий: что делает запуск и каков исход


SETTINGS_GAP: NeedGap = NeedGap(need=Need.SETTINGS, text="настройки не читаются")
FORM_GAP: NeedGap = NeedGap(need=Need.FORM, text="нет ссылки на форму")
OPENAI_GAP: NeedGap = NeedGap(need=Need.OPENAI_VAULT, text="ключ OpenAI — вкладка «Ключи и ссылки»")
VAULT_BROKEN: str = "файл ключей и ссылок не читается"


def ready(part: RunPart) -> PartReadiness:
    return PartReadiness(part=part, unmet=())


def blocked(part: RunPart, *gaps: NeedGap) -> PartReadiness:
    return PartReadiness(part=part, unmet=gaps or (SETTINGS_GAP,))


def mode_of(*parts: PartReadiness, plan: LinePlan | None = None) -> ModeReadiness:
    lines: LinePlan = plan or plan_of(*(part.part for part in parts if part.part is not RunPart.PACKAGES_IN))
    return ModeReadiness(plan=lines, parts=parts)


def test_a_blocked_base_opens_the_window() -> None:
    """Не готова таблица — не готово ничего: окно настройщика — всё, чего не хватает, задаётся в нём (§13 задача 7.1)."""
    assert mode_of(blocked(RunPart.PLAN), ready(RunPart.PACKAGE)).step is ModeStep.OPEN_SETUP
    assert not mode_of(blocked(RunPart.PLAN), ready(RunPart.PACKAGE)).runs(RunPart.PACKAGE)


def test_no_working_line_opens_the_window() -> None:
    mode: ModeReadiness = mode_of(plan=plan_of())
    assert mode.step is ModeStep.OPEN_SETUP and mode.lines == (msg.LINES_NONE_WORKING,) and not mode.is_ready


def test_the_run_is_ready_when_every_working_part_is() -> None:
    """Готовность окна — то же правило, что у запуска: всё, что работает, готово; линия без опоры не мешает."""
    assert mode_of(ready(RunPart.PLAN), ready(RunPart.PACKAGE)).is_ready
    assert not mode_of(ready(RunPart.PLAN), blocked(RunPart.PACKAGE)).is_ready
    assert mode_of(ready(RunPart.PLAN), plan=plan_of(RunPart.PLAN, RunPart.DOC_COPY)).is_ready


def test_a_ready_table_runs_the_plan() -> None:
    assert mode_of(ready(RunPart.PLAN), blocked(RunPart.PACKAGE)).step is ModeStep.RUN_PLAN


def test_mode_b_runs_the_packages_and_its_parts_run_by_their_own_readiness() -> None:
    """Вход «Пакеты»: готово чтение пакетов — прогон пакетов; части идут по своей готовности, опоры им не нужны."""
    ready_mode: ModeReadiness = mode_of(ready(RunPart.PACKAGES_IN), ready(RunPart.DOC), ready(RunPart.BROADCAST))
    assert ready_mode.step is ModeStep.RUN_PACKAGES
    assert ready_mode.runs(RunPart.DOC) and ready_mode.runs(RunPart.BROADCAST)
    blocked_mode: ModeReadiness = mode_of(ready(RunPart.PACKAGES_IN), ready(RunPart.DOC), blocked(RunPart.BROADCAST))
    assert blocked_mode.step is ModeStep.RUN_PACKAGES and blocked_mode.runs(RunPart.DOC)
    assert not blocked_mode.runs(RunPart.BROADCAST) and blocked_mode.outcome is RunOutcome.FAILED


def test_mode_b_with_unread_settings_opens_the_window() -> None:
    """Основа входа «Пакеты» — чтение пакетов: не готово оно — не готово ничего."""
    mode: ModeReadiness = mode_of(blocked(RunPart.PACKAGES_IN), ready(RunPart.BROADCAST))
    assert mode.step is ModeStep.OPEN_SETUP and not mode.runs(RunPart.BROADCAST)


def test_the_table_never_runs_the_packages() -> None:
    mode: ModeReadiness = mode_of(ready(RunPart.PLAN), ready(RunPart.MERGE), ready(RunPart.BROADCAST))
    assert mode.step is ModeStep.RUN_PLAN and not mode.runs(RunPart.PACKAGES_IN) and mode.runs(RunPart.BROADCAST)


def test_from_the_table_the_package_runs_only_with_the_ai() -> None:
    """Нейросеть не готова (нет ключа) — пакет и эфиры от таблицы не идут, хоть и готовы: их тексты были бы «по
    номерам» (§14 решение 50)."""
    mode: ModeReadiness = mode_of(
        ready(RunPart.PLAN), blocked(RunPart.MERGE, OPENAI_GAP), ready(RunPart.PACKAGE), ready(RunPart.BROADCAST),
    )
    assert not mode.runs(RunPart.PACKAGE) and not mode.runs(RunPart.BROADCAST)


def test_the_texts_of_the_run_follow_the_lines() -> None:
    """Откуда тексты эфиров (§14 решение 50): пакеты — из пакетов; таблица с нейросетью — от неё; без неё — тексты
    видео."""
    packages: RunScope = RunScope(frozenset({RunPart.PACKAGES_IN, RunPart.DOC}))
    with_ai: RunScope = RunScope(frozenset({RunPart.PLAN, RunPart.MERGE}))
    without_ai: RunScope = RunScope(frozenset({RunPart.PLAN, RunPart.DOC}))
    assert RunTexts(packages).source is RunTextSource.PACKAGES
    assert RunTexts(with_ai).source is RunTextSource.LLM
    assert RunTexts(without_ai).source is RunTextSource.VIDEOS
    assert [source.human for source in RunTextSource] == [
        "от нейросети", "тексты видео, у эфира из нескольких видео — «по номерам», только для людей", "из пакетов"
    ]


def test_a_part_runs_only_with_its_support() -> None:
    """Копия документа готова, а документу не хватает папки — копия не идёт; ключи не идут без эфиров."""
    mode: ModeReadiness = mode_of(
        ready(RunPart.PLAN), blocked(RunPart.DOC), ready(RunPart.DOC_COPY), blocked(RunPart.BROADCAST),
        ready(RunPart.KEYS),
    )
    assert mode.runs(RunPart.PLAN) and not mode.runs(RunPart.DOC) and not mode.runs(RunPart.DOC_COPY)
    assert not mode.runs(RunPart.KEYS)
    assert mode.scope(dry_run=True) == RunScope(parts=frozenset({RunPart.PLAN}), dry_run=True)


def test_a_blocked_part_makes_the_outcome_a_failure_and_a_line_without_support_does_not() -> None:
    """Не настроенная часть — ошибка (код 1); линия без опоры — нет (§14 решение 37): строк консоли у неё нет."""
    assert mode_of(ready(RunPart.PLAN), blocked(RunPart.PACKAGE)).outcome is RunOutcome.FAILED
    assert mode_of(ready(RunPart.PLAN), ready(RunPart.PACKAGE)).outcome is RunOutcome.DONE
    unsupported: ModeReadiness = mode_of(
        ready(RunPart.PACKAGES_IN), ready(RunPart.BROADCAST), plan=plan_of(RunPart.BROADCAST, RunPart.MERGE)
    )
    assert unsupported.outcome is RunOutcome.DONE
    assert unsupported.lines == ()
    assert unsupported.step is ModeStep.RUN_PACKAGES


def test_the_event_names_the_parts_by_state() -> None:
    mode: ModeReadiness = mode_of(ready(RunPart.PLAN), ready(RunPart.MERGE), blocked(RunPart.PACKAGE))
    assert mode.event.text == "mode_readiness ready=plan,merge blocked=package runs=plan,merge no_support=-"


def test_the_snapshot_has_a_field_for_every_line() -> None:
    mode: ModeReadiness = mode_of(
        ready(RunPart.PLAN), blocked(RunPart.MERGE, OPENAI_GAP), plan=plan_of(RunPart.PLAN, RunPart.MERGE, RunPart.KEYS)
    )
    text: str = mode.snapshot.text
    assert text.startswith("run_snapshot_lines plan=on=yes;state=works;ready=yes;unmet=- ")
    assert "merge=on=yes;state=works;ready=no;unmet=openai_vault" in text
    assert "keys=on=yes;state=no_support;ready=no;unmet=-" in text
    assert "announce=on=no;state=off;ready=no;unmet=-" in text
    assert all(f" {part.value}=" in text for part in LINE_ORDER)


def test_merge_without_the_key_is_blocked_the_table_runs_and_the_outcome_is_a_failure() -> None:
    """Нет ключа OpenAI: строка «Не готово — Нейросеть: …», таблица всё равно прогоняется, исход — ошибка (код 1);
    merge в прогоне нет, и пакет от таблицы без нейросети не идёт."""
    mode: ModeReadiness = mode_of(ready(RunPart.PLAN), blocked(RunPart.MERGE, OPENAI_GAP), ready(RunPart.PACKAGE))
    assert mode.step is ModeStep.RUN_PLAN and mode.outcome is RunOutcome.FAILED
    assert mode.lines == (msg.RUN_NEED_BLOCKED.format(parts=RunPart.MERGE.human_label, gap=OPENAI_GAP.text),)
    assert not mode.runs(RunPart.MERGE) and not mode.runs(RunPart.PACKAGE)


def test_merge_with_the_key_runs() -> None:
    mode: ModeReadiness = mode_of(ready(RunPart.PLAN), ready(RunPart.MERGE), ready(RunPart.PACKAGE))
    assert mode.runs(RunPart.MERGE) and mode.outcome is RunOutcome.DONE and mode.lines == ()


def test_one_need_of_several_parts_is_one_line_naming_them_all() -> None:
    """Сломанные настройки нужны таблице и пакету — одна строка, в ней обе части (а не две строки)."""
    mode: ModeReadiness = mode_of(blocked(RunPart.PLAN), blocked(RunPart.PACKAGE))
    parts: str = msg.LIST_JOINER.join((RunPart.PLAN.human_label, RunPart.PACKAGE.human_label))
    assert mode.lines == (msg.RUN_NEED_BLOCKED.format(parts=parts, gap=SETTINGS_GAP.text),)


def test_needs_are_said_in_work_order() -> None:
    mode: ModeReadiness = mode_of(ready(RunPart.PLAN), blocked(RunPart.PACKAGE, SETTINGS_GAP, FORM_GAP))
    package: str = RunPart.PACKAGE.human_label
    assert mode.lines == (
        msg.RUN_NEED_BLOCKED.format(parts=package, gap=SETTINGS_GAP.text),
        msg.RUN_NEED_BLOCKED.format(parts=package, gap=FORM_GAP.text),
    )


def test_one_text_of_different_needs_is_one_line_naming_all_their_parts() -> None:
    """Разные нужды с одним текстом (сломанный сейф) — одна строка со всеми частями, а не строка на нужду."""
    mode: ModeReadiness = mode_of(
        blocked(RunPart.PLAN, NeedGap(need=Need.SHEETS_VAULT, text=VAULT_BROKEN)),
        blocked(RunPart.MERGE, NeedGap(need=Need.OPENAI_VAULT, text=VAULT_BROKEN)),
    )
    parts: str = msg.LIST_JOINER.join((RunPart.PLAN.human_label, RunPart.MERGE.human_label))
    assert mode.lines == (msg.RUN_NEED_BLOCKED.format(parts=parts, gap=VAULT_BROKEN),)


def test_a_ready_run_says_nothing() -> None:
    assert mode_of(ready(RunPart.PLAN), ready(RunPart.PACKAGE)).lines == ()


def test_the_packages_are_the_base_even_when_an_output_is_blocked() -> None:
    """Основа входа «Пакеты» — чтение пакетов, первая часть по порядку работы: превью на Диске без папки не готовы, а
    запуск идёт; не готово чтение — не готово ничего."""
    plan: LinePlan = plan_of(RunPart.DRIVE_PREVIEWS, RunPart.PACKAGE)
    mode: ModeReadiness = ModeReadiness(
        plan=plan, parts=(ready(RunPart.PACKAGES_IN), blocked(RunPart.DRIVE_PREVIEWS), ready(RunPart.PACKAGE))
    )
    assert tuple(part.part for part in mode.parts) == plan.working
    assert mode.step is ModeStep.RUN_PACKAGES and mode.runs(RunPart.PACKAGE) and not mode.runs(RunPart.DRIVE_PREVIEWS)
    assert mode.outcome is RunOutcome.FAILED
