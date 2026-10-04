"""Вкладки окна настройщика по порядку окна (CLAUDE.md §8.2, §14 решения 37, 48).

«Главная» с линиями по этапам, затем вкладки в порядке этапов — «Таблица плана», «Пакет», «Нейросеть», «Превью»,
«Google-документ», «Telegram», «Эфиры YouTube», «Форма» — и «Токены», «Логи», «Дополнительно». Модели вкладок строятся
на сейфе, livecraft.json и channels.json установки; папка материалов на Google Диске — одно поле сейфа на «Превью» и на
«Google-документе»: после любой записи оба поля перечитываются (`reload_links`). Загруженный токен меняет поля сейфа,
ссылку на форму, ботов и чаты Telegram (и бота и чат поддержки) и контакты документа объявлений — их вкладки и разделы настроек
перечитываются (`token_loaded`). Несохранённое окна —
набранное на любой вкладке или в любом разделе настроек (`is_dirty`). Своих правил здесь нет.
"""
from __future__ import annotations

import webbrowser
from collections.abc import Callable
from typing import TypeAlias

from app.config.setting_key import SettingKey
from app.setup.page import SetupPage
from app.setup.panels.folder_check import FolderCheck
from app.setup.panels.keys_panel import KeysPanel
from app.setup.panels.link_panel import SettingLink
from app.setup.panels.logs_panel import LogsPanel
from app.setup.panels.table_check import TableCheck
from app.setup.panels.token_panel import TokenPanel
from app.setup.tabs.advanced_tab import AdvancedTab
from app.setup.tabs.channels_tab import ChannelsModels, ChannelsTab
from app.setup.tabs.doc_tab import DocTab
from app.setup.tabs.form_tab import FormTab
from app.setup.tabs.home_tab import HomeTab
from app.setup.tabs.logs_tab import LogsTab
from app.setup.tabs.merge_tab import MergeTab
from app.setup.tabs.package_tab import PackageTab
from app.setup.tabs.plan_tab import PlanTab
from app.setup.tabs.previews_tab import PreviewsTab
from app.setup.tabs.publish_tab import PublishTab, TelegramModels
from app.setup.setup_vault import SetupVault
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tokens_tab import TokensTab

# Вкладка окна: у каждой есть страница блокнота (`frame`) и своя `SetupPage`.
SetupTab: TypeAlias = (
    HomeTab | PlanTab | PackageTab | MergeTab | PreviewsTab | DocTab | PublishTab | ChannelsTab | FormTab | TokensTab
    | LogsTab | AdvancedTab
)


class SetupTabs:
    """Вкладки окна: по полю на вкладку и настройки окна (`context`) — для несохранённого разделов настроек."""

    def __init__(self, context: SetupContext, go_to: Callable[[SetupPage], None]) -> None:
        vault: SetupVault = context.vault
        folder: FolderCheck = FolderCheck.of(context.paths)
        self.context: SetupContext = context
        self.home: HomeTab = HomeTab(context.notebook, context.switches, go_to)
        self.plan: PlanTab = PlanTab(context, KeysPanel.of(vault, SetupPage.PLAN), TableCheck.of(context.paths))
        self.package: PackageTab = PackageTab(context)
        self.merge: MergeTab = MergeTab(context, KeysPanel.of(vault, SetupPage.MERGE))
        self.previews: PreviewsTab = PreviewsTab(context, KeysPanel.of(vault, SetupPage.PREVIEWS), folder)
        self.doc: DocTab = DocTab(context, KeysPanel.of(vault, SetupPage.DOC), folder)
        self.telegram: PublishTab = PublishTab(context, TelegramModels.of(context.paths, vault), webbrowser.open)
        languages: tuple[str, ...] = context.settings.panel.form_languages
        self.broadcasts: ChannelsTab = ChannelsTab(context, ChannelsModels.from_paths(context.paths, languages))
        form: SettingLink = SettingLink.from_paths(context.paths, SettingKey.FORM_URL)
        self.form: FormTab = FormTab(context, form)
        self.tokens: TokensTab = TokensTab(context, TokenPanel.from_paths(context.paths), self.token_loaded)
        self.logs: LogsTab = LogsTab(context, KeysPanel.of(vault, SetupPage.LOGS), LogsPanel.from_paths(context.paths))
        self.advanced: AdvancedTab = AdvancedTab(context)

    @property
    def all(self) -> tuple[SetupTab, ...]:
        """Вкладки в порядке окна."""
        return (
            self.home, self.plan, self.package, self.merge, self.previews, self.doc, self.telegram, self.broadcasts,
            self.form, self.tokens, self.logs, self.advanced,
        )

    @property
    def is_dirty(self) -> bool:
        """Хотя бы на одной вкладке или в одном разделе настроек есть несохранённое."""
        editing: tuple[PlanTab | MergeTab | PreviewsTab | DocTab | PublishTab | ChannelsTab | FormTab | LogsTab, ...] = (
            self.plan, self.merge, self.previews, self.doc, self.telegram, self.broadcasts, self.form, self.logs,
        )
        return self.context.settings.is_dirty or any(tab.is_dirty for tab in editing)

    def hide_revealed(self) -> None:
        """Спрятать за маску своё значение, показанное на любой вкладке с полями сейфа (§14 решение 11)."""
        for tab in (self.plan, self.merge, self.previews, self.doc, self.telegram, self.logs):
            tab.hide_revealed()

    def reload_links(self) -> None:
        """Папка материалов на Диске — как она сейчас в сейфе, на обеих вкладках, где она есть."""
        self.previews.folder.reload()
        self.doc.folder.reload()

    def show_chats(self) -> None:
        """Чаты Telegram — как они сейчас на диске, на обеих вкладках, где они есть: чат, подключённый на одной, и перенос
        группы в супергруппу видны на другой сразу; кто бот и названия чатов этого окна остаются."""
        self.telegram.show_chats()
        self.logs.show_chats()

    def token_loaded(self) -> None:
        """Загружен токен: поля сейфа, ссылка на форму, Telegram, чат поддержки и разделы настроек (контакты документа
        объявлений) — как они сейчас на диске; окно — по свежей проверке."""
        self.plan.keys.reload()
        self.merge.keys.reload()
        self.reload_links()
        self.telegram.reload()
        self.logs.reload()
        self.form.form_link.reload()
        self.context.settings.reload()
        self.context.on_saved()
