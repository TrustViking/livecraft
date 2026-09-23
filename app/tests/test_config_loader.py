from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.config import loader as loader_module
from app.config.loader import (
    AUTH_ALL,
    CHANNEL_KEYS,
    FORM_KEYS,
    LLM_KEYS,
    SETTINGS_KEYS,
    ChannelConfig,
    ConfigError,
    ConfigProblem,
    FormSettings,
    LivecraftConfig,
    LivecraftSettings,
    Platform,
    Privacy,
    ReasoningEffort,
    ServiceTier,
    load_channels,
    load_livecraft_config,
    load_settings,
    normalize_handle,
    parse_channels,
    parse_settings,
    render_channels_file,
    render_settings_file,
    save_channels_file,
    save_settings_file,
)
from app.paths import LivecraftPaths
from app.secretsafe.value import SecretField
from app.ui import messages_ru as msg

REPO_SETTINGS: Path = Path(__file__).resolve().parents[2] / "secrets" / "livecraft.json"
REPO_CHANNELS_EXAMPLE: Path = Path(__file__).resolve().parents[2] / "app" / "examples" / "channels.example.json"


def _settings_data() -> dict[str, Any]:
    """Настройки из настоящего поставочного файла репо — а не выдуманные в тесте."""
    return json.loads(REPO_SETTINGS.read_text(encoding="utf-8"))


def _channels_data() -> dict[str, Any]:
    return json.loads(REPO_CHANNELS_EXAMPLE.read_text(encoding="utf-8"))


def _write(path: Path, data: Any) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def _settings_error(tmp_path: Path, data: Any) -> ConfigError:
    path: Path = _write(tmp_path / "livecraft.json", data)
    with pytest.raises(ConfigError) as raised:
        load_settings(path)
    return raised.value


def _channels_error(tmp_path: Path, data: Any) -> ConfigError:
    path: Path = _write(tmp_path / "channels.json", data)
    with pytest.raises(ConfigError) as raised:
        load_channels(path)
    return raised.value


def _channel(**changes: Any) -> dict[str, Any]:
    base: dict[str, Any] = copy.deepcopy(_channels_data()["channels"][0])
    base.update(changes)
    return base


# --- настоящие файлы репо читаются


def test_the_shipped_settings_file_loads(tmp_path: Path) -> None:
    settings: LivecraftSettings = load_settings(REPO_SETTINGS)
    assert settings.min_lead_minutes == 60
    assert settings.keep_days == 30
    assert settings.auto_start is True and settings.set_thumbnail is True
    assert settings.category_id == "22"
    assert settings.youtube_pause_seconds == 0.5
    assert settings.image_dir_template == "{date}/{language}"
    assert settings.timezone == "Europe/Kyiv"
    assert settings.llm.model == "gpt-5.2" and settings.llm.fallback_model == "gpt-5.2"
    assert settings.llm.reasoning_effort is ReasoningEffort.MEDIUM
    assert settings.llm.service_tier is ServiceTier.DEFAULT
    assert (settings.llm.timeout_sec, settings.llm.max_output_tokens) == (120, 6000)
    assert settings.form.date_format == "%d.%m.%Y"
    assert settings.form.fields["time"] is None
    assert settings.form.values["platform"]["youtube"] == "You Tube"


def test_the_channels_example_loads() -> None:
    channels: tuple[ChannelConfig, ...] = load_channels(REPO_CHANNELS_EXAMPLE)
    assert [channel.handle for channel in channels] == ["@kanal_ua", "@kanal_ru"]
    assert channels[1].languages == ("ru", "en")
    assert channels[0].privacy is Privacy.PUBLIC and channels[1].privacy is Privacy.UNLISTED
    assert all(channel.platform is Platform.YOUTUBE for channel in channels)


def test_both_files_load_together(tmp_path: Path) -> None:
    config: LivecraftConfig = load_livecraft_config(REPO_SETTINGS, REPO_CHANNELS_EXAMPLE)
    assert config.settings == load_settings(REPO_SETTINGS)
    assert config.channels == load_channels(REPO_CHANNELS_EXAMPLE)


def test_the_settings_template_is_the_shipped_file() -> None:
    """Шаблон в консоли — ровно то, что лежит в поставке: иначе «восстановите файл» даст другой файл."""
    assert json.loads(msg.CONFIG_SETTINGS_TEMPLATE) == _settings_data()


