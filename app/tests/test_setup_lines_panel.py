"""Линии работы в окне без Tk (app\\setup\\panels\\lines_panel.py; CLAUDE.md §14 решения 37, 47, 48, 49): переключение и
выбор входа пишут только раздел lines, выбор ключей — только раздел broadcasts; строки «Главной» — для наборов «всё»,
«без таблицы» и «только эфиры и ключи», строка входа, строка ключей и её причины."""
from __future__ import annotations

from app.config.files import SettingsFile
from app.config.settings import LivecraftSettings
from app.paths import LivecraftPaths
from app.run.mode import LINE_ORDER, LineStage, RunPart
from app.setup.page import SetupPage
from app.setup.panels.lines_panel import KeysChoice, KeysReason, KeysRow, LineRow, LinesPanel, LineTone
from app.setup.readiness import Readiness
from app.tests.fixtures.settings import (
    DRIVE_FOLDER_URL, lines_on, lines_without, set_drive_folder, set_form_url, set_lines,
)
from app.ui import messages_ru as msg

FORM_URL: str = "https://forms.gle/AbCdEf123456"


def _rows(paths: LivecraftPaths) -> dict[RunPart, LineRow]:
    rows: tuple[LineRow, ...] = LinesPanel.from_paths(paths).rows(Readiness.check(paths))
    return {row.part: row for row in rows}


def _configured(paths: LivecraftPaths) -> LivecraftPaths:
    """Готовый корень с формой и папкой на Диске: не хватает только бота Telegram."""
    set_form_url(paths, FORM_URL)
    set_drive_folder(paths, DRIVE_FOLDER_URL)
    return paths


def test_switching_a_line_writes_only_the_lines_and_reads_the_file_again(ready_paths: LivecraftPaths) -> None:
    before: dict[str, object] = SettingsFile.of(ready_paths).load().to_data()
    panel: LinesPanel = LinesPanel.from_paths(ready_paths).switch(RunPart.DOC, False)
    after: LivecraftSettings = SettingsFile.of(ready_paths).load()
    assert {key for key, value in after.to_data().items() if before[key] != value} == {"lines"}
    assert after.lines == lines_without(RunPart.DOC) == panel.lines
    assert not panel.plan.works(RunPart.DOC) and not panel.plan.works(RunPart.DOC_COPY)


def test_switching_keeps_what_was_saved_after_the_panel_was_read(ready_paths: LivecraftPaths) -> None:
    """Раздел lines — поверх файла, как он сейчас на диске: ссылка, записанная после чтения модели, не откатывается."""
    panel: LinesPanel = LinesPanel.from_paths(ready_paths)
    set_form_url(ready_paths, FORM_URL)
    panel.switch(RunPart.KEYS, False)
    assert SettingsFile.of(ready_paths).load().form.url == FORM_URL


def test_all_lines_on_every_row_is_switchable_and_names_what_it_lacks(ready_paths: LivecraftPaths) -> None:
    """«Всё»: у всех линий ползунок доступен; телеграму не хватает бота, остальные готовы."""
    rows: dict[RunPart, LineRow] = _rows(_configured(ready_paths))
    assert list(rows) == list(LINE_ORDER)
    assert all(row.is_switchable for row in rows.values())
    assert rows[RunPart.ANNOUNCE].state == msg.SETUP_LINE_BLOCKED.format(gaps=msg.READINESS_GAP_TELEGRAM)
    assert "«Livecraft — настройка»" not in rows[RunPart.ANNOUNCE].state      # вкладку называет «Перейти»
    assert rows[RunPart.ANNOUNCE].tone is LineTone.BLOCKED
    ready: list[RunPart] = [part for part, row in rows.items() if row.tone is LineTone.READY]
    assert ready == [part for part in LINE_ORDER if part is not RunPart.ANNOUNCE]
    assert all(row.state == msg.SETUP_LINE_READY for part, row in rows.items() if part in ready)
    assert rows[RunPart.MERGE].does == msg.SETUP_LINE_DOES["merge"]
    assert rows[RunPart.DOC_COPY].page is SetupPage.DOC and rows[RunPart.KEYS].page is SetupPage.KEYS


