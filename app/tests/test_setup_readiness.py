from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.config.loader import ConfigProblem
from app.paths import LivecraftPaths
from app.secretsafe.crypto import KEY_FIELDS, KEY_SALT, KEY_VERSION, KEY_WRAPPED, SALT_BYTES
from app.secretsafe.store import VAULT_FILE_ENCODING, LocalVaultState, VaultStore
from app.secretsafe.value import SecretField, SecretValue
from app.secretsafe.vault import Vault, VaultOrigin
from app.setup.readiness import ModeReadiness, PartReadiness, Readiness
from app.setup.run_mode import RunMode, RunPart
from app.tests.conftest import (
    REPO_CHANNELS_EXAMPLE,
    SHIPPED_SETTINGS_FILE,
    SUPPLIED_VALUES,
    write_supplied_vault,
)
from app.ui import messages_ru as msg

OWN_SHEETS_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table"


def _copy_configs(paths: LivecraftPaths) -> None:
    shutil.copyfile(SHIPPED_SETTINGS_FILE, paths.config_file)
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, paths.channels_file)


def _save_own_sheets_id(paths: LivecraftPaths) -> None:
    """Личный сейф пишется тем же путём, что и настройщиком: VaultStore.save_local."""
    own: Vault = Vault.empty().with_field(
        SecretField.SHEETS_ID, SecretValue(field=SecretField.SHEETS_ID, value=OWN_SHEETS_ID), VaultOrigin.OWN
    )
    VaultStore.open(paths).save_local(own)


def _mode_texts(readiness: Readiness) -> tuple[str, ...]:
    """Строки частей и строки лога всех режимов, с нейросетью и без."""
    texts: list[str] = []
    for mode in RunMode:
        for no_llm in (False, True):
            mode_readiness: ModeReadiness = readiness.for_mode(mode, no_llm=no_llm)
            texts.extend((*mode_readiness.lines, mode_readiness.log_line))
    return tuple(texts)


def _every_text(readiness: Readiness) -> str:
    """Всё, что Readiness отдаёт наружу — людям и в лог."""
    return "\n".join(
        (*readiness.summary_lines, *readiness.problems, *readiness.warnings, *readiness.template_lines,
         readiness.log_line, *_mode_texts(readiness))
    )


# --- чистая установка: файлы читаются независимо друг от друга


def test_a_clean_root_is_not_ready(livecraft_paths: LivecraftPaths) -> None:
    """Ни конфигов, ни сейфа: обе ошибки названы — сначала настройки, потом каналы; шаблонов нет (файлов нет)."""
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert not readiness.is_ready
    assert readiness.settings is None and readiness.channels is None and readiness.config is None
    assert readiness.settings_error is not None and readiness.settings_error.config_path == livecraft_paths.config_file
    assert readiness.channels_error is not None and readiness.channels_error.kind is ConfigProblem.FILE_MISSING
    assert readiness.config_errors == (readiness.settings_error, readiness.channels_error)
    assert readiness.problems[0] == msg.CONFIG_FIX_IN_SETUP.format(
        error=readiness.settings_error, tab=msg.SETUP_TAB_SETTINGS
    )
    assert readiness.problems[1] == msg.READINESS_CHANNELS_MISSING
    assert readiness.template_lines == ()


def test_settings_are_read_without_channels(livecraft_paths: LivecraftPaths) -> None:
    """Боевой случай 24-09-2026: нет channels.json — livecraft.json всё равно прочитан."""
    shutil.copyfile(SHIPPED_SETTINGS_FILE, livecraft_paths.config_file)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.settings is not None and readiness.settings_error is None
    assert readiness.channels is None and readiness.config is None
    assert msg.READINESS_FIELD_LINE.format(
        label=msg.FORM_URL_LABEL, origin=msg.READINESS_FORM_NOT_CONFIGURED
    ) in readiness.summary_lines


def test_channels_are_read_without_settings(livecraft_paths: LivecraftPaths) -> None:
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, livecraft_paths.channels_file)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.channels is not None and len(readiness.channels) == 2
    assert readiness.settings is None and readiness.settings_error is not None
    assert readiness.summary_lines[-1] == msg.READINESS_CHANNELS_LINE.format(count=2, languages="ru, uk")


