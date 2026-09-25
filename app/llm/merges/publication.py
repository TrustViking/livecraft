"""Санация принятого merge перед публикацией: окончательные название и описание слота (CLAUDE.md §3 шаг 5).

Перенесено из restreamer, поведение как есть (§14 решение 23): `app\\publish\\post_llm_sanitation.py`
(`build_sanitized_merged_publication_payload`, `sanitize_post_llm_text`, `sanitize_post_llm_title`,
`_strip_final_body_cta_paragraph`, `_apply_publish_cta_gate`) и `app\\publish\\sanitizers\\quality_gate.py`
(`PublishQualityGate`). Порядок шагов донора:
1. блоки «🌐 …:» с ссылками снимаются из текста (`OfficialLinksBlocks`);
2. санация текста (`SanitizedDescription`): хвост в конце и внутри абзацев (ссылки, хештеги, призывы), чистка ссылок,
   сдвоенные маркеры пунктов, абзац-призыв в конце тела; строки `tail_parse`, `tail_layout`, `post_llm_sanitation`;
3. официальные ссылки из источников и из текста (`AuthoritativeLinks`), рекомендуемые видео — задача 3.14b;
4. повторная нормализация качества тела (без названия и без числа источников — как у донора);
5. призыв не публикуется никогда (`publish_cta_gate_dropped` — у донора строка пишется дважды: при санации и здесь);
6. сборка описания (`DescriptionParts`) и проверка перед публикацией (`PublishGate`): повтор абзацев или призыв
   в начале — блок не публикуется, слот получает тексты источников;
7. строка `publish_sanitation_applied=yes` с ключами донора.

Метка источника в строках лога — `primary_success`: так донор помечает успешный merge (`_PRIMARY_PUBLISH_SOURCE`).
Описание, собранное донором из санации без официальных ссылок (`PostLlmSanitizationResult.full_text`), в боевом пути
не используется — не собирается. Текста описания в строках лога нет.
"""
from __future__ import annotations

import logging
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from app.core.url_text import dedupe_nonempty, is_youtube_url, sanitize_urls_in_text
from app.llm.merges.description import MergedDescription
from app.llm.merges.hook import BadHookLexicon
from app.llm.merges.links import AuthoritativeLinks
from app.llm.merges.quality import QualityRequest
from app.observability.logging_setup import get_logger
from app.slots.texts import SlotTextOrigin, SlotTexts
from app.texts.composer import DescriptionParts
from app.texts.description_marks import ALLOWED_BULLET_MARKERS, PLAIN_BULLET_PATTERN, CtaLexicon
from app.texts.official_links import OfficialLinksBlocks
from app.texts.paragraphs import has_duplicate_paragraphs, normalize_multiline_text
from app.texts.tail import EmbeddedTail, TailFragments, TrailingTail, clean_double_bullet_markers

if TYPE_CHECKING:
    from app.llm.merges.attempt import MergeRules
    from app.sources.video import SourceVideo

LOGGER: logging.Logger = get_logger("llm")

# Метка успешного merge в строках санации (`merge_orchestrator.py::_PRIMARY_PUBLISH_SOURCE` донора).
PRIMARY_SOURCE_LABEL: Final[str] = "primary_success"
PARAGRAPH_SPLIT_PATTERN: Final[re.Pattern[str]] = re.compile(r"\n\s*\n")
WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
LINE_BREAK: Final[str] = "\n"
PARAGRAPH_JOINER: Final[str] = "\n\n"
LAYOUT_EMPTY: Final[str] = "empty"
BLOCK_EMITTED: Final[str] = "emitted"
BLOCK_SUPPRESSED: Final[str] = "suppressed"
BLOCK_ABSENT: Final[str] = "absent"
BLOCK_SKIPPED: Final[str] = "skipped"
YES: Final[str] = "yes"
NO: Final[str] = "no"


def _flag(value: bool) -> str:
    return YES if value else NO