def test_the_channels_template_loads_with_the_same_loader(tmp_path: Path) -> None:
    """Шаблон каналов из консоли, вписанный как есть, проходит тот же загрузчик."""
    path: Path = tmp_path / "channels.json"
    path.write_text(msg.CONFIG_CHANNELS_TEMPLATE, encoding="utf-8")
    assert len(load_channels(path)) == 1


# --- секретов в конфиге нет (§5, §7.5)


def test_the_settings_file_carries_no_vault_field() -> None:
    """Ключ OpenAI, id таблицы, диапазон и URL формы живут в сейфе — в livecraft.json их нет."""
    data: dict[str, Any] = _settings_data()
    flat: str = json.dumps(data).lower()
    for field in SecretField:
        assert field.value not in data
        assert field.value not in data["llm"] and field.value not in data["form"]
    for forbidden in ("api_key", "sheets_id", "sheets_range", "form_url", "spreadsheet", "docs.google.com", "sk-"):
        assert forbidden not in flat


def test_the_settings_keys_are_exactly_the_documented_ones() -> None:
    data: dict[str, Any] = _settings_data()
    assert tuple(data) == SETTINGS_KEYS
    assert tuple(data["llm"]) == LLM_KEYS
    assert tuple(data["form"]) == FORM_KEYS
    assert tuple(data["form"]["fields"]) == FormSettings.FIELD_KEYS
    assert tuple(data["form"]["values"]) == FormSettings.VALUE_KEYS


def test_the_loader_does_not_know_the_vault() -> None:
    """Конфиг и сейф не пересекаются: загрузчик ничего не импортирует из app.secretsafe."""
    source: str = Path(loader_module.__file__).read_text(encoding="utf-8")
    assert "secretsafe" not in source


# --- ни одного умолчания: нет поля — ошибка с его ключом


@pytest.mark.parametrize("key", SETTINGS_KEYS)
def test_every_top_level_settings_field_is_required(tmp_path: Path, key: str) -> None:
    data: dict[str, Any] = _settings_data()
    del data[key]
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.key_path == key
    assert error.kind is ConfigProblem.FIELD_MISSING
    assert error.is_template_needed


@pytest.mark.parametrize("key", LLM_KEYS)
def test_every_llm_field_is_required(tmp_path: Path, key: str) -> None:
    data: dict[str, Any] = _settings_data()
    del data["llm"][key]
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.key_path == f"llm.{key}" and error.kind is ConfigProblem.FIELD_MISSING


@pytest.mark.parametrize("key", FORM_KEYS)
def test_every_form_field_is_required(tmp_path: Path, key: str) -> None:
    data: dict[str, Any] = _settings_data()
    del data["form"][key]
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.key_path == f"form.{key}" and error.kind is ConfigProblem.FIELD_MISSING


@pytest.mark.parametrize("key", FormSettings.FIELD_KEYS)
def test_all_nine_form_question_keys_are_required(tmp_path: Path, key: str) -> None:
    """Девять ключей фиксированы; вопроса нет — ключ всё равно есть, со значением null."""
    data: dict[str, Any] = _settings_data()
    del data["form"]["fields"][key]
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.key_path == f"form.fields.{key}" and error.kind is ConfigProblem.FIELD_MISSING


@pytest.mark.parametrize("key", FormSettings.VALUE_KEYS)
def test_both_form_value_groups_are_required(tmp_path: Path, key: str) -> None:
    data: dict[str, Any] = _settings_data()
    del data["form"]["values"][key]
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.key_path == f"form.values.{key}"


@pytest.mark.parametrize("key", CHANNEL_KEYS)
def test_every_channel_field_is_required(tmp_path: Path, key: str) -> None:
    channel: dict[str, Any] = _channel()
    del channel[key]
    error: ConfigError = _channels_error(tmp_path, {"channels": [channel]})
    assert error.key_path == f"channels[0].{key}" and error.kind is ConfigProblem.FIELD_MISSING


