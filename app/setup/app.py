"""Окно настройщика: .\\livecraft.bat --setup (CLAUDE.md §8, §14 решение 37).

`SetupApp` — запуск окна для установки. `SetupWindow.open` — окно так, как его открывает программа:
осведомлённость о DPI до создания Tk (иначе шрифт на HiDPI мыльный, §8.1), затем окно. `SetupWindow` — само
окно: «Главная» с линиями работы по этапам, по вкладке на линию, «Токены», «Логи» и «Дополнительно» (`SetupTabs`;
окно открывается на «Главной»), строка готовности внизу и вопрос при закрытии с несохранённым. Правил у окна нет:
что годно, что писать и готова ли программа к запуску, решают модели вкладок, `LinesPanel` и `Readiness`. «Перейти» на «Главной» открывает
вкладку линии (`show_page`). После каждого переключения линии и каждой записи на любой вкладке окно перерисовывается
по свежей проверке (`refresh`): ползунки и готовность линий, «Запуск сделает: …», ссылка на папку Диска на обеих
вкладках, что войдёт в токен, бледность полей всех вкладок и строка готовности. Сейф при этом не перечитывается:
окно читает его один раз и заново — только после своей записи (`SetupVault`). Окно не выше доли экрана
(`WINDOW_SCREEN_SHARE`): вкладка, которая не помещается, прокручивается (`TabScroll`), а не уходит за край экрана вместе
с нижними полями; и не уже полосы вкладок: иначе названия последних вкладок обрезаются. Живые проверки
(таблица плана, папка Диска, ключ OpenAI, форма ключей, вход в канал и проверка каналов) — тот же код, что у запуска, в
фоновом потоке (`CheckLine`): после сохранения значения или по кнопке, каналы — только по кнопке (вход открывает
браузер); при открытии окна проверок нет.

Значения сейфа окно показывает только масками; исключение — своё значение по кнопке «показать» (§14 решение 11),
которое прячется при уходе с вкладки. Буфер обмена окно не трогает; строка готовности — только проблемы `Readiness`,
в них значений нет. Вставка, выделение, вырезание и копирование в полях работают в любой раскладке (`EditShortcuts`).
Бота Telegram строит вкладка «Telegram» из сейфа своей строки токена — того, что на ней сейчас; адрес бота окно
открывает браузером.

Ошибка программы в обработчике окна (кнопка, таймер, событие) не пропадает и окно не закрывает (`ActionFailure`): Tk
отдаёт её окну вместо печати в stderr, которого у оконного livecraftw.exe нет, — строка с трассировкой в лог запуска и
окно-сообщение с путём лога; окно работает дальше.
"""
from __future__ import annotations

import ctypes
import tkinter as tk
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from tkinter import messagebox, ttk
from types import TracebackType
from typing import Final

from app.observability.log_event import MESSAGE_TEMPLATE, LogArea, LogEvent, get_logger
from app.paths import LivecraftPaths
from app.resources.loader import ResourceBundle
from app.setup.page import SetupPage
from app.setup.panels.lines_panel import LineRow, LinesPanel
from app.setup.panels.settings_panel import SettingsPanel
from app.setup.readiness import Readiness
from app.setup.setup_vault import SetupVault
from app.setup.tabs.field_shade import FieldShades
from app.setup.tabs.line_switches import LineSwitches
from app.setup.tabs.setup_context import SettingsBook, SetupContext
from app.setup.tabs.setup_tabs import SetupTabs
from app.setup.tabs.tab_event import EditShortcuts, TkEvent
from app.setup.tabs.tab_layout import PAD, TEXT_WRAP_PIXELS
from app.setup.tabs.tab_theme import SetupTheme
from app.ui.messages import msg
from app.version import APP_VERSION

PROCESS_SYSTEM_DPI_AWARE: Final[int] = 1   # SetProcessDpiAwareness: осведомлённость о DPI системы
CLOSE_PROTOCOL: Final[str] = "WM_DELETE_WINDOW"
# Доля высоты экрана, выше которой окно не растёт: остаток — заголовок окна и панель задач Windows (на экране 1080 окно
# без предела уходило нижним краем под панель задач).
WINDOW_SCREEN_SHARE: Final[float] = 0.85

