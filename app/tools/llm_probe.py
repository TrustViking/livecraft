"""Пробник нейросети: ключ из сейфа → выбор модели → один короткий запрос (CLAUDE.md §5 tools\\).

Запуск из корня репо: `python -m app.tools.llm_probe`. В поставку не идёт. Сети в тестах нет — SDK openai
подменяется; боевую пробу делает Артур.

Идёт тем же путём, что будущий merge: `Readiness` читает сейф и настройки, одна строка создаёт реализацию
разъёма (`OpenAiClient.from_vault` берёт ключ), дальше всё — через `LlmBackend`: `ModelChoice.select` проверяет
основную модель (и запасную, если основная недоступна), затем выбранной модели уходит проверочный промт
`prompt_startup_ping.txt` с настройками `llm` livecraft.json. Печатает выбранную модель и почему, ответ
(не длиннее ANSWER_MAX_CHARS), токены, тариф каждого запроса и стоимость запуска. Ни ключа, ни текста промта. Фильтр секретов в логах ставится сразу после чтения сейфа, до первого обращения к OpenAI.
Коды: 0 — ответ получен; 1 — сбой запроса или модели нет; 2 — нет ключа, сейф или настройки не готовы.
"""
from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Final

import openai

from app.config.settings import LivecraftSettings, LlmSettings
from app.core.clock import Clock
from app.core.dates import ISO_TIMESPEC
from app.core.text_format import SPACE
from app.llm.backend import LlmBackend, LlmRequest, LlmResponse
from app.llm.backends.openai import OpenAiClient
from app.llm.errors import LlmRequestError
from app.llm.selection import ModelChoice
from app.llm.usage import COST_FORMAT, RunUsage
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.resources.loader import TextResource
from app.run.exit_code import ExitCode
from app.secretsafe.vault import Vault
from app.setup.readiness import Readiness
from app.tools.probe import ProbeConsole, ProbeLauncher, ProbeSession
from app.ui import messages_ru as msg

LOGGER = get_logger(LogArea.LLM_PROBE)

PROG: Final[str] = "python -m app.tools.llm_probe"
PING_RESOURCE: Final[str] = "prompt_startup_ping.txt"
PING_LABEL: Final[str] = "startup_ping"
ANSWER_MAX_CHARS: Final[int] = 200


class LlmProbeEvent(str, Enum):
    """События пробника нейросети в логе."""

    FAILED = "llm_probe_failed"


@dataclass(frozen=True)
class StartupPing:
    """Проверочный промт донора: модель отвечает строгим JSON о себе. Подставляются модель и момент UTC."""

    resource: TextResource = TextResource(PING_RESOURCE)

    def render(self, model_name: str, now: datetime) -> str:
        moment: str = now.astimezone(timezone.utc).isoformat(timespec=ISO_TIMESPEC)
        return self.resource.body.format(model_name=model_name, utc_now=moment)


@dataclass(frozen=True)
class LlmProbeReport:
    """Что показать человеку после запроса: ответ (коротко), токены, тариф каждого запроса, стоимость запуска."""

    usage: RunUsage
    response: LlmResponse | None

    @property
    def lines(self) -> tuple[str, ...]:
        answer: tuple[str, ...] = (self._answer_line(self.response),) if self.response is not None else ()
        return (*answer, self._tokens_line, self._requests_line, self._cost_line)

    def _answer_line(self, response: LlmResponse) -> str:
        text: str = SPACE.join(response.text.split())
        if len(text) > ANSWER_MAX_CHARS:
            text = msg.LLM_PROBE_ANSWER_CUT.format(text=text[:ANSWER_MAX_CHARS].rstrip())
        return msg.LLM_PROBE_ANSWER.format(text=text)

    @property
    def _tokens_line(self) -> str:
        usage: RunUsage = self.usage
        if not usage.tokens_known:
            return msg.LLM_PROBE_TOKENS_UNKNOWN
        return msg.LLM_PROBE_TOKENS.format(
            input=usage.input_tokens,
            cached=usage.cached_input_tokens,
            output=usage.output_tokens,
            thinking=usage.thinking_tokens,
            total=usage.tokens,
        )

    @property
    def _requests_line(self) -> str:
        """Тариф у каждого запроса отдельно: «проверка — default, проба — flex», а не общий список тарифов."""
        tiers: str = msg.LIST_JOINER.join(
            msg.LLM_PROBE_TIER_ENTRY.format(label=msg.LLM_REQUEST_LABEL_TEXT.get(label, label), tier=tier)
            for label, tier in self.usage.tier_by_request
        )
        return msg.LLM_PROBE_REQUESTS.format(requests=self.usage.requests, tiers=tiers or msg.NONE_TEXT)

    @property
    def _cost_line(self) -> str:
        cost: str = COST_FORMAT.format(self.usage.cost_usd)
        if self.usage.cost_known:
            return msg.LLM_PROBE_COST.format(cost=cost)
        models: str = msg.LIST_JOINER.join(sorted(self.usage.models)) or msg.NONE_TEXT
        return msg.LLM_PROBE_COST_UNKNOWN.format(cost=cost, models=models)


