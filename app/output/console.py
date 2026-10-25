"""Консоль после запуска контура B (CLAUDE.md §3 шаг 12): «Итог» и блоки сверху вниз.

Шапку (версия и время) печатает запуск при старте, строки по ходу работы — прогресс; итоговый текст начинается со
строки «Итог». Порядок блоков: ВНИМАНИЕ, ОПУБЛИКОВАЛИ, ИСПРАВИЛИ, КЛЮЧИ СТРИМЕРУ, УЖЕ СТОЯЛО, ТЕКСТЫ НЕ ОБНОВЛЯЛИСЬ
(эфиры слотов «по номерам» с прежними текстами — название как на YouTube), НЕ ПУБЛИКОВАЛИ (без прошедших слотов — их
число в «Итоге»); пустой блок не печатается. Эфиры группируются по каналу в порядке
channels.json; ключ — только маской, полный — в keys.txt (путь к нему — в подвале путей запуска). В ИСПРАВИЛИ — только
тексты эфира; настройки с «было / стало» — во ВНИМАНИЕ. Dry-run говорит о намерениях и без блока ключей, --status —
только УЖЕ СТОЯЛО. Каждый блок — таблица консоли (§14 решение 78): «-» между сообщениями ВНИМАНИЕ и между каналами
(группами) блоков эфиров; блок из одной строки — этой строкой с названием блока впереди; одинаковое во ВНИМАНИЕ —
одной строкой (app\\output\\attention.py). Ширина таблиц — ширина консоли процесса (`ConsoleWidth.system`): итог
готовится до печати, а печатает его вызывающий (`Console.say_lines`) в ту же консоль.
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, field
from typing import Final

from app.form.question import NO_VALUE
from app.observability.logging_setup import mask_stream_key
from app.output.attention import AttentionLines, NotAdmittedSummary
from app.output.report import ReportKind, RunReport
from app.output.result import CREATED_KINDS, ERROR_KINDS, BroadcastResult, FieldChange, KeyState, OutcomeKind
from app.output.result_text import ResultText
from app.output.run_totals import RunTotals
from app.output.skipped import SkippedSlots
from app.pipeline.memory import ReplacedBroadcast
from app.ui.console_table import ConsoleTable, ConsoleWidth
from app.ui.messages import msg

# AMBIGUOUS приходит во «Внимание» предупреждением со ссылками — строка ошибки его бы продублировала.
ATTENTION_ERROR_KINDS: Final[frozenset[OutcomeKind]] = ERROR_KINDS - {OutcomeKind.AMBIGUOUS}

LineRender = Callable[[BroadcastResult], str]


@dataclass(frozen=True)
class ConsoleBlock:
    """Блок консоли: название (и счётчик) и записи — сообщение или группа строк канала; записей нет — блока нет."""

    title: str
    entries: Sequence[Sequence[str]]
    count: int | None = None

    @property
    def table(self) -> ConsoleTable:
        """Таблица блока: «-» между записями; одна строка — с названием блока впереди."""
        text: str = self.title if self.count is None else msg.CONSOLE_BLOCK_COUNTED.format(
            title=self.title, count=self.count
        )
        entries: tuple[tuple[str, ...], ...] = tuple(tuple(entry) for entry in self.entries)
        return ConsoleTable(text, entries, is_separated=True, is_titled_line=True)


@dataclass(frozen=True)
class RunConsole:
    """Итог запуска контура B для консоли и ширина его таблиц; подвал путей печатает запуск
    (app\\run\\run_report.py)."""

    report: RunReport
    width: int = field(default_factory=lambda: ConsoleWidth.system().columns)

    @property
    def lines(self) -> tuple[str, ...]:
        lines: list[str] = [*self.report.summary_lines]
        attention: tuple[tuple[str, ...], ...] = tuple((line,) for line in AttentionLines(self._attention).collapsed)
        for block in (ConsoleBlock(msg.CONSOLE_BLOCK_ATTENTION, attention), *self._blocks):
            lines.extend(block.table.lines(self.width))
        return tuple(lines)

    @property
    def _blocks(self) -> tuple[ConsoleBlock, ...]:
        """Блоки эфиров в порядке вывода; --status — только УЖЕ СТОЯЛО, dry-run — без ключей."""
        totals: RunTotals = self.report.totals
        matched: ConsoleBlock = ConsoleBlock(
            msg.CONSOLE_BLOCK_MATCHED, self._grouped({OutcomeKind.MATCHED}, self._matched_line), totals.matched
        )
        if self.report.kind is ReportKind.STATUS:
            return (matched,)
        is_dry_run: bool = self.report.is_dry_run
        skipped: SkippedSlots = self.report.skipped.shown_in_console
        blocks: list[ConsoleBlock] = [
            ConsoleBlock(
                msg.CONSOLE_BLOCK_CREATED_DRY_RUN if is_dry_run else msg.CONSOLE_BLOCK_CREATED,
                self._grouped(CREATED_KINDS, self._broadcast_line),
                totals.created,
            ),
            ConsoleBlock(
                msg.CONSOLE_BLOCK_FIXED_DRY_RUN if is_dry_run else msg.CONSOLE_BLOCK_FIXED,
                self._grouped({OutcomeKind.FIXED}, self._fixed_line),
                totals.fixed,
            ),
        ]
        if not is_dry_run:
            keys: list[BroadcastResult] = [result for result in self.report.results if result.key_state is not None]
            blocks.append(ConsoleBlock(msg.CONSOLE_BLOCK_KEYS, self._by_channel(keys, self._key_line), len(keys)))
        blocks.append(matched)
        kept: list[list[str]] = self._grouped({OutcomeKind.KEPT}, self._broadcast_line)
        blocks.append(ConsoleBlock(msg.CONSOLE_BLOCK_KEPT, kept, totals.kept))
        blocks.append(ConsoleBlock(msg.CONSOLE_BLOCK_SKIPPED, self._skipped_lines(skipped), len(skipped.lines)))
        return tuple(blocks)

    def _grouped(self, kinds: Collection[OutcomeKind], render: LineRender) -> list[list[str]]:
        return self._by_channel([result for result in self.report.results if result.kind in kinds], render)

    def _by_channel(self, results: Sequence[BroadcastResult], render: LineRender) -> list[list[str]]:
        """Запись на канал: шапка канала и его эфиры; каналы — в порядке channels.json, внутри — по порядку слотов."""
        ranks: dict[str, int] = {key: index for index, key in enumerate(self.report.channel_order)}
        for result in results:
            ranks.setdefault(result.channel.key, len(ranks))
        groups: dict[str, list[str]] = {}
        for result in sorted(results, key=lambda found: (ranks[found.channel.key], found.key.sort_key)):
            channel = result.channel
            group: list[str] = groups.setdefault(channel.key, [msg.CONSOLE_CHANNEL_GROUP.format(
                account_name=channel.account_name, handle=channel.handle, google_account=channel.google_account
            )])
            group.append(render(result))
        return list(groups.values())

    def _broadcast_line(self, result: BroadcastResult) -> str:
        return msg.CONSOLE_BROADCAST_LINE.format(
            date=result.key.human_date,
            time=result.key.time_text,
            language=result.key.language,
            title=result.title or NO_VALUE,
        )

    def _matched_line(self, result: BroadcastResult) -> str:
        """Уже стояло; не удалось исправить (обложка) — хвостом, причина — во ВНИМАНИЕ."""
        return self._broadcast_line(result) + ResultText(result).unfixed_tail

    def _fixed_line(self, result: BroadcastResult) -> str:
        """ИСПРАВИЛИ — только то, что исправлено по факту, и хвостом то, что исправить не удалось."""
        line: str = self._content_line(result)
        return line if self.report.is_dry_run else line + ResultText(result).unfixed_tail

    def _content_line(self, result: BroadcastResult) -> str:
        """Хвост «обновлено» — только тексты эфира; настройки названы во ВНИМАНИЕ. Нет текстов — строка без хвоста."""
        content: list[FieldChange] = [change for change in result.changes if change.is_content]
        if not content:
            return self._broadcast_line(result)
        template: str = msg.CONSOLE_FIX_PLANNED_LINE if self.report.is_dry_run else msg.CONSOLE_FIXED_LINE
        return template.format(
            date=result.key.human_date,
            time=result.key.time_text,
            language=result.key.language,
            title=result.title or NO_VALUE,
            what=msg.LIST_JOINER.join(change.name for change in content),
        )

    def _key_line(self, result: BroadcastResult) -> str:
        """Ключ — только маской (как в логе), полный — в keys.txt; слова состояния — те же, что в keys.txt."""
        state: str = msg.KEY_FORM_SENT_LEAD
        if result.key_state is KeyState.FAILED:
            state = msg.CONSOLE_KEY_FAILED.format(reason=result.failure_text)
        return msg.CONSOLE_KEY_LINE.format(
            date=result.key.human_date,
            time=result.key.time_text,
            language=result.key.language,
            key=mask_stream_key(result.stream_key),
            state=state,
        )

    def _skipped_lines(self, skipped: SkippedSlots) -> list[list[str]]:
        """Запись на причину, а не на канал: у этих слотов канала нет."""
        return [[group.console_title, *(line.console_line for line in group.lines)] for group in skipped.groups]

    @property
    def _attention(self) -> list[str]:
        """Всё, что требует внимания, полным текстом, не допущенные — по причине (`NotAdmittedSummary`); постоянные
        особенности площадки — только в отчёте."""
        results: tuple[BroadcastResult, ...] = self.report.results
        lines: list[str] = [
            msg.CONSOLE_ATTENTION_ERROR.format(text=ResultText(result).body)
            for result in results
            if result.kind in ATTENTION_ERROR_KINDS
        ]
        lines.extend(msg.CONSOLE_ATTENTION_ERROR.format(text=failure.text) for failure in self.report.failures)
        lines.extend(
            msg.CONSOLE_ATTENTION_NOT_DELIVERED.format(prefix=result.label.text, reason=result.failure_text)
            for result in results
            if result.key_state is KeyState.FAILED
        )
        lines.extend(self._two_keys)
        lines.extend(NotAdmittedSummary(tuple(result for result in results if result.kind is OutcomeKind.NOT_ADMITTED)).lines)
        lines.extend(self._restored)
        lines.extend(msg.CONSOLE_ATTENTION_PACKAGE.format(text=line.text) for line in self.report.packages.unreadable)
        lines.extend(msg.CONSOLE_ATTENTION_TEXT.format(text=text) for text in self.report.warnings)
        return lines

    @property
    def _two_keys(self) -> list[str]:
        """Эфир слота заменён новым, а прежний ключ форма уже подтверждала: в форме на дату два ключа."""
        lines: list[str] = []
        for result in self.report.results:
            replaced: ReplacedBroadcast | None = result.replaced
            if replaced is not None:
                lines.append(msg.CONSOLE_ATTENTION_TWO_KEYS.format(
                    prefix=result.label.text,
                    new_key=mask_stream_key(result.stream_key),
                    old_key=mask_stream_key(replaced.stream_key),
                ))
        return lines

    @property
    def _restored(self) -> list[str]:
        """Настройки, которые программа вернула к плану (или вернёт в dry-run): видимость, категория, метка."""
        return [
            self._restored_line(result, change)
            for result in self.report.results
            if result.kind not in ERROR_KINDS
            for change in result.changes
            if not change.is_content
        ]

    def _restored_line(self, result: BroadcastResult, change: FieldChange) -> str:
        is_before_known: bool = change.before != NO_VALUE
        if self.report.is_dry_run:
            template: str = (
                msg.CONSOLE_ATTENTION_RESTORE_PLANNED if is_before_known
                else msg.CONSOLE_ATTENTION_RESTORE_PLANNED_UNKNOWN
            )
        else:
            template = msg.CONSOLE_ATTENTION_RESTORED if is_before_known else msg.CONSOLE_ATTENTION_RESTORED_UNKNOWN
        return template.format(prefix=result.label.text, field=change.name, before=change.before, after=change.after)