@dataclass(frozen=True)
class SanitizedDescription:
    """Текст ответа после санации: тело, призыв, хештеги, ссылки хвоста, сколько ссылок изменено, раскладка хвоста.

    Поля — `PostLlmSanitizationResult` донора без `full_text` (в боевом пути не используется). Тексты в `repr`
    не печатаются.
    """

    body: str = field(repr=False)
    cta_text: str = field(default="", repr=False)
    hashtags_line: str = field(default="", repr=False)
    source_urls: tuple[str, ...] = ()
    url_change_count: int = 0
    hashtags_split_from_cta: bool = False
    tail_layout: str = LAYOUT_EMPTY
    malformed_source_urls_dropped: int = 0

    @classmethod
    def of(cls, text: str, language: str, source_label: str, cta: CtaLexicon) -> SanitizedDescription:
        """Санация текста (`sanitize_post_llm_text` донора) и её строки лога."""
        normalized: str = normalize_multiline_text(text)
        if not normalized:
            empty: SanitizedDescription = cls(body="")
            LOGGER.info("%s", empty.summary_line(language, source_label))
            return empty
        lines: list[str] = normalized.split(LINE_BREAK)
        trailing: TrailingTail = TrailingTail.of(lines, cta)
        embedded: EmbeddedTail = EmbeddedTail.of(LINE_BREAK.join(lines[: trailing.body_end_index]).strip(), cta)
        body, body_changes = sanitize_urls_in_text(embedded.body_text)
        body = cls._without_final_cta(clean_double_bullet_markers(body), cta, language, source_label)
        fragments: TailFragments = embedded.fragments.followed_by(trailing.fragments)
        cta_text, cta_changes = sanitize_urls_in_text(LINE_BREAK.join(fragments.cta_lines).strip())
        sanitized: SanitizedDescription = cls._assembled(body, cta_text, fragments, body_changes + cta_changes)
        for line in sanitized.tail_lines(language, source_label):
            LOGGER.info("%s", line)
        sanitized.drop_cta(language, source_label)
        LOGGER.info("%s", sanitized.summary_line(language, source_label))
        return sanitized

    @classmethod
    def _assembled(cls, body: str, cta_text: str, fragments: TailFragments, text_changes: int) -> SanitizedDescription:
        """Итог санации из тела, призыва и снятого хвоста; `text_changes` — ссылки, изменённые в теле и призыве."""
        urls: tuple[str, ...] = fragments.source_urls
        parts: DescriptionParts = DescriptionParts(
            body=body,
            hashtags_line=fragments.hashtags_line,
            recommended_urls=tuple(url for url in urls if is_youtube_url(url)),
            official_urls=tuple(url for url in urls if not is_youtube_url(url)),
            cta=cta_text,
        )
        return cls(
            body=body,
            cta_text=cta_text,
            hashtags_line=fragments.hashtags_line,
            source_urls=urls,
            url_change_count=fragments.url_change_count + text_changes,
            hashtags_split_from_cta=fragments.hashtags_split_from_cta,
            tail_layout=parts.layout,
            malformed_source_urls_dropped=fragments.malformed_urls_dropped,
        )

    @staticmethod
    def _without_final_cta(body: str, cta: CtaLexicon, language: str, source_label: str) -> str:
        """Последний абзац тела — призыв, который хвост не снял: убирается, если тело остаётся (абзацев от двух).
        Абзац-призыв узнаётся по лексикону; одна строка без маркера пункта — ещё и по подсказке в строке."""
        normalized: str = str(body or "").strip()
        if not normalized:
            LOGGER.debug("removed_final_body_cta=no lang=%s source=%s reason=empty", language, source_label)
            return body
        paragraphs: list[str] = [part.strip() for part in PARAGRAPH_SPLIT_PATTERN.split(normalized) if part.strip()]
        if len(paragraphs) < 2:
            LOGGER.debug("removed_final_body_cta=no lang=%s source=%s reason=single_paragraph", language, source_label)
            return body
        last: str = paragraphs[-1]
        last_lines: list[str] = [line.strip() for line in last.splitlines() if line.strip()]
        is_cta: bool = cta.looks_like_cta_paragraph(last)
        if not is_cta and len(last_lines) == 1 and not SanitizedDescription._is_bullet(last_lines[0]):
            is_cta = cta.looks_like_cta_line(last)
        if not is_cta:
            LOGGER.debug("removed_final_body_cta=no lang=%s source=%s reason=not_cta", language, source_label)
            return body
        LOGGER.info("removed_final_body_cta=yes lang=%s source=%s removed_chars=%d", language, source_label, len(last))
        return PARAGRAPH_JOINER.join(paragraphs[:-1])

    @staticmethod
    def _is_bullet(line: str) -> bool:
        return bool(PLAIN_BULLET_PATTERN.match(line)) or any(line.startswith(f"{marker} ") for marker in ALLOWED_BULLET_MARKERS)

    def drop_cta(self, language: str, source_label: str) -> None:
        """Призыв не публикуется никогда (`_apply_publish_cta_gate` донора): только строка лога, если он был."""
        cta_text: str = self.cta_text.strip()
        if cta_text:
            LOGGER.info("publish_cta_gate_dropped lang=%s source=%s cta_chars=%d", language, source_label, len(cta_text))

    @property
    def cta_found(self) -> bool:
        return bool(self.cta_text)

    @property
    def hashtags_found(self) -> bool:
        return bool(self.hashtags_line)

    @property
    def tail_was_separated(self) -> bool:
        return bool(self.cta_text or self.hashtags_line or self.source_urls)

    def tail_lines(self, language: str, source_label: str) -> tuple[str, str]:
        """Строки `tail_parse` и `tail_layout` с ключами донора."""
        return (
            f"tail_parse lang={language} source={source_label} cta_found={_flag(self.cta_found)} "
            f"hashtags_found={_flag(self.hashtags_found)} hashtags_split_from_cta={_flag(self.hashtags_split_from_cta)}",
            f"tail_layout lang={language} source={source_label} layout={self.tail_layout}",
        )

    def summary_line(self, language: str, source_label: str) -> str:
        """Строка `post_llm_sanitation` с ключами донора."""
        return (
            f"post_llm_sanitation lang={language} source={source_label} urls_normalized={self.url_change_count} "
            f"tail_separated={_flag(self.tail_was_separated)} tail_cta_found={_flag(self.cta_found)} "
            f"hashtags_found={_flag(self.hashtags_found)} source_urls_found={len(self.source_urls)} "
            f"malformed_source_urls_dropped={self.malformed_source_urls_dropped}"
        )


