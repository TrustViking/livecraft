"""Зависимости части «эфиры» одного запуска — одним объектом, собранным один раз (CLAUDE.md §3 шаги 2.2, 7–11).

Площадка YouTube → сверка каналов (паспорт, токены) → книга каналов со строками входа в консоль → шлюз, который пускает
к площадке только подтверждённые каналы (`VerifiedPlatform`); формы ключей — одна сессия на запуск (`FormBook`).
Расход YouTube считает шлюз площадки. Часы — в поясе программы (инвариант 4). Память программы сюда не входит: её
открывает и всегда закрывает сам прогон части (app\\broadcasts\\stage.py).
"""
from __future__ import annotations

import random
from dataclasses import dataclass

from app.config.settings import LivecraftSettings
from app.core.clock import Clock
from app.form.book import FormBook
from app.paths import LivecraftPaths
from app.pipeline.progress import RunProgress
from app.platforms.base import BroadcastPlatform
from app.platforms.channel_book import ChannelBook
from app.platforms.channel_console import ChannelConsole
from app.platforms.channel_sync import ChannelSync
from app.platforms.verified import VerifiedPlatform
from app.platforms.youtube import YouTubePlatform
from app.platforms.youtube_usage import YouTubeUsage
from app.ui.console import Console


@dataclass(frozen=True)
class BroadcastServices:
    """`platform` — площадка за шлюзом подтверждённых каналов; `book` — каналы запуска; `forms` — формы ключей;
    `usage` — расход YouTube за запуск; `rng` — выбор обложки из превью слота; `progress` — строки по ходу работы."""

    paths: LivecraftPaths
    settings: LivecraftSettings
    platform: BroadcastPlatform
    book: ChannelBook
    forms: FormBook
    usage: YouTubeUsage
    clock: Clock
    rng: random.Random
    progress: RunProgress

    @classmethod
    def open(cls, paths: LivecraftPaths, settings: LivecraftSettings, console: Console) -> BroadcastServices:
        """Боевые зависимости: YouTube с входами владельцев каналов, формы по сети, консоль оператора."""
        clock: Clock = Clock(settings.zone)
        youtube: YouTubePlatform = YouTubePlatform.open(paths, settings)
        book: ChannelBook = ChannelBook(youtube, ChannelSync(youtube, paths, clock), ChannelConsole(console))
        return cls(
            paths=paths,
            settings=settings,
            platform=VerifiedPlatform(youtube, book),
            book=book,
            forms=FormBook.for_run(paths, clock),
            usage=youtube.gateway.usage,
            clock=clock,
            rng=random.Random(),
            progress=RunProgress(console),
        )
