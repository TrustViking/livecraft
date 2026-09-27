from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.config.files import ShippedSettings
from app.config.json_node import ConfigError, ConfigProblem
from app.core.text_format import NEWLINE, TEXT_ENCODING
from app.observability.log_event import LogArea, get_logger
from app.paths import LivecraftPaths
from app.run.exit_code import RunOutcome
from app.run.mode import ModeReadiness, ModeStep, Need, PartReadiness, PartState, RunMode, RunPart
from app.secretsafe.crypto import SALT_BYTES, VaultFileKey
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import LocalVaultState, VaultStore
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.setup.readiness import PlanBasis, Readiness
from app.tests.conftest import FORM_URL, REPO_CHANNELS_EXAMPLE, SHIPPED_SETTINGS_FILE
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.settings import set_form_url
from app.tests.fixtures.vault import SUPPLIED_VALUES, write_supplied_vault
from app.ui import messages_ru as msg

OWN_SHEETS_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table"
NOT_UTF8_BYTES: bytes = b"\xff\xfe\x00vault\x80\x81"
SETTINGS_TEMPLATE: str = ShippedSettings().template.rstrip(NEWLINE)
SETUP_WINDOW_NAME: str = "«Livecraft — настройка»"


def _copy_configs(paths: LivecraftPaths) -> None:
    shutil.copyfile(SHIPPED_SETTINGS_FILE, paths.config_file)
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, paths.channels_file)


def _break_setting(paths: LivecraftPaths, key: str, value: Any) -> None:
    data: dict[str, Any] = json.loads(paths.config_file.read_text(encoding=TEXT_ENCODING))
    data[key] = value
    paths.config_file.write_text(json.dumps(data, ensure_ascii=False), encoding=TEXT_ENCODING)


def _save_own_sheets_id(paths: LivecraftPaths) -> None:
    """Личный сейф пишется тем же путём, что и настройщиком: VaultStore.save_local."""
    own: Vault = Vault.empty().with_field(
        SecretField.SHEETS_ID, SecretValue(field=SecretField.SHEETS_ID, value=OWN_SHEETS_ID), VaultOrigin.OWN
    )
    VaultStore.open(paths).save_local(own)


def _configured(paths: LivecraftPaths) -> Readiness:
    """Всё настроено, и форма тоже: готовы все реализованные части."""
    set_form_url(paths, FORM_URL)
    return Readiness.check(paths)


def _gaps_text(part: PartReadiness) -> str:
    return NEWLINE.join(gap.text for gap in part.unmet)


def _mode_texts(readiness: Readiness) -> tuple[str, ...]:
    """Строки нужд и строки лога всех режимов, с нейросетью и без."""
    texts: list[str] = []
    for mode in RunMode:
        for no_llm in (False, True):
            mode_readiness: ModeReadiness = readiness.for_mode(mode, no_llm=no_llm)
            texts.extend((*mode_readiness.lines, mode_readiness.event.text))
    return tuple(texts)


def _every_text(readiness: Readiness) -> str:
    """Всё, что Readiness отдаёт наружу — людям и в лог."""
    return NEWLINE.join(
        (*readiness.summary_lines, *readiness.problems, readiness.window_line, *readiness.warnings,
         *readiness.template_lines, readiness.event.text, *_mode_texts(readiness))
    )


# --- чистая установка: файлы читаются независимо друг от друга


def test_a_clean_root_is_not_ready(livecraft_paths: LivecraftPaths) -> None:
    """Ни конфигов, ни сейфа: обе ошибки названы — сначала настройки, потом каналы; шаблонов нет (файлов нет)."""
    readiness: Readiness = Readiness.check(livecraft_paths)
    settings_error: ConfigError | None = readiness.settings.error
    assert not readiness.is_ready
    assert readiness.settings.value is None and readiness.channels.value is None
    assert settings_error is not None and settings_error.config_path == livecraft_paths.config_file
    assert readiness.channels.is_missing and readiness.channels.error is not None
    assert readiness.channels.error.reason is ConfigProblem.FILE_MISSING
    assert readiness.problems[0] == msg.CONFIG_FIX_IN_SETUP.format(error=settings_error, tab=msg.SETUP_TAB_SETTINGS)
    assert readiness.problems[1] == msg.READINESS_CHANNELS_MISSING
    assert readiness.template_lines == ()


