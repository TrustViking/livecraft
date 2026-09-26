"""Правила merge одним плоским объектом на запуск: словари, тексты промта, заголовки блоков и проверка перед публикацией.

`MergeLexicons` — все словари и подсказки merge: призывы, негодный тезис, заголовки повестки, подсказки служебных
строк и официальных ссылок, канонические служебные строки, язык служебных строк (с определителем языка),
допустимые латинские слова. Читаются один раз за процесс. `MergeRules` — они, тексты промта (`MergePromptTexts`),
заголовки блоков описания (`PublishHeadings`) и проверка перед публикацией (`PublishGate`). Кто чем пользуется,
берёт это прямо из `MergeRules`: цепочек правил внутри правил нет.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import cache

from app.llm.merges.agenda import AgendaLexicon
from app.llm.merges.description import MergedDescription
from app.llm.merges.hook import BadHookLexicon
from app.llm.merges.links import OfficialLinkHints
from app.llm.merges.opening import DescriptionOpening
from app.llm.merges.prompt_texts import MergePromptTexts
from app.llm.merges.script_mix import ScriptMixProbe
from app.llm.merges.service_lines import ServiceLanguage, ServiceLineCatalog
from app.texts.composer import PublishHeadings
from app.texts.description_marks import CtaLexicon
from app.texts.phrase_lexicon import ServiceHints


@dataclass(frozen=True)
class MergeLexicons:
    """Словари и подсказки merge."""

    cta: CtaLexicon
    bad_hooks: BadHookLexicon
    agenda: AgendaLexicon
    service_hints: ServiceHints
    link_hints: OfficialLinkHints
    catalog: ServiceLineCatalog
    service: ServiceLanguage
    script_mix: ScriptMixProbe

    @classmethod
    @cache
    def load(cls) -> MergeLexicons:
        """Словари из ресурсов программы; читаются один раз за процесс."""
        return cls(
            cta=CtaLexicon.load(),
            bad_hooks=BadHookLexicon.load(),
            agenda=AgendaLexicon.load(),
            service_hints=ServiceHints.load(),
            link_hints=OfficialLinkHints.load(),
            catalog=ServiceLineCatalog.load(),
            service=ServiceLanguage.load(),
            script_mix=ScriptMixProbe.load(),
        )


@dataclass(frozen=True)
class PublishGate:
    """Проверка описания перед публикацией: призыв или негодный тезис в первом абзаце."""

    bad_hooks: BadHookLexicon
    cta: CtaLexicon

    def has_opener_cta(self, text: str) -> bool:
        """Первая непустая строка или весь первый абзац — негодный тезис, или первая строка начинается с призыва."""
        opening: DescriptionOpening = DescriptionOpening(MergedDescription(text))
        first_line: str = opening.first_line
        if not first_line:
            return False
        if self.bad_hooks.matches(first_line) or self.bad_hooks.matches(opening.first_paragraph):
            return True
        return self.cta.starts_with_prefix(first_line)


@dataclass(frozen=True)
class MergeRules:
    """Всё, чем пользуется merge, одним объектом на запуск."""

    lexicons: MergeLexicons
    texts: MergePromptTexts
    headings: PublishHeadings
    gate: PublishGate

    @classmethod
    def load(cls) -> MergeRules:
        lexicons: MergeLexicons = MergeLexicons.load()
        return cls(
            lexicons=lexicons,
            texts=MergePromptTexts.load(),
            headings=PublishHeadings.load(),
            gate=PublishGate(bad_hooks=lexicons.bad_hooks, cta=lexicons.cta),
        )
