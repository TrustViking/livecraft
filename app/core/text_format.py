"""Как livecraft пишет текст: кодировка файлов, перевод строки, абзац и пробел — по одному объявлению (CLAUDE.md §11).

Эти значения нужны всем слоям — от чтения ресурсов и файла лога до сборки описания эфира, — поэтому живут
в самом нижнем пакете: `app\\core` не импортирует ничего, а его импортирует каждый. Здесь же — шаблоны
пробелов и границы абзацев: ими пользуются и `app\\core`, и тексты описания.
"""
from __future__ import annotations

import re
from typing import Final

TEXT_ENCODING: Final[str] = "utf-8"     # кодировка всех текстовых файлов программы: конфиги, сейф, лог, пакет
NEWLINE: Final[str] = "\n"              # перевод строки: строки файла, строки абзаца
PARAGRAPH_BREAK: Final[str] = "\n\n"    # граница абзацев — пустая строка
SPACE: Final[str] = " "                 # пробел между словами и полями строки

WHITESPACE_RUN_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")         # любые пробелы подряд
REPEATED_SPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s{2,}")      # два и больше пробела подряд
# Граница абзацев: пустая строка, в том числе строка из одних пробелов.
PARAGRAPH_BREAK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\n\s*\n")
