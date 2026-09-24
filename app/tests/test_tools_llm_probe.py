from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.config.loader import LivecraftSettings, load_settings
from app.llm.errors import LlmErrorKind
from app.llm.model import LlmModel
from app.llm.selection import ChoiceReason
from app.paths import LivecraftPaths, ROOT_ENV_VAR
from app.secretsafe.value import SecretField
from app.tests.conftest import SUPPLIED_VALUES, FakeLlmSdk, api_error, llm_answer, write_supplied_vault
from app.tools import llm_probe
from app.tools.llm_probe import ANSWER_MAX_CHARS, LlmProbe, ProbeExit, StartupPing
from app.ui import messages_ru as msg

MOMENT: datetime = datetime(2026, 9, 24, 18, 30, tzinfo=timezone.utc)
PING_ANSWER: str = json.dumps({"status": "ok", "provider": "openai", "model": "gpt-5.6-sol", "version": "unknown"})


def run_probe(paths: LivecraftPaths, sdk: FakeLlmSdk) -> tuple[int, list[str]]:
    lines: list[str] = []
    code: int = LlmProbe(paths=paths, say=lines.append, sdk=sdk, now=lambda: MOMENT).run()
    return code, lines


def assert_no_vault_values(lines: list[str]) -> None:
    text: str = "\n".join(lines)
    for value in SUPPLIED_VALUES.values():
        assert value not in text


def test_ping_prompt_gets_the_model_and_the_moment() -> None:
    prompt: str = StartupPing().render(LlmModel("gpt-5.4"), MOMENT)
    assert prompt.startswith("You are a health-check responder for the LLM API.")
    assert "expected_model=gpt-5.4" in prompt and "utc_now=2026-09-24T18:30:00+00:00" in prompt


def test_probe_prints_the_model_the_answer_tokens_and_cost(ready_paths: LivecraftPaths) -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(llm_answer("", output_tokens=16), llm_answer(PING_ANSWER))
    code, lines = run_probe(ready_paths, sdk)
    assert code == ProbeExit.OK == 0
    settings: LivecraftSettings = load_settings(ready_paths.config_file)
    assert lines[0] == msg.LLM_PROBE_TITLE
    assert lines[1] == msg.LLM_PROBE_SETTINGS.format(
        primary=settings.llm.model,
        fallback=settings.llm.fallback_model,
        tier=settings.llm.service_tier.value,
        effort=settings.llm.reasoning_effort.value,
    )
    assert msg.LLM_CHOICE_LINE.format(model=settings.llm.model, reason=ChoiceReason.PRIMARY_CONFIRMED.human) in lines
    assert msg.LLM_PROBE_ANSWER.format(text=PING_ANSWER) in lines
    assert msg.LLM_PROBE_TOKENS.format(input=2000, cached=400, output=116, reasoning=80, total=2116, requests=2) in lines
    assert lines[-1].startswith("Стоимость: $0.00") and "(тариф flex)" in lines[-1]
    ping_call: dict[str, object] = sdk.calls[1]
    assert ping_call["model"] == settings.llm.model and ping_call["max_output_tokens"] == settings.llm.max_output_tokens
    assert "expected_model=" + settings.llm.model in json.dumps(ping_call["input"])
    assert sdk.created[0]["api_key"] == SUPPLIED_VALUES[SecretField.OPENAI_API_KEY]
    assert_no_vault_values(lines)


def test_long_answer_is_cut(ready_paths: LivecraftPaths) -> None:
    code, lines = run_probe(ready_paths, FakeLlmSdk(llm_answer(""), llm_answer("слово " * 100)))
    answer: str = next(line for line in lines if line.startswith("Ответ модели: "))
    assert code == ProbeExit.OK
    assert answer.endswith("…") and len(answer) <= len("Ответ модели: ") + ANSWER_MAX_CHARS + 1


def test_unknown_served_model_makes_the_cost_a_lower_bound(ready_paths: LivecraftPaths) -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(llm_answer("", model="gpt-9-preview"), llm_answer(PING_ANSWER, model="gpt-9-preview"))
    code, lines = run_probe(ready_paths, sdk)
    assert code == ProbeExit.OK
    assert "gpt-9-preview" in lines[-1] and lines[-1].startswith("Стоимость: не меньше $")


def test_failed_request_is_code_1(ready_paths: LivecraftPaths) -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(llm_answer(""), api_error(400, "bad input"))
    code, lines = run_probe(ready_paths, sdk)
    assert code == ProbeExit.ERRORS == 1
    assert msg.LLM_REQUEST_FAILED_STATUS.format(reason=LlmErrorKind.BAD_REQUEST.human, status=400) in lines
    assert not any(line.startswith("Ответ модели") for line in lines)
    assert lines[-2].startswith("Токены:")


def test_rejected_key_is_code_1_and_nothing_else_is_asked(ready_paths: LivecraftPaths) -> None:
    sdk: FakeLlmSdk = FakeLlmSdk(api_error(401, f"Incorrect API key provided: {SUPPLIED_VALUES[SecretField.OPENAI_API_KEY]}"))
    code, lines = run_probe(ready_paths, sdk)
    assert code == ProbeExit.ERRORS
    assert len(sdk.calls) == 1
    assert any(line.startswith("Модель не выбрана.") for line in lines)
    assert_no_vault_values(lines)


def test_no_key_is_code_2_without_openai(ready_paths: LivecraftPaths) -> None:
    write_supplied_vault(
        ready_paths, {field: value for field, value in SUPPLIED_VALUES.items() if field is not SecretField.OPENAI_API_KEY}
    )
    sdk: FakeLlmSdk = FakeLlmSdk()
    code, lines = run_probe(ready_paths, sdk)
    assert code == ProbeExit.CONFIG == 2
    assert sdk.created == [] and sdk.calls == []
    assert msg.LLM_REQUEST_FAILED.format(reason=LlmErrorKind.NOT_CONFIGURED.human) in lines
    assert lines[-1] == msg.SETUP_REQUIRED


def test_no_settings_is_code_2(livecraft_paths: LivecraftPaths) -> None:
    sdk: FakeLlmSdk = FakeLlmSdk()
    code, lines = run_probe(livecraft_paths, sdk)
    assert code == ProbeExit.CONFIG
    assert sdk.created == [] and lines[-1] == msg.SETUP_REQUIRED


def test_broken_vault_is_code_2(ready_paths: LivecraftPaths) -> None:
    ready_paths.vault_file.write_text("{не json", encoding="utf-8")
    code, lines = run_probe(ready_paths, FakeLlmSdk())
    assert code == ProbeExit.CONFIG and lines[-1] == msg.SETUP_REQUIRED


def test_main_on_an_empty_root_is_code_2(monkeypatch: pytest.MonkeyPatch, livecraft_paths: LivecraftPaths) -> None:
    monkeypatch.setenv(ROOT_ENV_VAR, str(livecraft_paths.root))
    assert llm_probe.main([]) == ProbeExit.CONFIG
