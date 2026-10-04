"""Строки хода в консоли, пока идут таблица и вывод: строка перед каждым долгим шагом (CLAUDE.md §13 задачи 9.5,
9.6).

Итоговые строки частей (видео, превью, нейросеть, документ, Telegram) готовы только после всей части, а видео, копии
превью на Google Диск, обращения к модели, документы и объявления идут минутами: без строк хода человек не видит,
работает ли программа, и может закрыть окно посреди отправки. Владелец цикла (`SourceCatalog`, `PreviewStage`,
`MergeStage`, `DocStage`, `AnnounceStage`) получает прогресс параметром своего прогона и зовёт его перед каждым шагом
цикла; строка уходит сразу на консоль оператора. Так же говорят чтение таблицы плана — строка перед каждым повтором
обращения (`SheetsReader`: без неё повторы — до полутора минут тишины) — и вход оператора в Google (`OperatorSheets`). В отчёт запуска строки хода не идут — как строки хода эфиров
(app\\pipeline\\progress.py). Без консоли (тесты, служебные вызовы) прогресс молчит.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.ui.console import Console
from app.ui.messages import msg


@dataclass(frozen=True)
class StepCount:
    """Место шага в своём цикле — «n из N», счёт с единицы."""

    place: int
    total: int


@dataclass(frozen=True)
class StageProgress:
    """Строки хода на консоль оператора; `console` None — молчит."""

    console: Console | None = None

    def operator_note(self, text: str) -> None:
        """Строка входа оператора в Google: перед браузером, каким аккаунтом вошли, аккаунту таблица не открыта —
        что сказать, решает правило входа (app\\sheets\\operator.py)."""
        self._say(text)

    def sheets_retry(self, step: StepCount) -> None:
        """Перед повтором обращения к таблице плана: `step` — номер повтора из разрешённых политикой."""
        self._say(msg.PROGRESS_SHEETS_RETRY.format(place=step.place, total=step.total))

    def video_started(self, step: StepCount, link: str) -> None:
        """До чтения данных видео ряда таблицы (yt-dlp, обложка)."""
        self._say(msg.PROGRESS_VIDEO.format(place=step.place, total=step.total, link=link))

    def drive_copy_started(self, step: StepCount) -> None:
        """До загрузки копии превью на Google Диск."""
        self._say(msg.PROGRESS_DRIVE_PREVIEW.format(place=step.place, total=step.total))

    def merge_started(self, step: StepCount, date: str, time: str, language: str) -> None:
        """До обращения к модели за текстами слота; `step` — место среди слотов, которым нужен merge, дата — для людей
        (17.03.2027)."""
        line: str = msg.PROGRESS_MERGE_SLOT
        self._say(line.format(place=step.place, total=step.total, date=date, time=time, language=language))

    def doc_started(self, step: StepCount, date: str) -> None:
        """До создания документа объявлений дня; дата — для людей."""
        self._say(msg.PROGRESS_DOC.format(place=step.place, total=step.total, date=date))

    def announce_started(self, step: StepCount, date: str) -> None:
        """До отправки объявлений дня в Telegram; дата — для людей."""
        self._say(msg.PROGRESS_ANNOUNCE.format(place=step.place, total=step.total, date=date))

    def package_send_started(self, name: str) -> None:
        """До отправки пакета .bcast в Telegram."""
        self._say(msg.PROGRESS_ANNOUNCE_PACKAGE.format(name=name))

    def _say(self, text: str) -> None:
        if self.console is not None:
            self.console.say(text)


# Прогресс без консоли: стадия, которой его не дали (тесты, служебные вызовы), не печатает ничего.
SILENT_PROGRESS: Final[StageProgress] = StageProgress()
