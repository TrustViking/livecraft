"""Строка фоновой проверки окна: отложенный опрос не переживает свои виджеты, итог снимает ожидание, цвет — у каждой
строки итога по её знаку, а фоновый поток не держит ни одного объекта Tk (объекты Tk живут в главном потоке)."""
from __future__ import annotations

import gc
import inspect
import queue
import sys
import threading
import time
import tkinter as tk
import weakref
from collections.abc import Iterator
from tkinter import ttk
from types import FrameType, FunctionType, ModuleType

import pytest

from app.setup.panels.folder_check import FolderVerdict
from app.setup.panels.form_check import FormVerdict
from app.setup.tabs.check_line import CheckLine, CheckMail, CheckRun, CheckTexts, CheckVerdict, ResultRow, RowState
from app.setup.tabs.tab_theme import STATUS_SET_FOREGROUND, STATUS_UNSET_FOREGROUND
from app.ui import messages_ru as msg

TEXTS: CheckTexts = CheckTexts(
    button="Проверить",
    checking="Проверяю…",
    login="Открылся браузер",
    interrupted=FolderVerdict(is_ok=False, text="Проверка прервалась"),
)
DONE: FolderVerdict = FolderVerdict(is_ok=True, text="Папка годится")
WAIT_SEC: float = 10.0
THREADING_FILE: str = "threading.py"      # кадры модуля threading — уже не код строки проверки


@pytest.fixture
def root() -> Iterator[tk.Tk]:
    window: tk.Tk = tk.Tk()
    window.withdraw()
    try:
        yield window
    finally:
        window.destroy()


def _pending(window: tk.Tk) -> tuple[str, ...]:
    """Ожидания `after`, которые Tcl ещё держит."""
    return tuple(window.tk.splitlist(window.tk.call("after", "info")))


def _done(_mail: CheckMail) -> CheckVerdict:
    return DONE


def _waiting_run(release: threading.Event, told: str = "") -> CheckRun:
    """Проверка, которая говорит `told` (если есть) и не отдаёт итог, пока тест её не отпустит."""

    def _run(mail: CheckMail) -> CheckVerdict:
        if told:
            mail.tell(told)
        release.wait(WAIT_SEC)
        return DONE

    return _run


def _wait(root: tk.Tk, line: CheckLine) -> None:
    deadline: float = time.monotonic() + WAIT_SEC
    while line.is_running:
        assert time.monotonic() < deadline, "проверка не закончилась"
        root.update()
        time.sleep(0.01)


def test_destroying_the_line_cancels_its_pending_poll(root: tk.Tk) -> None:
    """Окно закрыли посреди проверки: ожидание опроса снято, Tcl не позовёт удалённую команду."""
    release: threading.Event = threading.Event()
    frame: ttk.Frame = ttk.Frame(root)
    line: CheckLine = CheckLine(frame, TEXTS, lambda: _waiting_run(release))
    try:
        line.start()
        poll_id: str | None = line.poll_id
        assert poll_id is not None and poll_id in _pending(root)
        frame.destroy()
        assert poll_id not in _pending(root)
        assert line.poll_id is None
    finally:
        release.set()


def test_the_result_leaves_no_pending_poll_and_frees_the_button(root: tk.Tk) -> None:
    frame: ttk.Frame = ttk.Frame(root)
    line: CheckLine = CheckLine(frame, TEXTS, lambda: _done)
    line.start()
    _wait(root, line)
    assert line.poll_id is None
    assert _pending(root) == ()
    assert str(line.button.cget("state")) == tk.NORMAL
    assert line.result_text == DONE.text


def test_an_extra_button_starts_its_own_check_and_every_button_waits(root: tk.Tk) -> None:
    """Вторая кнопка строки запускает свою проверку; пока она идёт, недоступны обе кнопки; после итога — on_done."""
    release: threading.Event = threading.Event()
    done: list[bool] = []
    frame: ttk.Frame = ttk.Frame(root)
    line: CheckLine = CheckLine(frame, TEXTS, lambda: _done, lambda: done.append(True))
    other: ttk.Button = line.add_button("Войти", lambda: line.start_run(_waiting_run(release)))
    other.invoke()
    try:
        assert line.is_running and done == []
        assert [str(button.cget("state")) for button in line.buttons] == [tk.DISABLED, tk.DISABLED]
    finally:
        release.set()
    _wait(root, line)
    assert [str(button.cget("state")) for button in line.buttons] == [tk.NORMAL, tk.NORMAL]
    assert line.result_text == DONE.text and done == [True]


def test_lines_told_during_the_check_are_shown_before_the_result(root: tk.Tk) -> None:
    release: threading.Event = threading.Event()
    frame: ttk.Frame = ttk.Frame(root)
    line: CheckLine = CheckLine(frame, TEXTS, lambda: _waiting_run(release, "Канал «UA»: вход…"))
    line.start()
    try:
        deadline: float = time.monotonic() + WAIT_SEC
        while line.result_text != "Канал «UA»: вход…":
            assert time.monotonic() < deadline, "строки по ходу проверки нет"
            root.update()
            time.sleep(0.01)
    finally:
        release.set()
    _wait(root, line)
    assert line.result_text == DONE.text


def test_the_mail_is_the_login_callback_of_the_models() -> None:
    """Модель зовёт «открылся браузер» без аргументов — это сама почта: строка о браузере уходит в очередь."""
    mail: CheckMail = CheckMail(inbox=queue.Queue(), login=TEXTS.login)
    mail()
    assert mail.inbox.get_nowait() == TEXTS.login


