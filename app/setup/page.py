"""Вкладки окна настройщика — по порядку окна (CLAUDE.md §8.2, §14 решения 37, 48).

Первая вкладка — «Главная» с линиями всех этапов работы, дальше — по вкладке на линию в порядке этапов: вход («Таблица
плана», «Пакет» — там и папка пакетов для входа «Пакеты»), обработка, вывод (малые линии — разделами одной вкладки:
«Превью» — на диске и на Google Диске, «Google-документ» — документ и копия), эфиры («Эфиры YouTube», «Форма» —
передача ключей и ссылка на форму), затем «Токены» — токен доступа (§14 решения 16, 45), «Логи» — бот и чат поддержки и
архив логов (§14 решения 20, 46), последняя — «Дополнительно».
`SetupPage` называет вкладку: окно по нему находит вкладку для кнопки «Перейти» (`of_line`), строка нужды называет
вкладку, где нужду закрыть (`NEED_PAGES`, `gap_line`), поля сейфа вкладки — какие они (`secret_fields`), а линии
вкладки — чей ползунок стоит вверху вкладки или её разделов (`lines`).
"""
from __future__ import annotations

from enum import Enum
from typing import Final

from app.run.mode import Need, RunPart
from app.secretsafe.field import SecretField
from app.ui.messages import msg


class SetupPage(str, Enum):
    """Вкладка окна. Значение — английский идентификатор и ключ названия для человека (`title`)."""

    HOME = "home"
    PLAN = "plan"
    PACKAGE = "package"
    MERGE = "merge"
    PREVIEWS = "previews"
    DOC = "doc"
    TELEGRAM = "telegram"
    BROADCASTS = "broadcasts"
    KEYS = "keys"
    TOKENS = "tokens"
    LOGS = "logs"
    ADVANCED = "advanced"

    @classmethod
    def of_line(cls, part: RunPart) -> SetupPage:
        """Вкладка, на которой настраивается линия `part`; вход «Пакеты» — на «Пакете»: там папка пакетов."""
        if part is RunPart.PACKAGES_IN:
            return cls.PACKAGE
        return next(page for page in cls if part in page.lines)

    @property
    def title(self) -> str:
        return msg.SETUP_TAB_TITLES[self.value]

    @property
    def lines(self) -> tuple[RunPart, ...]:
        """Линии вкладки в порядке её разделов; у «Главной», «Токенов», «Логов» и «Дополнительно» линий нет."""
        return PAGE_LINES.get(self, ())

    @property
    def secret_fields(self) -> tuple[SecretField, ...]:
        """Поля сейфа, которые вводятся на этой вкладке; у вкладок без сейфа — ни одного."""
        return PAGE_SECRET_FIELDS.get(self, ())

    def gap_line(self, what: str) -> str:
        """Строка нужды: что задать — и что это делается на этой вкладке настройщика."""
        return msg.READINESS_GAP_IN_SETUP.format(what=what, tab=self.title)


PAGE_LINES: Final[dict[SetupPage, tuple[RunPart, ...]]] = {
    SetupPage.PLAN: (RunPart.PLAN,),
    SetupPage.MERGE: (RunPart.MERGE,),
    SetupPage.PREVIEWS: (RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS),
    SetupPage.DOC: (RunPart.DOC, RunPart.DOC_COPY),
    SetupPage.PACKAGE: (RunPart.PACKAGE,),
    SetupPage.TELEGRAM: (RunPart.ANNOUNCE,),
    SetupPage.BROADCASTS: (RunPart.BROADCAST,),
    SetupPage.KEYS: (RunPart.KEYS,),
}
# Таблица плана — на «Таблице плана», ключ OpenAI — на «Нейросети», токен бота — шаг 1 вкладки «Telegram», папка
# материалов на Google Диске — на «Превью» и на «Google-документе» (одно поле на двух вкладках, §14 решение 39), токен
# бота поддержки — на «Логах» (§14 решение 58).
PAGE_SECRET_FIELDS: Final[dict[SetupPage, tuple[SecretField, ...]]] = {
    SetupPage.PLAN: (SecretField.SHEETS_ID,),
    SetupPage.MERGE: (SecretField.OPENAI_API_KEY,),
    SetupPage.PREVIEWS: (SecretField.DRIVE_FOLDER,),
    SetupPage.DOC: (SecretField.DRIVE_FOLDER,),
    SetupPage.TELEGRAM: (SecretField.TELEGRAM_BOT_TOKEN,),
    SetupPage.LOGS: (SecretField.SUPPORT_BOT_TOKEN,),
}
# На какой вкладке закрывается нужда. Папка материалов на Google Диске — на «Превью» (там же её проверка; на
# «Google-документе» — та же строка). client_secret.json в окне не задаётся (§9) — его кладут рядом с программой,
# вкладки у этой нужды нет.
NEED_PAGES: Final[dict[Need, SetupPage]] = {
    Need.OPENAI_VAULT: SetupPage.MERGE,
    Need.SHEETS_VAULT: SetupPage.PLAN,
    Need.FORM: SetupPage.KEYS,
    Need.DRIVE_FOLDER: SetupPage.PREVIEWS,
    Need.TELEGRAM: SetupPage.TELEGRAM,
    Need.CHANNELS: SetupPage.BROADCASTS,
    Need.SETTINGS: SetupPage.ADVANCED,
}