def test_a_missing_settings_file_asks_for_the_template(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as raised:
        load_settings(tmp_path / "livecraft.json")
    assert raised.value.kind is ConfigProblem.FILE_MISSING and raised.value.is_template_needed
    assert raised.value.key_path == msg.CONFIG_ROOT_KEY


def test_a_missing_channels_file_asks_for_the_template(tmp_path: Path) -> None:
    with pytest.raises(ConfigError) as raised:
        load_channels(tmp_path / "channels.json")
    assert raised.value.is_template_needed


def test_an_invalid_value_does_not_ask_for_the_template(tmp_path: Path) -> None:
    data: dict[str, Any] = _settings_data()
    data["keep_days"] = 0
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.kind is ConfigProblem.INVALID and not error.is_template_needed


# --- структура JSON


def test_a_duplicate_key_is_an_error(tmp_path: Path) -> None:
    """json молча взял бы последнее значение — здесь это ошибка с именем поля."""
    text: str = REPO_SETTINGS.read_text(encoding="utf-8").replace('"keep_days": 30,', '"keep_days": 30, "keep_days": 7,')
    path: Path = tmp_path / "livecraft.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        load_settings(path)
    assert raised.value.key_path == "keep_days"
    assert raised.value.problem == msg.CONFIG_PROBLEM_DUPLICATE_KEY


def test_a_duplicate_form_option_is_an_error(tmp_path: Path) -> None:
    text: str = REPO_SETTINGS.read_text(encoding="utf-8").replace(
        '"youtube": "You Tube",', '"youtube": "You Tube", "youtube": "YouTube",'
    )
    path: Path = tmp_path / "livecraft.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        load_settings(path)
    assert raised.value.key_path == "form.values.platform.youtube"


def test_an_unknown_key_is_an_error(tmp_path: Path) -> None:
    data: dict[str, Any] = _settings_data()
    data["telegram_enabled"] = True
    assert _settings_error(tmp_path, data).key_path == "telegram_enabled"


@pytest.mark.parametrize("text", ["", "не json", "{", "[]", '"строка"'])
def test_a_file_that_is_not_a_json_object_is_an_error(tmp_path: Path, text: str) -> None:
    path: Path = tmp_path / "livecraft.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        load_settings(path)
    assert raised.value.key_path == msg.CONFIG_ROOT_KEY


# --- значения верхнего уровня


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("min_lead_minutes", -1),
        ("min_lead_minutes", "60"),
        ("min_lead_minutes", True),
        ("keep_days", 0),
        ("keep_days", 1.5),
        ("auto_start", "true"),
        ("set_thumbnail", 1),
        ("category_id", ""),
        ("category_id", 22),
        ("youtube_pause_seconds", -0.1),
        ("youtube_pause_seconds", "0.5"),
        ("youtube_pause_seconds", False),
        ("timezone", ""),
        ("timezone", None),
    ],
)
def test_a_bad_top_level_value_is_an_error(tmp_path: Path, key: str, value: Any) -> None:
    data: dict[str, Any] = _settings_data()
    data[key] = value
    assert _settings_error(tmp_path, data).key_path == key


def test_a_whole_number_pause_is_read_as_a_number(tmp_path: Path) -> None:
    data: dict[str, Any] = _settings_data()
    data["youtube_pause_seconds"] = 2
    assert load_settings(_write(tmp_path / "livecraft.json", data)).youtube_pause_seconds == 2.0


# --- часовой пояс: объект настроек сам проверяет и сам отдаёт зону (§14 решение 10)

KYIV: str = "Europe/Kyiv"


def test_the_shipped_settings_give_the_kyiv_zone() -> None:
    zone: ZoneInfo = load_settings(REPO_SETTINGS).zone
    assert isinstance(zone, ZoneInfo)
    assert zone.key == KYIV


def test_the_zone_is_real_and_follows_summer_time() -> None:
    """Не заглушка UTC: зимой Киев +02:00, летом +03:00 — база зон стоит и читается."""
    zone: ZoneInfo = load_settings(REPO_SETTINGS).zone
    assert datetime(2027, 1, 15, 12, 0, tzinfo=zone).utcoffset() == timedelta(hours=2)
    assert datetime(2027, 7, 15, 12, 0, tzinfo=zone).utcoffset() == timedelta(hours=3)


