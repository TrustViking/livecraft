"""Что войдёт в токен доступа: ползунок на каждое значение (CLAUDE.md §8.2 п.10, §14 решения 65–67, 70, 77).

`TokenItem` — значение, которое токен может нести: поле сейфа, открытая настройка или группа файлов secrets\\ (проект
Google с входом оператора, каналы YouTube с входами в них). Член знает свой источник и свою линию работы: ползунки
вкладки «Токены» стоят группами по линиям (`TokenGroup`) — сначала проект Google, как на «Главной», затем линии в
порядке «Главной». `TokenScope` — что выбрано: только выбранное идёт в токен — поля сейфа (`vault`), открытые настройки
(`carries`; куда слать объявления едет с чатом, на который указывает, — `TokenSettings.only`) и файлы (`files`).
Ничего не выбрано — в токене ничего.

Файлы: «Проект Google» — файл клиента по пути из настроек и вход оператора (sheets.token.json), сделанный через него;
«Каналы YouTube» — каналы channels.json с записями паспорта и входы в них, сделанные через выбранный проект, даже когда
сам проект в токен не идёт. Вход другого проекта не едет — канал идёт без входа (§14 решение 67). В токен идёт только
своё: полученное с токеном помнит учёт `ReceivedFiles`.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Final

from app.config.files import SettingsFile
from app.config.setting_key import SettingKey
from app.google.oauth_client import OAuthClient
from app.paths import FileName, LivecraftPaths
from app.run.mode import LINE_ORDER, RunPart
from app.secretsafe.field import SecretField
from app.secretsafe.vault import Vault
from app.setup.panels.token_file import ReceivedFiles, TokenFile
from app.setup.panels.token_files import TokenChannels, TokenFileName, TokenFiles
from app.ui.messages import msg


class TokenItem(str, Enum):
    """Значение, которое токен может нести (§14 решение 77), в порядке ползунков внутри группы. Значение — английский
    идентификатор и ключ подписи ползунка (`label`)."""

    GOOGLE_PROJECT = "google_project"        # проект Google, выбранный на «Главной», и вход оператора через него
    PLAN_SHEET = "plan_sheet"                # таблица плана
    OPENAI_KEY = "openai_key"                # ключ OpenAI
    PREVIEWS_FOLDER = "previews_folder"      # папка Google Диска для превью
    DOCS_FOLDER = "docs_folder"              # папка Google Диска для документов объявлений
    DOC_CONTACTS = "doc_contacts"            # контакты для стримеров в шапке документа объявлений
    BOT_TOKEN = "bot_token"                  # токен бота Telegram
    PRIVATE_CHAT = "private_chat"            # чат с ботом
    GROUP_CHAT = "group_chat"                # группа с ботом
    YOUTUBE_CHANNELS = "youtube_channels"    # каналы YouTube, паспорт и входы в них
    FORM_LINK = "form_link"                  # ссылка на форму ключей

    @property
    def field(self) -> SecretField | None:
        """Поле сейфа значения; значение — не из сейфа — None."""
        return ITEM_FIELDS.get(self)

    @property
    def setting(self) -> SettingKey | None:
        """Открытая настройка значения; значение — не настройка — None."""
        return ITEM_SETTINGS.get(self)

    @property
    def line(self) -> RunPart | None:
        """Линия работы, в группе которой стоит ползунок; проект Google — своя группа (None)."""
        return ITEM_LINES.get(self)

    @property
    def label(self) -> str:
        return msg.SETUP_TOKENS_ITEM_LABELS[self.value]

    @property
    def hint(self) -> str:
        """Подсказка под ползунком; её нет — пусто."""
        return msg.SETUP_TOKENS_ITEM_HINTS.get(self.value, "")


ITEM_FIELDS: Final[dict[TokenItem, SecretField]] = {
    TokenItem.PLAN_SHEET: SecretField.SHEETS_ID,
    TokenItem.OPENAI_KEY: SecretField.OPENAI_API_KEY,
    TokenItem.PREVIEWS_FOLDER: SecretField.DRIVE_PREVIEWS_FOLDER,
    TokenItem.DOCS_FOLDER: SecretField.DRIVE_DOCS_FOLDER,
    TokenItem.BOT_TOKEN: SecretField.TELEGRAM_BOT_TOKEN,
}
ITEM_SETTINGS: Final[dict[TokenItem, SettingKey]] = {
    TokenItem.DOC_CONTACTS: SettingKey.DOCS_CONTACTS,
    TokenItem.PRIVATE_CHAT: SettingKey.TELEGRAM_PRIVATE_CHAT_ID,
    TokenItem.GROUP_CHAT: SettingKey.TELEGRAM_GROUP_CHAT_ID,
    TokenItem.FORM_LINK: SettingKey.FORM_URL,
}
# Линия каждого значения: кому из линий оно нужно прежде всего (ссылка на форму — линии «Ключи в форму», вкладке «Форма»).
ITEM_LINES: Final[dict[TokenItem, RunPart]] = {
    TokenItem.PLAN_SHEET: RunPart.PLAN,
    TokenItem.OPENAI_KEY: RunPart.MERGE,
    TokenItem.PREVIEWS_FOLDER: RunPart.DRIVE_PREVIEWS,
    TokenItem.DOCS_FOLDER: RunPart.DOC,
    TokenItem.DOC_CONTACTS: RunPart.DOC,
    TokenItem.BOT_TOKEN: RunPart.ANNOUNCE,
    TokenItem.PRIVATE_CHAT: RunPart.ANNOUNCE,
    TokenItem.GROUP_CHAT: RunPart.ANNOUNCE,
    TokenItem.YOUTUBE_CHANNELS: RunPart.BROADCAST,
    TokenItem.FORM_LINK: RunPart.KEYS,
}


@dataclass(frozen=True)
class TokenGroup:
    """Группа ползунков вкладки «Токены»: заголовок и значения в порядке ползунков."""

    heading: str
    items: tuple[TokenItem, ...]

    @classmethod
    def all(cls) -> tuple[TokenGroup, ...]:
        """Группы в порядке вкладки: проект Google (заголовок — как на «Главной»), затем линии в порядке «Главной»;
        линия без значений группы не даёт."""
        project: TokenGroup = cls(msg.SETUP_CLIENT_TITLE, tuple(item for item in TokenItem if item.line is None))
        lines: tuple[TokenGroup, ...] = tuple(
            cls(part.human_label, tuple(item for item in TokenItem if item.line is part)) for part in LINE_ORDER
        )
        return tuple(group for group in (project, *lines) if group.items)


@dataclass(frozen=True)
class TokenScope:
    """Что человек выбрал ползунками вкладки «Токены» (§14 решение 77): значения `items`. Годно любое сочетание."""

    items: frozenset[TokenItem] = frozenset()

    @classmethod
    def of(cls, *items: TokenItem) -> TokenScope:
        return cls(frozenset(items))

    def vault(self, own: Vault) -> Vault:
        """Свои значения сейфа `own` — только выбранные поля."""
        kept: Vault = own
        for item in TokenItem:
            if item.field is not None and item not in self.items:
                kept = kept.without_field(item.field)
        return kept

    def carries(self, key: SettingKey) -> bool:
        """Открытая настройка `key` выбрана."""
        return any(item.setting is key for item in self.items)

    def collect(self, paths: LivecraftPaths) -> TokenFiles:
        """Свои файлы установки, которые выбраны; полученное с токеном не идёт никуда."""
        return TokenFiles(self.files(paths, ReceivedFiles.load(paths)))

    def files(self, paths: LivecraftPaths, received: ReceivedFiles) -> tuple[TokenFile, ...]:
        """Свои файлы этого выбора. Проект — свой файл по пути из настроек под именем токена и свой вход оператора
        через него; каналы — свои каналы с паспортом и входы в них через выбранный проект (проект в токен может и не
        идти). Ни проекта, ни каналов — файлов нет."""
        has_project: bool = TokenItem.GOOGLE_PROJECT in self.items
        has_channels: bool = TokenItem.YOUTUBE_CHANNELS in self.items
        if not has_project and not has_channels:
            return ()
        chosen: Path | None = SettingsFile.placed(paths).project_file
        client: TokenFile | None = None if chosen is None else received.own(chosen)
        project: OAuthClient | None = None if client is None else OAuthClient.of_text(client.text)
        found: list[TokenFile | None] = []
        if has_project:
            found.append(None if client is None else TokenFile(TokenFileName.CLIENT.value, client.text))
            found.append(received.own_login(paths.file(FileName.SHEETS_TOKEN), project))
        if has_channels:
            channels: TokenChannels | None = TokenChannels.collect(paths, received, project)
            found.extend(() if channels is None else channels.files(paths))
        return tuple(file for file in found if file is not None)
