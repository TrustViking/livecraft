"""Вкладка окна «Нейросеть» — линия MERGE (CLAUDE.md §8.2, §14 решения 22, 37, 50).

Вверху — ползунок линии. Ниже — строка поля сейфа «Ключ OpenAI» (`KeyRows` поверх `KeysPanel` вкладки; вид ключа
проверяется при сохранении) и в ней живая проверка ключа (`CheckLine` поверх `LlmKeyCheck`: тот же выбор модели, что у
запуска, в фоновом потоке): сменился ключ, с которым пойдёт запуск, — проверка идёт сама, иначе — по кнопке «Проверить
ключ»; при открытии окна проверок нет. Затем модель и её параметры (раздел настроек `SettingsSection`, своя кнопка
«Сохранить»); тексты эфиров решают линии запуска, своего переключателя у них нет (§14 решение 50). Все поля вкладки
нужны только нейросети: она не работает — поля бледные. Своих правил у вкладки нет.
"""
from __future__ import annotations

from collections.abc import Callable
from tkinter import ttk
from typing import Final

from app.config.setting_key import SettingKey
from app.secretsafe.field import SecretField
from app.secretsafe.vault import VaultEntry
from app.setup.page import SetupPage
from app.setup.panels.keys_panel import KeysPanel
from app.setup.panels.llm_key_check import LlmKeyCheck, LlmKeyVerdict
from app.setup.tabs.check_line import CheckLine, CheckTexts
from app.setup.tabs.key_rows import KeyRowView, KeyRows
from app.setup.tabs.settings_section import SettingsSection
from app.setup.tabs.setup_context import SetupContext
from app.setup.tabs.tab_shell import TabShell
from app.ui.messages import msg

MODEL_KEYS: Final[tuple[SettingKey, ...]] = (
    SettingKey.LLM_MODEL,
    SettingKey.LLM_FALLBACK_MODEL,
    SettingKey.LLM_REASONING_EFFORT,
    SettingKey.LLM_SERVICE_TIER,
    SettingKey.LLM_TIMEOUT_SEC,
    SettingKey.LLM_MAX_OUTPUT_TOKENS,
)


class MergeTab:
    """Вкладка «Нейросеть»: оболочка, строка ключа OpenAI (`keys`) с проверкой ключа (модель `check`, строка
    `key_line`) и ключом, с которым пойдёт запуск (`key_entry`), и параметры модели (`model`)."""

    def __init__(self, context: SetupContext, keys: KeysPanel) -> None:
        self.shell: TabShell = TabShell(context, SetupPage.MERGE)
        self.keys: KeyRows = KeyRows(self.shell.body, keys, self.shell, self.keys_saved)
        self.window_saved: Callable[[], None] = context.on_saved
        self.key_entry: VaultEntry | None = keys.vault.entry(SecretField.OPENAI_API_KEY)
        self.check: LlmKeyCheck = LlmKeyCheck.of(context.paths)
        texts: CheckTexts = CheckTexts(
            button=msg.SETUP_LLM_KEY_BUTTON_CHECK,
            checking=msg.SETUP_LLM_KEY_CHECKING,
            interrupted=LlmKeyVerdict.failed(msg.SETUP_TABLE_INTERRUPTED),
        )
        key_frame: ttk.Frame = self.keys.rows[SecretField.OPENAI_API_KEY].block.frame
        self.key_line: CheckLine = CheckLine(key_frame, texts, lambda: self.check.run)
        self.model: SettingsSection = SettingsSection(self.shell.body, context, MODEL_KEYS)
        self.keys.shade(context.shades)

    @property
    def frame(self) -> ttk.Frame:
        return self.shell.frame

    @property
    def page(self) -> SetupPage:
        return self.shell.page

    @property
    def rows(self) -> dict[SecretField, KeyRowView]:
        return self.keys.rows

    @property
    def is_dirty(self) -> bool:
        """Несохранённое — в модели сейфа или введено в поле ключа; разделы настроек считает модель настроек окна."""
        return self.keys.panel.is_dirty or self.keys.has_typed

    def hide_revealed(self) -> None:
        """Уход с вкладки прячет показанное своё значение (§14 решение 11)."""
        self.keys.hide_revealed()

    def keys_saved(self) -> None:
        """Сейф записан: окно узнаёт о записи; ключ, с которым пойдёт запуск, сменился и задан — его проверка."""
        self.window_saved()
        entry: VaultEntry | None = self.keys.panel.vault.entry(SecretField.OPENAI_API_KEY)
        if entry is not None and entry != self.key_entry:
            self.key_line.start()
        self.key_entry = entry