@pytest.mark.parametrize(
    "name",
    [
        "Europe/Nowhere",       # такой зоны нет
        "europe/kyiv",          # регистр имени зоны значим
        "Europe",               # папка базы, а не зона
        "../etc/passwd",        # выход из базы
        "Europe/../Europe/Kyiv",  # не нормализованный путь
        "/Europe/Kyiv",         # абсолютный путь
        "Europe\\Kyiv",         # на Windows открывается, но в базе такого имени нет
        "Europe/Kyiv ",         # то же с хвостовым пробелом
        "Europe/Kyiv\x00",      # нулевой символ
        "__init__.py",          # файл пакета tzdata, а не зона
    ],
)
def test_an_unreadable_zone_is_a_config_error_on_timezone(tmp_path: Path, name: str) -> None:
    data: dict[str, Any] = _settings_data()
    data["timezone"] = name
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.key_path == "timezone"
    assert error.problem == msg.CONFIG_PROBLEM_TIMEZONE_UNKNOWN
    assert error.kind is ConfigProblem.INVALID


def test_another_real_zone_is_accepted(tmp_path: Path) -> None:
    data: dict[str, Any] = _settings_data()
    data["timezone"] = "UTC"
    assert load_settings(_write(tmp_path / "livecraft.json", data)).zone.key == "UTC"


def test_the_zone_hint_names_a_correct_example() -> None:
    assert KYIV in msg.CONFIG_PROBLEM_TIMEZONE_UNKNOWN


@pytest.mark.parametrize("template", ["{date}", "{language}", "image/fixed", "", "   "])
def test_the_preview_template_needs_date_and_language(tmp_path: Path, template: str) -> None:
    data: dict[str, Any] = _settings_data()
    data["image_dir_template"] = template
    assert _settings_error(tmp_path, data).key_path == "image_dir_template"


@pytest.mark.parametrize("template", ["C:/image/{date}/{language}", "/image/{date}/{language}", "\\\\srv\\{date}\\{language}"])
def test_the_preview_template_must_be_relative(tmp_path: Path, template: str) -> None:
    """Корень задаёт paths.py (§5): абсолютный шаблон увёл бы превью мимо папки image\\."""
    data: dict[str, Any] = _settings_data()
    data["image_dir_template"] = template
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.key_path == "image_dir_template"
    assert error.problem == msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_ABSOLUTE


@pytest.mark.parametrize("template", ["{date}/{language}/{channel}", "{date}/{language}/{0}", "{date}/{language}/{"])
def test_the_preview_template_knows_no_other_placeholder(tmp_path: Path, template: str) -> None:
    data: dict[str, Any] = _settings_data()
    data["image_dir_template"] = template
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.problem == msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_FORMAT


# --- LLM: допустимые значения держит enum


@pytest.mark.parametrize("value", ["extreme", "MEDIUM", "", None, 3])
def test_an_unknown_reasoning_effort_is_an_error(tmp_path: Path, value: Any) -> None:
    data: dict[str, Any] = _settings_data()
    data["llm"]["reasoning_effort"] = value
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.key_path == "llm.reasoning_effort"
    assert "xhigh" in error.problem


@pytest.mark.parametrize("value", ["turbo", "Flex", "", None])
def test_an_unknown_service_tier_is_an_error(tmp_path: Path, value: Any) -> None:
    data: dict[str, Any] = _settings_data()
    data["llm"]["service_tier"] = value
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.key_path == "llm.service_tier" and "priority" in error.problem


@pytest.mark.parametrize("effort", [member.value for member in ReasoningEffort])
def test_every_documented_reasoning_effort_is_accepted(tmp_path: Path, effort: str) -> None:
    data: dict[str, Any] = _settings_data()
    data["llm"]["reasoning_effort"] = effort
    assert load_settings(_write(tmp_path / "livecraft.json", data)).llm.reasoning_effort.value == effort


def test_the_allowed_llm_values_are_the_documented_ones() -> None:
    assert [member.value for member in ReasoningEffort] == ["none", "low", "medium", "high", "xhigh", "max"]
    assert [member.value for member in ServiceTier] == ["default", "flex", "fast", "priority"]