def test_settings_are_read_without_channels(livecraft_paths: LivecraftPaths) -> None:
    """Боевой случай 24-09-2026: нет channels.json — livecraft.json всё равно прочитан."""
    shutil.copyfile(SHIPPED_SETTINGS_FILE, livecraft_paths.config_file)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.settings.value is not None and readiness.settings.error is None
    assert readiness.channels.value is None
    assert msg.READINESS_FIELD_LINE.format(
        label=msg.FORM_URL_LABEL, origin=msg.READINESS_FORM_NOT_CONFIGURED
    ) in readiness.summary_lines


def test_channels_are_read_without_settings(livecraft_paths: LivecraftPaths) -> None:
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, livecraft_paths.channels_file)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.channels.value is not None and len(readiness.channels.value.channels) == 2
    assert readiness.settings.value is None and readiness.settings.error is not None
    assert readiness.summary_lines[-1] == msg.READINESS_CHANNELS_LINE.format(count=2, languages="ru, uk")


# --- конфиги на месте, сейфа нет


def test_configs_without_a_vault_leave_only_the_vault_problem(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert not readiness.is_ready
    assert readiness.settings.error is None and readiness.channels.error is None and readiness.vault.error is None
    assert readiness.problems == (Vault.empty().admission_reason,)
    for field in SecretField.current():
        assert field.human_label in readiness.problems[0]
    assert SecretField.KEY_FORM_URL.human_label not in readiness.problems[0]      # не требуется (§14 решение 15)
    assert readiness.template_lines == ()


def test_a_broken_config_field_is_named_with_where_to_fix_it(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    _break_setting(livecraft_paths, "keep_days", 0)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.settings.error is not None and readiness.settings.error.key_path == "keep_days"
    line: str = readiness.problems[0]
    assert str(livecraft_paths.config_file) in line and "keep_days" in line and msg.SETUP_TAB_SETTINGS in line
    assert readiness.channels.value is not None                  # каналы от сломанных настроек не зависят
    assert readiness.template_lines == (SETTINGS_TEMPLATE,)      # только для лога


def test_a_broken_channels_file_is_named_with_its_tab_and_template(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    livecraft_paths.channels_file.write_text('{"channels": []}', encoding=TEXT_ENCODING)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.channels.is_broken
    assert msg.SETUP_TAB_CHANNELS in readiness.problems[0]
    assert str(livecraft_paths.channels_file) in readiness.problems[0]
    lines: tuple[str, ...] = readiness.template_lines
    assert lines[-1] == msg.CONFIG_CHANNELS_TEMPLATE
    assert len(lines) == len(msg.CONFIG_CHANNELS_FIELDS) + 1
    body: str = NEWLINE.join(lines[:-1])
    assert msg.CONFIG_LANGUAGES_RULE in body and "public, unlisted" in body and "youtube" in body


def test_a_missing_config_field_brings_the_template_for_the_log(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    data: dict[str, Any] = json.loads(livecraft_paths.config_file.read_text(encoding=TEXT_ENCODING))
    del data["timezone"]
    livecraft_paths.config_file.write_text(json.dumps(data, ensure_ascii=False), encoding=TEXT_ENCODING)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.settings.error is not None and readiness.settings.error.key_path == "timezone"
    assert readiness.template_lines == (SETTINGS_TEMPLATE,)


# --- готово


def test_a_supplied_vault_and_configs_are_ready(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.is_ready
    assert readiness.problems == () and readiness.warnings == () and readiness.template_lines == ()
    assert readiness.window_line == msg.SETUP_READY
    assert readiness.vault.load is not None and readiness.vault.load.local_state is LocalVaultState.ABSENT


def test_the_summary_names_every_field_and_its_origin(ready_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines
    assert lines[0] == msg.READINESS_SUMMARY_TITLE
    for field in SecretField.current():
        assert msg.READINESS_FIELD_LINE.format(label=field.human_label, origin=msg.VAULT_ORIGIN_SUPPLIED) in lines
    assert lines[-1] == msg.READINESS_CHANNELS_LINE.format(count=2, languages="ru, uk")


def test_the_summary_of_an_empty_vault_says_no_for_every_field(livecraft_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(livecraft_paths).summary_lines
    for field in SecretField.current():
        assert msg.READINESS_FIELD_LINE.format(label=field.human_label, origin=msg.NONE_TEXT) in lines
    assert lines[-1] == msg.READINESS_CHANNELS_ABSENT


def test_an_own_value_shows_as_own_in_the_summary(ready_paths: LivecraftPaths) -> None:
    """Личный сейф перекрывает поставочный — сводка говорит «своё» у перекрытого поля (§7.3)."""
    _save_own_sheets_id(ready_paths)
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.is_ready
    assert msg.READINESS_FIELD_LINE.format(
        label=SecretField.SHEETS_ID.human_label, origin=msg.VAULT_ORIGIN_OWN
    ) in readiness.summary_lines
    assert msg.READINESS_FIELD_LINE.format(
        label=SecretField.OPENAI_API_KEY.human_label, origin=msg.VAULT_ORIGIN_SUPPLIED
    ) in readiness.summary_lines
    assert readiness.vault.load is not None and readiness.vault.load.local_state is LocalVaultState.READ


# --- личный сейф не читается: громко, но работа идёт


def test_an_unreadable_own_vault_warns_and_runs_on_supplied_values(ready_paths: LivecraftPaths) -> None:
    """§16: молчаливый откат недопустим — получатель незаметно работал бы на чужом ключе и таблице.

    Предупреждение называет поля сейфа нынешними названиями — без формы ключей: её в сейфе больше нет.
    """
    _save_own_sheets_id(ready_paths)
    data: dict[str, Any] = json.loads(ready_paths.vault_local_file.read_text(encoding=TEXT_ENCODING))
    key: str = VaultFileKey.WRAPPED_KEY.value
    wrapped: bytes = base64.b64decode(data[key], validate=True)
    data[key] = base64.b64encode(wrapped[:-1] + bytes([wrapped[-1] ^ 0xFF])).decode("ascii")
    ready_paths.vault_local_file.write_text(json.dumps(data), encoding=TEXT_ENCODING)
    readiness: Readiness = Readiness.check(ready_paths)
    fields: str = msg.LIST_JOINER.join(field.human_label for field in SecretField.current())
    assert readiness.warnings == (msg.VAULT_LOCAL_UNREADABLE.format(fields=fields),)
    assert SecretField.KEY_FORM_URL.human_label not in readiness.warnings[0]
    assert readiness.is_ready                                  # запуск идёт — на поставочных значениях
    vault: Vault | None = readiness.vault.vault
    assert vault is not None and all(vault.origin_of(field) is VaultOrigin.SUPPLIED for field in SecretField.current())
    assert "local=unreadable" in readiness.event.text


def test_no_warning_without_an_own_vault(ready_paths: LivecraftPaths) -> None:
    assert Readiness.check(ready_paths).warnings == ()


# --- файл сейфа чужого формата


def test_a_vault_file_of_an_unknown_format_is_named(ready_paths: LivecraftPaths) -> None:
    """§7.3: неизвестная версия формата — ошибка с именем файла и код 2, а не тихое игнорирование."""
    ready_paths.vault_local_file.write_text(
        json.dumps({
            VaultFileKey.VERSION.value: 7,
            VaultFileKey.SALT.value: base64.b64encode(bytes(SALT_BYTES)).decode("ascii"),
            VaultFileKey.FIELDS.value: {},
        }),
        encoding=TEXT_ENCODING,
    )
    readiness: Readiness = Readiness.check(ready_paths)
    error = readiness.vault.error
    assert error is not None and not readiness.is_ready
    assert any(ready_paths.vault_local_file.name in line for line in readiness.problems)
    assert readiness.problems[-1] == error.human and msg.VAULT_FILE_ADVICE_LOCAL in readiness.problems[-1]
    assert error.detail not in readiness.problems[-1]
    assert "vault=broken" in readiness.event.text


def _assert_broken_local_file(paths: LivecraftPaths, readiness: Readiness) -> None:
    """Повреждённый личный файл — не «чужой сейф»: отказ с именем файла, а не предупреждение и поставка."""
    assert not readiness.is_ready
    assert readiness.vault.error is not None and readiness.vault.vault is None
    assert any(paths.vault_local_file.name in line for line in readiness.problems)
    assert readiness.problems[-1] == readiness.vault.error.human
    assert readiness.warnings == ()


def test_a_local_vault_file_that_is_not_utf8_stops_the_run(ready_paths: LivecraftPaths) -> None:
    ready_paths.vault_local_file.write_bytes(NOT_UTF8_BYTES)
    _assert_broken_local_file(ready_paths, Readiness.check(ready_paths))


def test_a_local_vault_file_that_does_not_open_stops_the_run(ready_paths: LivecraftPaths) -> None:
    ready_paths.vault_local_file.mkdir()
    _assert_broken_local_file(ready_paths, Readiness.check(ready_paths))


def test_the_config_problems_come_before_the_vault_problem(livecraft_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert len(readiness.problems) == 3
    assert readiness.problems[2] == Vault.empty().admission_reason


# --- ни значений, ни масок ни в одном выводе (§7.4)


@pytest.mark.parametrize("own", [False, True])
def test_no_value_and_no_mask_leaves_readiness(ready_paths: LivecraftPaths, own: bool) -> None:
    """Оператору нужно знать, откуда значение, а не само значение — и даже не его маску."""
    if own:
        _save_own_sheets_id(ready_paths)
    readiness: Readiness = Readiness.check(ready_paths)
    vault: Vault | None = readiness.vault.vault
    assert vault is not None
    text: str = _every_text(readiness)
    for secret in vault.secrets():
        assert secret.reveal() not in text
        assert secret.masked not in text
    for value in (*SUPPLIED_VALUES.values(), OWN_SHEETS_ID):     # и перекрытое поставочное тоже
        assert value not in text


def test_no_value_leaves_readiness_when_things_are_broken(ready_paths: LivecraftPaths) -> None:
    """И при поломке: удалили одно поле поставки — причина и сводка говорят о поле, не о значениях."""
    write_supplied_vault(ready_paths, {k: v for k, v in SUPPLIED_VALUES.items() if k is not SecretField.SHEETS_RANGE})
    readiness: Readiness = Readiness.check(ready_paths)
    assert not readiness.is_ready
    text: str = _every_text(readiness)
    for value in SUPPLIED_VALUES.values():
        assert value not in text
    assert SecretField.SHEETS_RANGE.human_label in readiness.problems[0]


def test_a_vault_without_the_form_url_is_ready(ready_paths: LivecraftPaths) -> None:
    """Ссылки на форму в сейфе нет, form.url пуст — программа готова: форма — открытая настройка (§14 решение 15)."""
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.vault.vault is not None and readiness.vault.vault.get(SecretField.KEY_FORM_URL) is None
    assert readiness.settings.value is not None and not readiness.settings.value.form.is_configured
    assert readiness.is_ready


def test_the_log_line_carries_labels_and_state_only(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.vault.vault is not None
    line: str = readiness.event.text
    assert line.startswith("readiness settings=ok channels=2 local=absent vault=")
    assert readiness.vault.vault.log_line in line
    assert line.endswith(" ready=yes")
    assert line.isascii()


def test_check_prints_nothing(livecraft_paths: LivecraftPaths, capsys: pytest.CaptureFixture[str]) -> None:
    """Печатает только main: Readiness лишь читает и отвечает на вопросы о себе."""
    Readiness.check(livecraft_paths)
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_the_readiness_object_is_frozen(ready_paths: LivecraftPaths) -> None:
    with pytest.raises(Exception):
        Readiness.check(ready_paths).has_client_secret = False     # type: ignore[misc]


# --- форма ключей в сводке: по livecraft.json, а не по сейфу (§14 решение 15)

LEGACY_FORM_LABEL: str = SecretField.KEY_FORM_URL.human_label


def _write_form_url(paths: LivecraftPaths, url: str) -> None:
    """Ссылка в файле как есть, в обход разбора: так в файле оказывается и негодная ссылка."""
    data: dict[str, Any] = json.loads(paths.config_file.read_text(encoding=TEXT_ENCODING))
    data["form"]["url"] = url
    paths.config_file.write_text(json.dumps(data, ensure_ascii=False), encoding=TEXT_ENCODING)


def test_the_summary_says_the_form_is_not_configured_on_the_shipped_settings(ready_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines
    assert msg.READINESS_FIELD_LINE.format(label=msg.FORM_URL_LABEL, origin=msg.READINESS_FORM_NOT_CONFIGURED) in lines
    assert lines[-1] == msg.READINESS_CHANNELS_LINE.format(count=2, languages="ru, uk")


@pytest.mark.parametrize("url", ["https://docs.google.com]/forms/x", "https://[bad"])
def test_an_unparsable_form_url_is_a_settings_problem_not_a_crash(ready_paths: LivecraftPaths, url: str) -> None:
    _write_form_url(ready_paths, url)
    readiness: Readiness = Readiness.check(ready_paths)
    error: ConfigError | None = readiness.settings.error
    assert readiness.settings.value is None and error is not None
    assert (error.key_path, error.problem) == ("form.url", msg.CONFIG_PROBLEM_FORM_URL)


def test_the_summary_says_the_form_is_configured_and_hides_the_link(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = _configured(ready_paths)
    lines: tuple[str, ...] = readiness.summary_lines
    assert msg.READINESS_FIELD_LINE.format(label=msg.FORM_URL_LABEL, origin=msg.READINESS_FORM_CONFIGURED) in lines
    assert FORM_URL not in NEWLINE.join(lines) + readiness.event.text


@pytest.mark.parametrize("in_vault", [False, True])
def test_the_legacy_vault_field_has_no_summary_line(ready_paths: LivecraftPaths, in_vault: bool) -> None:
    """Устаревшее поле сейфа не показывается ни «нет», ни «поставка»: о форме — одна строка по настройкам."""
    if in_vault:
        write_supplied_vault(ready_paths, {**SUPPLIED_VALUES, SecretField.KEY_FORM_URL: FORM_URL})
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines
    form_lines: list[str] = [line for line in lines if LEGACY_FORM_LABEL in line]
    assert form_lines == [
        msg.READINESS_FIELD_LINE.format(label=msg.FORM_URL_LABEL, origin=msg.READINESS_FORM_NOT_CONFIGURED)
    ]


def test_without_readable_settings_there_is_no_form_line(livecraft_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(livecraft_paths).summary_lines
    assert not any(msg.FORM_URL_LABEL in line for line in lines)


# --- нужды частей: одна строка «что задать и где» на нужду (Readiness.gap)


def test_a_fully_configured_root_has_every_built_part_ready(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = _configured(ready_paths)
    for need in Need:
        assert readiness.gap(need) is None
    for part in RunPart:
        state: PartReadiness = readiness.part(part)
        assert state.state is (PartState.READY if part.is_built else PartState.NOT_BUILT)
        assert state.unmet == ()


def test_without_channels_the_table_and_package_are_ready(ready_paths: LivecraftPaths) -> None:
    """Эфиров в этой версии нет: нехватка каналов — не «не готово», а та же строка «появится позже»."""
    set_form_url(ready_paths, FORM_URL)
    ready_paths.channels_file.unlink()
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.part(RunPart.PLAN).state is PartState.READY
    assert readiness.part(RunPart.PACKAGE).state is PartState.READY
    assert readiness.part(RunPart.BROADCAST).state is PartState.NOT_BUILT
    assert readiness.gap(Need.CHANNELS) == msg.READINESS_GAP_IN_SETUP.format(
        what=msg.READINESS_GAP_CHANNELS_MISSING, tab=msg.SETUP_TAB_CHANNELS
    )
    mode: ModeReadiness = readiness.for_mode(RunMode.ALL, no_llm=True)
    assert all(msg.READINESS_GAP_CHANNELS_MISSING not in line for line in mode.lines)


def test_the_all_mode_without_the_openai_key_blocks_only_the_merge(ready_paths: LivecraftPaths) -> None:
    """Без ключа OpenAI режим «всё» без --no-llm: нейросеть не готова — одна строка «Не готово», исход — ошибка,
    таблица прогоняется без merge; с --no-llm нейросети в режиме нет — ни строки, ни ошибки."""
    set_form_url(ready_paths, FORM_URL)
    write_supplied_vault(ready_paths, {k: v for k, v in SUPPLIED_VALUES.items() if k is not SecretField.OPENAI_API_KEY})
    readiness: Readiness = Readiness.check(ready_paths)
    gap: str | None = readiness.gap(Need.OPENAI_VAULT)
    assert gap is not None and readiness.part(RunPart.MERGE).state is PartState.BLOCKED
    with_llm: ModeReadiness = readiness.for_mode(RunMode.ALL, no_llm=False)
    assert [part.part for part in with_llm.in_state(PartState.BLOCKED)] == [RunPart.MERGE]
    assert with_llm.lines[0] == msg.RUN_NEED_BLOCKED.format(parts=RunPart.MERGE.human_label, gap=gap)
    assert with_llm.step is ModeStep.RUN_PLAN and with_llm.outcome is RunOutcome.FAILED
    basis: PlanBasis | None = readiness.plan_basis(with_llm)
    assert basis is not None and not basis.with_merge
    without_llm: ModeReadiness = readiness.for_mode(RunMode.ALL, no_llm=True)
    assert without_llm.in_state(PartState.BLOCKED) == () and without_llm.outcome is RunOutcome.DONE
    assert all(RunPart.MERGE.human_label not in line for line in without_llm.lines)


def test_without_the_form_the_package_waits(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(ready_paths)       # поставочная ссылка на форму пуста
    state: PartReadiness = readiness.part(RunPart.PACKAGE)
    assert state.state is PartState.BLOCKED and [gap.need for gap in state.unmet] == [Need.FORM]
    assert _gaps_text(state) == msg.READINESS_GAP_IN_SETUP.format(what=msg.READINESS_GAP_FORM, tab=msg.SETUP_TAB_SETTINGS)
    assert readiness.part(RunPart.PLAN).state is PartState.READY


def test_without_client_secret_the_table_waits(ready_paths: LivecraftPaths) -> None:
    ready_paths.client_secret_file.unlink()
    readiness: Readiness = _configured(ready_paths)
    plan: PartReadiness = readiness.part(RunPart.PLAN)
    assert plan.state is PartState.BLOCKED
    assert _gaps_text(plan) == msg.READINESS_GAP_CLIENT_SECRET.format(path=ready_paths.client_secret_file)
    assert readiness.for_mode(RunMode.BROADCAST, no_llm=False).is_nothing_ready     # основа режима А не готова


def test_without_the_table_fields_one_line_names_both(ready_paths: LivecraftPaths) -> None:
    """Нужда «сейф таблицы» — одна строка, в ней оба поля, которых нет."""
    write_supplied_vault(ready_paths, {SecretField.OPENAI_API_KEY: SUPPLIED_VALUES[SecretField.OPENAI_API_KEY]})
    plan: PartReadiness = _configured(ready_paths).part(RunPart.PLAN)
    labels: str = msg.LIST_JOINER.join((SecretField.SHEETS_ID.human_label, SecretField.SHEETS_RANGE.human_label))
    assert plan.state is PartState.BLOCKED and len(plan.unmet) == 1
    assert _gaps_text(plan) == msg.READINESS_GAP_IN_SETUP.format(what=labels, tab=msg.SETUP_TAB_KEYS)


def test_a_broken_settings_file_blocks_the_parts_that_need_it_with_the_key(ready_paths: LivecraftPaths) -> None:
    _break_setting(ready_paths, "keep_days", 0)
    readiness: Readiness = Readiness.check(ready_paths)
    for part in (RunPart.PLAN, RunPart.PACKAGE):
        action: str = _gaps_text(readiness.part(part))
        assert "keep_days" in action and msg.SETUP_TAB_SETTINGS in action
    assert readiness.gap(Need.FORM) is None           # о сломанных настройках говорит их собственная нужда


def test_a_broken_settings_file_is_one_line_for_the_table_and_the_package(ready_paths: LivecraftPaths) -> None:
    """Сломанный livecraft.json в режиме «всё» — одна строка про настройки, в ней и таблица плана, и пакет."""
    _break_setting(ready_paths, "keep_days", 0)
    mode: ModeReadiness = Readiness.check(ready_paths).for_mode(RunMode.ALL, no_llm=False)
    settings_lines: list[str] = [line for line in mode.lines if "keep_days" in line]
    assert len(settings_lines) == 1
    assert RunPart.PLAN.human_label in settings_lines[0] and RunPart.PACKAGE.human_label in settings_lines[0]
    assert settings_lines[0] == msg.RUN_NEED_BLOCKED.format(
        parts=msg.LIST_JOINER.join((RunPart.PLAN.human_label, RunPart.PACKAGE.human_label)),
        gap=Readiness.check(ready_paths).gap(Need.SETTINGS),
    )


def test_parts_not_built_are_not_blocked(ready_paths: LivecraftPaths) -> None:
    """Частей, которых нет в этой версии, настройкой не починить: строка «появится позже», а не «не готово»."""
    readiness: Readiness = Readiness.check(ready_paths)
    for part in (RunPart.ANNOUNCE, RunPart.BROADCAST, RunPart.PACKAGES_IN):
        assert readiness.part(part).state is PartState.NOT_BUILT
    assert readiness.part(RunPart.MERGE).state is PartState.READY


def test_the_announce_mode_with_everything_set_blocks_nothing(ready_paths: LivecraftPaths) -> None:
    mode: ModeReadiness = _configured(ready_paths).for_mode(RunMode.ANNOUNCE, no_llm=False)
    assert [part.part for part in mode.in_state(PartState.READY)] == [RunPart.PLAN, RunPart.MERGE, RunPart.PACKAGE]
    assert mode.in_state(PartState.BLOCKED) == ()
    assert [part.part for part in mode.in_state(PartState.NOT_BUILT)] == [RunPart.ANNOUNCE]
    assert mode.lines == (RunPart.ANNOUNCE.not_built_line,)
    assert not mode.is_nothing_ready
    assert mode.is_part_ready(RunPart.PLAN) and mode.is_part_ready(RunPart.MERGE)
    assert mode.event.text == "mode_readiness mode=announce ready=plan,merge,package blocked=- not_built=announce"


def test_the_from_package_mode_needs_no_table_and_no_key(ready_paths: LivecraftPaths) -> None:
    """Режим Б этой версии — одни «пока нет»: это не «не готово ничего», окно для него не открывается."""
    ready_paths.vault_file.unlink()
    ready_paths.client_secret_file.unlink()
    mode: ModeReadiness = _configured(ready_paths).for_mode(RunMode.FROM_PACKAGE, no_llm=False)
    assert mode.in_state(PartState.READY) == () and mode.in_state(PartState.BLOCKED) == ()
    assert [part.part for part in mode.in_state(PartState.NOT_BUILT)] == [RunPart.PACKAGES_IN, RunPart.BROADCAST]
    assert not mode.is_nothing_ready


def test_a_clean_root_has_nothing_ready(livecraft_paths: LivecraftPaths) -> None:
    for mode in RunMode:
        if not mode.is_from_table:
            continue
        state: ModeReadiness = Readiness.check(livecraft_paths).for_mode(mode, no_llm=False)
        assert state.is_nothing_ready and state.is_fixable_in_setup


def test_the_mode_lines_follow_the_work_order(ready_paths: LivecraftPaths) -> None:
    ready_paths.channels_file.unlink()
    readiness: Readiness = Readiness.check(ready_paths)
    mode: ModeReadiness = readiness.for_mode(RunMode.ALL, no_llm=False)
    assert mode.lines == (
        msg.RUN_NEED_BLOCKED.format(parts=RunPart.PACKAGE.human_label, gap=readiness.gap(Need.FORM)),
        RunPart.ANNOUNCE.not_built_line,
        RunPart.BROADCAST.not_built_line,
    )


def test_a_broken_own_vault_file_blocks_the_table_and_is_fixable_in_the_window(ready_paths: LivecraftPaths) -> None:
    """Свой повреждённый файл окно заменяет первым сохранением: открывать его есть зачем (D9)."""
    ready_paths.vault_local_file.write_bytes(NOT_UTF8_BYTES)
    readiness: Readiness = _configured(ready_paths)
    mode: ModeReadiness = readiness.for_mode(RunMode.ALL, no_llm=False)
    assert mode.is_nothing_ready and mode.is_fixable_in_setup
    assert readiness.vault.error is not None
    gap: str = msg.READINESS_GAP_VAULT_BROKEN.format(problem=readiness.vault.error.problem)
    assert _gaps_text(mode.parts[0]) == gap
    assert ready_paths.vault_local_file.name in gap


def test_a_broken_supplied_vault_file_blocks_the_table_and_is_not_fixable_in_the_window(
    ready_paths: LivecraftPaths,
) -> None:
    """Файл, пришедший с программой, окно не заменит: только установка."""
    ready_paths.vault_file.write_bytes(NOT_UTF8_BYTES)
    readiness: Readiness = _configured(ready_paths)
    mode: ModeReadiness = readiness.for_mode(RunMode.ALL, no_llm=False)
    assert mode.is_nothing_ready and not mode.is_fixable_in_setup
    assert ready_paths.vault_file.name in _gaps_text(mode.parts[0])
    assert readiness.vault.error is not None and readiness.problems[-1] == readiness.vault.error.human
    assert msg.VAULT_FILE_ADVICE_SUPPLIED in readiness.problems[-1]


# --- строка готовности окна настройщика: окно уже открыто


def test_the_window_line_does_not_send_to_the_open_window(ready_paths: LivecraftPaths) -> None:
    """Проблема настроек в окне — без совета открыть «Livecraft — настройка»: только вкладка."""
    _break_setting(ready_paths, "keep_days", 0)
    readiness: Readiness = Readiness.check(ready_paths)
    error: ConfigError | None = readiness.settings.error
    assert error is not None
    assert readiness.window_line == msg.CONFIG_FIX_ON_TAB.format(error=error, tab=msg.SETUP_TAB_SETTINGS)
    assert SETUP_WINDOW_NAME not in readiness.window_line and "в настройщике" not in readiness.window_line
    assert readiness.problems[0] == msg.CONFIG_FIX_IN_SETUP.format(error=error, tab=msg.SETUP_TAB_SETTINGS)


def test_the_window_line_of_a_broken_own_vault_names_the_tab_not_the_window(ready_paths: LivecraftPaths) -> None:
    ready_paths.vault_local_file.write_bytes(NOT_UTF8_BYTES)
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.vault.error is not None
    assert readiness.window_line == msg.VAULT_FILE_BROKEN.format(
        problem=readiness.vault.error.problem, advice=msg.VAULT_FILE_ADVICE_WINDOW
    )
    assert SETUP_WINDOW_NAME not in readiness.window_line


def test_the_window_line_of_a_clean_root_lists_every_problem(livecraft_paths: LivecraftPaths) -> None:
    lines: list[str] = Readiness.check(livecraft_paths).window_line.split(NEWLINE)
    assert len(lines) == 3 and lines[1] == msg.READINESS_CHANNELS_MISSING
    assert all(SETUP_WINDOW_NAME not in line for line in lines)


# --- что делает запуск режима (ModeReadiness.step), с чем идёт прогон и что уходит в лог


def test_a_clean_root_opens_the_setup_window(livecraft_paths: LivecraftPaths) -> None:
    mode: ModeReadiness = Readiness.check(livecraft_paths).for_mode(RunMode.ALL, no_llm=False)
    assert mode.step is ModeStep.OPEN_SETUP


def test_a_broken_supplied_vault_file_refuses_without_a_window(ready_paths: LivecraftPaths) -> None:
    ready_paths.vault_file.write_bytes(NOT_UTF8_BYTES)
    assert _configured(ready_paths).for_mode(RunMode.ALL, no_llm=False).step is ModeStep.REFUSE


def test_a_ready_table_runs_the_plan_and_a_missing_form_fails_the_package(ready_paths: LivecraftPaths) -> None:
    """Таблица готова — прогон; без ссылки на форму пакет не готов — исход режима «ошибка» (код 1)."""
    unformed: ModeReadiness = Readiness.check(ready_paths).for_mode(RunMode.ALL, no_llm=False)
    assert unformed.step is ModeStep.RUN_PLAN and unformed.outcome is RunOutcome.FAILED
    formed: ModeReadiness = _configured(ready_paths).for_mode(RunMode.ALL, no_llm=False)
    assert formed.step is ModeStep.RUN_PLAN and formed.outcome is RunOutcome.DONE


def test_the_package_mode_only_reports(ready_paths: LivecraftPaths) -> None:
    mode: ModeReadiness = _configured(ready_paths).for_mode(RunMode.FROM_PACKAGE, no_llm=False)
    assert mode.step is ModeStep.REPORT and mode.outcome is RunOutcome.DONE


def test_a_ready_table_gives_the_run_its_settings_and_vault_at_once(ready_paths: LivecraftPaths) -> None:
    """Прогону — настройки, сейф и готовность нейросети: с ключом и без --no-llm merge идёт, с --no-llm — нет."""
    readiness: Readiness = Readiness.check(ready_paths)
    basis: PlanBasis | None = readiness.plan_basis(readiness.for_mode(RunMode.ALL, no_llm=True))
    expected: PlanBasis = PlanBasis(
        settings=readiness.settings.value, vault=readiness.vault.vault, with_merge=False   # type: ignore[arg-type]
    )
    assert basis == expected
    with_llm: PlanBasis | None = readiness.plan_basis(readiness.for_mode(RunMode.ALL, no_llm=False))
    assert with_llm is not None and with_llm.with_merge


def test_a_mode_without_the_table_gets_no_plan_run(ready_paths: LivecraftPaths) -> None:
    ready: Readiness = _configured(ready_paths)
    assert ready.plan_basis(ready.for_mode(RunMode.FROM_PACKAGE, no_llm=False)) is None


def test_a_table_that_is_not_ready_gets_no_plan_run(livecraft_paths: LivecraftPaths) -> None:
    clean: Readiness = Readiness.check(livecraft_paths)
    assert clean.plan_basis(clean.for_mode(RunMode.ALL, no_llm=False)) is None


def _logged(readiness: Readiness) -> list[str]:
    with LogCapture.on(LogArea.MAIN) as capture:
        readiness.log(get_logger(LogArea.MAIN))
    return capture.messages()


def test_the_log_names_missing_files_and_broken_fields_without_values(livecraft_paths: LivecraftPaths) -> None:
    """Нет файла — «ещё не настроено» (INFO); сломанное поле — ключ, вид и причина (ERROR) и шаблон (DEBUG)."""
    livecraft_paths.config_file.write_text("{}", encoding=TEXT_ENCODING)
    readiness: Readiness = Readiness.check(livecraft_paths)
    lines: list[str] = _logged(readiness)
    assert lines[0] == readiness.event.text and lines[0].endswith(" ready=no")
    assert any(line.startswith(f"config_error path={livecraft_paths.config_file} key=") for line in lines)
    assert f"config_missing path={livecraft_paths.channels_file}" in lines
    assert any(line.startswith("config_template template=") for line in lines)


def test_the_log_names_a_broken_vault_file_with_its_reason(ready_paths: LivecraftPaths) -> None:
    ready_paths.vault_file.write_text("{", encoding=TEXT_ENCODING)
    lines: list[str] = _logged(Readiness.check(ready_paths))
    vault_line: str = "vault_error file=vault.dat source=supplied reason=damaged detail=vault file is not valid JSON"
    assert any(line.startswith(vault_line) for line in lines)
    for value in SUPPLIED_VALUES.values():
        assert value not in NEWLINE.join(lines)
