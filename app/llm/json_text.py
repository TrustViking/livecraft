"""JSON из ответа модели: чистые разборы строки (CLAUDE.md §0 — свободные функции без предметных объектов).

Перенесены из restreamer как есть (`app\\llm\\merges\\merge_parser.py`: `strip_json_code_fences`,
`extract_json_object_candidates`, `parse_json_tolerant`); `parse_json_object` — правило
`llm_client._extract_structured_payload_or_none` донора: весь текст, затем каждый объект `{…}` по очереди,
затем терпимый разбор.
"""
from __future__ import annotations

import json
import re
from typing import Any, Final, cast

FENCE_OPEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\s*```(?:json)?\s*", flags=re.IGNORECASE)
FENCE_CLOSE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s*```\s*$")
FENCE_MARK: Final[str] = "```"
PARSE_DIRECT: Final[str] = "direct"          # разобран весь текст
PARSE_CANDIDATE: Final[str] = "candidate"    # разобран единственный объект {…} внутри текста
PARSE_FAIL: Final[str] = "fail"


def strip_json_code_fences(text: str) -> str:
    """Снять обёртку ```json … ``` вокруг ответа."""
    cleaned: str = str(text or "").strip()
    if cleaned.startswith(FENCE_MARK):
        cleaned = FENCE_OPEN_PATTERN.sub("", cleaned)
        cleaned = FENCE_CLOSE_PATTERN.sub("", cleaned)
    return cleaned.strip()


def extract_json_object_candidates(text: str) -> list[str]:
    """Объекты верхнего уровня `{…}` в тексте по порядку; скобки внутри строк JSON не считаются."""
    candidates: list[str] = []
    in_string: bool = False
    escaped: bool = False
    depth: int = 0
    start_index: int = -1
    for index, char in enumerate(str(text or "")):
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            if depth == 0:
                start_index = index
            depth += 1
            continue
        if char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start_index >= 0:
                candidate: str = str(text)[start_index : index + 1].strip()
                if candidate:
                    candidates.append(candidate)
                start_index = -1
    return candidates


def parse_json_tolerant(raw_text: str) -> tuple[dict[str, object] | None, str]:
    """Объект JSON и как он найден: весь текст (`direct`), единственный объект внутри (`candidate`) или `fail`."""
    text: str = strip_json_code_fences(raw_text)
    if not text:
        return (None, PARSE_FAIL)
    try:
        parsed: Any = json.loads(text)
    except ValueError:
        candidates: list[str] = extract_json_object_candidates(text)
        if len(candidates) != 1:
            return (None, PARSE_FAIL)
        try:
            parsed = json.loads(candidates[0])
        except ValueError:
            return (None, PARSE_FAIL)
        if isinstance(parsed, dict):
            return (cast(dict[str, object], parsed), PARSE_CANDIDATE)
        return (None, PARSE_FAIL)
    if isinstance(parsed, dict):
        return (cast(dict[str, object], parsed), PARSE_DIRECT)
    return (None, PARSE_FAIL)


def parse_json_object(raw_text: str) -> dict[str, Any] | None:
    """Первый объект JSON в ответе: весь текст, затем объекты `{…}` по порядку, затем терпимый разбор."""
    text: str = strip_json_code_fences(raw_text)
    if not text:
        return None
    for candidate in (text, *extract_json_object_candidates(text)):
        try:
            parsed: Any = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(parsed, dict):
            return cast(dict[str, Any], parsed)
    tolerant, _ = parse_json_tolerant(text)
    return cast(dict[str, Any], tolerant) if tolerant is not None else None