@pytest.mark.parametrize(("key", "value"), [("timeout_sec", 0), ("max_output_tokens", 0), ("model", ""), ("fallback_model", 5)])
def test_a_bad_llm_value_is_an_error(tmp_path: Path, key: str, value: Any) -> None:
    data: dict[str, Any] = _settings_data()
    data["llm"][key] = value
    assert _settings_error(tmp_path, data).key_path == f"llm.{key}"


# --- форма: контракт вопросов и вариантов (§6 инвариант 2)


def test_youtube_must_be_among_the_platform_options(tmp_path: Path) -> None:
    data: dict[str, Any] = _settings_data()
    del data["form"]["values"]["platform"]["youtube"]
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.key_path == "form.values.platform"
    assert "youtube" in error.problem


@pytest.mark.parametrize("date_format", ["%d.%m", "%m.%Y", "%d.%Y", "%y-%m-%d", "день"])
def test_the_date_format_needs_day_month_and_full_year(tmp_path: Path, date_format: str) -> None:
    data: dict[str, Any] = _settings_data()
    data["form"]["date_format"] = date_format
    assert _settings_error(tmp_path, data).key_path == "form.date_format"


@pytest.mark.parametrize("value", ["", "   ", 5, [], {}])
def test_a_question_name_is_text_or_null(tmp_path: Path, value: Any) -> None:
    data: dict[str, Any] = _settings_data()
    data["form"]["fields"]["date"] = value
    error: ConfigError = _settings_error(tmp_path, data)
    assert error.key_path == "form.fields.date" and error.problem == msg.CONFIG_PROBLEM_TEXT_OR_NULL


def test_a_null_question_means_the_question_is_absent(tmp_path: Path) -> None:
    data: dict[str, Any] = _settings_data()
    data["form"]["fields"]["platform"] = None
    assert load_settings(_write(tmp_path / "livecraft.json", data)).form.fields["platform"] is None


@pytest.mark.parametrize("value", [{}, [], "uk", {"uk": ""}, {"": "Украинский"}, {"uk": 5}])
def test_option_texts_are_a_non_empty_code_to_text_object(tmp_path: Path, value: Any) -> None:
    data: dict[str, Any] = _settings_data()
    data["form"]["values"]["language"] = value
    assert _settings_error(tmp_path, data).key_path == "form.values.language"


def test_an_unknown_form_question_is_an_error(tmp_path: Path) -> None:
    data: dict[str, Any] = _settings_data()
    data["form"]["fields"]["title"] = "Название эфира"
    assert _settings_error(tmp_path, data).key_path == "form.fields.title"


# --- каналы


@pytest.mark.parametrize(
    "handle",
    [
        "@ab",                    # короче 3 символов после @
        "@" + "a" * 31,           # длиннее 30
        "kanal_ua",               # без @
        "@kanal ua",              # пробел
        "@kanal/ua",              # запрещённый символ
        "@kanal?ua",
        "@kanal\tua",             # управляющий символ
    ],
)
def test_a_bad_handle_is_an_error(tmp_path: Path, handle: str) -> None:
    error: ConfigError = _channels_error(tmp_path, {"channels": [_channel(handle=handle)]})
    assert error.key_path == "channels[0].handle"


@pytest.mark.parametrize("name", ["", "   ", "x" * 101, " Канал", "Канал ", "Канал\nUA"])
def test_a_bad_account_name_is_an_error(tmp_path: Path, name: str) -> None:
    error: ConfigError = _channels_error(tmp_path, {"channels": [_channel(account_name=name)]})
    assert error.key_path == "channels[0].account_name"


@pytest.mark.parametrize("account", ["you", "you@", "@gmail.com", "you@@gmail.com", "you@gm ail.com", ""])
def test_a_bad_google_account_is_an_error(tmp_path: Path, account: str) -> None:
    error: ConfigError = _channels_error(tmp_path, {"channels": [_channel(google_account=account)]})
    assert error.key_path == "channels[0].google_account"


@pytest.mark.parametrize("languages", [[], "uk", ["UK"], [" uk"], [""], [1], ["uk", "uk"]])
def test_bad_languages_are_an_error(tmp_path: Path, languages: Any) -> None:
    error: ConfigError = _channels_error(tmp_path, {"channels": [_channel(languages=languages)]})
    assert error.key_path == "channels[0].languages"