LOGGER = get_logger(LogArea.SETUP)


class SetupEvent(str, Enum):
    """События окна настройщика в логе."""

    ACTION_FAILED = "setup_action_failed"


@dataclass(frozen=True)
class ActionFailure:
    """Ошибка программы в обработчике окна: окно, поверх которого встаёт сообщение, и лог запуска, куда ушла причина.

    Это не перехват: Tk уже оборвал обработчик и отдаёт исключение окну (`report_callback_exception`), где иначе
    напечатал бы его в stderr сам.
    """

    parent: tk.Tk
    log: Path

    def install(self) -> None:
        """Ошибки обработчиков окна `parent` — сюда."""
        self.parent.report_callback_exception = self.report

    def report(self, error_type: type[BaseException], error: BaseException, trace: TracebackType | None) -> None:
        """Строка с трассировкой в лог и окно-сообщение с путём лога; окно остаётся открытым."""
        event: LogEvent = LogEvent.of(SetupEvent.ACTION_FAILED, error=error_type.__name__, log=self.log)
        LOGGER.error(MESSAGE_TEMPLATE, event.text, exc_info=(error_type, error, trace))
        messagebox.showerror(
            msg.SETUP_WINDOW_TITLE.format(version=APP_VERSION),
            msg.SETUP_ACTION_FAILED.format(log=self.log),
            parent=self.parent,
        )


@dataclass(frozen=True)
class DpiAwareness:
    """Осведомлённость процесса о DPI экрана (§8.1): ставится до создания Tk, одна на процесс."""

    level: int = PROCESS_SYSTEM_DPI_AWARE

    def apply(self) -> None:
        """Чёткий шрифт на HiDPI. Не Windows или нет shcore — окно просто будет с системным масштабом."""
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(self.level)  # type: ignore[attr-defined]
        except (AttributeError, OSError):
            return


