from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pytest

from app.config.files import SettingsFile, ShippedSettings
from app.config.json_node import ConfigError, ConfigProblem, SettingProblem
from app.config.settings import FormQuestion, FormSettings, LivecraftSettings, ReasoningEffort, ServiceTier, SettingKey
from app.secretsafe.field import SecretField
from app.tests.fixtures.config import settings_data, settings_error, write_json
from app.tests.fixtures.settings import with_form_url
from app.ui import messages_ru as msg

SHIPPED: LivecraftSettings = ShippedSettings().settings
KYIV: str = "Europe/Kyiv"
TOP_KEYS: tuple[str, ...] = (
    "min_lead_minutes", "keep_days", "auto_start", "set_thumbnail", "category_id", "youtube_pause_seconds",
    "image_dir_template", "timezone", "llm", "form",
)
LLM_KEYS: tuple[str, ...] = ("model", "fallback_model", "reasoning_effort", "service_tier", "timeout_sec", "max_output_tokens")
FORM_KEYS: tuple[str, ...] = ("url", "fields", "values", "date_format")
FORM_QUESTIONS: tuple[str, ...] = (
    "language", "account_name", "date", "platform", "stream_key", "stream_url", "time", "broadcast_url", "slot_id",
)


def _load(tmp_path: Path, data: Any) -> LivecraftSettings:
    return SettingsFile(write_json(tmp_path / "livecraft.json", data)).load()


# --- ключи файла — члены SettingKey; из них выводятся разделы и данные файла


def test_the_setting_keys_are_the_documented_ones_in_file_order() -> None:
    assert SettingKey.leaves() == TOP_KEYS
    assert SettingKey.leaves(SettingKey.LLM) == LLM_KEYS
    assert SettingKey.leaves(SettingKey.FORM) == FORM_KEYS
    assert FormSettings.FIELD_KEYS == FORM_QUESTIONS == tuple(question.value for question in FormQuestion)
    assert FormSettings.VALUE_KEYS == ("language", "platform")


def test_a_setting_key_is_its_path_in_the_file() -> None:
    assert (SettingKey.LLM_MODEL.leaf, SettingKey.LLM_MODEL.section) == ("model", "llm")
    assert (SettingKey.TIMEZONE.leaf, SettingKey.TIMEZONE.section) == ("timezone", "")


def test_the_settings_data_keep_the_key_order_of_the_file() -> None:
    data: dict[str, Any] = SHIPPED.to_data()
    assert tuple(data) == TOP_KEYS and tuple(data["llm"]) == LLM_KEYS and tuple(data["form"]) == FORM_KEYS
    assert tuple(data["form"]["fields"]) == FORM_QUESTIONS
    assert data == settings_data()


def test_the_shipped_settings_are_read() -> None:
    assert (SHIPPED.min_lead_minutes, SHIPPED.keep_days) == (60, 30)
    assert SHIPPED.auto_start is True and SHIPPED.set_thumbnail is True
    assert (SHIPPED.category_id, SHIPPED.youtube_pause_seconds) == ("22", 0.5)
    assert (SHIPPED.image_dir_template, SHIPPED.timezone) == ("{date}/{language}", KYIV)
    assert (SHIPPED.llm.model, SHIPPED.llm.fallback_model) == ("gpt-5.6-sol", "gpt-5.4")
    assert SHIPPED.llm.reasoning_effort is ReasoningEffort.MEDIUM and SHIPPED.llm.service_tier is ServiceTier.FLEX
    assert (SHIPPED.llm.timeout_sec, SHIPPED.llm.max_output_tokens) == (900, 8000)
    assert SHIPPED.form.date_format == "%d.%m.%Y" and SHIPPED.form.fields["time"] is None
    assert SHIPPED.form.values["platform"]["youtube"] == "You Tube"


# --- секретов в конфиге нет (§5, §7.5)