@pytest.mark.parametrize("platform", ["facebook", "rumble", "YouTube", ""])
def test_an_unknown_platform_is_an_error(tmp_path: Path, platform: str) -> None:
    """Площадки v1 — только YouTube (§1)."""
    error: ConfigError = _channels_error(tmp_path, {"channels": [_channel(platform=platform)]})
    assert error.key_path == "channels[0].platform"


@pytest.mark.parametrize("privacy", ["private", "Public", "", None])
def test_an_unknown_privacy_is_an_error(tmp_path: Path, privacy: Any) -> None:
    error: ConfigError = _channels_error(tmp_path, {"channels": [_channel(privacy=privacy)]})
    assert error.key_path == "channels[0].privacy"


def test_a_repeated_handle_is_an_error_whatever_the_case(tmp_path: Path) -> None:
    """Ник — ключ канала; большие и маленькие буквы не различаются (§6 инвариант 5)."""
    channels: list[dict[str, Any]] = [_channel(handle="@Kanal_UA"), _channel(handle="@kanal_ua")]
    error: ConfigError = _channels_error(tmp_path, {"channels": channels})
    assert error.key_path == "channels[1].handle"


def test_an_empty_channel_list_is_an_error(tmp_path: Path) -> None:
    assert _channels_error(tmp_path, {"channels": []}).key_path == "channels"


def test_equal_account_names_are_allowed(tmp_path: Path) -> None:
    channels: list[dict[str, Any]] = [_channel(handle="@one_ch"), _channel(handle="@two_ch")]
    assert len(load_channels(_write(tmp_path / "channels.json", {"channels": channels}))) == 2


def test_the_account_name_is_stored_in_nfc(tmp_path: Path) -> None:
    decomposed: str = "Канал и\u0306"          # «й» двумя символами
    channel: ChannelConfig = load_channels(
        _write(tmp_path / "channels.json", {"channels": [_channel(account_name=decomposed)]})
    )[0]
    assert channel.account_name == "Канал й"


# --- правила объекта конфига


@pytest.fixture
def config() -> LivecraftConfig:
    return load_livecraft_config(REPO_SETTINGS, REPO_CHANNELS_EXAMPLE)


def test_served_languages_are_the_union_of_channel_languages(config: LivecraftConfig) -> None:
    assert config.served_languages == frozenset({"uk", "ru", "en"})


@pytest.mark.parametrize("handle", ["@kanal_ua", "kanal_ua", "@KANAL_UA", "Kanal_Ua"])
def test_channel_by_handle_ignores_the_at_sign_and_the_case(config: LivecraftConfig, handle: str) -> None:
    channel: ChannelConfig | None = config.channel_by_handle(handle)
    assert channel is not None and channel.handle == "@kanal_ua"


def test_an_unknown_handle_finds_no_channel(config: LivecraftConfig) -> None:
    assert config.channel_by_handle("@nobody") is None


def test_auth_targets_all_is_every_channel(config: LivecraftConfig) -> None:
    assert config.auth_targets(AUTH_ALL) == config.channels


def test_auth_targets_by_handle_is_one_channel(config: LivecraftConfig) -> None:
    targets: tuple[ChannelConfig, ...] = config.auth_targets("@Kanal_RU")
    assert [channel.handle for channel in targets] == ["@kanal_ru"]


def test_auth_targets_of_an_unknown_handle_is_empty(config: LivecraftConfig) -> None:
    assert config.auth_targets("@nobody") == ()


def test_the_channel_key_is_the_normalized_handle(config: LivecraftConfig) -> None:
    assert [channel.key for channel in config.channels] == ["kanal_ua", "kanal_ru"]
    assert normalize_handle("@Kanal_UA") == "kanal_ua"


# --- запись каналов: только через render_channels_file


def test_the_rendered_channels_file_reads_back_the_same(tmp_path: Path) -> None:
    channels: tuple[ChannelConfig, ...] = load_channels(REPO_CHANNELS_EXAMPLE)
    path: Path = tmp_path / "channels.json"
    path.write_text(render_channels_file(channels), encoding="utf-8")
    assert load_channels(path) == channels


def test_the_rendered_file_keeps_russian_letters_readable() -> None:
    text: str = render_channels_file(load_channels(REPO_CHANNELS_EXAMPLE))
    assert "Канал UA" in text and "\\u" not in text