# --- цвет по строке итога: «✓» — зелёная, «✗» — красная, справка — обычная


@pytest.mark.parametrize(
    ("text", "state"),
    [
        ("✓ Форма «TEST»: вопросы на месте — «Время стрима».", RowState.OK),
        ("✗ Форма ключей «TEST»: нет дат 18.03.2027 — эфиры на эти даты не создаются.", RowState.PROBLEM),
        ("Даты «Время стрима» от сегодня: 17.03.2027.", RowState.NOTE),
    ],
)
def test_the_state_of_a_result_row_is_its_mark(text: str, state: RowState) -> None:
    assert ResultRow(text).state is state


def test_every_row_of_the_form_result_has_its_own_colour(root: tk.Tk) -> None:
    """Итог формы с вопросами на месте и без даты 18.03.2027: «✓ вопросы» — зелёная, «✗ нет дат» — красная, даты —
    обычная справка; итог не одним цветом по «годится ли»."""
    ok: str = msg.SETUP_FORM_OK.format(form="TEST", questions="«Время стрима»")
    note: str = msg.SETUP_FORM_DATES.format(question="Время стрима", dates="17.03.2027")
    missing: str = msg.CHECK_PROBLEM_LINE.format(line=msg.FORM_DATES_MISSING.format(form="TEST", dates="18.03.2027"))
    verdict: FormVerdict = FormVerdict(is_ok=False, lines=(ok, note, missing))
    frame: ttk.Frame = ttk.Frame(root)
    line: CheckLine = CheckLine(frame, TEXTS, lambda: lambda _mail: verdict)
    line.start()
    _wait(root, line)
    assert [row.text for row in line.shown] == [ok, note, missing]
    colours: list[str] = [str(label.cget("foreground")) for label in line.labels]
    assert colours[0] == STATUS_SET_FOREGROUND and colours[2] == STATUS_UNSET_FOREGROUND
    assert colours[1] not in (STATUS_SET_FOREGROUND, STATUS_UNSET_FOREGROUND)


# --- фоновый поток без Tk: ни одного объекта Tk среди того, что держит поток проверки


def _reachable_tk(start: list[object]) -> list[object]:
    """Объекты Tk, до которых можно дойти от `start` по ссылкам, не заходя в модули, классы и глобальные словари."""
    module_dicts: set[int] = {id(vars(module)) for module in list(sys.modules.values()) if module is not None}
    seen: set[int] = set()
    found: list[object] = []
    queue: list[object] = list(start)
    while queue:
        item: object = queue.pop()
        if id(item) in seen or id(item) in module_dicts or isinstance(item, (ModuleType, type)):
            continue
        seen.add(id(item))
        if isinstance(item, (tk.Misc, tk.Variable, tk.Image)):
            found.append(item)
            continue
        referents: list[object] = gc.get_referents(item)
        if isinstance(item, FunctionType):
            referents = [ref for ref in referents if ref is not item.__globals__]
        queue.extend(referents)
    return found


def test_the_check_thread_holds_no_tk_object(root: tk.Tk) -> None:
    """Всё, что держит фоновый поток в коде строки (кадры `CheckMail.work` и самой проверки: почта, модель, итог
    «прервалась»), — без объектов Tk, хотя рядом со строкой на вкладке есть и виджеты, и переменная Tk: мусорщик
    фонового потока не соберёт объект Tk вне главного потока."""
    held: list[object] = []

    def _look(mail: CheckMail) -> CheckVerdict:
        frame: FrameType | None = inspect.currentframe()
        while frame is not None and not frame.f_code.co_filename.endswith(THREADING_FILE):
            held.extend(value for name, value in frame.f_locals.items() if name != "held")
            frame = frame.f_back
        return DONE

    host: ttk.Frame = ttk.Frame(root)
    host.variable = tk.BooleanVar(master=root)       # type: ignore[attr-defined]  # переменная Tk вкладки
    line: CheckLine = CheckLine(host, TEXTS, lambda: _look)
    line.start()
    _wait(root, line)
    assert line.result_text == DONE.text
    assert any(isinstance(item, CheckMail) for item in held)
    assert _reachable_tk(held) == []


class _WindowGarbage:
    """Мусор закрытого окна: объект в кольце ссылок с переменной Tk — его соберёт только сборщик колец."""

    def __init__(self, root: tk.Tk) -> None:
        self.me: _WindowGarbage = self
        self.variable: tk.BooleanVar = tk.BooleanVar(master=root)


def test_the_window_garbage_is_collected_in_the_main_thread_before_the_check_starts(root: tk.Tk) -> None:
    """Переменная Tk в мусоре окна уничтожается в главном потоке — до того, как фоновый поток проверки сможет разбудить
    сборщик у себя (иначе «main thread is not in main loop»). Автосборка на время теста выключена: собрать мусор может
    только сама строка."""
    was_enabled: bool = gc.isenabled()
    gc.disable()
    try:
        garbage: weakref.ref[_WindowGarbage] = weakref.ref(_WindowGarbage(root))
        assert garbage() is not None
        line: CheckLine = CheckLine(ttk.Frame(root), TEXTS, lambda: _done)
        line.start()
        assert garbage() is None
        _wait(root, line)
    finally:
        if was_enabled:
            gc.enable()