def test_the_settings_file_carries_no_vault_field() -> None:
    """Ключ OpenAI, id таблицы и диапазон живут в сейфе — в livecraft.json их нет; ссылка на форму в поставке пуста."""
    data: dict[str, Any] = settings_data()
    flat: str = str(data).lower()
    for field in SecretField:
        assert field.value not in data and field.value not in data["llm"] and field.value not in data["form"]
    for forbidden in ("api_key", "sheets_id", "sheets_range", "form_url", "spreadsheet", "docs.google.com", "sk-"):
        assert forbidden not in flat


def test_the_config_package_does_not_know_the_vault() -> None:
    """Конфиг и сейф не пересекаются: модули app\\config ничего не импортируют из app.secretsafe."""
    for module in (Path(__file__).resolve().parents[1] / "config").glob("*.py"):
        assert "secretsafe" not in module.read_text(encoding="utf-8"), module.name


# --- ни одного умолчания: нет поля — ошибка с его ключом


@pytest.mark.parametrize("key", TOP_KEYS)
def test_every_top_level_settings_field_is_required(tmp_path: Path, key: str) -> None:
    data: dict[str, Any] = settings_data()
    del data[key]
    error: ConfigError = settings_error(tmp_path, data)
    assert error.key_path == key and error.reason is ConfigProblem.FIELD_MISSING


@pytest.mark.parametrize(("section", "key"), [*(("llm", key) for key in LLM_KEYS), *(("form", key) for key in FORM_KEYS)])
def test_every_section_field_is_required(tmp_path: Path, section: str, key: str) -> None:
    data: dict[str, Any] = settings_data()
    del data[section][key]
    error: ConfigError = settings_error(tmp_path, data)
    assert error.key_path == f"{section}.{key}" and error.reason is ConfigProblem.FIELD_MISSING


@pytest.mark.parametrize(("group", "key"), [*(("fields", key) for key in FORM_QUESTIONS), ("values", "language"), ("values", "platform")])
def test_all_form_question_and_option_keys_are_required(tmp_path: Path, group: str, key: str) -> None:
    """Вопросов девять; вопроса нет в форме — ключ всё равно есть, со значением null."""
    data: dict[str, Any] = settings_data()
    del data["form"][group][key]
    error: ConfigError = settings_error(tmp_path, data)
    assert error.key_path == f"form.{group}.{key}" and error.reason is ConfigProblem.FIELD_MISSING


