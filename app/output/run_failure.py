"""Сбой запуска без слота: канал, к которому нельзя, или файл программы (CLAUDE.md §6 инвариант 9, §10).

Отказ или сбой канала — одна строка на канал, а не на каждый его эфир: объекты такого канала не допущены и коротко
названы в «Не допущено». Сбой в «Итог по эфирам» не входит, а в код выхода входит (`RunExit`).
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.config.channel import ChannelConfig
from app.pipeline.plan import PlannedBroadcast
from app.platforms.channel import Channel
from app.platforms.error import PlatformError
from app.ui.messages import msg


@dataclass(frozen=True)
class RunFailure:
    """Что не удалось (канал для людей или путь файла) и почему — текстом для людей."""

    subject: str
    human: str

    @classmethod
    def of_channel(cls, channel: ChannelConfig, error: PlatformError) -> RunFailure:
        """Отказ площадки по каналу целиком: текст — отказа площадки."""
        return cls(subject=channel.label, human=error.human)

    @classmethod
    def of_keys_file(cls, shown: str, error: OSError) -> RunFailure:
        """keys.txt не записан: путь для людей и причина от системы."""
        return cls(subject=shown, human=msg.KEYS_WRITE_FAILED.format(detail=error))

    @classmethod
    def channel_refusals(cls, planned: Sequence[PlannedBroadcast]) -> tuple[RunFailure, ...]:
        """Полный текст отказа или сбоя канала не допущенных объектов — один раз на канал."""
        found: dict[str, RunFailure] = {}
        for item in planned:
            channel: Channel | None = item.admission.channel
            if item.admission.is_admitted or channel is None or channel.config.key in found:
                continue
            error: PlatformError | None = channel.access_error()
            if error is not None:
                found[channel.config.key] = cls.of_channel(channel.config, error)
        return tuple(found.values())

    @property
    def text(self) -> str:
        return msg.RUN_FAILURE_LINE.format(subject=self.subject, text=self.human)
