"""Таблица плана на вкладке «Таблица плана» без окна: образец и проверка (CLAUDE.md §8.2 п.2, §14 решение 26).

`TableSample` — какой должна быть таблица: шапка из колонки языка (`LANGUAGE_HEADER` — её пишет сама программа, §14
решение 29), колонки чипа видео (для человека), названий колонок плана (`PlanColumn.human` — их узнаёт и сам план) и
колонки превью (`PREVIEW_HEADER` — её пишет сама программа, §14 решение 27) и строка образца. `TableCheck` читает
таблицу тем же кодом, что запуск (`SheetsReader.read_plan`, `SheetPlan.plan_rows`), в зоне программы и по её часам, и
отдаёт `TableVerdict` — строки итога для окна. Проверка идёт в фоновом потоке окна: модель не знает ни потоков, ни Tk;
«открылся браузер» она сообщает тем, кого ей дали (`on_login`). Вход оператора — по тому же правилу, что в запуске
(`OperatorSheets`, app\\sheets\\operator.py): каким аккаунтом вошли и повторный вход, когда аккаунту таблица не открыта;
строки правила — первыми строками итога. По тому же правилу таблицу читает и проверка формы ключей (`read_plan`).

В строках итога нет значений сейфа (§7.4): лист, буквы колонок, число эфиров и ближайший момент, либо текст ошибки
чтения или проблемы плана — они сами без значений.
"""
from __future__ import annotations

import dataclasses
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from app.config.files import SettingsFile
from app.config.json_node import ConfigError
from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.core.dates import format_human_datetime
from app.core.text_format import NEWLINE
from app.google.auth import GoogleLogin
from app.paths import LivecraftPaths
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.store import VaultStore
from app.secretsafe.vault import Vault
from app.sheets.client import SheetsReadError, SheetsTarget
from app.sheets.operator import OperatorDoor, OperatorSheets
from app.sheets.plan import PlanColumn, SheetColumns, SheetPlan
from app.sheets.preview import LANGUAGE_HEADER, PREVIEW_HEADER
from app.sheets.rows import PlannedRows
from app.ui.messages import msg


@dataclass(frozen=True)
class TableSample:
    """Образец таблицы плана: шапка и одна строка — колонка языка (её пишет программа), колонка чипа видео
    (для человека), колонки плана в порядке `PlanColumn`, последней — колонка превью (её пишет программа); пояс
    программы `timezone` — для текста после образца."""

    timezone: str

    @property
    def header(self) -> tuple[str, ...]:
        plan: tuple[str, ...] = tuple(column.human for column in PlanColumn)
        return (LANGUAGE_HEADER, msg.SETUP_TABLE_SAMPLE_CHIP_HEADER, *plan, PREVIEW_HEADER)

    @property
    def row(self) -> tuple[str, ...]:
        plan: tuple[str, ...] = tuple(msg.SETUP_TABLE_SAMPLE_ROW[column.value] for column in PlanColumn)
        by_program: str = msg.SETUP_TABLE_SAMPLE_BY_PROGRAM
        return (by_program, msg.SETUP_TABLE_SAMPLE_CHIP, *plan, by_program)

    @property
    def rules(self) -> str:
        """Что после образца: строка — видео, форматы даты и времени, пояс программы, что пишет программа."""
        return msg.SETUP_TABLE_TEXT_AFTER.format(timezone=self.timezone)


@dataclass(frozen=True)
class TableVerdict:
    """Итог проверки: годится ли таблица и строки для окна."""

    is_ok: bool
    lines: tuple[str, ...]

    @classmethod
    def failed(cls, problem: str) -> TableVerdict:
        return cls(is_ok=False, lines=(msg.SETUP_TABLE_FAILED.format(problem=problem),))

    @classmethod
    def of_plan(cls, plan: SheetPlan, columns: SheetColumns, rows: PlannedRows) -> TableVerdict:
        """Лист, буквы колонок, число будущих эфиров и ближайший; есть отсеянные строки — ещё строка разбора."""
        found: dict[str, str] = {column.value: columns.letters(column) for column in PlanColumn}
        first: str = msg.SETUP_TABLE_OK_NONE.format(sheet=plan.sheet_title, **found)
        if rows.admitted:
            nearest: str = format_human_datetime(min(row.start for row in rows.admitted))
            first = msg.SETUP_TABLE_OK_NEAREST.format(
                sheet=plan.sheet_title, count=len(rows.admitted), nearest=nearest, **found
            )
        return cls(is_ok=True, lines=(first, rows.console_line) if rows.skipped else (first,))

    @property
    def text(self) -> str:
        return NEWLINE.join(self.lines)

    def after(self, notes: Sequence[str]) -> TableVerdict:
        """Тот же итог, перед строками которого — строки входа оператора: каким аккаунтом вошли, аккаунту таблица не
        открыта."""
        return dataclasses.replace(self, lines=(*notes, *self.lines))


@dataclass(frozen=True)
class TableCheck:
    """Проверка таблицы плана этой установки: сейф и livecraft.json — с диска, таблица — на входе оператора `door`
    по тому же правилу, что запуск (`OperatorSheets`; в тестах вход — подделка), «сейчас» — часами `clock`."""

    paths: LivecraftPaths
    door: OperatorDoor
    clock: Clock = field(default_factory=Clock.utc)

    @classmethod
    def of(cls, paths: LivecraftPaths) -> TableCheck:
        """Боевая проверка: вход оператора этой установки; браузер — если входа ещё не было или аккаунту входа
        таблица не открыта."""
        return cls(paths=paths, door=OperatorDoor(GoogleLogin.operator(paths)))

    def read_plan(self, vault: Vault, on_login: Callable[[], None], say: Callable[[str], None]) -> SheetPlan:
        """План таблицы, которую называет сейф, — по правилу входа оператора (`OperatorSheets`): перед браузером —
        `on_login`, строки правила (каким аккаунтом вошли, аккаунту таблица не открыта) — в `say`. Таблица не задана —
        SheetsReadError(NOT_CONFIGURED) сразу, до входа в Google."""
        SheetsTarget.from_vault(vault)
        return OperatorSheets(self.door, on_login, say).read_plan(vault).plan

    def run(self, on_login: Callable[[], None]) -> TableVerdict:
        """Прочитать таблицу и сказать, что нашлось; сейф, настройки или чтение не удались — строка с причиной.
        Строки входа оператора — первыми строками итога."""
        try:
            vault: Vault = VaultStore.open(self.paths).load().vault
            settings: LivecraftSettings = SettingsFile.of(self.paths).load()
        except (VaultFormatError, ConfigError) as error:
            return TableVerdict.failed(error.human)
        notes: list[str] = []
        try:
            plan: SheetPlan = self.read_plan(vault, on_login, notes.append)
        except SheetsReadError as error:
            return TableVerdict.failed(error.human).after(notes)
        if plan.columns is None or plan.problem is not None:
            return TableVerdict.failed(plan.problem_text).after(notes)
        rows: PlannedRows = plan.plan_rows(settings.zone, self.clock.now())
        return TableVerdict.of_plan(plan, plan.columns, rows).after(notes)
