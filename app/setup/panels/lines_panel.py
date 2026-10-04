"""Линии работы в окне настройщика — без Tk (CLAUDE.md §8.2, §14 решения 37, 47, 48, 49).

Что делает запуск, решают переключатели линий (раздел `lines` livecraft.json) и выбор ключей (раздел `broadcasts`).
Модель держит их, как они сейчас в файле, и пишет каждое изменение сразу — только свой раздел поверх файла, как он
сейчас на диске (`SettingsFile.latest`): разделы, сохранённые другими вкладками, не трогаются.

«Главная» по этапам работы (§14 решение 48). Вход — одно из двух: таблица плана или пакеты (`choose_input` пишет
линию таблицы: включена — вход «Таблица», выключена — вход «Пакеты»); строка входа — что он делает и чего ему не
хватает (`input_row`). Строка линии (`LineRow`) — название, что линия делает, состояние (работает, выключена или не
работает без опоры — какой линии ей не хватает и почему) и готовность: чего не хватает работающей линии — нужды
запуска (`Readiness.part`) без хвоста вкладки: её называет кнопка «Перейти» рядом. Ползунок линии без опоры
недоступен: её значение вернётся, когда опору включат. Строка «Ключи» (`KeysRow`) — выбор «новые | все» и почему он
сейчас ничего не решает (`KeysReason`). Внизу «Главной» — что сделает запуск: откуда эфиры, работающие линии и, при
«все», что ключи всех эфиров уйдут заново.

Модель неизменяемая: `switch`, `choose_input` и `choose_keys` отдают модель, прочитанную заново; OSError — наружу,
сказать о нём человеку — дело окна.
"""
from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from enum import Enum

from app.config.broadcasts import BroadcastSettings
from app.config.files import SettingsFile
from app.config.lines import LineSettings
from app.config.settings import LivecraftSettings
from app.paths import LivecraftPaths
from app.run.line_plan import LinePlan, LineStatus
from app.run.mode import Need, NeedGap, RunPart
from app.setup.page import SetupPage
from app.setup.panels.broadcasts_panel import BroadcastsPanel
from app.setup.readiness import Readiness
from app.ui.messages import msg


class LineTone(str, Enum):
    """Каким цветом окно пишет состояние линии. Значение — идентификатор."""

    READY = "ready"          # работает и готова
    BLOCKED = "blocked"      # работает, но чего-то не хватает
    QUIET = "quiet"          # выключена или ждёт опору


@dataclass(frozen=True)
class LineRow:
    """Строка линии (или входа): её состояние в плане линий и чего не хватает ей, если она работает."""

    status: LineStatus
    unmet: tuple[NeedGap, ...]

    @property
    def part(self) -> RunPart:
        return self.status.part

    @property
    def title(self) -> str:
        """Название строки: у ползунка передачи ключей — что он делает, у остальных — название линии."""
        return msg.SETUP_LINE_TITLES.get(self.part.value, self.part.human_label)

    @property
    def does(self) -> str:
        """Что делает линия — одной строкой."""
        return msg.SETUP_LINE_DOES[self.part.value]

    @property
    def page(self) -> SetupPage:
        """Вкладка линии — для «Перейти»."""
        return SetupPage.of_line(self.part)

    @property
    def is_switchable(self) -> bool:
        """Ползунок доступен: опора линии работает (или опоры нет)."""
        return self.status.missing is None

    @property
    def state(self) -> str:
        """Без опоры — без какой линии она не работает и почему; выключена — «выключена»; работает — готова или чего не
        хватает."""
        missing: RunPart | None = self.status.missing
        if missing is not None:
            return msg.SETUP_LINE_SUPPORT_REASONS.get(missing.value, msg.SETUP_LINE_WITH_SUPPORT).format(
                line=missing.human_label
            )
        if not self.status.is_on:
            return msg.SETUP_LINE_OFF
        if self.unmet:
            gaps: str = msg.SETUP_LINE_GAP_JOINER.join(gap.window_text for gap in self.unmet)
            return msg.SETUP_LINE_BLOCKED.format(gaps=gaps)
        return msg.SETUP_LINE_READY

    @property
    def tone(self) -> LineTone:
        if self.status.missing is not None or not self.status.is_on:
            return LineTone.QUIET
        return LineTone.BLOCKED if self.unmet else LineTone.READY


class KeysChoice(str, Enum):
    """Какие ключи передать в форму (§14 решения 47, 49). Значение — идентификатор и ключ подписи кнопки."""

    NEW = "new"      # ключи эфиров, поставленных этим запуском, и один повтор неподтверждённого ключа
    ALL = "all"      # ключи всех эфиров запуска ещё раз

    @classmethod
    def of(cls, broadcasts: BroadcastSettings) -> KeysChoice:
        return cls.ALL if broadcasts.resend_keys else cls.NEW

    @property
    def resend_keys(self) -> bool:
        return self is KeysChoice.ALL


class KeysReason(str, Enum):
    """Почему выбор «новые | все» сейчас ничего не решает. Значение — идентификатор и ключ строки причины."""

    OFF = "off"                      # передача ключей выключена на вкладке «Форма»
    NO_BROADCASTS = "no_broadcasts"  # эфиры выключены
    NO_MERGE = "no_merge"            # вход «Таблица», нейросеть выключена: от таблицы эфиры идут только с ней
    NO_FORM = "no_form"              # вход «Таблица», ссылка на форму не задана


