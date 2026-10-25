"""Кнопки проверки и строки её итога в окне настройщика: проверка — в фоновом потоке (CLAUDE.md §8.2).

Так проверяются таблица плана (`TableCheck`), папки Google Диска — превью и документов (`FolderCheck`), ключ OpenAI
(`LlmKeyCheck`), форма ключей (`FormCheck`), каналы YouTube (`ChannelsCheck`), проект Google (`ClientCheck`) и cookies YouTube (`CookiesFileCheck`), так же создаётся и загружается токен
доступа (`TokenPanel`) и сохраняется архив логов (`LogsPanel`): модель ходит в сеть или на диск и, может быть,
открывает браузер входа, и окно не должно замирать. Тот же фоновый опрос (`MailPoll`) без кнопки и строки итога
узнаёт у Telegram названия подключённых чатов (`ChatConnectBlock.name_chats`).

Объекты Tk живут только в главном потоке: их там создают и там же уничтожают — иначе переменная Tk, которую соберёт
мусорщик фонового потока, падает с «main thread is not in main loop». Поэтому фоновый поток не держит ни одного объекта
Tk: что проверять, строка спрашивает у вкладки в главном потоке (`job` — модель проверки, без окна), а поток получает
только её и почту `CheckMail` — очередь значений; мусор окна (кольца ссылок с переменными Tk) строка собирает в
главном потоке перед стартом проверки. Модель кладёт в почту строки по ходу проверки (о браузере или всё,
что успела сказать, — `tell`) и итог, а окно забирает их через `after`. У строки одна главная кнопка и, если нужно, ещё
кнопки той же проверки (`add_button`: «Войти в выбранный канал» рядом с «Проверить все каналы»); пока проверка идёт,
недоступны все. Итог приходит всегда: непредвиденная ошибка модели даёт итог «проверка прервалась», а сама обрывает
поток и попадает в лог запуска (`threading.excepthook`, app\\main.py::Launch.run). После итога — `on_done`, если его
дали (вкладка каналов перечитывает каналы, вкладка «Логи» открывает папку архива по итогу `verdict`). Окно закрыли посреди проверки — строка снимает свой отложенный опрос, иначе
Tcl позвал бы уже удалённую команду.

Итог — строками, и у каждой строки свой цвет по её знаку (`ResultRow`): «✓» — зелёная, «✗» — красная, справка без
знака — обычная. Своих правил у строки нет.
"""
from __future__ import annotations

import functools
import gc
import queue
import threading
import tkinter as tk
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from tkinter import ttk
from typing import Final, Generic, TypeAlias, TypeVar

from app.core.text_format import NEWLINE
from app.setup.panels.channels_check import ChannelsVerdict
from app.setup.panels.client_check import ClientVerdict
from app.setup.panels.cookies_check import CookiesVerdict
from app.setup.panels.folder_check import FolderVerdict
from app.setup.panels.form_check import FormVerdict
from app.setup.panels.llm_key_check import LlmKeyVerdict
from app.setup.panels.logs_panel import LogsVerdict
from app.setup.panels.table_check import TableVerdict
from app.setup.panels.token_panel import TokenVerdict
from app.setup.tabs.field_shade import FOREGROUND_OPTION
from app.setup.tabs.tab_layout import HINT_FOREGROUND, PAD, TEXT_KEY, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_theme import STATUS_SET_FOREGROUND, STATUS_UNSET_FOREGROUND
from app.ui.messages import msg

POLL_MS: Final[int] = 100               # как часто окно заглядывает в очередь фоновой проверки
DESTROY_EVENT: Final[str] = "<Destroy>"  # виджет строки уничтожен: окно закрыли
LABEL_STYLE: Final[str] = "TLabel"      # стиль надписи ttk: его цвет текста — цвет справки без знака

CheckVerdict: TypeAlias = (
    TableVerdict | FolderVerdict | LlmKeyVerdict | FormVerdict | ChannelsVerdict | TokenVerdict | LogsVerdict
    | ClientVerdict | CookiesVerdict
)
MailT = TypeVar("MailT")


class RowState(str, Enum):
    """Что говорит строка итога: годится, проблема или справка. Значение — идентификатор."""

    OK = "ok"
    PROBLEM = "problem"
    NOTE = "note"

    @property
    def foreground(self) -> str | None:
        """Цвет строки: годится — зелёный, проблема — красный; справка — None, цвет текста темы."""
        return _STATE_FOREGROUNDS.get(self)