class SetupWindow:
    """Окно настройщика. Поля: пути установки, корень Tk, стиль, общее у вкладок (`context`), вкладки, строка
    готовности, отложенная раскладка (`layout_call`) и признак закрытия."""

    def __init__(self, paths: LivecraftPaths) -> None:
        self.paths: LivecraftPaths = paths
        self.root: tk.Tk = tk.Tk()
        # Иконка Livecraft в заголовке и на панели задач (§14 решение 53); default — её получают и окна-сообщения.
        self.root.iconbitmap(default=str(ResourceBundle.of_process().icon_file))
        self.root.title(msg.SETUP_WINDOW_TITLE.format(version=APP_VERSION))
        self.is_closed: bool = False
        self.edit_shortcuts: EditShortcuts = EditShortcuts.install(self.root)
        self.theme: SetupTheme = SetupTheme.applied_to(self.root)
        self.root.maxsize(self.root.winfo_screenwidth(), int(self.root.winfo_screenheight() * WINDOW_SCREEN_SHARE))
        self.notebook: ttk.Notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=PAD, pady=PAD)
        self.context: SetupContext = SetupContext(
            notebook=self.notebook,
            paths=paths,
            vault=SetupVault.open(paths),
            switches=LineSwitches(self.root, LinesPanel.from_paths(paths), self.refresh),
            shades=FieldShades(),
            settings=SettingsBook(SettingsPanel.from_paths(paths), self.settings_saved),
            on_saved=self.refresh,
        )
        self.tabs: SetupTabs = SetupTabs(self.context, self.show_page)
        self._place_tabs()
        self.readiness_line: ttk.Label = ttk.Label(self.root, wraplength=TEXT_WRAP_PIXELS, justify=tk.LEFT)
        # Строка готовности получает место раньше блокнота: окно ниже содержимого вкладки не выдавливает её.
        self.readiness_line.pack(side=tk.BOTTOM, fill=tk.X, padx=PAD, pady=PAD, before=self.notebook)
        self.root.protocol(CLOSE_PROTOCOL, self.request_close)
        self.refresh()
        # Раскладка в конструкторе показала бы окно до withdraw; отложенный вызов отменяет закрытие окна (`close`).
        self.layout_call: str = self.root.after_idle(self._keep_tabs_visible)

    @classmethod
    def open(cls, paths: LivecraftPaths, log: Path) -> SetupWindow:
        """Окно так, как его открывает программа: осведомлённость о DPI до создания Tk, затем окно; ошибки его
        обработчиков — в лог запуска `log` и окном-сообщением."""
        DpiAwareness().apply()
        window: SetupWindow = cls(paths)
        ActionFailure(window.root, log).install()
        return window

    @property
    def is_dirty(self) -> bool:
        """Хотя бы на одной вкладке есть несохранённое; на «Главной» править нечего: ползунки пишутся сразу."""
        return self.tabs.is_dirty

    def _place_tabs(self) -> None:
        """Вкладки — на блокнот в порядке окна; первая, «Главная», открыта. Уход с вкладки прячет показанное своё
        значение (§14 решение 11)."""
        for tab in self.tabs.all:
            self.notebook.add(tab.frame, text=tab.page.title)
        self.notebook.bind(TkEvent.TAB_CHANGED, lambda _event: self.tabs.hide_revealed())

    def _keep_tabs_visible(self) -> None:
        """Окно не уже своей естественной ширины — полосы вкладок и содержимого: названия вкладок не обрезаются."""
        self.root.update_idletasks()
        _width, height = self.root.minsize()
        self.root.minsize(self.root.winfo_reqwidth(), height)

    def show_page(self, page: SetupPage) -> None:
        """«Перейти»: открыть вкладку `page`."""
        self.notebook.select(next(tab.frame for tab in self.tabs.all if tab.page is page))

    def refresh(self) -> None:
        """Окно по свежей проверке: ползунки и готовность линий, вход и ключи «Главной», «Запуск сделает: …», ссылки
        на папку Диска, что войдёт в токен, чаты Telegram на «Telegram» и «Логах» с выбором и строкой назначения и надписью
        кнопки «Отправить логи» (бот и чат могли смениться на любой из двух вкладок), бледность полей всех вкладок (последней — поверх того, что нарисовали вкладки) и строка готовности."""
        readiness: Readiness = Readiness.of(self.paths, self.context.vault.strict)
        lines: LinesPanel = LinesPanel.from_paths(self.paths)
        rows: tuple[LineRow, ...] = lines.rows(readiness)
        self.context.switches.show(lines, rows)
        self.tabs.home.show(lines, readiness, rows)
        self.tabs.reload_links()
        self.tabs.tokens.show_contents()
        self.tabs.show_chats()
        self.context.shades.apply(lines.plan)
        self.readiness_line.configure(text=readiness.window_line)

    def settings_saved(self) -> None:
        """Настройки записаны: окно заново, пометки языков формы на «Эфирах YouTube», пояс программы в тексте образца
        таблицы и оговорки «Дополнительно» — без перезапуска окна."""
        self.refresh()
        panel: SettingsPanel = self.context.settings.panel
        self.tabs.broadcasts.refresh_form_languages(panel.form_languages)
        self.tabs.plan.table.show_rules(panel.settings.timezone)
        self.tabs.advanced.show_notices()

    def request_close(self) -> None:
        """Закрытие окна: есть несохранённое — спросить; «нет» — окно остаётся открытым."""
        if self.is_dirty and not messagebox.askyesno(
            msg.SETUP_CLOSE_DIRTY_TITLE, msg.SETUP_CLOSE_DIRTY_TEXT, parent=self.root
        ):
            return
        self.close()

    def close(self) -> None:
        """Окно разрушается. Отложенная раскладка, которая ещё не сработала, отменяется: её команду Tk удаляет вместе с
        окном, и Tcl позвал бы удалённую команду («invalid command name»)."""
        self.root.after_cancel(self.layout_call)
        self.is_closed = True
        self.root.destroy()

    def mainloop(self) -> None:
        self.root.mainloop()


class SetupApp:
    """Запуск настройщика для установки `paths` с логом запуска `log`. tkinter.TclError (нет Tk или рабочего стола) —
    наружу, в main."""

    def __init__(self, paths: LivecraftPaths, log: Path) -> None:
        self.paths: LivecraftPaths = paths
        self.log: Path = log

    def run(self) -> None:
        """Окно так, как его открывает программа, и его цикл событий до закрытия."""
        SetupWindow.open(self.paths, self.log).mainloop()
