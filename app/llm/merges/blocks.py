"""Описание merge по блокам: тезис, вводная строка и пункты, заголовок ссылок и ссылки, призыв.

`DescriptionBlocks.of` раскладывает текст по абзацам (`_BlocksBuilder`), `render` собирает блоки обратно в текст —
этим пользуется нормализация качества (`quality.py`). Список открывает строка с маркером роли или простым маркером
(заголовок официальных ссылок — не список); продолжает его и строка с любым другим эмодзи-маркером, если её текст
не начинается призывом: маркер такой строки нормализация заменит маркером роли. Короткий призыв (`has_short_cta`) —
служебная строка:
её язык проверяется и, если он явно не тот, призыв заменяется каноническим.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from app.core.text_format import NEWLINE, PARAGRAPH_BREAK, PARAGRAPH_BREAK_PATTERN, SPACE
from app.core.web_link import PATH_SLASH, URL_LINE_PATTERN
from app.llm.merges import rules
from app.texts.description_marks import BulletLine, CtaLexicon, is_official_links_heading
from app.texts.paragraphs import collapse_spaces, nonempty_lines

URL_PATH_SLASHES: Final[int] = 3                  # «https://site.org/» — у ссылки на корень сайта слэш снимается


@dataclass(frozen=True)
class DescriptionBlocks:
    """Блоки описания. `theses_lines` — вводная строка (если есть) и пункты; `lead_in` — вводная строка."""

    hook: str
    lead_in: str
    theses_lines: tuple[str, ...]
    links_heading: str
    links_urls: tuple[str, ...]
    cta: str

    @classmethod
    def of(cls, text: str, cta: CtaLexicon) -> DescriptionBlocks:
        """Разбор текста на блоки по абзацам."""
        builder: _BlocksBuilder = _BlocksBuilder()
        paragraphs: list[str] = [part.strip() for part in PARAGRAPH_BREAK_PATTERN.split(text) if part.strip()]
        for paragraph in paragraphs:
            builder.take(paragraph, cta)
        return builder.finish(paragraphs)

    def render(self) -> str:
        """Текст из блоков: тезис, пункты, заголовок и ссылки, призыв — абзацами через пустую строку."""
        paragraphs: list[str] = []
        if self.hook:
            paragraphs.append(collapse_spaces(self.hook))
        if self.theses_lines:
            paragraphs.append(NEWLINE.join(line.strip() for line in self.theses_lines if line.strip()).strip())
        if self.links_heading:
            paragraphs.append(NEWLINE.join([self.links_heading.strip(), *self._rendered_urls()]).strip())
        if self.cta:
            paragraphs.append(collapse_spaces(self.cta))
        return PARAGRAPH_BREAK.join(paragraph for paragraph in paragraphs if paragraph).strip()

    def _rendered_urls(self) -> list[str]:
        """Ссылки без краёв; у ссылки на корень сайта конечный слэш снимается."""
        urls: list[str] = []
        for item in self.links_urls:
            url: str = item.strip()
            if not url:
                continue
            if url.endswith(PATH_SLASH) and url.count(PATH_SLASH) == URL_PATH_SLASHES:
                url = url.rstrip(PATH_SLASH)
            urls.append(url)
        return urls

    @property
    def is_single_echo_cta(self) -> bool:
        """Призыв повторяет тезис, а пунктов и заголовка ссылок нет."""
        return bool(self.hook) and self.hook == self.cta and not self.theses_lines and not self.links_heading

    @property
    def is_single_echo_thesis(self) -> bool:
        """Единственная строка пунктов повторяет тезис, а заголовка ссылок нет."""
        return (
            bool(self.hook)
            and len(self.theses_lines) == 1
            and self.theses_lines[0] == self.hook
            and not self.links_heading
        )

    @property
    def has_short_cta(self) -> bool:
        """Призыв есть и он короткий (не длиннее 140 знаков после схлопывания пробелов) — служебная строка."""
        return bool(self.cta) and len(collapse_spaces(self.cta)) <= rules.SERVICE_LINE_MAX_CHARS


class _BlocksBuilder:
    """Изменяемое состояние разбора по абзацам; наружу — только `DescriptionBlocks`."""

    def __init__(self) -> None:
        self.hook: str = ""
        self.lead_in: str = ""
        self.theses_lines: list[str] = []
        self.links_heading: str = ""
        self.links_urls: list[str] = []
        self.cta: str = ""

    def take(self, paragraph: str, cta: CtaLexicon) -> None:
        lines: list[str] = nonempty_lines(paragraph)
        if not lines:
            return
        if is_official_links_heading(lines[0]):
            self._take_links(lines)
            return
        if any(self._opens_list(line) for line in lines):
            self._take_bullets(lines, cta)
            return
        if cta.looks_like_cta_paragraph(paragraph):
            self.cta = collapse_spaces(paragraph)
            return
        if not self.hook:
            self.hook = SPACE.join(lines).strip()
        elif not self.cta:
            self.cta = collapse_spaces(paragraph)

    def _take_links(self, lines: list[str]) -> None:
        """Заголовок ссылок, за ним строки-ссылки; прочие строки после ссылок — призыв, если его ещё нет."""
        self.links_heading = lines[0]
        trailing_after_urls: list[str] = []
        for line in lines[1:]:
            if URL_LINE_PATTERN.match(line):
                self.links_urls.append(line)
            else:
                trailing_after_urls.append(line)
        if trailing_after_urls and not self.cta:
            self.cta = collapse_spaces(SPACE.join(trailing_after_urls))

    def _opens_list(self, line: str) -> bool:
        """Строка списка: маркер роли или простой маркер, но не заголовок официальных ссылок."""
        return BulletLine.of(line).is_bullet and not is_official_links_heading(line)

    def _continues_list(self, line: str, cta: CtaLexicon) -> bool:
        """Строка списка или строка с любым другим эмодзи-маркером, текст которой не начинается призывом."""
        bullet: BulletLine = BulletLine.of(line)
        if is_official_links_heading(line):
            return False
        return bullet.is_bullet or (bullet.is_marked and not cta.starts_with_prefix(bullet.content))

    def _take_bullets(self, lines: list[str], cta: CtaLexicon) -> None:
        first_bullet: int = next(index for index, line in enumerate(lines) if self._opens_list(line))
        while first_bullet > 0 and self._continues_list(lines[first_bullet - 1], cta):
            first_bullet -= 1
        bullet_end: int = first_bullet
        while bullet_end < len(lines) and self._continues_list(lines[bullet_end], cta):
            bullet_end += 1
        bullets: list[str] = lines[first_bullet:bullet_end]
        if first_bullet > 0:
            self._take_lead_in_and_bullets(lines, first_bullet, bullets)
        else:
            self.theses_lines.extend(bullets)
        trailing_lines: list[str] = lines[bullet_end:]
        if not trailing_lines:
            return
        if is_official_links_heading(trailing_lines[0]):
            self._take_links(trailing_lines)
        elif not self.cta:
            self.cta = collapse_spaces(SPACE.join(trailing_lines))

    def _take_lead_in_and_bullets(self, lines: list[str], first_bullet: int, bullets: list[str]) -> None:
        """Строка перед первым пунктом — вводная (если пунктов ещё не было); строки до неё — тезис."""
        if not self.theses_lines:
            self.lead_in = lines[first_bullet - 1]
            self.theses_lines = [self.lead_in, *bullets]
        else:
            self.theses_lines.extend(bullets)
        if not self.hook:
            self.hook = SPACE.join(lines[: first_bullet - 1]).strip()

    def finish(self, paragraphs: list[str]) -> DescriptionBlocks:
        """Пунктов не нашлось — непустые строки второго абзаца считаются пунктами, первая из них — вводной;
        тезиса нет — им становится первый абзац."""
        second_lines: list[str] = nonempty_lines(paragraphs[1]) if len(paragraphs) > 1 else []
        if not self.theses_lines and second_lines:
            self.theses_lines = second_lines
            self.lead_in = second_lines[0]
        if not self.hook and paragraphs:
            self.hook = collapse_spaces(paragraphs[0])
        return DescriptionBlocks(
            hook=self.hook,
            lead_in=self.lead_in,
            theses_lines=tuple(self.theses_lines),
            links_heading=self.links_heading,
            links_urls=tuple(self.links_urls),
            cta=self.cta,
        )
