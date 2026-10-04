from __future__ import annotations

from app.llm.json_text import JsonFound, JsonText, ParsedJson


def test_code_fences_are_stripped() -> None:
    assert JsonText.of('```json\n{"a": 1}\n```').text == '{"a": 1}'
    assert JsonText.of('```JSON {"a": 1} ```').text == '{"a": 1}'
    assert JsonText.of('```\n{"a": 1}\n```').text == '{"a": 1}'
    assert JsonText.of('  {"a": 1}  ').text == '{"a": 1}'
    assert JsonText.of("").text == ""


def test_objects_skip_braces_inside_strings() -> None:
    text: str = 'Вот: {"title": "a {b} \\"c}", "n": {"x": 1}} и ещё {"d": 2} хвост }'
    assert JsonText(text).objects == ('{"title": "a {b} \\"c}", "n": {"x": 1}}', '{"d": 2}')


def test_tolerant_parse_reports_how_the_object_was_found() -> None:
    assert ParsedJson.tolerant('{"a": 1}') == ParsedJson({"a": 1}, JsonFound.DIRECT)
    assert ParsedJson.tolerant('мусор {"a": 1} мусор') == ParsedJson({"a": 1}, JsonFound.CANDIDATE)
    failed: ParsedJson = ParsedJson(None, JsonFound.FAIL)
    assert ParsedJson.tolerant('{"a": 1} {"b": 2}') == failed       # два объекта — не угадываем
    assert ParsedJson.tolerant("[1, 2]") == failed
    assert ParsedJson.tolerant('[1] {"b": 2}') == ParsedJson({"b": 2}, JsonFound.CANDIDATE)
    assert ParsedJson.tolerant('[{"b": 2}]') == failed                # весь текст разобрался, но не объект
    assert ParsedJson.tolerant("") == failed
    assert ParsedJson.tolerant("{битый") == failed
    assert ParsedJson.tolerant("мусор {битый} мусор") == failed


def test_object_is_found_in_a_fenced_answer_with_junk_around() -> None:
    answer: str = '```json\nКонечно! Вот ответ:\n{"title": "Эфир {1}", "description": "текст"}\nГотово.\n```'
    assert ParsedJson.first_object(answer) == ParsedJson({"title": "Эфир {1}", "description": "текст"}, JsonFound.CANDIDATE)


def test_first_object_wins_and_nothing_is_none() -> None:
    assert ParsedJson.first_object('{"a": 1}') == ParsedJson({"a": 1}, JsonFound.DIRECT)
    assert ParsedJson.first_object('{"a": 1} {"b": 2}').data == {"a": 1}
    assert ParsedJson.first_object('[1] {"b": 2}').data == {"b": 2}
    assert ParsedJson.first_object("просто текст") == ParsedJson(None, JsonFound.FAIL)
    assert ParsedJson.first_object("").data is None
