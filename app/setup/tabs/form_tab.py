"""Вкладка окна «Форма» — линия KEYS (CLAUDE.md §8.2, §14 решения 15, 37, 47, 51).

Вверху — ползунок линии «Передавать ключи в форму» (та же переменная, что у линии на «Главной»; какие ключи передать,
«новые | все», выбирают на «Главной»). Ниже — ссылка на Google-форму для ключей стримов (`LinkRowView`; ссылка
проверяется при сохранении тем же разбором, что читает livecraft.json) и в её строке живая проверка формы (`CheckLine`
поверх `FormCheck`: форма читается тем же кодом, что у запуска, в фоновом потоке): ссылка сохранена — проверка идёт
сама, иначе — по кнопке «Проверить форму»; при открытии окна проверок нет. Ссылка на форму нужна не только ключам: ею
пользуются пакет, документ объявлений и Telegram (`FieldUse`), поэтому она бледная, только когда не работает ни одна
из этих линий или вход — «Пакеты»: тогда форма у каждого эфира — из его пакета. Своих правил у вкладки нет.
"""
from __future__ import annotations

from tkinter import ttk

from app.setup.page import SetupPage
from app.setup.panels.form_check import FormCheck, FormVerdict
from app.setup.panels.link_panel import SettingLink
from app.setup.tabs.check_line import CheckLine, CheckTexts
from app.setup.tabs.link_row import LinkRowView
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_shell import TabShell
from app.ui.messages import msg


class FormTab:
    """Вкладка «Форма»: оболочка и ссылка на форму (`form_link`) с проверкой формы (модель `check`, строка `line`)."""

    def __init__(self, context: SetupContext, form_link: SettingLink) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.KEYS)
        self.form_link: LinkRowView = LinkRowView(self.shell.body, form_link, self.shell, self.link_saved)
        self.check: FormCheck = FormCheck.of(context.paths)
        texts: CheckTexts = CheckTexts(
            button=msg.SETUP_FORM_BUTTON_CHECK,
            checking=msg.SETUP_FORM_CHECKING,
            interrupted=FormVerdict.failed(msg.SETUP_TABLE_INTERRUPTED),
            login=msg.SETUP_TABLE_LOGIN,
        )
        self.line: CheckLine = CheckLine(self.form_link.frame, texts, lambda: self.check.run)

    @property
    def frame(self) -> ttk.Frame:
        return self.shell.frame

    @property
    def page(self) -> SetupPage:
        return self.shell.page

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — набрано в поле ссылки: ползунок пишется сразу."""
        return self.form_link.is_dirty

    def link_saved(self) -> None:
        """Ссылка на форму записана: задана — её проверка; убрана — проверять нечего."""
        if self.form_link.link.is_set:
            self.line.start()