def test_an_unknown_key_is_an_error(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["telegram_enabled"] = True
    assert settings_error(tmp_path, data).key_path == "telegram_enabled"


def test_an_unknown_form_question_is_an_error(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["form"]["fields"]["title"] = "Название эфира"
    assert settings_error(tmp_path, data).key_path == "form.fields.title"


def test_a_duplicate_key_is_an_error(tmp_path: Path) -> None:
    """json молча взял бы последнее значение — здесь это ошибка с именем поля."""
    text: str = ShippedSettings().template.replace('"keep_days": 30,', '"keep_days": 30, "keep_days": 7,')
    path: Path = tmp_path / "livecraft.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        SettingsFile(path).load()
    assert (raised.value.key_path, raised.value.problem) == ("keep_days", msg.CONFIG_PROBLEM_DUPLICATE_KEY)


def test_a_duplicate_form_option_is_an_error(tmp_path: Path) -> None:
    text: str = ShippedSettings().template.replace('"youtube": "You Tube",', '"youtube": "You Tube", "youtube": "YouTube",')
    path: Path = tmp_path / "livecraft.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        SettingsFile(path).load()
    assert raised.value.key_path == "form.values.platform.youtube"


def test_the_error_text_names_the_file_the_key_and_the_problem(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    del data["timezone"]
    error: ConfigError = settings_error(tmp_path, data)
    assert str(error) == msg.CONFIG_ERROR.format(
        path=tmp_path / "livecraft.json", key="timezone", problem=msg.CONFIG_PROBLEM_MISSING_KEY
    )


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
    data: dict[str, Any] = settings_data()
    data[key] = value
    error: ConfigError = settings_error(tmp_path, data)
    assert error.key_path == key and error.reason is ConfigProblem.INVALID


def test_a_whole_number_pause_is_read_as_a_number(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["youtube_pause_seconds"] = 2
    assert _load(tmp_path, data).youtube_pause_seconds == 2.0


@pytest.mark.parametrize("literal", ["NaN", "Infinity", "-Infinity"])
def test_a_non_finite_pause_in_the_file_is_a_config_error(tmp_path: Path, literal: str) -> None:
    """json.loads принимает эти слова, а nan < 0 ложно: без проверки конечности пауза прошла бы минимум."""
    text: str = ShippedSettings().template.replace('"youtube_pause_seconds": 0.5', f'"youtube_pause_seconds": {literal}')
    path: Path = tmp_path / "livecraft.json"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError) as raised:
        SettingsFile(path).load()
    assert (raised.value.key_path, raised.value.problem) == ("youtube_pause_seconds", msg.CONFIG_PROBLEM_NUMBER_FINITE)


def test_a_negative_pause_still_names_the_minimum(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["youtube_pause_seconds"] = -1
    assert settings_error(tmp_path, data).problem == msg.CONFIG_PROBLEM_NUMBER_MIN.format(minimum=0.0)


# --- часовой пояс: объект настроек сам проверяет и сам отдаёт зону (§14 решение 10)


def test_the_zone_is_real_and_follows_summer_time() -> None:
    """Не заглушка UTC: зимой Киев +02:00, летом +03:00 — база зон стоит и читается."""
    zone: ZoneInfo = SHIPPED.zone
    assert zone.key == KYIV
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
    data: dict[str, Any] = settings_data()
    data["timezone"] = name
    error: ConfigError = settings_error(tmp_path, data)
    assert (error.key_path, error.problem, error.reason) == ("timezone", msg.CONFIG_PROBLEM_TIMEZONE_UNKNOWN, ConfigProblem.INVALID)


def test_another_real_zone_is_accepted(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["timezone"] = "UTC"
    assert _load(tmp_path, data).zone.key == "UTC"


def test_the_zone_hint_names_a_correct_example() -> None:
    assert KYIV in msg.CONFIG_PROBLEM_TIMEZONE_UNKNOWN


# --- шаблон папки превью


@pytest.mark.parametrize(
    ("template", "problem"),
    [
        ("{date}", msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_PLACEHOLDERS.format(absent="language")),
        ("{language}", msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_PLACEHOLDERS.format(absent="date")),
        ("image/fixed", msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_PLACEHOLDERS.format(absent="date, language")),
        ("C:/image/{date}/{language}", msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_ABSOLUTE),
        ("/image/{date}/{language}", msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_ABSOLUTE),
        ("\\\\srv\\{date}\\{language}", msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_ABSOLUTE),
        ("{date}/{language}/{channel}", msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_FORMAT),
        ("{date}/{language}/{0}", msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_FORMAT),
        ("{date}/{language}/{", msg.CONFIG_PROBLEM_IMAGE_TEMPLATE_FORMAT),
    ],
)
def test_the_preview_template_is_relative_with_date_and_language_only(tmp_path: Path, template: str, problem: str) -> None:
    """Корень задаёт paths.py (§5): абсолютный шаблон увёл бы превью мимо папки image\\."""
    data: dict[str, Any] = settings_data()
    data["image_dir_template"] = template
    error: ConfigError = settings_error(tmp_path, data)
    assert (error.key_path, error.problem) == ("image_dir_template", problem)


# --- LLM: допустимые значения держит enum


@pytest.mark.parametrize(("key", "value", "allowed"), [("reasoning_effort", "extreme", "xhigh"), ("reasoning_effort", None, "xhigh"), ("service_tier", "Flex", "priority"), ("service_tier", "", "priority")])
def test_an_unknown_llm_choice_names_the_allowed_values(tmp_path: Path, key: str, value: Any, allowed: str) -> None:
    data: dict[str, Any] = settings_data()
    data["llm"][key] = value
    error: ConfigError = settings_error(tmp_path, data)
    assert error.key_path == f"llm.{key}" and allowed in error.problem


@pytest.mark.parametrize("effort", [member.value for member in ReasoningEffort])
def test_every_documented_reasoning_effort_is_accepted(tmp_path: Path, effort: str) -> None:
    data: dict[str, Any] = settings_data()
    data["llm"]["reasoning_effort"] = effort
    assert _load(tmp_path, data).llm.reasoning_effort.value == effort


def test_the_allowed_llm_values_are_the_documented_ones() -> None:
    assert [member.value for member in ReasoningEffort] == ["none", "low", "medium", "high", "xhigh", "max"]
    assert [member.value for member in ServiceTier] == ["default", "flex", "fast", "priority"]


@pytest.mark.parametrize(("key", "value"), [("timeout_sec", 0), ("max_output_tokens", 0), ("model", ""), ("fallback_model", 5)])
def test_a_bad_llm_value_is_an_error(tmp_path: Path, key: str, value: Any) -> None:
    data: dict[str, Any] = settings_data()
    data["llm"][key] = value
    assert settings_error(tmp_path, data).key_path == f"llm.{key}"


# --- форма: контракт вопросов и вариантов (§6 инвариант 2)


def test_youtube_must_be_among_the_platform_options(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    del data["form"]["values"]["platform"]["youtube"]
    error: ConfigError = settings_error(tmp_path, data)
    assert error.key_path == "form.values.platform" and "youtube" in error.problem


@pytest.mark.parametrize("date_format", ["%d.%m", "%m.%Y", "%d.%Y", "%y-%m-%d", "день"])
def test_the_date_format_needs_day_month_and_full_year(tmp_path: Path, date_format: str) -> None:
    data: dict[str, Any] = settings_data()
    data["form"]["date_format"] = date_format
    assert settings_error(tmp_path, data).key_path == "form.date_format"


@pytest.mark.parametrize("value", ["", "   ", 5, [], {}])
def test_a_question_name_is_text_or_null(tmp_path: Path, value: Any) -> None:
    data: dict[str, Any] = settings_data()
    data["form"]["fields"]["date"] = value
    error: ConfigError = settings_error(tmp_path, data)
    assert (error.key_path, error.problem) == ("form.fields.date", msg.CONFIG_PROBLEM_TEXT_OR_NULL)


def test_a_null_question_means_the_question_is_absent(tmp_path: Path) -> None:
    data: dict[str, Any] = settings_data()
    data["form"]["fields"]["platform"] = None
    assert _load(tmp_path, data).form.fields["platform"] is None


@pytest.mark.parametrize("value", [{}, [], "uk", {"uk": ""}, {"": "Украинский"}, {"uk": 5}])
def test_option_texts_are_a_non_empty_code_to_text_object(tmp_path: Path, value: Any) -> None:
    data: dict[str, Any] = settings_data()
    data["form"]["values"]["language"] = value
    assert settings_error(tmp_path, data).key_path == "form.values.language"


# --- ссылка на форму ключей: открытая настройка form.url (§14 решение 15)

FORM_LONG: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-own-form/viewform"
FORM_SHORT: str = "https://forms.gle/AbCdEf123456"
UNPARSABLE_FORM_URLS: tuple[str, ...] = ("https://docs.google.com]/forms/x", "https://[bad")


def _data_with_form_url(url: Any) -> dict[str, Any]:
    data: dict[str, Any] = settings_data()
    data["form"]["url"] = url
    return data


def test_the_shipped_form_url_is_empty_and_not_configured() -> None:
    """Поставка без чьих-либо данных (§14 решение 16): форма не настроена, и это не ошибка файла."""
    assert SHIPPED.form.url == "" and not SHIPPED.form.is_configured
    assert SHIPPED.form.url_problem is None and SHIPPED.form.problem is None and SHIPPED.problem is None


@pytest.mark.parametrize(
    "url",
    [
        FORM_LONG,
        FORM_SHORT,
        "https://docs.google.com/forms/d/e/1FAIpQLSf-own-form/viewform?usp=sf_link",
        "HTTPS://DOCS.GOOGLE.COM/forms/d/e/1FAIpQLSf-own-form/viewform",
    ],
)
def test_a_good_form_url_is_read_as_is(tmp_path: Path, url: str) -> None:
    form: FormSettings = _load(tmp_path, _data_with_form_url(url)).form
    assert form.url == url and form.is_configured


@pytest.mark.parametrize(
    "url",
    [
        "http://docs.google.com/forms/d/e/1FAIpQLSf-own-form/viewform",    # http
        "http://forms.gle/AbCdEf123456",                                   # http
        "https://example.com/forms/d/e/1FAIpQLSf-own-form/viewform",       # чужой хост
        "https://docs.google.com.evil.example/forms/d/e/x/viewform",       # чужой хост с похожим началом
        "https://docs.google.com@evil.example/forms/d/e/x/viewform",       # чужой хост за «@»
        "https://docs.google.com:8443/forms/d/e/x/viewform",               # чужой порт
        "https://docs.google.com/spreadsheets/d/1own/edit",                # docs.google.com без /forms/
        "https://docs.google.com/",                                        # docs.google.com без пути
        "https://forms.gle/",                                              # короткий адрес без кода
        "https://docs.google.com/forms/d/e/1FAIpQLSf own/viewform",        # пробел внутри
        f" {FORM_SHORT}",                                                  # пробел по краю
        "   ",                                                             # одни пробелы — не «пусто»
        "docs.google.com/forms/d/e/1FAIpQLSf-own-form/viewform",           # без схемы
        *UNPARSABLE_FORM_URLS,                                             # urlsplit бросает ValueError
    ],
)
def test_a_bad_form_url_is_an_error_at_form_url(tmp_path: Path, url: str) -> None:
    error: ConfigError = settings_error(tmp_path, _data_with_form_url(url))
    assert (error.key_path, error.problem, error.reason) == ("form.url", msg.CONFIG_PROBLEM_FORM_URL, ConfigProblem.INVALID)


@pytest.mark.parametrize("url", UNPARSABLE_FORM_URLS)
def test_an_unparsable_form_url_is_a_problem_of_the_field_not_an_exception(url: str) -> None:
    form: FormSettings = with_form_url(SHIPPED, url).form
    expected: SettingProblem = SettingProblem(key="form.url", text=msg.CONFIG_PROBLEM_FORM_URL)
    assert (form.url_problem, form.problem) == (expected, expected)


@pytest.mark.parametrize("value", [None, 5, [], {}, True])
def test_the_form_url_must_be_a_string(tmp_path: Path, value: Any) -> None:
    error: ConfigError = settings_error(tmp_path, _data_with_form_url(value))
    assert (error.key_path, error.problem) == ("form.url", msg.CONFIG_PROBLEM_STRING)


def test_the_form_url_is_written_first_and_reads_back() -> None:
    settings: LivecraftSettings = with_form_url(SHIPPED, FORM_SHORT)
    data: dict[str, Any] = settings.to_data()
    assert list(data["form"])[0] == "url" and data["form"]["url"] == FORM_SHORT
    assert SettingsFile(Path("livecraft.json")).parse(data) == settings


def test_the_form_url_problem_is_checked_before_the_rest_of_the_form() -> None:
    form: FormSettings = with_form_url(SHIPPED, "http://forms.gle/x").form
    assert form.problem == form.url_problem
    assert form.url_problem is not None and form.url_problem.key == "form.url"


def test_the_settings_problem_starts_with_the_form() -> None:
    """Смысловые проблемы настроек — по порядку: форма, шаблон превью, часовой пояс; путь — от корня файла."""
    assert with_form_url(SHIPPED, "http://forms.gle/x").problem == SettingProblem(key="form.url", text=msg.CONFIG_PROBLEM_FORM_URL)