@dataclass(frozen=True)
class KeysRow:
    """Строка «Ключи» на «Главной»: линия передачи ключей (`line`) и выбор «новые | все» (`choice`)."""

    line: LineRow
    choice: KeysChoice

    @property
    def reason(self) -> KeysReason | None:
        """Почему выбор ничего не решает — первое по порядку: передача выключена, эфиров нет, формы нет; решает —
        None."""
        status: LineStatus = self.line.status
        if not status.is_on:
            return KeysReason.OFF
        if status.missing is not None:
            return KeysReason.NO_MERGE if status.missing is RunPart.MERGE else KeysReason.NO_BROADCASTS
        if any(gap.need is Need.FORM for gap in self.line.unmet):
            return KeysReason.NO_FORM
        return None

    @property
    def is_active(self) -> bool:
        return self.reason is None

    @property
    def text(self) -> str:
        """Строка под кнопками: причина, почему выбор ничего не решает, иначе — что делает выбранное."""
        reason: KeysReason | None = self.reason
        if reason is not None:
            return msg.SETUP_KEYS_INACTIVE[reason.value]
        return msg.SETUP_KEYS_HINTS[self.choice.value]


@dataclass(frozen=True)
class LinesPanel:
    """Переключатели линий и выбор ключей, как они сейчас в файле настроек (файл не читается — поставочные), и файл."""

    lines: LineSettings
    broadcasts: BroadcastSettings
    file: SettingsFile

    @classmethod
    def from_paths(cls, paths: LivecraftPaths) -> LinesPanel:
        """Линии в livecraft.json этой установки."""
        return cls.from_file(SettingsFile.of(paths))

    @classmethod
    def from_file(cls, file: SettingsFile) -> LinesPanel:
        latest: LivecraftSettings = file.latest
        return cls(lines=latest.lines, broadcasts=latest.broadcasts, file=file)

    @property
    def plan(self) -> LinePlan:
        return self.lines.line_plan

    @property
    def keys_choice(self) -> KeysChoice:
        return KeysChoice.of(self.broadcasts)

    @property
    def run_line(self) -> str:
        """«Запуск сделает (эфиры — …): …» — вход и работающие линии в порядке «Главной», при «все» у передачи ключей —
        что ключи всех эфиров уйдут заново; ни одной — «ничего не сделает»."""
        plan: LinePlan = self.plan
        working: tuple[str, ...] = tuple(self._run_label(line.part) for line in plan.lines if plan.works(line.part))
        if not working:
            return msg.SETUP_HOME_RUNS_NOTHING
        source: str = msg.SETUP_HOME_RUN_SOURCES[plan.source.value]
        return msg.SETUP_HOME_RUNS.format(source=source, lines=msg.LIST_JOINER.join(working))

    def rows(self, readiness: Readiness) -> tuple[LineRow, ...]:
        """Строки линий в порядке «Главной»; готовность работающей линии — по свежей проверке `readiness`."""
        plan: LinePlan = self.plan
        return tuple(
            LineRow(status, readiness.part(status.part, plan).unmet if plan.works(status.part) else ())
            for status in plan.lines
        )

    def input_row(self, readiness: Readiness) -> LineRow:
        """Строка входа: таблица плана или чтение пакетов — что делает и чего ему не хватает; вход есть всегда."""
        plan: LinePlan = self.plan
        status: LineStatus = LineStatus(part=plan.source, is_on=True, missing=None)
        return LineRow(status, readiness.part(plan.source, plan).unmet)

    def keys_row(self, rows: tuple[LineRow, ...]) -> KeysRow:
        """Строка «Ключи»: строка линии передачи ключей из `rows` и выбор «новые | все»."""
        line: LineRow = next(row for row in rows if row.part is RunPart.KEYS)
        return KeysRow(line=line, choice=self.keys_choice)

    def switch(self, part: RunPart, is_on: bool) -> LinesPanel:
        """Переключить линию `part` — сразу в файл, только раздел `lines`; модель, прочитанная заново."""
        latest: LivecraftSettings = self.file.latest
        lines: LineSettings = dataclasses.replace(latest.lines, **{part.value: is_on})
        self.file.save(dataclasses.replace(latest, lines=lines))
        return LinesPanel.from_file(self.file)

    def choose_input(self, source: RunPart) -> LinesPanel:
        """Вход «Таблица» (`RunPart.PLAN`) или «Пакеты» (`RunPart.PACKAGES_IN`): линия таблицы плана — включена или
        выключена; новых полей настроек нет (§14 решение 48)."""
        return self.switch(RunPart.PLAN, source is RunPart.PLAN)

    def choose_keys(self, choice: KeysChoice) -> LinesPanel:
        """«новые | все» — сразу в файл, только раздел broadcasts (`BroadcastsPanel.switch_resend`); модель, прочитанная
        заново."""
        BroadcastsPanel(broadcasts=self.broadcasts, file=self.file).switch_resend(choice.resend_keys)
        return LinesPanel.from_file(self.file)

    def _run_label(self, part: RunPart) -> str:
        """Линия в «Запуск сделает»: передача ключей при «все» — с тем, что ключи всех эфиров уйдут заново."""
        if part is RunPart.KEYS and self.keys_choice.resend_keys:
            return msg.SETUP_HOME_RUNS_KEYS_ALL.format(line=part.human_label)
        return part.human_label
