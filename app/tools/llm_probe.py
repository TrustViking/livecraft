"""Пробник нейросети: ключ из сейфа → выбор модели → один короткий запрос (CLAUDE.md §5 tools\\).

Запуск из корня репо: `python -m app.tools.llm_probe`. В поставку не идёт. Сети в тестах нет — SDK openai
подменяется; боевую пробу делает Артур.

Идёт тем же путём, что будущий merge: `Readiness` читает сейф и настройки, `OpenAiClient.from_vault` берёт
ключ, `ModelChoice.select` проверяет основную модель (и запасную, если основная недоступна), затем выбранной
модели уходит проверочный промт `prompt_startup_ping.txt` с настройками `llm` livecraft.json. Печатает
выбранную модель и почему, ответ (не длиннее ANSWER_MAX_CHARS), токены и стоимость запуска. Ни ключа, ни
текста промта. Фильтр секретов в логах ставится сразу после чтения сейфа, до первого обращения к OpenAI.
Коды: 0 — ответ получен; 1 — сбой запроса или модели нет; 2 — нет ключа, сейф или настройки не готовы.
"""
from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import IntEnum
from typing import Any, Final

import openai

from app.config.loader import LivecraftSettings, LlmSettings
from app.llm.client import LlmRequest, LlmResponse, OpenAiClient
from app.llm.errors import LlmRequestError
from app.llm.model import LlmModel
from app.llm.selection import ModelChoice
from app.llm.usage import RunUsage
from app.observability.logging_setup import close_logging, get_logger, install_secret_filter, setup_logging
from app.paths import LivecraftPaths, build_paths, ensure_dirs, resolve_root
from app.resources.loader import RESOURCE_ENCODING, TextResource
from app.secretsafe.vault import Vault
from app.setup.readiness import Readiness
from app.ui import messages_ru as msg

LOGGER_NAME: Final[str] = "tools.llm_probe"
LOGGER = get_logger(LOGGER_NAME)

PROG: Final[str] = "python -m app.tools.llm_probe"
PING_RESOURCE: Final[str] = "prompt_startup_ping.txt"
PING_LABEL: Final[str] = "startup_ping"
UTC_TIMESPEC: Final[str] = "seconds"
ANSWER_MAX_CHARS: Final[int] = 200
COST_FORMAT: Final[str] = "{:.6f}"
LIST_JOINER: Final[str] = ", "


class ProbeExit(IntEnum):
    OK = 0          # модель выбрана и ответила
    ERRORS = 1      # запрос не удался или подходящей модели нет
    CONFIG = 2      # нет ключа, сейф или настройки не готовы — к OpenAI не обращались


@dataclass(frozen=True)
class StartupPing:
    """Проверочный промт донора: модель отвечает строгим JSON о себе. Подставляются модель и момент UTC."""

    resource: TextResource = TextResource(PING_RESOURCE)

    def render(self, model: LlmModel, now: datetime) -> str:
        template: str = self.resource.path.read_text(encoding=RESOURCE_ENCODING)
        moment: str = now.astimezone(timezone.utc).isoformat(timespec=UTC_TIMESPEC)
        return template.format(model_name=model.name, utc_now=moment)


@dataclass(frozen=True)
class LlmProbeReport:
    """Что показать человеку после запроса: ответ (коротко), токены и стоимость запуска. Ни ключа, ни промта."""

    usage: RunUsage
    response: LlmResponse | None

    @property
    def lines(self) -> tuple[str, ...]:
        answer: tuple[str, ...] = (self._answer_line(self.response),) if self.response is not None else ()
        return (*answer, self._tokens_line, self._cost_line)

    @staticmethod
    def _answer_line(response: LlmResponse) -> str:
        text: str = " ".join(response.text.split())
        if len(text) > ANSWER_MAX_CHARS:
            text = msg.LLM_PROBE_ANSWER_CUT.format(text=text[:ANSWER_MAX_CHARS].rstrip())
        return msg.LLM_PROBE_ANSWER.format(text=text)

    @property
    def _tokens_line(self) -> str:
        usage: RunUsage = self.usage
        if not usage.tokens_known:
            return msg.LLM_PROBE_TOKENS_UNKNOWN.format(requests=usage.requests)
        return msg.LLM_PROBE_TOKENS.format(
            input=usage.input_tokens,
            cached=usage.cached_input_tokens,
            output=usage.output_tokens,
            reasoning=usage.reasoning_tokens,
            total=usage.tokens,
            requests=usage.requests,
        )

    @property
    def _cost_line(self) -> str:
        cost: str = COST_FORMAT.format(self.usage.cost_usd)
        tiers: str = LIST_JOINER.join(sorted(self.usage.service_tiers)) or msg.LLM_PROBE_NONE
        if self.usage.cost_known:
            return msg.LLM_PROBE_COST.format(cost=cost, tiers=tiers)
        models: str = LIST_JOINER.join(sorted(self.usage.models)) or msg.LLM_PROBE_NONE
        return msg.LLM_PROBE_COST_UNKNOWN.format(cost=cost, tiers=tiers, models=models)


