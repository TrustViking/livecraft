"""Проверка ключа OpenAI без окна (app\\setup\\panels\\llm_key_check.py, CLAUDE.md §8.2, §7.4): тот же выбор модели, что
у запуска (`ModelChoice.select`), на ключе из сейфа установки. К OpenAI тесты не ходят: SDK openai — подделка, разъём —
тот же клиент, что у запуска (`OpenAiClient.from_vault`), либо нейросеть за разъёмом, у которой проба не удаётся."""
from __future__ import annotations

import logging
from collections.abc import Callable

from app.config.settings import LlmSettings
from app.llm.backend import LlmBackend
from app.llm.backends.openai import OpenAiClient
from app.llm.errors import LlmErrorKind, LlmFailure
from app.llm.selection import ChoiceReason
from app.observability.log_event import LogArea
from app.paths import LivecraftPaths
from app.secretsafe.field import SecretField
from app.secretsafe.vault import Vault
from app.setup.panels.llm_key_check import LlmKeyCheck, LlmKeyVerdict
from app.tests.conftest import TOKEN_VALUES, FakeLlmSdk, api_error, llm_answer, write_token_vault
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.merges import FAKE_BACKEND, QueueBackend
from app.ui import messages_ru as msg

KEY: str = TOKEN_VALUES[SecretField.OPENAI_API_KEY]


def _on_sdk(sdk: FakeLlmSdk) -> Callable[[Vault, LlmSettings], LlmBackend]:
    """Клиент OpenAI запуска на подделке SDK."""
    return lambda vault, settings: OpenAiClient.from_vault(vault, settings, sdk=sdk)


def _check(paths: LivecraftPaths, open_backend: Callable[[Vault, LlmSettings], LlmBackend]) -> LlmKeyVerdict:
    return LlmKeyCheck(paths=paths, open_backend=open_backend).run(lambda: None)


def _choice_line(model: str, reason: ChoiceReason) -> str:
    return msg.LLM_CHOICE_LINE.format(model=model, reason=reason.human)


def test_a_key_the_main_model_answers_is_accepted(ready_paths: LivecraftPaths) -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(llm_answer(""))
    verdict: LlmKeyVerdict = _check(ready_paths, _on_sdk(sdk))
    choice: str = _choice_line("gpt-5.6-sol", ChoiceReason.PRIMARY_CONFIRMED)
    assert verdict == LlmKeyVerdict(is_ok=True, text=msg.SETUP_LLM_KEY_OK.format(choice=choice))
    assert [call["model"] for call in sdk.calls] == ["gpt-5.6-sol"]
    assert sdk.created[0]["api_key"] == KEY            # ключ дошёл до SDK — и только туда


def test_a_main_model_out_of_reach_is_named_and_the_fallback_is_chosen(ready_paths: LivecraftPaths) -> None:
    """Основная недоступна этому ключу — ключ принят, работает запасная, и строка это говорит."""
    sdk: FakeLlmSdk = FakeLlmSdk(api_error(404, "The model does not exist", code="model_not_found"), llm_answer(""))
    verdict: LlmKeyVerdict = _check(ready_paths, _on_sdk(sdk))
    choice: str = _choice_line("gpt-5.4", ChoiceReason.FALLBACK_CONFIRMED)
    assert verdict == LlmKeyVerdict(is_ok=True, text=msg.SETUP_LLM_KEY_OK.format(choice=choice))
    assert [call["model"] for call in sdk.calls] == ["gpt-5.6-sol", "gpt-5.4"]


def test_a_refused_key_is_the_ready_refusal_text_without_the_key(ready_paths: LivecraftPaths) -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(api_error(401, f"Incorrect API key provided: {KEY}", code="invalid_api_key"))
    with LogCapture.on(LogArea.LLM) as capture:
        verdict: LlmKeyVerdict = _check(ready_paths, _on_sdk(sdk))
    refusal: str = LlmFailure(LlmErrorKind.AUTH, "openai", status_code=401).human
    assert verdict == LlmKeyVerdict.failed(msg.LLM_CHOICE_REFUSED.format(reason=refusal))
    assert not verdict.is_ok
    assert KEY not in verdict.text
    assert capture.messages() and all(KEY not in line for line in capture.messages())


def test_a_probe_that_fails_not_for_access_leaves_the_key_unchecked(ready_paths: LivecraftPaths) -> None:
    """Сбой пробы, который о доступе ничего не говорит, — ключ не проверен: причина и модель, с которой пойдёт
    запуск."""
    verdict: LlmKeyVerdict = _check(ready_paths, lambda vault, settings: QueueBackend(probe_kind=LlmErrorKind.SERVER))
    failure: str = LlmFailure(LlmErrorKind.SERVER, FAKE_BACKEND, detail="server_error").human
    choice: str = _choice_line("gpt-5.6-sol", ChoiceReason.PRIMARY_UNCHECKED)
    assert verdict == LlmKeyVerdict(is_ok=False, text=msg.SETUP_LLM_KEY_UNCHECKED.format(reason=failure, choice=choice))


def test_without_a_key_nothing_is_asked(ready_paths: LivecraftPaths) -> None:
    write_token_vault(ready_paths, {SecretField.SHEETS_ID: TOKEN_VALUES[SecretField.SHEETS_ID]})
    sdk: FakeLlmSdk = FakeLlmSdk(llm_answer(""))
    verdict: LlmKeyVerdict = _check(ready_paths, _on_sdk(sdk))
    assert verdict == LlmKeyVerdict.failed(LlmFailure(LlmErrorKind.NOT_CONFIGURED, "openai").human)
    assert sdk.created == [] and sdk.calls == []
