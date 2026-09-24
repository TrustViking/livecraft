from __future__ import annotations

from app.llm.json_text import (
    PARSE_CANDIDATE,
    PARSE_DIRECT,
    PARSE_FAIL,
    extract_json_object_candidates,
    parse_json_object,
    parse_json_tolerant,
    strip_json_code_fences,
)


def test_code_fences_are_stripped() -> None:
    assert strip_json_code_fences('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_json_code_fences('```JSON {"a": 1} ```') == '{"a": 1}'
    assert strip_json_code_fences('```\n{"a": 1}\n```') == '{"a": 1}'
    assert strip_json_code_fences('  {"a": 1}  ') == '{"a": 1}'
    assert strip_json_code_fences("") == ""


def test_candidates_skip_braces_inside_strings() -> None:
    text: str = 'Вот: {"title": "a {b} \\"c}", "n": {"x": 1}} и ещё {"d": 2} хвост }'
    assert extract_json_object_candidates(text) == ['{"title": "a {b} \\"c}", "n": {"x": 1}}', '{"d": 2}']


def test_tolerant_parse_reports_how_the_object_was_found() -> None:
    assert parse_json_tolerant('{"a": 1}') == ({"a": 1}, PARSE_DIRECT)
    assert parse_json_tolerant('мусор {"a": 1} мусор') == ({"a": 1}, PARSE_CANDIDATE)
    assert parse_json_tolerant('{"a": 1} {"b": 2}') == (None, PARSE_FAIL)       # два объекта — не угадываем
    assert parse_json_tolerant("[1, 2]") == (None, PARSE_FAIL)
    assert parse_json_tolerant("") == (None, PARSE_FAIL)
    assert parse_json_tolerant("{битый") == (None, PARSE_FAIL)


def test_object_is_found_in_a_fenced_answer_with_junk_around() -> None:
    answer: str = '```json\nКонечно! Вот ответ:\n{"title": "Эфир {1}", "description": "текст"}\nГотово.\n```'
    assert parse_json_object(answer) == {"title": "Эфир {1}", "description": "текст"}


def test_first_object_wins_and_nothing_is_none() -> None:
    assert parse_json_object('{"a": 1} {"b": 2}') == {"a": 1}
    assert parse_json_object('[1] {"b": 2}') == {"b": 2}
    assert parse_json_object("просто текст") is None
    assert parse_json_object("") is None