@dataclass(frozen=True)
class LlmProbe:
    """Один прогон пробника в сессии запуска; фабрика SDK и «сейчас» — полями, в тестах свои."""

    session: ProbeSession
    sdk: Callable[..., object] = openai.OpenAI
    clock: Clock = field(default_factory=Clock.utc)
    ping: StartupPing = StartupPing()

    @property
    def console(self) -> ProbeConsole:
        return self.session.console

    def run(self) -> int:
        self.console.say(msg.LLM_PROBE_TITLE)
        readiness: Readiness = Readiness.check(self.session.paths)
        if readiness.vault.error is not None:
            return self.console.refuse(readiness.vault.error.human)
        vault: Vault = readiness.vault.vault if readiness.vault.vault is not None else Vault.empty()
        self.session.log.protect(vault.log_filter())        # до первого обращения к OpenAI (§7.4)
        self.console.say_lines(readiness.warnings)
        settings: LivecraftSettings | None = readiness.settings.value
        if settings is None:
            return self.console.refuse(str(readiness.settings.error))
        try:
            backend: LlmBackend = OpenAiClient.from_vault(vault, settings.llm, sdk=self.sdk)
        except LlmRequestError as error:
            return self.console.refuse(error.human)
        return self._probe(backend, settings.llm)

    def _probe(self, backend: LlmBackend, llm: LlmSettings) -> int:
        self.console.say(self._settings_line(llm))
        choice: ModelChoice = ModelChoice.select(backend, llm.model, llm.fallback_model)
        self.console.say(choice.human)
        if choice.chosen is None:
            return self._finish(backend.run_usage, None, ExitCode.ERRORS)
        request: LlmRequest = LlmRequest.from_settings(
            llm, choice.chosen, self.ping.render(choice.chosen, self.clock.now()), PING_LABEL
        )
        try:
            response: LlmResponse = backend.complete(request)
        except LlmRequestError as error:
            failed: LogEvent = LogEvent.of(LlmProbeEvent.FAILED, backend=error.backend, reason_code=error.kind)
            failed = failed.extended(status_code=error.status_code, api_error_code=error.api_error_code)
            failed.extended(api_error_param=error.api_error_param, detail=error.detail).emit(LOGGER, logging.ERROR)
            self.console.say(error.human)
            return self._finish(backend.run_usage, None, ExitCode.ERRORS)
        return self._finish(backend.run_usage, response, ExitCode.OK)

    def _finish(self, usage: RunUsage, response: LlmResponse | None, code: ExitCode) -> int:
        """Строки отчёта и строка расхода запуска (у неё своё имя события) с кодом выхода."""
        self.console.say_lines(LlmProbeReport(usage=usage, response=response).lines)
        LogEvent.of(usage.log_line, exit=code).emit(LOGGER)
        return int(code)

    def _settings_line(self, llm: LlmSettings) -> str:
        return msg.LLM_PROBE_SETTINGS.format(
            primary=llm.model,
            fallback=llm.fallback_model or msg.NONE_TEXT,
            tier=llm.service_tier.value,
            effort=llm.reasoning_effort.value,
        )


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа пробника: ключей нет — есть только --help; корень, папки и лог — у `ProbeLauncher`."""
    argparse.ArgumentParser(prog=PROG).parse_args(argv)
    return ProbeLauncher.system().run(lambda session: LlmProbe(session=session).run())


if __name__ == "__main__":
    sys.exit(main())
