"""Тексты промта merge: боевые шаблоны донора и встроенные в его код тексты (CLAUDE.md §2, §14 решение 23).

Источник боевых текстов — `restreamer\\app\\llm\\prompts\\templates.yaml` в том виде, в каком его отдаёт загрузчик донора
(`app\\config\\template_loader.py` → поля `AppTemplates`): ресурсы `merge_prompt_title_description.txt`,
`merge_prompt_structural_rules.txt`, `merge_prompt_no_description.txt`, `merge_prompt_contracts.json`,
`merge_retry_reinforcements.json` — значения побайтно. Тексты, которые донор держал в коде (политики ссылок и
смешения тем, строка-якорь спикеров, запасные строки повтора), — ресурсы `merge_policy_*`, `merge_prompt_speaker_anchor.txt`,
`merge_retry_fallback_lines.json`, `merge_retry_expanded_lines.json` без правки строк. Первая строка `.txt` и ключ
`source` в `.json` — откуда перенесено.

Подстановка `{ключ}` в контракт и строки повтора — правило донора `_format_template_placeholders`: `replace` по ключам
в порядке их перечисления и `strip` итога, а не `str.format` (в шаблонах бывают фигурные скобки не для подстановки).
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from functools import cache
from types import MappingProxyType
from typing import Any, Final

from app.resources.loader import RESOURCE_ENCODING, TextResource

TITLE_DESCRIPTION_RESOURCE: Final[str] = "merge_prompt_title_description.txt"
STRUCTURAL_RULES_RESOURCE: Final[str] = "merge_prompt_structural_rules.txt"
NO_DESCRIPTION_RESOURCE: Final[str] = "merge_prompt_no_description.txt"
SPEAKER_ANCHOR_RESOURCE: Final[str] = "merge_prompt_speaker_anchor.txt"
CONTRACTS_RESOURCE: Final[str] = "merge_prompt_contracts.json"
LINK_POLICY_RESOURCE: Final[str] = "merge_policy_link.txt"
CROSS_DOMAIN_POLICY_RESOURCE: Final[str] = "merge_policy_cross_domain.txt"
RETRY_REINFORCEMENTS_RESOURCE: Final[str] = "merge_retry_reinforcements.json"
RETRY_FALLBACKS_RESOURCE: Final[str] = "merge_retry_fallback_lines.json"
EXPANDED_RETRY_RESOURCE: Final[str] = "merge_retry_expanded_lines.json"
SERVICE_HINTS_RESOURCE: Final[str] = "merge_service_hints.txt"
SOURCE_LINE_PREFIX: Final[str] = "#"
JSON_VALUE_KEY: Final[str] = "value"
LINE_BREAK: Final[str] = "\n"


class MergeContractMode(str, Enum):
    """Контракт описания по числу и сходству источников. Значения — `mode_label` донора и ключи шаблона контрактов."""

    COMPACT = "compact"
    EXPANDED = "expanded"
    NARRATIVE = "narrative"


def fill_placeholders(template: str, values: Mapping[str, object]) -> str:
    """`{ключ}` → значение по порядку ключей, затем `strip` (донор: `_format_template_placeholders`)."""
    text: str = str(template or "")
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text.strip()


@dataclass(frozen=True)
class MergePromptTexts:
    """Все тексты, из которых собирается промт merge и инструкция повтора.

    `contracts` и `retry_reinforcements` — боевые шаблоны как есть (края срезаются в момент применения, как у донора);
    `retry_fallbacks` — строки повтора на случай, когда в `retry_reinforcements` нет сигнала; `expanded_retry` — строки
    расширенного профиля повтора по сигналу плюс `unknown`, `three_plus_sources`, `four_plus_sources`.
    """

    title_description: str
    structural_rules: str
    contracts: Mapping[MergeContractMode, str]
    retry_reinforcements: Mapping[str, tuple[str, ...]]
    no_description: str
    link_policy: str
    cross_domain_policy: str
    speaker_anchor: str
    retry_fallbacks: Mapping[str, tuple[str, ...]]
    expanded_retry: Mapping[str, tuple[str, ...]]
    service_hints: tuple[str, ...]

    @classmethod
    @cache
    def load(cls) -> MergePromptTexts:
        """Тексты из ресурсов программы; читаются один раз за процесс."""
        contracts: Mapping[str, Any] = cls._resource_value(CONTRACTS_RESOURCE)
        return cls(
            title_description=cls._resource_text(TITLE_DESCRIPTION_RESOURCE),
            structural_rules=cls._resource_text(STRUCTURAL_RULES_RESOURCE),
            contracts=MappingProxyType({mode: str(contracts[mode.value]) for mode in MergeContractMode}),
            retry_reinforcements=cls._resource_lines(RETRY_REINFORCEMENTS_RESOURCE),
            no_description=cls._resource_text(NO_DESCRIPTION_RESOURCE),
            link_policy=cls._resource_text(LINK_POLICY_RESOURCE),
            cross_domain_policy=cls._resource_text(CROSS_DOMAIN_POLICY_RESOURCE),
            speaker_anchor=cls._resource_text(SPEAKER_ANCHOR_RESOURCE),
            retry_fallbacks=cls._resource_lines(RETRY_FALLBACKS_RESOURCE),
            expanded_retry=cls._resource_lines(EXPANDED_RETRY_RESOURCE),
            service_hints=TextResource(SERVICE_HINTS_RESOURCE).lines,
        )

    @staticmethod
    def _resource_text(name: str) -> str:
        """Значение `.txt`-ресурса: без первой строки-источника и без краёв (загрузчик донора отдаёт значения без краёв)."""
        raw: str = TextResource(name).path.read_text(encoding=RESOURCE_ENCODING)
        first, _, rest = raw.partition(LINE_BREAK)
        return (rest if first.startswith(SOURCE_LINE_PREFIX) else raw).strip()

    @staticmethod
    def _resource_value(name: str) -> Any:
        return TextResource(name).data[JSON_VALUE_KEY]

    @classmethod
    def _resource_lines(cls, name: str) -> Mapping[str, tuple[str, ...]]:
        """Словарь «ключ → строки» из `.json`-ресурса."""
        payload: Mapping[str, Any] = cls._resource_value(name)
        return MappingProxyType({str(key): tuple(str(line) for line in lines) for key, lines in payload.items()})

    def contract_template(self, mode: MergeContractMode) -> str:
        return str(self.contracts[mode] or "").strip()

    def reinforcement_lines(self, signal: str, values: Mapping[str, object]) -> tuple[str, ...]:
        """Строки повтора по сигналу: из боевого шаблона, иначе запасные; пустые строки шаблона выпадают.

        Донор: `_load_retry_reinforcement_lines` — к выбранным строкам применяется подстановка `{ключ}`.
        """
        template_lines: tuple[str, ...] = tuple(
            stripped for line in self.retry_reinforcements.get(signal, ()) if (stripped := str(line or "").strip())
        )
        selected: tuple[str, ...] = template_lines or self.retry_fallbacks.get(signal, ())
        return tuple(fill_placeholders(line, values) for line in selected)

    def speaker_anchor_line(self, source_count: int, min_names: int, names: tuple[str, ...]) -> str:
        """Строка-якорь спикеров; имена подставляются последними, как в f-строке донора."""
        return (
            self.speaker_anchor.replace("{source_count}", str(source_count))
            .replace("{min_names}", str(min_names))
            .replace("{names_joined}", ", ".join(names))
        )
