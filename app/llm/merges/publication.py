"""Санация принятого merge перед публикацией: окончательные название и описание слота (CLAUDE.md §3 шаг 5).

Шаги санации (`PublicationBody.of`):
1. блоки «🌐 …:» с ссылками снимаются из текста (`OfficialLinksBlocks`);
2. санация текста (`SanitizedDescription`): хвост в конце и внутри абзацев (ссылки, хештеги, призывы), чистка ссылок,
   сдвоенные маркеры пунктов, абзац-призыв в конце тела; строки `tail_parse`, `tail_layout`, `post_llm_sanitation`;
3. официальные ссылки из источников и из текста (`AuthoritativeLinks`);
4. повторная нормализация качества тела (без названия и без числа источников);
4a. рекомендуемые материалы (`RecommendedMaterials`): до двух видео YouTube из описаний источников на языке слота,
   ближайшие к теме ответа — названию и телу после нормализации; ссылки YouTube ответа модели не публикуются
   никогда (поле `ignored_llm_youtube_urls`), и раскладка хвоста ответа их не называет;
5. сборка описания (`PublicationBody.compose`): призыв не публикуется никогда — здесь он отбрасывается и здесь же
   пишется строка `publish_cta_gate_dropped`;
6. проверка перед публикацией (`GateVerdict`): повтор абзацев или призыв в начале — блок не публикуется, слот получает
   тексты источников;
7. строка `publish_sanitation_applied=yes` — итог шагов.

Метка источника в строках лога — `primary_success`: так помечается успешный merge. Текста описания в строках лога нет.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Final

from app.core.sequence import unique_in_order
from app.core.text_format import NEWLINE, PARAGRAPH_BREAK
from app.core.web_link import WebLink
from app.llm.merges.description import MergedDescription
from app.llm.merges.links import AuthoritativeLinks, LinksBlock, TextLinks
from app.llm.merges.merge_rules import MergeRules, PublishGate
from app.llm.merges.quality import QualityNormalization, QualityRequest
from app.llm.merges.recommended import RecommendedCandidates, RecommendedMaterials
from app.observability.log_event import LogArea, LogEvent, get_logger
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.sources.video import SourceCatalog, SourceVideo
from app.texts.composer import LAYOUT_EMPTY, DescriptionParts, PublishHeadings
from app.texts.description_marks import CtaLexicon, FinalParagraph
from app.texts.official_links import OfficialLinksBlocks
from app.texts.paragraphs import collapse_spaces, has_duplicate_paragraphs, normalize_multiline_text, split_paragraphs
from app.texts.source_link import LinkedText
from app.texts.tail import EmbeddedTail, TailFragments, TrailingTail, clean_double_bullet_markers

LOGGER: logging.Logger = get_logger(LogArea.LLM)

PRIMARY_SOURCE_LABEL: Final[str] = "primary_success"      # метка успешного merge в строках санации


class SanitationEvent(str, Enum):
    """События санации в логе."""

    TAIL_PARSE = "tail_parse"
    TAIL_LAYOUT = "tail_layout"
    FINAL_CTA_KEPT = "removed_final_body_cta=no"
    FINAL_CTA_REMOVED = "removed_final_body_cta=yes"
    CTA_DROPPED = "publish_cta_gate_dropped"
    SANITIZED = "post_llm_sanitation"
    DUPLICATE = "publish_duplicate_paragraph_detected"
    OPENER_CTA = "publish_opener_cta_detected"
    APPLIED = "publish_sanitation_applied=yes"


@dataclass(frozen=True)
class SanitizedDescription:
    """Текст ответа после санации: тело, призыв, хештеги, ссылки хвоста, сколько ссылок изменено, раскладка хвоста.

    Тексты в `repr` не печатаются.
    """

    language: str
    body: str = field(repr=False)
    cta_text: str = field(default="", repr=False)
    hashtags_line: str = field(default="", repr=False)
    source_urls: tuple[str, ...] = ()
    url_change_count: int = 0
    hashtags_split_from_cta: bool = False
    tail_layout: str = LAYOUT_EMPTY
    malformed_source_urls_dropped: int = 0

    @classmethod
    def of(cls, text: str, language: str, cta: CtaLexicon) -> SanitizedDescription:
        """Санация текста и её строки лога."""
        normalized: str = normalize_multiline_text(text)
        if not normalized:
            empty: SanitizedDescription = cls(language=language, body="")
            empty.summary_event.emit(LOGGER)
            return empty
        lines: list[str] = normalized.split(NEWLINE)
        trailing: TrailingTail = TrailingTail.of(lines, cta)
        embedded: EmbeddedTail = EmbeddedTail.of(NEWLINE.join(lines[: trailing.body_end_index]).strip(), cta)
        fragments: TailFragments = embedded.fragments.followed_by(trailing.fragments)
        sanitized: SanitizedDescription = cls._assembled(language, LinkedText.of(embedded.body_text), fragments, cta)
        for event in (*sanitized.tail_events, sanitized.summary_event):
            event.emit(LOGGER)
        return sanitized

    @classmethod
    def _assembled(
        cls, language: str, linked_body: LinkedText, fragments: TailFragments, cta: CtaLexicon
    ) -> SanitizedDescription:
        """Итог санации из тела с почищенными ссылками и снятого хвоста: сдвоенные маркеры и абзац-призыв в конце
        тела уходят; ссылки, изменённые чисткой, считаются в теле, в призыве и в хвосте. Раскладка хвоста
        называет только то, что может попасть в описание: ссылки YouTube ответа не публикуются."""
        body: str = cls._without_final_cta(clean_double_bullet_markers(linked_body.text), language, cta)
        linked_cta: LinkedText = LinkedText.of(NEWLINE.join(fragments.cta_lines).strip())
        urls: tuple[str, ...] = fragments.source_urls
        parts: DescriptionParts = DescriptionParts(
            body=body,
            hashtags_line=fragments.hashtags_line,
            official_urls=tuple(url for url in urls if not WebLink.of(url).unwrapped.is_youtube),
            cta=linked_cta.text,
        )
        return cls(
            language=language,
            body=body,
            cta_text=linked_cta.text,
            hashtags_line=fragments.hashtags_line,
            source_urls=urls,
            url_change_count=fragments.url_change_count + linked_body.change_count + linked_cta.change_count,
            hashtags_split_from_cta=fragments.hashtags_split_from_cta,
            tail_layout=parts.layout,
            malformed_source_urls_dropped=fragments.malformed_urls_dropped,
        )

    @classmethod
    def _without_final_cta(cls, body: str, language: str, cta: CtaLexicon) -> str:
        """Последний абзац тела — призыв, который хвост не снял: убирается, если тело остаётся (абзацев от двух)."""
        final: FinalParagraph = cta.final_paragraph(body)
        if final is not FinalParagraph.CTA:
            kept: LogEvent = LogEvent.of(SanitationEvent.FINAL_CTA_KEPT, lang=language, source=PRIMARY_SOURCE_LABEL)
            kept.extended(reason=final).emit(LOGGER, logging.DEBUG)
            return body
        paragraphs: list[str] = split_paragraphs(body)
        removed: LogEvent = LogEvent.of(SanitationEvent.FINAL_CTA_REMOVED, lang=language, source=PRIMARY_SOURCE_LABEL)
        removed.extended(removed_chars=len(paragraphs[-1])).emit(LOGGER)
        return PARAGRAPH_BREAK.join(paragraphs[:-1])

    @property
    def cta_found(self) -> bool:
        return bool(self.cta_text)

    @property
    def hashtags_found(self) -> bool:
        return bool(self.hashtags_line)

    @property
    def tail_was_separated(self) -> bool:
        return bool(self.cta_text or self.hashtags_line or self.source_urls)

    def event(self, name: SanitationEvent) -> LogEvent:
        """Строка лога санации: язык и метка источника."""
        return LogEvent.of(name, lang=self.language, source=PRIMARY_SOURCE_LABEL)

    @property
    def tail_events(self) -> tuple[LogEvent, ...]:
        """Строки `tail_parse` и `tail_layout`."""
        parse: LogEvent = self.event(SanitationEvent.TAIL_PARSE).extended(
            cta_found=self.cta_found,
            hashtags_found=self.hashtags_found,
            hashtags_split_from_cta=self.hashtags_split_from_cta,
        )
        return parse, self.event(SanitationEvent.TAIL_LAYOUT).extended(layout=self.tail_layout)

    @property
    def summary_event(self) -> LogEvent:
        """Строка `post_llm_sanitation`."""
        return self.event(SanitationEvent.SANITIZED).extended(
            urls_normalized=self.url_change_count,
            tail_separated=self.tail_was_separated,
            tail_cta_found=self.cta_found,
            hashtags_found=self.hashtags_found,
            source_urls_found=len(self.source_urls),
            malformed_source_urls_dropped=self.malformed_source_urls_dropped,
        )


@dataclass(frozen=True)
class PublicationSlot:
    """Что нужно санации о слоте: язык блока, источники в порядке рядов, правила merge и видео запуска (данные
    и язык рекомендуемых видео)."""

    language: str
    sources: tuple[SourceVideo, ...] = field(repr=False)
    rules: MergeRules = field(repr=False)
    catalog: SourceCatalog = field(repr=False)


@dataclass(frozen=True)
class PublicationBody:
    """Описание после санации, до сборки: тело, блоки «🌐 …:», санация текста, официальные ссылки и рекомендуемые
    материалы."""

    language: str
    text: str = field(repr=False)
    blocks: OfficialLinksBlocks = field(repr=False)
    sanitized: SanitizedDescription = field(repr=False)
    links: AuthoritativeLinks = field(repr=False)
    recommended: RecommendedMaterials = field(repr=False)

    @classmethod
    def of(cls, title: str, description: str, slot: PublicationSlot) -> PublicationBody:
        """Шаги санации 1–4a; строки лога — по ходу. Тема ответа для рекомендуемых — название и тело."""
        blocks: OfficialLinksBlocks = OfficialLinksBlocks.of(description.strip())
        sanitized: SanitizedDescription = SanitizedDescription.of(blocks.cleaned_text, slot.language, slot.rules.lexicons.cta)
        text_urls: tuple[str, ...] = unique_in_order((*blocks.source_urls, *sanitized.source_urls))
        text_links: TextLinks = TextLinks(text_urls, sanitized.malformed_source_urls_dropped)
        links: AuthoritativeLinks = AuthoritativeLinks.of(
            slot.language, slot.sources, text_links, slot.rules.lexicons.link_hints
        )
        body: str = sanitized.body
        if slot.sources:
            request: QualityRequest = QualityRequest(language=slot.language)
            body = QualityNormalization.of(MergedDescription(body), request, slot.rules.lexicons).description.text
        candidates: RecommendedCandidates = RecommendedCandidates.of(
            links.description_links, slot.sources, NEWLINE.join((title, body)), slot.rules.lexicons.stop_words
        )
        recommended: RecommendedMaterials = RecommendedMaterials.select(candidates, slot.language, slot.catalog)
        return cls(slot.language, body, blocks, sanitized, links, recommended)

    @property
    def parts(self) -> DescriptionParts:
        """Части описания без призыва: тело, хештеги, рекомендуемые материалы, официальные ссылки."""
        return DescriptionParts(
            body=self.text,
            hashtags_line=self.sanitized.hashtags_line,
            recommended=self.recommended.entries,
            official_urls=self.links.urls,
        )

    def compose(self, headings: PublishHeadings) -> str:
        """Описание для публикации. Призыв не публикуется никогда: он отбрасывается здесь — строкой лога."""
        cta_text: str = self.sanitized.cta_text.strip()
        if cta_text:
            self.sanitized.event(SanitationEvent.CTA_DROPPED).extended(cta_chars=len(cta_text)).emit(LOGGER)
        return self.parts.compose(self.language, headings)

    @property
    def links_block(self) -> LinksBlock:
        if self.links.urls:
            return LinksBlock.EMITTED
        return LinksBlock.SUPPRESSED if self.blocks.empty_blocks_suppressed > 0 else LinksBlock.ABSENT

    def extend(self, event: LogEvent) -> LogEvent:
        """Поля строки `publish_sanitation_applied` о хвосте, ссылках текста, рекомендуемых и официальных ссылках."""
        links: AuthoritativeLinks = self.links
        text_youtube: int = links.text.youtube_count
        tail: LogEvent = event.extended(
            cta_found=self.sanitized.cta_found,
            hashtags_found=self.sanitized.hashtags_found,
            hashtags_split_from_cta=self.sanitized.hashtags_split_from_cta,
            tail_layout=self.parts.layout,
            recommended_materials_text_candidates_ignored=text_youtube,
        )
        return self.recommended.extend(tail).extended(
            official_links_heading_found=self.blocks.heading_found,
            official_links_text_links=len(links.text.urls) - text_youtube,
            official_links_source_links=links.emitted_source_video_urls,
            official_links_final_count=len(links.urls),
            official_links_block=self.links_block,
            official_links_dedup_applied=links.duplicate_urls_removed > 0,
            official_links_non_youtube_only=True,
            empty_official_links_suppressed=self.blocks.empty_blocks_suppressed,
            ignored_llm_youtube_urls=links.text.youtube_count,
        )


@dataclass(frozen=True)
class GateVerdict:
    """Проверка описания перед публикацией: повтор абзацев, призыв или негодный тезис в начале."""

    has_duplicate: bool
    has_opener_cta: bool

    @classmethod
    def of(cls, description: str, gate: PublishGate) -> GateVerdict:
        return cls(has_duplicate=has_duplicate_paragraphs(description), has_opener_cta=gate.has_opener_cta(description))

    @property
    def is_blocked(self) -> bool:
        """Повтор абзацев или призыв в начале: блок не публикуется."""
        return self.has_duplicate or self.has_opener_cta

    def extend(self, event: LogEvent) -> LogEvent:
        """Поля строки о блоке, не прошедшем проверку: что нашла проверка."""
        return event.extended(
            has_publish_stage_duplicate=self.has_duplicate, has_publish_stage_opener_cta=self.has_opener_cta
        )

    @property
    def found(self) -> tuple[SanitationEvent, ...]:
        """События найденного: повтор абзацев, затем призыв в начале."""
        pairs: tuple[tuple[bool, SanitationEvent], ...] = (
            (self.has_duplicate, SanitationEvent.DUPLICATE),
            (self.has_opener_cta, SanitationEvent.OPENER_CTA),
        )
        return tuple(event for is_found, event in pairs if is_found)


@dataclass(frozen=True)
class MergePublication:
    """Название и описание принятого merge после санации, сама санация, итог проверки и раскладка описания."""

    title: str = field(repr=False)
    description: str = field(repr=False)
    body: PublicationBody = field(repr=False)
    verdict: GateVerdict
    layout: str

    @classmethod
    def of(cls, title: str, description: str, slot: PublicationSlot) -> MergePublication:
        """Санация, сборка и проверка перед публикацией; строки лога — по ходу, итог — в конце."""
        body: PublicationBody = PublicationBody.of(title, description, slot)
        final: str = body.compose(slot.rules.headings)
        publication: MergePublication = cls(
            title=collapse_spaces(title),
            description=final,
            body=body,
            verdict=GateVerdict.of(final, slot.rules.gate),
            layout=body.parts.layout,
        )
        publication.log()
        return publication

    @property
    def is_blocked(self) -> bool:
        return self.verdict.is_blocked

    @property
    def slot_texts(self) -> SlotTexts | None:
        """Тексты слота из модели; заблокированный блок — None (слот получает тексты источников)."""
        if self.is_blocked:
            return None
        return SlotTexts(title=self.title, description=self.description, origin=SlotTextOrigin.MERGED)

    def log(self) -> None:
        """Строки проверки (ERROR) и итог санации."""
        for name in self.verdict.found:
            found: LogEvent = self.body.sanitized.event(name).extended(description_chars=len(self.description))
            found.emit(LOGGER, logging.ERROR)
        self.event.emit(LOGGER)

    @property
    def event(self) -> LogEvent:
        """Строка `publish_sanitation_applied=yes`."""
        return self.body.extend(self.body.sanitized.event(SanitationEvent.APPLIED))