def test_without_the_table_only_the_ai_waits_for_it(ready_paths: LivecraftPaths) -> None:
    """«Без таблицы» — вход «Пакеты» (§14 решение 51): нейросеть недоступна и говорит, что ждёт таблицу; вывод, эфиры и
    ключи работают от пакетов — форма настроек им тогда не нужна."""
    set_lines(ready_paths, lines_without(RunPart.PLAN))
    rows: dict[RunPart, LineRow] = _rows(ready_paths)
    waiting: list[RunPart] = [part for part, row in rows.items() if not row.is_switchable]
    assert waiting == [RunPart.MERGE]
    assert rows[RunPart.MERGE].state == msg.SETUP_LINE_SUPPORT_REASONS["plan"]
    assert rows[RunPart.MERGE].state == "работает только от таблицы плана"
    assert rows[RunPart.MERGE].tone is LineTone.QUIET
    assert rows[RunPart.PLAN].state == msg.SETUP_LINE_OFF
    working: list[RunPart] = [part for part in LINE_ORDER if part not in (RunPart.PLAN, RunPart.MERGE)]
    assert all(rows[part].tone is not LineTone.QUIET for part in working)
    ready: list[RunPart] = [part for part in working if rows[part].state == msg.SETUP_LINE_READY]
    assert ready == [
        RunPart.LOCAL_PREVIEWS, RunPart.DOC_COPY, RunPart.PACKAGE, RunPart.BROADCAST, RunPart.KEYS
    ]                                                       # остальным не хватает папки Диска и бота — не опоры
    runs: str = msg.SETUP_HOME_RUNS.format(
        source="из пакетов", lines=msg.LIST_JOINER.join(part.human_label for part in working)
    )
    assert LinesPanel.from_paths(ready_paths).run_line == runs


def test_from_the_table_without_the_ai_the_package_and_the_broadcasts_wait_for_it(ready_paths: LivecraftPaths) -> None:
    """Таблица без нейросети (§14 решение 50): пакет, эфиры и ключи ждут нейросеть — от таблицы они работают только с
    ней."""
    set_lines(ready_paths, lines_without(RunPart.MERGE))
    rows: dict[RunPart, LineRow] = _rows(ready_paths)
    waiting: list[RunPart] = [part for part, row in rows.items() if not row.is_switchable]
    assert waiting == [RunPart.PACKAGE, RunPart.BROADCAST, RunPart.KEYS]
    assert all(rows[part].state == msg.SETUP_LINE_SUPPORT_REASONS["merge"] for part in waiting)
    assert "только с нейросетью" in rows[RunPart.PACKAGE].state


def test_only_the_broadcasts_and_the_keys(ready_paths: LivecraftPaths) -> None:
    """«Только эфиры и ключи» — вход «Пакеты»: выключенная линия без своей опоры — «выключена», с выключенной опорой —
    ждёт первую выключенную линию своей цепочки (нейросеть — таблицу, копия документа — документ)."""
    set_lines(ready_paths, lines_on(RunPart.BROADCAST, RunPart.KEYS))
    rows: dict[RunPart, LineRow] = _rows(ready_paths)
    off: list[RunPart] = [part for part, row in rows.items() if row.state == msg.SETUP_LINE_OFF]
    assert off == [
        RunPart.PLAN, RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS, RunPart.DOC, RunPart.PACKAGE, RunPart.ANNOUNCE
    ]
    assert rows[RunPart.MERGE].state == msg.SETUP_LINE_SUPPORT_REASONS["plan"]
    assert rows[RunPart.DOC_COPY].state == msg.SETUP_LINE_WITH_SUPPORT.format(line=RunPart.DOC.human_label)
    assert [part for part, row in rows.items() if row.tone is not LineTone.QUIET] == [RunPart.BROADCAST, RunPart.KEYS]


def test_a_line_waits_for_the_first_switched_off_line_of_its_chain(ready_paths: LivecraftPaths) -> None:
    set_lines(ready_paths, lines_without(RunPart.DOC))
    assert _rows(ready_paths)[RunPart.DOC_COPY].state == msg.SETUP_LINE_WITH_SUPPORT.format(line="Google-документ")