@dataclass(frozen=True)
class LlmProbe:
    """Один прогон пробника на корне `paths`; вывод `say`, фабрика SDK и «сейчас» — параметрами."""

    paths: LivecraftPaths
    say: Callable[[str], None]
    sdk: Callable[..., Any] = openai.OpenAI
    now: Callable[[], datetime] = field(default=lambda: datetime.now(timezone.utc))
    ping: StartupPing = StartupPing()

    def run(self) -> int:
        self.say(msg.LLM_PROBE_TITLE)
        readiness: Readiness = Readiness.check(self.paths)
        if readiness.vault_error is not None:
            return self._refuse(msg.VAULT_FILE_BROKEN.format(error=readiness.vault_error))
        vault: Vault = readiness.vault if readiness.vault is not None else Vault.empty()
        install_secret_filter(vault)                 # до первого обращения к OpenAI (§7.4)
        for warning in readiness.warnings:
            self.say(warning)
        settings: LivecraftSettings | None = readiness.settings
        if settings is None:
            return self._refuse(str(readiness.settings_error))
        try:
            client: OpenAiClient = OpenAiClient.from_vault(vault, settings.llm, sdk=self.sdk)
        except LlmRequestError as error:
            return self._refuse(error.human)
        return self._probe(client, settings.llm)

    def _probe(self, client: OpenAiClient, llm: LlmSettings) -> int:
        self.say(self._settings_line(llm))
        choice: ModelChoice = ModelChoice.select(client, llm)
        self.say(choice.human)
        if choice.chosen is None:
            return self._finish(client.run_usage, None, ProbeExit.ERRORS)
        request: LlmRequest = LlmRequest.from_settings(
            llm, choice.chosen, self.ping.render(choice.chosen, self.now()), PING_LABEL
        )
        try:
            response: LlmResponse = client.send(request)
        except LlmRequestError as error:
            LOGGER.error("llm_probe_failed %s", error.log_line)
            self.say(error.human)
            return self._finish(client.run_usage, None, ProbeExit.ERRORS)
        return self._finish(client.run_usage, response, ProbeExit.OK)

    def _finish(self, usage: RunUsage, response: LlmResponse | None, code: ProbeExit) -> int:
        for line in LlmProbeReport(usage=usage, response=response).lines:
            self.say(line)
        LOGGER.info("%s exit=%d", usage.log_line, int(code))
        return int(code)

    @staticmethod
    def _settings_line(llm: LlmSettings) -> str:
        return msg.LLM_PROBE_SETTINGS.format(
            primary=llm.model,
            fallback=llm.fallback_model or msg.LLM_PROBE_NO_FALLBACK,
            tier=llm.service_tier.value,
            effort=llm.reasoning_effort.value,
        )

    def _refuse(self, text: str) -> int:
        self.say(text)
        self.say(msg.SETUP_REQUIRED)
        return int(ProbeExit.CONFIG)


def _say(text: str) -> None:
    print(text, flush=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Точка входа пробника: корень, папки, логи; дальше — `LlmProbe`. Ключей нет — есть только --help."""
    argparse.ArgumentParser(prog=PROG).parse_args(argv)
    paths: LivecraftPaths = build_paths(resolve_root())
    ensure_dirs(paths)
    setup_logging(paths.logs_dir, debug=False)
    try:
        return LlmProbe(paths=paths, say=_say).run()
    finally:
        close_logging()


if __name__ == "__main__":
    sys.exit(main())