def test_the_config_property_joins_both_files(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.config is not None
    assert readiness.config.settings == readiness.settings and readiness.config.channels == readiness.channels


# --- конфиги на месте, сейфа нет


def test_configs_without_a_vault_leave_only_the_vault_problem(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert not readiness.is_ready
    assert readiness.config_errors == () and readiness.vault_error is None
    assert readiness.problems == (Vault.empty().admission_reason,)
    for field in SecretField.current():
        assert field.human_label in readiness.problems[0]
    assert SecretField.KEY_FORM_URL.human_label not in readiness.problems[0]      # не требуется (§14 решение 15)
    assert readiness.template_lines == ()


def test_a_broken_config_field_is_named_with_where_to_fix_it(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    data: dict[str, Any] = json.loads(livecraft_paths.config_file.read_text(encoding="utf-8"))
    data["keep_days"] = 0
    livecraft_paths.config_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.settings_error is not None and readiness.settings_error.key_path == "keep_days"
    line: str = readiness.problems[0]
    assert str(livecraft_paths.config_file) in line and "keep_days" in line and msg.SETUP_TAB_SETTINGS in line
    assert readiness.channels is not None                  # каналы от сломанных настроек не зависят
    assert readiness.template_lines == (msg.CONFIG_SETTINGS_TEMPLATE,)       # только для лога


def test_a_broken_channels_file_is_named_with_its_tab_and_template(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    livecraft_paths.channels_file.write_text('{"channels": []}', encoding="utf-8")
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.channels_error is not None
    assert msg.SETUP_TAB_CHANNELS in readiness.problems[0]
    assert str(livecraft_paths.channels_file) in readiness.problems[0]
    lines: tuple[str, ...] = readiness.template_lines
    assert lines[-1] == msg.CONFIG_CHANNELS_TEMPLATE
    assert len(lines) == len(msg.CONFIG_CHANNELS_FIELDS) + 1
    body: str = "\n".join(lines[:-1])
    assert msg.CONFIG_LANGUAGES_RULE in body and "public, unlisted" in body and "youtube" in body


def test_a_missing_config_field_brings_the_template_for_the_log(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    data: dict[str, Any] = json.loads(livecraft_paths.config_file.read_text(encoding="utf-8"))
    del data["timezone"]
    livecraft_paths.config_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.settings_error is not None and readiness.settings_error.key_path == "timezone"
    assert readiness.template_lines == (msg.CONFIG_SETTINGS_TEMPLATE,)


# --- готово


def test_a_supplied_vault_and_configs_are_ready(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.is_ready
    assert readiness.problems == () and readiness.warnings == () and readiness.template_lines == ()
    assert readiness.vault_load is not None and readiness.vault_load.local_state is LocalVaultState.ABSENT


def test_the_summary_names_every_field_and_its_origin(ready_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines
    assert lines[0] == msg.READINESS_SUMMARY_TITLE
    for field in SecretField.current():
        assert msg.READINESS_FIELD_LINE.format(label=field.human_label, origin=msg.VAULT_ORIGIN_SUPPLIED) in lines
    assert lines[-1] == msg.READINESS_CHANNELS_LINE.format(count=2, languages="ru, uk")


def test_the_summary_of_an_empty_vault_says_no_for_every_field(livecraft_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(livecraft_paths).summary_lines
    for field in SecretField.current():
        assert msg.READINESS_FIELD_LINE.format(label=field.human_label, origin=msg.READINESS_FIELD_ABSENT) in lines
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
    assert readiness.vault_load is not None and readiness.vault_load.local_state is LocalVaultState.READ


# --- личный сейф не читается: громко, но работа идёт


def test_an_unreadable_own_vault_warns_and_runs_on_supplied_values(ready_paths: LivecraftPaths) -> None:
    """§16: молчаливый откат недопустим — получатель незаметно работал бы на чужом ключе и таблице."""
    _save_own_sheets_id(ready_paths)
    data: dict[str, Any] = json.loads(ready_paths.vault_local_file.read_text(encoding=VAULT_FILE_ENCODING))
    wrapped: bytes = base64.b64decode(data[KEY_WRAPPED], validate=True)
    data[KEY_WRAPPED] = base64.b64encode(wrapped[:-1] + bytes([wrapped[-1] ^ 0xFF])).decode("ascii")
    ready_paths.vault_local_file.write_text(json.dumps(data), encoding=VAULT_FILE_ENCODING)
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.warnings == (msg.VAULT_LOCAL_UNREADABLE,)
    assert readiness.is_ready                                  # запуск идёт — на поставочных значениях
    assert readiness.vault is not None
    assert all(readiness.vault.origin_of(field) is VaultOrigin.SUPPLIED for field in SecretField.current())
    assert "local=unreadable" in readiness.log_line


def test_no_warning_without_an_own_vault(ready_paths: LivecraftPaths) -> None:
    assert Readiness.check(ready_paths).warnings == ()


# --- файл сейфа чужого формата


def test_a_vault_file_of_an_unknown_format_is_named(ready_paths: LivecraftPaths) -> None:
    """§7.3: неизвестная версия формата — ошибка с именем файла и код 2, а не тихое игнорирование."""
    ready_paths.vault_local_file.write_text(
        json.dumps({KEY_VERSION: 7, KEY_SALT: base64.b64encode(bytes(SALT_BYTES)).decode("ascii"), KEY_FIELDS: {}}),
        encoding=VAULT_FILE_ENCODING,
    )
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.vault_error is not None
    assert not readiness.is_ready
    assert any(ready_paths.vault_local_file.name in line for line in readiness.problems)
    assert readiness.problems[-1] == readiness.vault_error.human
    assert msg.VAULT_FILE_ADVICE_LOCAL in readiness.problems[-1]
    assert readiness.vault_error.detail not in readiness.problems[-1]
    assert "vault=broken" in readiness.log_line


NOT_UTF8_BYTES: bytes = b"\xff\xfe\x00vault\x80\x81"


def _assert_broken_local_file(paths: LivecraftPaths, readiness: Readiness) -> None:
    """Повреждённый личный файл — не «чужой сейф»: отказ с именем файла, а не предупреждение и поставка."""
    assert not readiness.is_ready
    assert readiness.vault_error is not None
    assert readiness.vault is None
    assert any(paths.vault_local_file.name in line for line in readiness.problems)
    assert readiness.problems[-1] == readiness.vault_error.human
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
    assert readiness.vault is not None
    text: str = _every_text(readiness)
    for secret in readiness.vault.secrets():
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
    assert readiness.vault is not None and readiness.vault.get(SecretField.KEY_FORM_URL) is None
    assert readiness.config is not None and not readiness.config.settings.form.is_configured
    assert readiness.is_ready


def test_the_log_line_carries_labels_and_state_only(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.vault is not None
    line: str = readiness.log_line
    assert line.startswith("settings=ok channels=2 local=absent vault=")
    assert readiness.vault.log_line in line
    assert line.isascii()


def test_check_prints_nothing(livecraft_paths: LivecraftPaths, capsys: pytest.CaptureFixture[str]) -> None:
    """Печатает только main: Readiness лишь читает и отвечает на вопросы о себе."""
    Readiness.check(livecraft_paths)
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_the_readiness_object_is_frozen(ready_paths: LivecraftPaths) -> None:
    with pytest.raises(Exception):
        Readiness.check(ready_paths).settings = None     # type: ignore[misc]


# --- форма ключей в сводке: по livecraft.json, а не по сейфу (§14 решение 15)

FORM_URL: str = "https://forms.gle/AbCdEf123456"
LEGACY_FORM_LABEL: str = SecretField.KEY_FORM_URL.human_label


def _set_form_url(paths: LivecraftPaths, url: str) -> None:
    data: dict[str, Any] = json.loads(paths.config_file.read_text(encoding="utf-8"))
    data["form"]["url"] = url
    paths.config_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def test_the_summary_says_the_form_is_not_configured_on_the_shipped_settings(ready_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines
    assert msg.READINESS_FIELD_LINE.format(label=msg.FORM_URL_LABEL, origin=msg.READINESS_FORM_NOT_CONFIGURED) in lines
    assert lines[-1] == msg.READINESS_CHANNELS_LINE.format(count=2, languages="ru, uk")


@pytest.mark.parametrize("url", ["https://docs.google.com]/forms/x", "https://[bad"])
def test_an_unparsable_form_url_is_a_settings_problem_not_a_crash(ready_paths: LivecraftPaths, url: str) -> None:
    _set_form_url(ready_paths, url)
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.settings is None
    assert readiness.settings_error is not None
    assert readiness.settings_error.key_path == "form.url"
    assert readiness.settings_error.problem == msg.CONFIG_PROBLEM_FORM_URL


def test_the_summary_says_the_form_is_configured_and_hides_the_link(ready_paths: LivecraftPaths) -> None:
    _set_form_url(ready_paths, FORM_URL)
    readiness: Readiness = Readiness.check(ready_paths)
    lines: tuple[str, ...] = readiness.summary_lines
    assert msg.READINESS_FIELD_LINE.format(label=msg.FORM_URL_LABEL, origin=msg.READINESS_FORM_CONFIGURED) in lines
    assert FORM_URL not in "\n".join(lines) + readiness.log_line


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


# --- готовность по частям режима (задача 3.8, §10)


def _configured(paths: LivecraftPaths) -> Readiness:
    """Всё настроено, и форма тоже: готовы все реализованные части."""
    _set_form_url(paths, FORM_URL)
    return Readiness.check(paths)


def _gaps_text(part: PartReadiness) -> str:
    assert part.action is not None
    return part.action


def test_a_fully_configured_root_has_every_built_part_ready(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = _configured(ready_paths)
    for part in RunPart:
        state: PartReadiness = readiness.part(part)
        assert state.is_built is part.is_built
        assert state.is_ready is part.is_built
        assert (state.action is None) is part.is_built


def test_without_channels_the_table_and_package_are_ready(ready_paths: LivecraftPaths) -> None:
    """Эфиров в этой версии нет: нехватка каналов — не «не готово», а та же строка «появится позже»."""
    _set_form_url(ready_paths, FORM_URL)
    ready_paths.channels_file.unlink()
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.part(RunPart.PLAN).is_ready
    assert readiness.part(RunPart.PACKAGE).is_ready
    broadcast: PartReadiness = readiness.part(RunPart.BROADCAST)
    assert not broadcast.is_blocked and not broadcast.is_built
    assert broadcast.action == RunPart.BROADCAST.not_built_line
    assert msg.READINESS_GAP_CHANNELS_MISSING not in _gaps_text(broadcast)


def test_the_all_mode_without_the_openai_key_blocks_nothing(ready_paths: LivecraftPaths) -> None:
    """Нейросети в этой версии нет: режим «всё» без --no-llm ключа OpenAI не требует и «эфиры» готовыми не
    показывает; с --no-llm строки о нейросети нет вовсе."""
    _set_form_url(ready_paths, FORM_URL)
    write_supplied_vault(ready_paths, {k: v for k, v in SUPPLIED_VALUES.items() if k is not SecretField.OPENAI_API_KEY})
    readiness: Readiness = Readiness.check(ready_paths)
    merge: PartReadiness = readiness.part(RunPart.MERGE)
    assert not merge.is_blocked and not merge.is_built and merge.action == RunPart.MERGE.not_built_line
    with_llm: ModeReadiness = readiness.for_mode(RunMode.ALL, no_llm=False)
    assert with_llm.blocked == ()
    assert RunPart.BROADCAST not in [part.part for part in with_llm.ready]
    assert with_llm.lines.count(RunPart.MERGE.not_built_line) == 1
    without_llm: ModeReadiness = readiness.for_mode(RunMode.ALL, no_llm=True)
    assert without_llm.blocked == () and RunPart.MERGE.not_built_line not in without_llm.lines


def test_without_the_form_the_package_waits(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(ready_paths)       # поставочная ссылка на форму пуста
    state: PartReadiness = readiness.part(RunPart.PACKAGE)
    assert state.is_blocked
    assert msg.READINESS_GAP_FORM in _gaps_text(state) and msg.SETUP_TAB_SETTINGS in _gaps_text(state)
    assert readiness.part(RunPart.PLAN).is_ready


def test_without_client_secret_the_table_waits(ready_paths: LivecraftPaths) -> None:
    ready_paths.client_secret_file.unlink()
    readiness: Readiness = _configured(ready_paths)
    plan: PartReadiness = readiness.part(RunPart.PLAN)
    assert plan.is_blocked
    assert str(ready_paths.client_secret_file) in _gaps_text(plan)
    assert readiness.for_mode(RunMode.BROADCAST, no_llm=False).is_nothing_ready     # основа режима А не готова


def test_without_the_table_fields_the_table_waits_and_names_both(ready_paths: LivecraftPaths) -> None:
    write_supplied_vault(ready_paths, {SecretField.OPENAI_API_KEY: SUPPLIED_VALUES[SecretField.OPENAI_API_KEY]})
    plan: PartReadiness = _configured(ready_paths).part(RunPart.PLAN)
    assert plan.is_blocked
    for field in (SecretField.SHEETS_ID, SecretField.SHEETS_RANGE):
        assert field.human_label in _gaps_text(plan)


def test_a_broken_settings_file_blocks_the_parts_that_need_it_with_the_key(ready_paths: LivecraftPaths) -> None:
    data: dict[str, Any] = json.loads(ready_paths.config_file.read_text(encoding="utf-8"))
    data["keep_days"] = 0
    ready_paths.config_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    readiness: Readiness = Readiness.check(ready_paths)
    for part in (RunPart.PLAN, RunPart.PACKAGE):
        action: str = _gaps_text(readiness.part(part))
        assert "keep_days" in action and msg.SETUP_TAB_SETTINGS in action


def test_parts_not_built_are_not_blocked(ready_paths: LivecraftPaths) -> None:
    """Частей, которых нет в этой версии, настройкой не починить: строка «появится позже», а не «не готово»."""
    readiness: Readiness = Readiness.check(ready_paths)
    for part in (RunPart.MERGE, RunPart.ANNOUNCE, RunPart.BROADCAST, RunPart.PACKAGES_IN):
        state: PartReadiness = readiness.part(part)
        assert not state.is_built and not state.is_blocked and not state.is_ready
        assert state.action == part.not_built_line


def test_the_announce_mode_with_everything_set_blocks_nothing(ready_paths: LivecraftPaths) -> None:
    mode: ModeReadiness = _configured(ready_paths).for_mode(RunMode.ANNOUNCE, no_llm=False)
    assert [part.part for part in mode.ready] == [RunPart.PLAN, RunPart.PACKAGE]
    assert mode.blocked == ()
    assert [part.part for part in mode.not_built] == [RunPart.MERGE, RunPart.ANNOUNCE]
    assert mode.lines == (RunPart.MERGE.not_built_line, RunPart.ANNOUNCE.not_built_line)
    assert not mode.is_nothing_ready
    assert mode.is_part_ready(RunPart.PLAN) and not mode.is_part_ready(RunPart.MERGE)
    assert mode.log_line == "mode=announce ready=plan,package blocked=- not_built=merge,announce"


def test_the_from_package_mode_needs_no_table_and_no_key(ready_paths: LivecraftPaths) -> None:
    """Режим Б этой версии — одни «пока нет»: это не «не готово ничего», окно для него не открывается."""
    ready_paths.vault_file.unlink()
    ready_paths.client_secret_file.unlink()
    mode: ModeReadiness = _configured(ready_paths).for_mode(RunMode.FROM_PACKAGE, no_llm=False)
    assert mode.ready == () and mode.blocked == ()
    assert [part.part for part in mode.not_built] == [RunPart.PACKAGES_IN, RunPart.BROADCAST]
    assert not mode.is_nothing_ready


def test_a_clean_root_has_nothing_ready(livecraft_paths: LivecraftPaths) -> None:
    for mode in RunMode:
        if not mode.is_from_table:
            continue
        state: ModeReadiness = Readiness.check(livecraft_paths).for_mode(mode, no_llm=False)
        assert state.is_nothing_ready and state.is_fixable_in_setup


def test_the_mode_lines_come_one_per_part_in_work_order(ready_paths: LivecraftPaths) -> None:
    ready_paths.channels_file.unlink()
    mode: ModeReadiness = Readiness.check(ready_paths).for_mode(RunMode.ALL, no_llm=False)
    parts: list[RunPart] = [part.part for part in mode.parts if part.action is not None]
    assert parts == [RunPart.MERGE, RunPart.PACKAGE, RunPart.ANNOUNCE, RunPart.BROADCAST]
    assert len(mode.lines) == 4


def test_a_broken_own_vault_file_blocks_the_table_and_is_fixable_in_the_window(ready_paths: LivecraftPaths) -> None:
    """Свой повреждённый файл окно заменяет первым сохранением: открывать его есть зачем (D9)."""
    ready_paths.vault_local_file.write_bytes(NOT_UTF8_BYTES)
    readiness: Readiness = _configured(ready_paths)
    mode: ModeReadiness = readiness.for_mode(RunMode.ALL, no_llm=False)
    assert mode.is_nothing_ready and mode.is_fixable_in_setup
    assert readiness.vault_error is not None
    gap: str = msg.READINESS_GAP_VAULT_BROKEN.format(problem=readiness.vault_error.problem)
    assert gap in mode.parts[0].action     # type: ignore[operator]
    assert ready_paths.vault_local_file.name in mode.parts[0].action     # type: ignore[operator]


def test_a_broken_supplied_vault_file_blocks_the_table_and_is_not_fixable_in_the_window(
    ready_paths: LivecraftPaths,
) -> None:
    """Файл, пришедший с программой, окно не заменит: только установка."""
    ready_paths.vault_file.write_bytes(NOT_UTF8_BYTES)
    readiness: Readiness = _configured(ready_paths)
    mode: ModeReadiness = readiness.for_mode(RunMode.ALL, no_llm=False)
    assert mode.is_nothing_ready and not mode.is_fixable_in_setup
    assert ready_paths.vault_file.name in mode.parts[0].action     # type: ignore[operator]
    assert readiness.problems[-1] == readiness.vault_error.human     # type: ignore[union-attr]
    assert msg.VAULT_FILE_ADVICE_SUPPLIED in readiness.problems[-1]