def test_a_switched_off_line_lacks_nothing(livecraft_paths: LivecraftPaths) -> None:
    """Выключенной линии нечего настраивать: строк нужд у неё нет, даже на чистой установке."""
    SettingsFile.of(livecraft_paths).install_shipped()
    set_lines(livecraft_paths, lines_on(RunPart.PLAN))
    rows: dict[RunPart, LineRow] = _rows(livecraft_paths)
    assert rows[RunPart.MERGE].unmet == () and rows[RunPart.MERGE].state == msg.SETUP_LINE_OFF
    assert rows[RunPart.PLAN].unmet and rows[RunPart.PLAN].tone is LineTone.BLOCKED


def test_no_working_line_means_the_run_does_nothing(ready_paths: LivecraftPaths) -> None:
    set_lines(ready_paths, lines_on())
    assert LinesPanel.from_paths(ready_paths).run_line == msg.SETUP_HOME_RUNS_NOTHING


def test_the_run_line_names_the_input(ready_paths: LivecraftPaths) -> None:
    """«Запуск сделает» называет, откуда эфиры: из таблицы плана или из пакетов."""
    working: str = msg.LIST_JOINER.join(part.human_label for part in LINE_ORDER)
    assert LinesPanel.from_paths(ready_paths).run_line == msg.SETUP_HOME_RUNS.format(
        source="из таблицы плана", lines=working
    )
    assert "(эфиры из таблицы плана)" in LinesPanel.from_paths(ready_paths).run_line


# --- этапы «Главной» и вход (§14 решение 48)


def test_every_line_stands_under_its_stage_in_the_home_order() -> None:
    assert LineStage.INPUT.parts == (RunPart.PLAN,)
    assert LineStage.PROCESSING.parts == (RunPart.MERGE,)
    assert LineStage.OUTPUT.parts == (
        RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS, RunPart.DOC, RunPart.DOC_COPY, RunPart.PACKAGE, RunPart.ANNOUNCE
    )
    assert LineStage.BROADCASTS.parts == (RunPart.BROADCAST, RunPart.KEYS)
    assert RunPart.PACKAGES_IN.stage is LineStage.INPUT
    assert [stage.human_label for stage in LineStage] == list(msg.SETUP_LINE_STAGES.values())


def test_choosing_the_input_writes_only_the_table_line(ready_paths: LivecraftPaths) -> None:
    """Вход — одно из двух (§14 решение 48): «Пакеты» выключают таблицу плана, «Таблица плана» включает её; новых
    полей в файле нет."""
    before: dict[str, object] = SettingsFile.of(ready_paths).load().to_data()
    panel: LinesPanel = LinesPanel.from_paths(ready_paths).choose_input(RunPart.PACKAGES_IN)
    after: LivecraftSettings = SettingsFile.of(ready_paths).load()
    assert {key for key, value in after.to_data().items() if before[key] != value} == {"lines"}
    assert after.lines == lines_without(RunPart.PLAN) and panel.plan.source is RunPart.PACKAGES_IN
    assert LinesPanel.from_paths(ready_paths).choose_input(RunPart.PLAN).plan.source is RunPart.PLAN
    assert SettingsFile.of(ready_paths).load().to_data() == before


def test_the_input_row_says_what_the_input_does_and_what_it_lacks(livecraft_paths: LivecraftPaths) -> None:
    """Строка входа: таблица на чистой установке — не хватает таблицы; пакеты — готовы; «Перейти» — на вкладку входа."""
    SettingsFile.of(livecraft_paths).install_shipped()
    table: LineRow = LinesPanel.from_paths(livecraft_paths).input_row(Readiness.check(livecraft_paths))
    assert (table.part, table.page, table.does) == (RunPart.PLAN, SetupPage.PLAN, msg.SETUP_LINE_DOES["plan"])
    assert table.tone is LineTone.BLOCKED and table.state.startswith("✗")
    set_lines(livecraft_paths, lines_without(RunPart.PLAN))
    packages: LineRow = LinesPanel.from_paths(livecraft_paths).input_row(Readiness.check(livecraft_paths))
    assert (packages.part, packages.page) == (RunPart.PACKAGES_IN, SetupPage.PACKAGE)
    assert packages.does == msg.SETUP_LINE_DOES["packages_in"]
    assert (packages.state, packages.tone) == (msg.SETUP_LINE_READY, LineTone.READY)