_STATE_FOREGROUNDS: Final[dict[RowState, str]] = {
    RowState.OK: STATUS_SET_FOREGROUND,
    RowState.PROBLEM: STATUS_UNSET_FOREGROUND,
}


@dataclass(frozen=True)
class ResultRow:
    """Строка итога проверки и её состояние — по знаку в начале строки."""

    text: str

    @classmethod
    def rows(cls, text: str) -> tuple[ResultRow, ...]:
        """Строки итога по порядку."""
        return tuple(cls(line) for line in text.split(NEWLINE))

    @property
    def state(self) -> RowState:
        if self.text.startswith(msg.CHECK_MARK_OK):
            return RowState.OK
        return RowState.PROBLEM if self.text.startswith(msg.CHECK_MARK_PROBLEM) else RowState.NOTE


@dataclass(frozen=True)
class CheckMail:
    """Почта фоновой проверки окну — без Tk: очередь значений и строка «открылся браузер». Сама почта — то, что модель
    зовёт, когда для входа открывается браузер (`on_login` моделей); `tell` — строка по ходу проверки."""

    inbox: queue.Queue[CheckVerdict | str]
    login: str

    def __call__(self) -> None:
        self.tell(self.login)

    def tell(self, text: str) -> None:
        """Строка по ходу проверки: окно покажет её при следующем опросе."""
        self.inbox.put(text)

    def work(self, run: CheckRun, interrupted: CheckVerdict) -> None:
        """Фоновый поток: только модель и очередь. Итог уходит в очередь и тогда, когда модель упала: иначе окно ждало
        бы его вечно, а кнопки остались бы недоступными."""
        verdict: CheckVerdict = interrupted
        try:
            verdict = run(self)
        finally:
            self.inbox.put(verdict)


# Проверка: получает почту (она же «открылся браузер»), отдаёт итог; не держит ни одного объекта Tk.
CheckRun: TypeAlias = Callable[[CheckMail], CheckVerdict]


class MailPoll(Generic[MailT]):
    """Фоновая работа и опрос её очереди окном: поток получает только работу без Tk, окно забирает значения очереди
    через `after` в главном потоке и отдаёт каждое `take`; `take` вернул True — работа кончилась, опрос останавливается.
    Поля: виджет, чьим `after` идёт опрос, очередь `inbox`, что делать со значением и id отложенного опроса `poll_id`
    (виджет уничтожен — опрос снимается, пока его команда ещё зарегистрирована)."""

    def __init__(self, widget: tk.Misc, take: Callable[[MailT], bool]) -> None:
        self.widget: tk.Misc = widget
        self.take: Callable[[MailT], bool] = take
        self.inbox: queue.Queue[MailT] = queue.Queue()
        self.poll_id: str | None = None
        widget.bind(DESTROY_EVENT, self._cancel, add=True)

    @property
    def is_running(self) -> bool:
        return self.poll_id is not None

    def start(self, work: Callable[[], None]) -> None:
        """Работа — в фоновом потоке, опрос очереди — в окне. Мусор окна (кольца ссылок с переменными Tk) — здесь, в
        главном потоке: мусорщик фонового потока уничтожал бы объекты Tk там."""
        gc.collect()
        threading.Thread(target=work, daemon=True).start()
        self.poll_id = self.widget.after(POLL_MS, self._poll)

    def _poll(self) -> None:
        """Забрать значения очереди; работа кончилась — опрос стоп (`take` может сразу начать новую работу), иначе —
        заглянуть снова."""
        self.poll_id = None
        while not self.inbox.empty():
            if self.take(self.inbox.get_nowait()):
                return
        self.poll_id = self.widget.after(POLL_MS, self._poll)

    def _cancel(self, _event: tk.Event) -> None:
        if self.poll_id is None:
            return
        self.widget.after_cancel(self.poll_id)
        self.poll_id = None


@dataclass(frozen=True)
class CheckTexts:
    """Тексты строки проверки: кнопка, «проверяю…», итог, если проверка оборвалась, и «открылся браузер» — у проверок,
    которые входят в Google сами (у проверки без входа строки о браузере нет)."""

    button: str
    checking: str
    interrupted: CheckVerdict
    login: str = ""


