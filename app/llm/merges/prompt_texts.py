"""Тексты промта merge: шаблоны, контракты, строки повтора и политики — ресурсы программы (CLAUDE.md §2, §14 решение 23).

Ресурсы: `merge_prompt_title_description.txt`, `merge_prompt_structural_rules.txt`, `merge_prompt_no_description.txt`,
`merge_prompt_contracts.json`, `merge_retry_reinforcements.json`, политики `merge_policy_*`, строка-якорь спикеров
`merge_prompt_speaker_anchor.txt` и запасные строки повтора `merge_retry_fallback_lines.json`. Первая строка `.txt`
и ключ `source` в `.json` — откуда взят текст; само значение `.json` — под ключом `value` (`PromptResource`).

Подстановка `{ключ}` (`PromptTemplate.filled`) — замена по ключам `Placeholder` в порядке их перечисления и `strip`
итога, а не `str.format`: в шаблонах бывают фигурные скобки не для подстановки.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from functools import cache
from types import MappingProxyType
from typing import Final

from app.config.json_node import JsonNode
from app.resources.loader import TextResource
from app.texts.phrase_lexicon import ServiceHints
from app.ui import messages_ru as msg

TITLE_DESCRIPTION_RESOURCE: Final[str] = "merge_prompt_title_description.txt"
STRUCTURAL_RULES_RESOURCE: Final[str] = "merge_prompt_structural_rules.txt"
NO_DESCRIPTION_RESOURCE: Final[str] = "merge_prompt_no_description.txt"
SPEAKER_ANCHOR_RESOURCE: Final[str] = "merge_prompt_speaker_anchor.txt"
CONTRACTS_RESOURCE: Final[str] = "merge_prompt_contracts.json"
LINK_POLICY_RESOURCE: Final[str] = "merge_policy_link.txt"
CROSS_DOMAIN_POLICY_RESOURCE: Final[str] = "merge_policy_cross_domain.txt"
RETRY_REINFORCEMENTS_RESOURCE: Final[str] = "merge_retry_reinforcements.json"
RETRY_FALLBACKS_RESOURCE: Final[str] = "merge_retry_fallback_lines.json"
JSON_VALUE_KEY: Final[str] = "value"
PLACEHOLDER_TOKEN: Final[str] = "{{{key}}}"     # «{source_count}» в тексте шаблона


class MergeContractMode(str, Enum):
    """Контракт описания по числу и сходству источников. Значения — метка контракта в логе и ключи шаблона контрактов."""

    COMPACT = "compact"
    EXPANDED = "expanded"
    NARRATIVE = "narrative"


class Placeholder(str, Enum):
    """Подстановка `{ключ}` в шаблонах контракта, строки-якоря и строк повтора."""

    SOURCE_COUNT = "source_count"
    COMPACT_BULLET_MIN = "compact_bullet_min"
    COMPACT_BULLET_MAX = "compact_bullet_max"
    COMPACT_BULLET_RANGE = "compact_bullet_range"
    EXPANDED_BULLET_MIN = "expanded_bullet_min"
    EXPANDED_BULLET_MAX = "expanded_bullet_max"
    EXPANDED_BULLET_RANGE = "expanded_bullet_range"
    SPEAKER_ANCHOR_LINE = "speaker_anchor_line"
    MIN_NAMES = "min_names"
    NAMES_JOINED = "names_joined"
    ACTUAL_BULLETS = "actual_bullets"
    REQUIRED_BULLETS = "required_bullets"
    MIN_BULLETS = "min_bullets"
    MAX_BULLETS = "max_bullets"
    OVERLOADED_COUNT = "overloaded_count"
    BULLET_NAME_LIMIT = "bullet_name_limit"
    BULLET_CHAR_LIMIT = "bullet_char_limit"
    ACTUAL_PARAGRAPHS = "actual_paragraphs"
    MAX_PARAGRAPHS = "max_paragraphs"

    @property
    def token(self) -> str:
        """Как подстановка записана в шаблоне: `{ключ}`."""
        return PLACEHOLDER_TOKEN.format(key=self.value)


@dataclass(frozen=True)
class PromptTemplate:
    """Текст шаблона с подстановками `{ключ}`."""

    text: str

    def filled(self, values: Mapping[Placeholder, object]) -> str:
        """`{ключ}` → значение по порядку ключей, затем края срезаются."""
        text: str = self.text
        for key, value in values.items():
            text = text.replace(key.token, str(value))
        return text.strip()


@dataclass(frozen=True)
class PromptResource:
    """Ресурс промта по имени: `.txt` — текст без строки-источника; `.json` — значение под ключом `value`."""

    name: str

    @property
    def text(self) -> str:
        return TextResource(self.name).body.strip()

    @property
    def value(self) -> JsonNode:
        resource: TextResource = TextResource(self.name)
        return JsonNode(value=resource.data, source=resource.path).field(JSON_VALUE_KEY)

    @property
    def lines(self) -> Mapping[str, tuple[str, ...]]:
        """Словарь «ключ → строки»: у каждого ключа непустой список строк (строки могут быть пустыми)."""
        node: JsonNode = self.value
        return MappingProxyType(
            {
                key: tuple(line.string() for line in node.field(key).items(msg.RESOURCE_PROBLEM_LINES))
                for key in node.value
            }
        )


@dataclass(frozen=True)
class MergePromptTexts:
    """Все тексты, из которых собирается промт merge и инструкция повтора.

    `contracts` и `retry_reinforcements` — шаблоны как есть (края срезаются в момент применения);
    `retry_fallbacks` — строки повтора на случай, когда в `retry_reinforcements` нет сигнала.
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
    service_hints: ServiceHints

    @classmethod
    @cache
    def load(cls) -> MergePromptTexts:
        """Тексты из ресурсов программы; читаются один раз за процесс."""
        contracts: JsonNode = PromptResource(CONTRACTS_RESOURCE).value
        return cls(
            title_description=PromptResource(TITLE_DESCRIPTION_RESOURCE).text,
            structural_rules=PromptResource(STRUCTURAL_RULES_RESOURCE).text,
            contracts=MappingProxyType({mode: contracts.field(mode.value).string() for mode in MergeContractMode}),
            retry_reinforcements=PromptResource(RETRY_REINFORCEMENTS_RESOURCE).lines,
            no_description=PromptResource(NO_DESCRIPTION_RESOURCE).text,
            link_policy=PromptResource(LINK_POLICY_RESOURCE).text,
            cross_domain_policy=PromptResource(CROSS_DOMAIN_POLICY_RESOURCE).text,
            speaker_anchor=PromptResource(SPEAKER_ANCHOR_RESOURCE).text,
            retry_fallbacks=PromptResource(RETRY_FALLBACKS_RESOURCE).lines,
            service_hints=ServiceHints.load(),
        )

    def contract_template(self, mode: MergeContractMode) -> PromptTemplate:
        return PromptTemplate(self.contracts[mode].strip())

    def reinforcement_lines(self, signal: str, values: Mapping[Placeholder, object]) -> tuple[str, ...]:
        """Строки повтора по сигналу: из шаблона, иначе запасные; пустые строки шаблона выпадают, в выбранные
        строки подставляются значения."""
        template_lines: tuple[str, ...] = tuple(
            stripped for line in self.retry_reinforcements.get(signal, ()) if (stripped := line.strip())
        )
        selected: tuple[str, ...] = template_lines or self.retry_fallbacks.get(signal, ())
        return tuple(PromptTemplate(line).filled(values) for line in selected)

    def speaker_anchor_line(self, source_count: int, min_names: int, names: tuple[str, ...]) -> str:
        """Строка-якорь спикеров; имена подставляются последними."""
        return PromptTemplate(self.speaker_anchor).filled(
            {
                Placeholder.SOURCE_COUNT: source_count,
                Placeholder.MIN_NAMES: min_names,
                Placeholder.NAMES_JOINED: msg.LIST_JOINER.join(names),
            }
        )
