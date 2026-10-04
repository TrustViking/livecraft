"""Ключ OpenAI на вкладке «Нейросеть» без окна: живая проверка (CLAUDE.md §8.2 п.3, §14 решение 22).

`LlmKeyCheck` читает сейф и livecraft.json этой установки, собирает разъём нейросети тем же путём, что запуск
(`OpenAiClient.from_vault`), и выбирает модель тем же правилом (`ModelChoice.select`: проба основной модели, при отказе
доступа — запасной). Итог — `LlmKeyVerdict`: строка для окна — какая модель работает и почему (основная недоступна —
выбрана запасная) либо готовый текст отказа (`LlmFailure.human`). Проверка идёт в фоновом потоке окна: модель не знает
ни потоков, ни Tk; входа в Google у неё нет.

Значение ключа не попадает ни в итог, ни в лог, ни в исключения (§7.4): ключ раскрывает только клиент OpenAI в
заголовке запроса, строки выбора модели и отказа — без значений.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final

from app.config.files import SettingsFile
from app.config.json_node import ConfigError
from app.config.settings import LivecraftSettings, LlmSettings
from app.llm.backend import LlmBackend
from app.llm.backends.openai import OpenAiClient
from app.llm.errors import LlmRequestError
from app.llm.selection import ChoiceReason, ModelChoice
from app.paths import LivecraftPaths
from app.secretsafe.crypto import VaultFormatError
from app.secretsafe.store import VaultStore
from app.secretsafe.vault import Vault
from app.ui.messages import msg

# Разъём нейросети по сейфу и настройкам модели: в программе — OpenAI, в тестах — подделка.
BackendSource = Callable[[Vault, LlmSettings], LlmBackend]
CONFIRMED_REASONS: Final[frozenset[ChoiceReason]] = frozenset(
    {ChoiceReason.PRIMARY_CONFIRMED, ChoiceReason.FALLBACK_CONFIRMED}
)


@dataclass(frozen=True)
class LlmKeyVerdict:
    """Итог проверки ключа: принят ли он и строка для окна."""

    is_ok: bool
    text: str

    @classmethod
    def failed(cls, problem: str) -> LlmKeyVerdict:
        return cls(is_ok=False, text=msg.SETUP_LLM_KEY_FAILED.format(problem=problem))

    @classmethod
    def of_choice(cls, choice: ModelChoice) -> LlmKeyVerdict:
        """Модель ответила на пробу — ключ принят; моделей нет — отказ; проба не удалась не из-за доступа — ключ не
        проверен (запуск всё равно попробует эту модель), причина — сбой пробы."""
        if choice.reason in CONFIRMED_REASONS:
            return cls(is_ok=True, text=msg.SETUP_LLM_KEY_OK.format(choice=choice.human))
        if not choice.is_usable or choice.failure is None:
            return cls.failed(choice.human)
        unchecked: str = msg.SETUP_LLM_KEY_UNCHECKED.format(reason=choice.failure.human, choice=choice.human)
        return cls(is_ok=False, text=unchecked)


@dataclass(frozen=True)
class LlmKeyCheck:
    """Проверка ключа OpenAI этой установки: сейф и livecraft.json — с диска, разъём — `open_backend`."""

    paths: LivecraftPaths
    open_backend: BackendSource

    @classmethod
    def of(cls, paths: LivecraftPaths) -> LlmKeyCheck:
        """Боевая проверка: клиент OpenAI с ключом из сейфа, как у запуска."""
        return cls(paths=paths, open_backend=lambda vault, settings: OpenAiClient.from_vault(vault, settings))

    def run(self, _on_login: Callable[[], None]) -> LlmKeyVerdict:
        """Выбрать модель тем же правилом, что запуск, и сказать итог; сейф, настройки или ключ не годятся — строка с
        причиной. Входа в Google нет: браузер не открывается."""
        try:
            vault: Vault = VaultStore.open(self.paths).load().vault
            settings: LivecraftSettings = SettingsFile.of(self.paths).load()
        except (VaultFormatError, ConfigError) as error:
            return LlmKeyVerdict.failed(error.human)
        try:
            backend: LlmBackend = self.open_backend(vault, settings.llm)
        except LlmRequestError as error:
            return LlmKeyVerdict.failed(error.human)
        return LlmKeyVerdict.of_choice(ModelChoice.select(backend, settings.llm.model, settings.llm.fallback_model))
