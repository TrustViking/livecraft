"""Файл ключей keystreams\\keys.txt (CLAUDE.md §5, §6 инварианты 1a, 6): производный, переписывается каждым запуском.

Ключ потока здесь — полностью: ради него файл и открывают (ключ — первой строкой блока). Строки строятся из объекта
эфира, а в --status — из эфира с меткой программы на площадке и результатов памяти. Строка «форма» — что сделано в
этом запуске, а если ничего — что знает память о подтверждении текущего ключа; линия «Ключи в форму» не идёт (§14
решение 37) — «не отправлялся» с её названием. Даты и время для людей — 17.03.2027
по поясу программы (§14 решение 31). Запись — целиком или никак; сбой — `RunFailure`, а не падение запуска.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, tzinfo
from pathlib import Path

from app.config.channel import ChannelConfig
from app.core.dates import format_human_datetime, parse_datetime_text
from app.core.text_format import NEWLINE, SPACE, TEXT_ENCODING
from app.core.youtube_video import YouTubeVideoId
from app.form.question import NO_VALUE
from app.observability.log_event import LogArea, LogEvent, Quoted, get_logger
from app.output.event import OutputEvent
from app.output.result import KeyFailure
from app.output.run_failure import RunFailure
from app.paths import FileName, LivecraftPaths, write_text_atomically
from app.pipeline.orphan import MarkedBroadcast
from app.pipeline.plan import PlannedBroadcast
from app.platforms.broadcast import CreatedBroadcast
from app.records.record_results import RecordResults
from app.run.mode import RunPart
from app.slots.slot import SlotKey
from app.ui.messages import msg

LOGGER = get_logger(LogArea.OUTPUT)


@dataclass(frozen=True)
class KeyConfirmation:
    """Что знает память о текущем ключе: подтверждение — только если оно про этот ключ; момент — в поясе `zone`."""

    results: RecordResults
    stream_key: str | None
    zone: tzinfo

    @property
    def text(self) -> str:
        if not self.results.confirms_key(self.stream_key):
            return msg.KEY_FORM_UNKNOWN
        confirmed_at: str | None = self.results.confirmed_at
        shown: str = NO_VALUE
        if confirmed_at is not None:
            shown = format_human_datetime(parse_datetime_text(confirmed_at, self.zone))
        return msg.KEY_FORM_CONFIRMED.format(confirmed_at=shown)


@dataclass(frozen=True)
class KeyDelivery:
    """Строка «форма» объекта эфира: не допущен, ключи в форму не идут (`to_form`), отправлен сейчас, должен был
    уйти и не ушёл, дважды не дошёл и сам больше не уходит (§14 решение 49) — иначе память."""

    item: PlannedBroadcast
    zone: tzinfo
    to_form: bool = True

    @property
    def text(self) -> str:
        item: PlannedBroadcast = self.item
        if not item.admission.is_admitted:
            reasons: str = SPACE.join(reason.wording.problem for reason in item.admission.reasons)
            return msg.KEY_FORM_NOT_ADMITTED.format(reasons=reasons)
        if not self.to_form:
            return msg.KEY_FORM_LINE_OFF.format(line=RunPart.KEYS.human_label)
        if item.outcome.is_form_sent:
            sent_at: datetime | None = item.outcome.form_sent_at
            shown: str = NO_VALUE if sent_at is None else format_human_datetime(sent_at.astimezone(self.zone))
            return msg.KEY_FORM_SENT.format(sent_at=shown)
        if item.outcome.should_send_key:
            return msg.KEY_FORM_FAILED.format(reason=KeyFailure(item.outcome.form_failure).text)
        if item.is_key_given_up:
            return msg.KEY_FORM_GIVEN_UP
        return KeyConfirmation(item.memory.results, item.match.stream_key, self.zone).text


@dataclass(frozen=True)
class KeyRow:
    """Блок ключа одного эфира: слот, канал, строка «форма», адрес и ключ потока, ссылка на эфир."""

    key: SlotKey
    channel: ChannelConfig
    form_text: str
    stream_url: str | None
    stream_key: str | None
    broadcast_url: str | None

    @classmethod
    def of_planned(cls, item: PlannedBroadcast, zone: tzinfo, to_form: bool) -> KeyRow:
        """Всё, что нужно, у объекта уже есть: ключ и ссылка — с площадки, канал — значения после фазы входов;
        `to_form` — идут ли ключи в форму."""
        key: CreatedBroadcast | None = item.match.key
        return cls(
            key=item.slot.key,
            channel=item.admission.channel_config(item.channel),
            form_text=KeyDelivery(item, zone, to_form).text,
            stream_url=None if key is None else key.stream_url,
            stream_key=item.match.stream_key,
            broadcast_url=None if key is None else key.broadcast_url,
        )

    @classmethod
    def of_marked(cls, marked: MarkedBroadcast, results: RecordResults, zone: tzinfo) -> KeyRow:
        """--status: ключ с площадки; в форму этот режим ничего не передаёт, строка «форма» — из памяти."""
        return cls(
            key=marked.key,
            channel=marked.channel,
            form_text=KeyConfirmation(results, marked.stream.stream_name, zone).text,
            stream_url=marked.stream.ingestion_address,
            stream_key=marked.stream.stream_name,
            broadcast_url=YouTubeVideoId(marked.broadcast.broadcast_id).watch_url,
        )

    @property
    def block(self) -> tuple[str, ...]:
        """Ключ — первой строкой после заголовка: он не уезжает за край экрана."""
        title: str = msg.KEYS_BLOCK_TITLE.format(
            date=self.key.human_date,
            time=self.key.time_text,
            language=self.key.language,
            account_name=self.channel.account_name,
            handle=self.channel.handle,
        )
        return (
            title,
            msg.KEYS_BLOCK_KEY.format(value=self.stream_key or NO_VALUE),
            msg.KEYS_BLOCK_STREAM.format(value=self.stream_url or NO_VALUE),
            msg.KEYS_BLOCK_BROADCAST.format(value=self.broadcast_url or NO_VALUE),
            msg.KEYS_BLOCK_FORM.format(value=self.form_text),
        )


@dataclass(frozen=True)
class KeysFile:
    """keys.txt запуска: шапка с моментом записи и блоки по порядку слотов (`SlotKey.sort_key`)."""

    rows: tuple[KeyRow, ...]
    written_at: datetime

    @property
    def text(self) -> str:
        """Блок на стрим, между блоками пустая строка."""
        lines: list[str] = [
            line.format(generated_at=format_human_datetime(self.written_at)) for line in msg.KEYS_FILE_HEADER
        ]
        for row in sorted(self.rows, key=lambda found: found.key.sort_key):
            lines.append("")
            lines.extend(row.block)
        return NEWLINE.join(lines) + NEWLINE

    def write(self, paths: LivecraftPaths) -> Path | RunFailure:
        """Файл целиком в keystreams\\; не записался — сбой запуска без слота, строка лога с причиной."""
        path: Path = paths.file(FileName.KEYS)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            write_text_atomically(path, self.text, TEXT_ENCODING)
        except OSError as error:
            failed: LogEvent = LogEvent.of(OutputEvent.KEYS_WRITE_FAILED, path=paths.shown(path))
            failed.extended(error=Quoted(str(error))).emit(LOGGER, logging.ERROR)
            return RunFailure.of_keys_file(paths.shown(path), error)
        LogEvent.of(OutputEvent.KEYS_WRITTEN, path=paths.shown(path), rows=len(self.rows)).emit(LOGGER)
        return path