@dataclass(frozen=True)
class PublishGate:
    """Проверка описания перед публикацией: повтор абзацев; призыв или негодный тезис в первом абзаце."""

    bad_hooks: BadHookLexicon
    cta: CtaLexicon

    def has_duplicate_paragraphs(self, text: str) -> bool:
        return has_duplicate_paragraphs(text)

    def has_opener_cta(self, text: str) -> bool:
        """Первая непустая строка или весь первый абзац — негодный тезис, или первая строка начинается с призыва."""
        paragraphs: list[str] = [part.strip() for part in PARAGRAPH_SPLIT_PATTERN.split(str(text or "").strip()) if part.strip()]
        if not paragraphs:
            return False
        first_paragraph: str = paragraphs[0]
        first_line: str = next((line.strip() for line in first_paragraph.split(LINE_BREAK) if line.strip()), "")
        if not first_line:
            return False
        if self.bad_hooks.matches(first_line) or self.bad_hooks.matches(first_paragraph):
            return True
        lowered: str = first_line.lower()
        return any(
            prefix.strip().lower() and lowered.startswith(prefix.strip().lower()) for prefix in self.cta.prefixes
        )


@dataclass(frozen=True)
class MergePublication:
    """Название и описание принятого merge после санации и итог проверки перед публикацией.

    `sanitized`, `blocks`, `links`, `text_urls` — шаги санации: из них строится строка лога `publish_sanitation_applied`.
    """

    language: str
    title: str = field(repr=False)
    description: str = field(repr=False)
    has_duplicate: bool
    has_opener_cta: bool
    layout: str
    sanitized: SanitizedDescription = field(repr=False)
    blocks: OfficialLinksBlocks = field(repr=False)
    links: AuthoritativeLinks = field(repr=False)
    text_urls: tuple[str, ...] = field(repr=False)

    @classmethod
    def of(
        cls, title: str, description: str, sources: Sequence[SourceVideo], language: str, rules: MergeRules
    ) -> MergePublication:
        """Шаги `build_sanitized_merged_publication_payload` донора; строки лога — по ходу, итог — в конце."""
        cta: CtaLexicon = rules.check.quality.cta
        blocks: OfficialLinksBlocks = OfficialLinksBlocks.of(description.strip())
        sanitized: SanitizedDescription = SanitizedDescription.of(blocks.cleaned_text, language, PRIMARY_SOURCE_LABEL, cta)
        text_urls: tuple[str, ...] = dedupe_nonempty((*blocks.source_urls, *sanitized.source_urls))
        links: AuthoritativeLinks = AuthoritativeLinks.of(
            language, sources, text_urls, sanitized.malformed_source_urls_dropped
        )
        body: str = sanitized.body
        if sources:
            body = MergedDescription(body).quality_normalized(QualityRequest(language=language), rules.check.quality).description.text
        sanitized.drop_cta(language, PRIMARY_SOURCE_LABEL)
        parts: DescriptionParts = DescriptionParts(body=body, hashtags_line=sanitized.hashtags_line, official_urls=links.urls)
        final: str = parts.compose(language, rules.headings)
        gate: PublishGate = PublishGate(bad_hooks=rules.check.bad_hooks, cta=cta)
        publication: MergePublication = cls(
            language=language,
            title=WHITESPACE_RUN_PATTERN.sub(" ", title.strip()).strip(),
            description=final,
            has_duplicate=gate.has_duplicate_paragraphs(final),
            has_opener_cta=gate.has_opener_cta(final),
            layout=parts.layout,
            sanitized=sanitized,
            blocks=blocks,
            links=links,
            text_urls=text_urls,
        )
        publication.log()
        return publication

    @property
    def is_blocked(self) -> bool:
        """Повтор абзацев или призыв в начале: блок не публикуется."""
        return self.has_duplicate or self.has_opener_cta

    @property
    def slot_texts(self) -> SlotTexts | None:
        """Тексты слота из модели; заблокированный блок — None (слот получает тексты источников)."""
        if self.is_blocked:
            return None
        return SlotTexts(title=self.title, description=self.description, origin=SlotTextOrigin.MERGED)

    def log(self) -> None:
        """Строки проверки (ERROR, как у донора) и итог санации."""
        if self.has_duplicate:
            LOGGER.error(
                "publish_duplicate_paragraph_detected lang=%s source=%s description_chars=%d",
                self.language, PRIMARY_SOURCE_LABEL, len(self.description),
            )
        if self.has_opener_cta:
            LOGGER.error(
                "publish_opener_cta_detected lang=%s source=%s description_chars=%d",
                self.language, PRIMARY_SOURCE_LABEL, len(self.description),
            )
        LOGGER.info("%s", self.log_line)

    @property
    def official_links_block(self) -> str:
        if self.links.urls:
            return BLOCK_EMITTED
        return BLOCK_SUPPRESSED if self.blocks.empty_blocks_suppressed > 0 else BLOCK_ABSENT

    @property
    def log_line(self) -> str:
        """Строка `publish_sanitation_applied=yes` — ключи и порядок донора; рекомендуемых видео до 3.14b нет."""
        sanitized: SanitizedDescription = self.sanitized
        links: AuthoritativeLinks = self.links
        text_youtube: int = sum(1 for url in self.text_urls if is_youtube_url(url))
        return (
            f"publish_sanitation_applied=yes lang={self.language} source={PRIMARY_SOURCE_LABEL} "
            f"cta_found={_flag(sanitized.cta_found)} hashtags_found={_flag(sanitized.hashtags_found)} "
            f"hashtags_split_from_cta={_flag(sanitized.hashtags_split_from_cta)} tail_layout={self.layout} "
            f"recommended_materials_text_candidates_ignored={text_youtube} "
            f"raw_youtube_urls_found={links.raw_youtube_urls_found} "
            f"deduped_youtube_candidates={links.deduped_youtube_candidates} "
            f"repeated_youtube_candidates={links.repeated_youtube_candidates} recommended_materials_final_count=0 "
            f"recommended_materials_block={BLOCK_SKIPPED} "
            f"official_links_heading_found={_flag(self.blocks.heading_found)} "
            f"official_links_text_links={len(self.text_urls) - text_youtube} "
            f"official_links_source_links={links.emitted_source_video_urls} "
            f"official_links_final_count={len(links.urls)} official_links_block={self.official_links_block} "
            f"official_links_dedup_applied={_flag(links.duplicate_urls_removed > 0)} official_links_non_youtube_only=yes "
            f"empty_official_links_suppressed={self.blocks.empty_blocks_suppressed} "
            f"ignored_llm_youtube_urls={links.ignored_llm_youtube_urls}"
        )