class CheckLine:
    """Кнопки и строки итога одной проверки. Поля: тексты, что проверять главной кнопкой (`job` — спрашивается в
    главном потоке и отдаёт модель без Tk), ряд кнопок, главная кнопка, все кнопки строки, рамка строк итога и их
    надписи, цвет справки (цвет текста темы), фоновая работа с опросом её очереди (`poll`), итог последней проверки
    (`verdict`; ещё не было — None) и что сделать после итога (`on_done`)."""

    def __init__(
        self,
        frame: ttk.Frame,
        texts: CheckTexts,
        job: Callable[[], CheckRun | None],
        on_done: Callable[[], None] | None = None,
    ) -> None:
        self.frame: ttk.Frame = frame
        self.texts: CheckTexts = texts
        self.job: Callable[[], CheckRun | None] = job
        self.on_done: Callable[[], None] | None = on_done
        self.row: ttk.Frame = ttk.Frame(frame)
        self.row.pack(anchor=tk.W, pady=(PAD, 0))
        self.buttons: list[ttk.Button] = []
        self.button: ttk.Button = self.add_button(texts.button, self.start)
        self.result: ttk.Frame = ttk.Frame(frame)
        self.result.pack(fill=tk.X, anchor=tk.W, pady=(PAD, 0))
        self.labels: list[ttk.Label] = []
        self.note_foreground: str = str(ttk.Style(frame).lookup(LABEL_STYLE, FOREGROUND_OPTION))
        self.poll: MailPoll[CheckVerdict | str] = MailPoll(self.button, self._take)
        self.verdict: CheckVerdict | None = None

    @property
    def is_running(self) -> bool:
        return self.poll.is_running

    @property
    def result_text(self) -> str:
        return NEWLINE.join(row.text for row in self.shown)

    @property
    def shown(self) -> tuple[ResultRow, ...]:
        """Строки итога, которые сейчас на экране."""
        return tuple(ResultRow(str(label.cget(TEXT_KEY))) for label in self.labels)

    def add_button(self, text: str, command: Callable[[], None]) -> ttk.Button:
        """Кнопка в ряду строки: недоступна, пока идёт проверка строки; `command` — в потоке окна."""
        button: ttk.Button = ttk.Button(self.row, text=text, command=command)
        button.pack(side=tk.LEFT, padx=(PAD if self.buttons else 0, 0))
        self.buttons.append(button)
        return button

    def start(self) -> None:
        """Главная кнопка и проверка после сохранения: модель, которую сейчас называет вкладка; вкладке нечего
        проверять (человек закрыл выбор файла) — ничего."""
        run: CheckRun | None = self.job()
        if run is not None:
            self.start_run(run)

    def start_run(self, run: CheckRun) -> None:
        """Проверка `run` (без объектов Tk) в фоновом потоке; кнопки недоступны до итога. Уже идёт проверка — ничего."""
        if self.is_running:
            return
        self._enable(False)
        self._show(self.texts.checking, HINT_FOREGROUND)
        mail: CheckMail = CheckMail(self.poll.inbox, self.texts.login)
        self.poll.start(functools.partial(mail.work, run, self.texts.interrupted))     # поток не держит строку

    def _take(self, item: CheckVerdict | str) -> bool:
        """Строка по ходу проверки — на экран; итог — строками своих цветов, кнопки снова доступны, затем `on_done`."""
        if isinstance(item, str):
            self._show(item, HINT_FOREGROUND)
            return False
        self.verdict = item
        self._show_rows(ResultRow.rows(item.text))
        self._enable(True)
        if self.on_done is not None:
            self.on_done()
        return True

    def _enable(self, is_enabled: bool) -> None:
        for button in self.buttons:
            button.configure(state=tk.NORMAL if is_enabled else tk.DISABLED)

    def _show(self, text: str, foreground: str) -> None:
        """Строки по ходу проверки — одним цветом справки."""
        self._place(tuple((row, foreground) for row in ResultRow.rows(text)))

    def _show_rows(self, rows: tuple[ResultRow, ...]) -> None:
        """Итог: у каждой строки цвет её состояния; справка — цветом текста темы."""
        self._place(tuple((row, row.state.foreground or self.note_foreground) for row in rows))

    def _place(self, rows: tuple[tuple[ResultRow, str], ...]) -> None:
        """Надписи строк итога: прежние уходят, новые — по строке на надпись."""
        for label in self.labels:
            label.destroy()
        self.labels = [
            ttk.Label(self.result, text=row.text, foreground=foreground, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
            for row, foreground in rows
        ]
        for label in self.labels:
            label.pack(fill=tk.X, anchor=tk.W)
