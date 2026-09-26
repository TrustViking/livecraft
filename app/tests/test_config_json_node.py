from __future__ import annotations

from enum import Enum
from pathlib import Path
from typing import Any

import pytest

from app.config.json_node import ConfigError, ConfigProblem, JsonNode, KeyPath, SettingProblem, UniqueKeys, json_value
from app.config.settings import ServiceTier
from app.ui import messages_ru as msg

SOURCE: Path = Path("livecraft.json")


def _node(value: Any) -> JsonNode:
    return JsonNode(value=value, source=SOURCE, path=KeyPath(("llm",)))


def _error(read: Any) -> ConfigError:
    with pytest.raises(ConfigError) as raised:
        read()
    return raised.value


# --- путь ключа


def test_the_key_path_names_fields_and_list_items() -> None:
    path: KeyPath = KeyPath().child("channels").item(1).child("languages")
    assert path.text == "channels[1].languages"
    assert KeyPath().child("form").child("fields").child("date").text == "form.fields.date"


def test_the_root_path_is_named_for_people() -> None:
    assert KeyPath().text == msg.CONFIG_ROOT_KEY


def test_the_path_within_a_list_item_drops_the_list() -> None:
    """Строке канала в окне нужно имя поля, а не путь в файле."""
    assert KeyPath(("channels", 1, "handle")).within_item.text == "handle"
    assert KeyPath(("channels",)).within_item.text == "channels"
    assert KeyPath(("channels", 1)).within_item.text == "channels[1]"


# --- ошибка по контракту (§11)


def test_the_config_error_follows_the_error_contract() -> None:
    error: ConfigError = ConfigError(SOURCE, KeyPath(("keep_days",)), msg.CONFIG_PROBLEM_BOOL)
    assert error.reason is ConfigProblem.INVALID
    assert str(error) == error.human == msg.CONFIG_ERROR.format(path=SOURCE, key="keep_days", problem=msg.CONFIG_PROBLEM_BOOL)
    assert error.log_line == f"config_error path={SOURCE} key=keep_days kind=invalid problem={msg.CONFIG_PROBLEM_BOOL}"
    assert error.key_path == "keep_days" and not error.is_file_missing


def test_a_missing_file_is_named_missing(tmp_path: Path) -> None:
    error: ConfigError = _error(lambda: JsonNode.read(tmp_path / "livecraft.json"))
    assert error.reason is ConfigProblem.FILE_MISSING and error.is_file_missing
    assert error.key_path == msg.CONFIG_ROOT_KEY and error.problem == msg.CONFIG_PROBLEM_FILE_MISSING


@pytest.mark.parametrize("text", ["", "не json", "{"])
def test_text_that_is_not_json_is_an_error_at_the_root(text: str) -> None:
    error: ConfigError = _error(lambda: JsonNode.parse(text, SOURCE))
    assert error.key_path == msg.CONFIG_ROOT_KEY and error.reason is ConfigProblem.INVALID


def test_a_file_that_is_not_text_is_an_error_at_the_root(tmp_path: Path) -> None:
    path: Path = tmp_path / "livecraft.json"
    path.write_bytes(b"\xff not json")
    assert _error(lambda: JsonNode.read(path)).key_path == msg.CONFIG_ROOT_KEY


# --- объект с полями


def test_a_mapping_has_exactly_the_listed_fields() -> None:
    node: JsonNode = _node({"model": "x", "tier": "y"})
    assert node.mapping(("model", "tier")) is node
    assert node.field("tier").path.text == "llm.tier"


@pytest.mark.parametrize(
    ("value", "key", "problem", "reason"),
    [
        ({"model": "x", "extra": 1}, "llm.extra", msg.CONFIG_PROBLEM_UNKNOWN_KEY, ConfigProblem.INVALID),
        ({}, "llm.model", msg.CONFIG_PROBLEM_MISSING_KEY, ConfigProblem.FIELD_MISSING),
        ([], "llm", msg.CONFIG_PROBLEM_NOT_MAPPING, ConfigProblem.INVALID),
        ('"строка"', "llm", msg.CONFIG_PROBLEM_NOT_MAPPING, ConfigProblem.INVALID),
    ],
)
def test_a_bad_mapping_names_the_field(value: Any, key: str, problem: str, reason: ConfigProblem) -> None:
    error: ConfigError = _error(lambda: _node(value).mapping(("model",)))
    assert (error.key_path, error.problem, error.reason) == (key, problem, reason)


def test_a_repeated_field_is_an_error_with_its_name() -> None:
    """json молча взял бы последнее значение — здесь это ошибка с именем поля."""
    node: JsonNode = JsonNode.parse('{"model": "a", "model": "b"}', SOURCE)
    error: ConfigError = _error(lambda: node.mapping(("model",)))
    assert (error.key_path, error.problem) == ("model", msg.CONFIG_PROBLEM_DUPLICATE_KEY)


