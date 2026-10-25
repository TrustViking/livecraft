"""Вкладки окна настройщика по порядку окна (CLAUDE.md §8.2, §14 решения 37, 48).

«Главная» с проектом Google и линиями по этапам, затем вкладки в порядке этапов — «Таблица плана», «Cookies YouTube»,
«Пакет», «Нейросеть», «Превью»,
«Google-документ», «Telegram», «Эфиры YouTube», «Форма» — и «Токены», «Логи», «Дополнительно». Модели вкладок строятся
на сейфе, livecraft.json и channels.json установки; у «Превью» и «Google-документа» — своя папка Google Диска и своя её
проверка (§14 решение 60): запись одной папки другую не меняет. Загруженный токен меняет поля сейфа (и обе папки
Диска), ссылку на форму, бота и чаты Telegram, контакты документа объявлений, каналы YouTube и проект Google — их
вкладки и разделы настроек перечитываются, а кто бот и названия чатов окно спрашивает у Telegram заново (`token_loaded`). Несохранённое окна —
набранное на любой вкладке, но не сохранённое, или поле настроек, запись которого отказала (`is_dirty`). Своих правил
здесь нет. Загрузка токена cookies не меняет: их в токене нет.
"""
from __future__ import annotations

import webbrowser
from collections.abc import Callable
from typing import TypeAlias

from app.config.setting_key import SettingKey
from app.core.system import FolderOpener
from app.secretsafe.field import SecretField
from app.setup.page import SetupPage
from app.setup.panels.client_check import ClientCheck
from app.setup.panels.cookies_check import CookiesFileCheck
from app.setup.panels.folder_check import FolderCheck
from app.setup.panels.keys_panel import KeysPanel
from app.setup.panels.link_panel import SettingLink
from app.setup.panels.logs_panel import LogsPanel
from app.setup.panels.table_check import TableCheck
from app.setup.panels.token_panel import TokenPanel
from app.setup.tabs.advanced_tab import AdvancedTab
from app.setup.tabs.channels_tab import ChannelsModels, ChannelsTab
from app.setup.tabs.cookies_tab import CookiesTab
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
    HomeTab | PlanTab | CookiesTab | PackageTab | MergeTab | PreviewsTab | DocTab | PublishTab | ChannelsTab | FormTab | TokensTab
    | LogsTab | AdvancedTab
)


class SetupTabs:
    """Вкладки окна: по полю на вкладку и настройки окна (`context`) — для несохранённого разделов настроек."""

    def __init__(self, context: SetupContext, go_to: Callable[[SetupPage], None]) -> None:
        vault: SetupVault = context.vault
        self.context: SetupContext = context
        self.show_page: Callable[[SetupPage], None] = go_to
        self.home: HomeTab = HomeTab(context, self.go_to, ClientCheck.of(context.paths))
        self.plan: PlanTab = PlanTab(context, KeysPanel.of(vault, SetupPage.PLAN), TableCheck.of(context.paths))
        self.cookies: CookiesTab = CookiesTab(context, CookiesFileCheck(context.paths))
        self.package: PackageTab = PackageTab(context)
        self.merge: MergeTab = MergeTab(context, KeysPanel.of(vault, SetupPage.MERGE))
        previews: FolderCheck = FolderCheck.of(context.paths, SecretField.DRIVE_PREVIEWS_FOLDER)
        self.previews: PreviewsTab = PreviewsTab(context, KeysPanel.of(vault, SetupPage.PREVIEWS), previews)
        docs: FolderCheck = FolderCheck.of(context.paths, SecretField.DRIVE_DOCS_FOLDER)
        self.doc: DocTab = DocTab(context, KeysPanel.of(vault, SetupPage.DOC), docs)
        self.telegram: PublishTab = PublishTab(context, TelegramModels.of(context.paths, vault), webbrowser.open)
        languages: tuple[str, ...] = context.settings.panel.form_languages
        self.broadcasts: ChannelsTab = ChannelsTab(context, ChannelsModels.from_paths(context.paths, languages))
        form: SettingLink = SettingLink.from_paths(context.paths, SettingKey.FORM_URL)
        self.form: FormTab = FormTab(context, form)
        self.tokens: TokensTab = TokensTab(context, TokenPanel.from_paths(context.paths), self.token_loaded)
        self.logs: LogsTab = LogsTab(context, LogsPanel.from_paths(context.paths), FolderOpener().show_file)
        self.advanced: AdvancedTab = AdvancedTab(context)

    @property
    def all(self) -> tuple[SetupTab, ...]:
        """Вкладки в порядке окна."""
        return (
            self.home, self.plan, self.cookies, self.package, self.merge, self.previews, self.doc, self.telegram, self.broadcasts,
            self.form, self.tokens, self.logs, self.advanced,
        )

    def go_to(self, page: SetupPage) -> None:
        """«Перейти»: вкладка `page`; «Главная» — с начала: там проект Google (§14 решение 66)."""
        self.show_page(page)
        if page is SetupPage.HOME:
            self.home.to_top()

    @property
    def is_dirty(self) -> bool:
        """Хотя бы на одной вкладке или в одном разделе настроек есть несохранённое."""
        editing: tuple[PlanTab | MergeTab | PreviewsTab | DocTab | PublishTab | ChannelsTab | FormTab, ...] = (
            self.plan, self.merge, self.previews, self.doc, self.telegram, self.broadcasts, self.form,
        )
        return self.context.settings.is_dirty or any(tab.is_dirty for tab in editing)

    def hide_revealed(self) -> None:
        """Спрятать за маску своё значение, показанное на любой вкладке с полями сейфа (§14 решение 11)."""
        for tab in (self.plan, self.merge, self.previews, self.doc, self.telegram):
            tab.hide_revealed()

    def token_loaded(self) -> None:
        """Загружен токен: поля сейфа (и папки Диска на своих вкладках), ссылка на форму, Telegram, разделы настроек
        (контакты документа объявлений), каналы и проект Google — как они сейчас на диске; окно — по свежей проверке; кто
        бот и названия чатов — у Telegram, в фоне."""
        self.plan.keys.reload()
        self.merge.keys.reload()
        self.previews.folder.reload()
        self.doc.folder.reload()
        self.telegram.reload()
        self.form.form_link.reload()
        self.broadcasts.channels_checked()
        self.context.settings.reload()
        self.home.client.show()
        self.context.on_saved()
        self.telegram.name_chats()