# --- строка «Ключи»: «новые | все» и почему выбор недоступен (§14 решения 47, 49)


def _keys(paths: LivecraftPaths) -> KeysRow:
    panel: LinesPanel = LinesPanel.from_paths(paths)
    return panel.keys_row(panel.rows(Readiness.check(paths)))


def test_choosing_all_keys_writes_only_the_broadcasts_section(ready_paths: LivecraftPaths) -> None:
    before: dict[str, object] = SettingsFile.of(ready_paths).load().to_data()
    panel: LinesPanel = LinesPanel.from_paths(ready_paths).choose_keys(KeysChoice.ALL)
    after: LivecraftSettings = SettingsFile.of(ready_paths).load()
    assert {key for key, value in after.to_data().items() if before[key] != value} == {"broadcasts"}
    assert after.broadcasts.resend_keys and panel.keys_choice is KeysChoice.ALL
    assert panel.choose_keys(KeysChoice.NEW).keys_choice is KeysChoice.NEW
    assert SettingsFile.of(ready_paths).load().to_data() == before


def test_the_keys_choice_is_active_with_a_hint_for_each_value(ready_paths: LivecraftPaths) -> None:
    set_form_url(ready_paths, FORM_URL)
    new: KeysRow = _keys(ready_paths)
    assert (new.is_active, new.reason, new.choice) == (True, None, KeysChoice.NEW)
    assert new.text == msg.SETUP_KEYS_HINTS["new"]
    LinesPanel.from_paths(ready_paths).choose_keys(KeysChoice.ALL)
    every: KeysRow = _keys(ready_paths)
    assert every.is_active and every.text == msg.SETUP_KEYS_HINTS["all"]
    assert "повторные строки" in every.text and "последнюю" in every.text
    keys_label: str = msg.SETUP_HOME_RUNS_KEYS_ALL.format(line=RunPart.KEYS.human_label)
    assert LinesPanel.from_paths(ready_paths).run_line.endswith(keys_label)


def test_the_keys_choice_is_inactive_while_the_keys_line_is_off(ready_paths: LivecraftPaths) -> None:
    set_form_url(ready_paths, FORM_URL)
    set_lines(ready_paths, lines_without(RunPart.KEYS))
    row: KeysRow = _keys(ready_paths)
    assert (row.is_active, row.reason) == (False, KeysReason.OFF)
    assert row.text == msg.SETUP_KEYS_INACTIVE["off"] and "«Форма»" in row.text


def test_the_keys_choice_is_inactive_without_broadcasts(ready_paths: LivecraftPaths) -> None:
    set_form_url(ready_paths, FORM_URL)
    set_lines(ready_paths, lines_without(RunPart.BROADCAST))
    assert _keys(ready_paths).reason is KeysReason.NO_BROADCASTS
    set_lines(ready_paths, lines_without(RunPart.MERGE))
    row: KeysRow = _keys(ready_paths)
    assert (row.reason, row.text) == (KeysReason.NO_MERGE, msg.SETUP_KEYS_INACTIVE["no_merge"])


def test_the_keys_choice_is_inactive_from_the_table_without_a_form(ready_paths: LivecraftPaths) -> None:
    """Вход «Таблица», форма не задана — выбор недоступен; вход «Пакеты» — форма у каждого эфира из пакета: выбор
    доступен и без ссылки."""
    row: KeysRow = _keys(ready_paths)
    assert (row.reason, row.text) == (KeysReason.NO_FORM, msg.SETUP_KEYS_INACTIVE["no_form"])
    set_lines(ready_paths, lines_without(RunPart.PLAN))
    assert _keys(ready_paths).is_active