def test_saving_moves_the_previous_file_aside(livecraft_paths: LivecraftPaths) -> None:
    """Прежний channels.json байт в байт — в channels.previous.json; новый — тем же загрузчиком (§8.2)."""
    old: bytes = REPO_CHANNELS_EXAMPLE.read_bytes()
    livecraft_paths.channels_file.write_bytes(old)
    channels: tuple[ChannelConfig, ...] = load_channels(livecraft_paths.channels_file)[:1]
    save_channels_file(livecraft_paths.channels_file, livecraft_paths.channels_previous_file, channels)
    assert livecraft_paths.channels_previous_file.read_bytes() == old
    assert load_channels(livecraft_paths.channels_file) == channels


def test_saving_the_first_channels_file_needs_no_previous_one(livecraft_paths: LivecraftPaths) -> None:
    """Настройщик на чистой установке: прежнего файла нет — и сохранять в previous нечего."""
    channels: tuple[ChannelConfig, ...] = load_channels(REPO_CHANNELS_EXAMPLE)
    save_channels_file(livecraft_paths.channels_file, livecraft_paths.channels_previous_file, channels)
    assert load_channels(livecraft_paths.channels_file) == channels
    assert not livecraft_paths.channels_previous_file.exists()


def test_the_error_text_names_the_file_the_key_and_the_problem(tmp_path: Path) -> None:
    data: dict[str, Any] = _settings_data()
    del data["timezone"]
    error: ConfigError = _settings_error(tmp_path, data)
    assert str(error) == msg.CONFIG_ERROR.format(
        path=tmp_path / "livecraft.json", key="timezone", problem=msg.CONFIG_PROBLEM_MISSING_KEY
    )


# --- запись livecraft.json и разбор уже прочитанных данных (задача 2.2)


def test_the_rendered_settings_file_is_the_shipped_file_byte_for_byte() -> None:
    """Настройщик, сохранивший поставку без правок, пишет ровно тот же файл."""
    assert render_settings_file(load_settings(REPO_SETTINGS)).encode("utf-8") == REPO_SETTINGS.read_bytes()


def test_the_saved_settings_file_reads_back_into_an_equal_object(livecraft_paths: LivecraftPaths) -> None:
    settings: LivecraftSettings = load_settings(REPO_SETTINGS)
    save_settings_file(livecraft_paths.config_file, settings)
    assert load_settings(livecraft_paths.config_file) == settings
    assert livecraft_paths.config_file.read_bytes() == REPO_SETTINGS.read_bytes()


def test_the_settings_data_keep_the_key_order_of_the_file() -> None:
    data: dict[str, Any] = load_settings(REPO_SETTINGS).to_data()
    assert tuple(data) == SETTINGS_KEYS
    assert tuple(data["llm"]) == LLM_KEYS
    assert tuple(data["form"]) == FORM_KEYS
    assert tuple(data["form"]["fields"]) == FormSettings.FIELD_KEYS
    assert data == _settings_data()


def test_the_channel_data_keep_the_key_order_of_the_file() -> None:
    channels: tuple[ChannelConfig, ...] = load_channels(REPO_CHANNELS_EXAMPLE)
    assert all(tuple(channel.to_data()) == CHANNEL_KEYS for channel in channels)
    assert [channel.to_data() for channel in channels] == _channels_data()["channels"]


def test_parsing_read_settings_data_equals_loading_the_file() -> None:
    assert parse_settings(_settings_data(), REPO_SETTINGS) == load_settings(REPO_SETTINGS)


def test_parsing_read_channels_data_equals_loading_the_file() -> None:
    assert parse_channels(_channels_data(), REPO_CHANNELS_EXAMPLE) == load_channels(REPO_CHANNELS_EXAMPLE)


def test_parsing_data_names_the_given_path_in_the_error(tmp_path: Path) -> None:
    """path разбора нужен только ошибке: она называет тот файл, который будет записан."""
    data: dict[str, Any] = _settings_data()
    data["keep_days"] = 0
    path: Path = tmp_path / "livecraft.json"
    with pytest.raises(ConfigError) as raised:
        parse_settings(data, path)
    assert raised.value.config_path == path
    assert raised.value.key_path == "keep_days"
