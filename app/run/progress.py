"""Строки хода в консоли, пока идут таблица и вывод: строка перед каждым долгим шагом (CLAUDE.md §13 задачи 9.5,
9.6).

Итоговые строки частей (видео, превью, нейросеть, документ, Telegram) готовы только после всей части, а видео, копии
превью на Google Диск, обращения к модели, документы и объявления идут минутами: без строк хода человек не видит,
работает ли программа, и может закрыть окно посреди отправки. Владелец цикла (`SourceCatalog`, `PreviewStage`,
`MergeStage`, `DocStage`, `AnnounceStage`) получает прогресс параметром своего прогона и зовёт его перед каждым шагом
цикла; строка уходит сразу на консоль оператора. Так же говорят чтение таблицы плана — строка перед каждым повтором
обращения (`SheetsReader`: без неё повторы — до полутора минут тишины) — и вход оператора в Google (`OperatorSheets`).
До таблицы говорят yt-dlp и deno (`SourceTools`, задача 9.27): загрузка с GitHub — строка начала с размером и строки
на 25, 50, 75 %, самообновление yt-dlp — строка перед ним; без них чистая установка молчала почти три минуты. В отчёт
запуска строки хода не идут — как строки хода эфиров
(app\\pipeline\\progress.py). В терминале ход этапа — одна строка, которая обновляется на месте, у шага «n из N» — с
полосой из «=»; по концу этапа последний шаг остаётся на экране, следующий этап пишет с новой строки
(`Console.progress`, `ProgressStage`, §14 решение 78). Без консоли (тесты, служебные вызовы) прогресс молчит.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.ui.console import Console, ProgressStage, StepCount
from app.ui.messages import msg


@dataclass(frozen=True)
class StageProgress:
    """Строки хода на консоль оператора; `console` None — молчит."""

    console: Console | None = None

    def operator_note(self, text: str) -> None:
        """Строка входа оператора в Google: перед браузером, каким аккаунтом вошли, аккаунту таблица не открыта —
        что сказать, решает правило входа (app\\sheets\\operator.py). Это сообщение, а не шаг этапа: оно остаётся на
        экране, а не уступает место следующему шагу."""
        if self.console is not None:
            self.console.say(text)

    def tool_note(self, text: str) -> None:
        """Строка хода yt-dlp и deno перед таблицей: начало загрузки с GitHub, её четверти, проверка обновления yt-dlp —
        что сказать, решает обновление (app\\runtime\\github_release.py, ytdlp_updater.py)."""
        self._say(text, ProgressStage.TOOLS)

    def sheets_retry(self, step: StepCount) -> None:
        """Перед повтором обращения к таблице плана: `step` — номер повтора из разрешённых политикой."""
        text: str = msg.PROGRESS_SHEETS_RETRY.format(place=step.place, total=step.total)
        self._say(text, ProgressStage.SHEETS_RETRY, step)

    def video_started(self, step: StepCount, link: str) -> None:
        """До чтения данных видео ряда таблицы (yt-dlp, обложка)."""
        self._say(msg.PROGRESS_VIDEO.format(place=step.place, total=step.total, link=link), ProgressStage.VIDEOS, step)

    def drive_copy_started(self, step: StepCount) -> None:
        """До загрузки копии превью на Google Диск."""
        text: str = msg.PROGRESS_DRIVE_PREVIEW.format(place=step.place, total=step.total)
        self._say(text, ProgressStage.DRIVE_PREVIEWS, step)

    def merge_started(self, step: StepCount, date: str, time: str, language: str) -> None:
        """До обращения к модели за текстами слота; `step` — место среди слотов, которым нужен merge, дата — для людей
        (17.03.2027)."""
        line: str = msg.PROGRESS_MERGE_SLOT
        text: str = line.format(place=step.place, total=step.total, date=date, time=time, language=language)
        self._say(text, ProgressStage.MERGE, step)

    def doc_started(self, step: StepCount, date: str) -> None:
        """До создания документа объявлений дня; дата — для людей."""
        self._say(msg.PROGRESS_DOC.format(place=step.place, total=step.total, date=date), ProgressStage.DOCS, step)

    def announce_started(self, step: StepCount, date: str) -> None:
        """До отправки объявлений дня в Telegram; дата — для людей."""
        text: str = msg.PROGRESS_ANNOUNCE.format(place=step.place, total=step.total, date=date)
        self._say(text, ProgressStage.ANNOUNCE, step)

    def package_send_started(self, name: str) -> None:
        """До отправки пакета .bcast в Telegram."""
        self._say(msg.PROGRESS_ANNOUNCE_PACKAGE.format(name=name), ProgressStage.PACKAGE_SEND)

    def _say(self, text: str, stage: ProgressStage, step: StepCount | None = None) -> None:
        """Шаг этапа `stage` — строкой хода, которая обновляется на месте; со счётом — с полосой (§14 решение 78)."""
        if self.console is not None:
            self.console.progress(text, stage, step)


# Прогресс без консоли: стадия, которой его не дали (тесты, служебные вызовы), не печатает ничего.
SILENT_PROGRESS: Final[StageProgress] = StageProgress()