# --- значения


@pytest.mark.parametrize(("value", "problem"), [("", msg.CONFIG_PROBLEM_NON_EMPTY_STRING), ("   ", msg.CONFIG_PROBLEM_NON_EMPTY_STRING), (5, msg.CONFIG_PROBLEM_NON_EMPTY_STRING)])
def test_text_is_a_non_empty_string(value: Any, problem: str) -> None:
    assert _error(lambda: _node(value).text()).problem == problem
    assert _node("gpt").text() == "gpt"


def test_a_string_may_be_empty_but_must_be_a_string() -> None:
    assert _node("").string() == ""
    assert _error(lambda: _node(None).string()).problem == msg.CONFIG_PROBLEM_STRING


def test_a_nullable_text_is_text_or_null() -> None:
    assert _node(None).nullable_text() is None and _node("Дата").nullable_text() == "Дата"
    assert _error(lambda: _node("  ").nullable_text()).problem == msg.CONFIG_PROBLEM_TEXT_OR_NULL


def test_a_text_mapping_is_code_to_text_without_repeats() -> None:
    assert _node({"uk": "Украинский"}).text_mapping() == {"uk": "Украинский"}
    for value in ({}, {"uk": ""}, {"": "x"}, {"uk": 5}, "uk"):
        assert _error(lambda: _node(value).text_mapping()).problem == msg.CONFIG_PROBLEM_TEXT_MAPPING
    repeated: JsonNode = JsonNode.parse('{"uk": "a", "uk": "b"}', SOURCE)
    assert _error(repeated.text_mapping).key_path == "uk"


@pytest.mark.parametrize("value", [-1, "60", True, 1.5])
def test_an_integer_has_a_minimum_and_is_not_bool(value: Any) -> None:
    assert _error(lambda: _node(value).integer(0)).problem == msg.CONFIG_PROBLEM_INT_MIN.format(minimum=0)


def test_a_number_may_be_fractional_and_must_be_finite() -> None:
    assert _node(2).number(0.0) == 2.0 and isinstance(_node(2).number(0.0), float)
    assert _error(lambda: _node(float("nan")).number(0.0)).problem == msg.CONFIG_PROBLEM_NUMBER_FINITE
    assert _error(lambda: _node(-1).number(0.0)).problem == msg.CONFIG_PROBLEM_NUMBER_MIN.format(minimum=0.0)
    assert _error(lambda: _node(False).number(0.0)).problem == msg.CONFIG_PROBLEM_NUMBER_MIN.format(minimum=0.0)


def test_a_boolean_is_true_or_false() -> None:
    assert _node(True).boolean() is True
    assert _error(lambda: _node(1).boolean()).problem == msg.CONFIG_PROBLEM_BOOL


def test_a_choice_names_the_allowed_values() -> None:
    assert _node("flex").choice(ServiceTier) is ServiceTier.FLEX
    error: ConfigError = _error(lambda: _node("turbo").choice(ServiceTier))
    assert error.problem == msg.CONFIG_PROBLEM_CHOICE.format(allowed="default, flex, fast, priority")


def test_items_are_a_non_empty_list_with_item_paths() -> None:
    items: tuple[JsonNode, ...] = _node(["a", "b"]).items(msg.CONFIG_PROBLEM_CHANNELS_EMPTY)
    assert [item.path.text for item in items] == ["llm[0]", "llm[1]"]
    assert _error(lambda: _node([]).items(msg.CONFIG_PROBLEM_CHANNELS_EMPTY)).problem == msg.CONFIG_PROBLEM_CHANNELS_EMPTY


def test_a_problem_of_the_object_is_raised_at_its_field() -> None:
    node: JsonNode = _node({})
    node.check(None)
    error: ConfigError = _error(lambda: node.check(SettingProblem(key="timezone", text="плохо")))
    assert (error.key_path, error.problem) == ("llm.timezone", "плохо")


# --- значение поля объекта → значение JSON


class _Sample(str, Enum):
    ONE = "one"


def test_the_json_value_of_a_field_is_plain_json() -> None:
    assert json_value(_Sample.ONE) == "one"
    assert json_value(("uk", "ru")) == ["uk", "ru"]
    assert json_value({"a": {"b": "c"}}) == {"a": {"b": "c"}}
    assert json_value(0.5) == 0.5


def test_unique_keys_remember_repeats() -> None:
    assert UniqueKeys([("a", 1), ("a", 2), ("b", 3)]).duplicates == ["a"]
