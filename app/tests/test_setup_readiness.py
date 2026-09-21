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
from app.setup.readiness import Readiness
from app.tests.conftest import (
    REPO_CHANNELS_EXAMPLE,
    REPO_SETTINGS_FILE,
    SUPPLIED_VALUES,
    write_supplied_vault,
)
from app.ui import messages_ru as msg

OWN_SHEETS_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table"


def _copy_configs(paths: LivecraftPaths) -> None:
    shutil.copyfile(REPO_SETTINGS_FILE, paths.config_file)
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, paths.channels_file)


def _save_own_sheets_id(paths: LivecraftPaths) -> None:
    """Личный сейф пишется тем же путём, что и настройщиком: VaultStore.save_local."""
    own: Vault = Vault.empty().with_field(
        SecretField.SHEETS_ID, SecretValue(field=SecretField.SHEETS_ID, value=OWN_SHEETS_ID), VaultOrigin.OWN
    )
    VaultStore.open(paths).save_local(own)


def _every_text(readiness: Readiness) -> str:
    """Всё, что Readiness отдаёт наружу — людям и в лог."""
    return "\n".join(
        (*readiness.summary_lines, *readiness.problems, *readiness.warnings, *readiness.template_lines,
         readiness.log_line)
    )


# --- чистая установка


def test_a_clean_root_is_not_ready(livecraft_paths: LivecraftPaths) -> None:
    """Ни конфигов, ни сейфа: первым загрузчик читает channels.json — его и называет, с шаблоном."""
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert not readiness.is_ready
    assert readiness.config_error is not None
    assert readiness.config_error.config_path == livecraft_paths.channels_file
    assert readiness.config_error.kind is ConfigProblem.FILE_MISSING
    assert str(readiness.config_error) == readiness.problems[0]
    assert readiness.template_lines[0] == msg.CONFIG_CHANNELS_HINT.format(path=livecraft_paths.channels_file)
    assert readiness.template_lines[-1] == msg.CONFIG_CHANNELS_TEMPLATE


def test_a_missing_settings_file_gets_the_settings_template(livecraft_paths: LivecraftPaths) -> None:
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, livecraft_paths.channels_file)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.config_error is not None
    assert readiness.config_error.config_path == livecraft_paths.config_file
    assert readiness.problems[0] == str(readiness.config_error)
    assert readiness.template_lines == (
        msg.CONFIG_SETTINGS_HINT.format(path=livecraft_paths.config_file),
        msg.CONFIG_SETTINGS_TEMPLATE,
    )


def test_the_channels_template_explains_every_field(livecraft_paths: LivecraftPaths) -> None:
    """Между подсказкой и шаблоном — что вписать в каждое поле; допустимые значения — от загрузчика."""
    lines: tuple[str, ...] = Readiness.check(livecraft_paths).template_lines
    body: str = "\n".join(lines[1:-1])
    assert len(lines) == len(msg.CONFIG_CHANNELS_FIELDS) + 2
    assert msg.CONFIG_LANGUAGES_RULE in body and "public, unlisted" in body and "youtube" in body


# --- конфиги на месте, сейфа нет


def test_configs_without_a_vault_leave_only_the_vault_problem(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert not readiness.is_ready
    assert readiness.config_error is None and readiness.vault_error is None
    assert readiness.problems == (Vault.empty().admission_reason,)
    for field in SecretField:
        assert field.human_label in readiness.problems[0]
    assert readiness.template_lines == ()


def test_a_broken_config_field_is_named(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    data: dict[str, Any] = json.loads(livecraft_paths.config_file.read_text(encoding="utf-8"))
    data["keep_days"] = 0
    livecraft_paths.config_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.config_error is not None and readiness.config_error.key_path == "keep_days"
    assert readiness.template_lines == ()          # значение негодное, файл и поле на месте — шаблон не нужен


def test_a_missing_config_field_brings_the_template(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    data: dict[str, Any] = json.loads(livecraft_paths.config_file.read_text(encoding="utf-8"))
    del data["timezone"]
    livecraft_paths.config_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.config_error is not None and readiness.config_error.key_path == "timezone"
    assert readiness.template_lines[-1] == msg.CONFIG_SETTINGS_TEMPLATE


# --- готово


def test_a_supplied_vault_and_configs_are_ready(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.is_ready
    assert readiness.problems == () and readiness.warnings == () and readiness.template_lines == ()
    assert readiness.vault_load is not None and readiness.vault_load.local_state is LocalVaultState.ABSENT


def test_the_summary_names_every_field_and_its_origin(ready_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines
    assert lines[0] == msg.READINESS_SUMMARY_TITLE
    for field in SecretField:
        assert msg.READINESS_FIELD_LINE.format(label=field.human_label, origin=msg.VAULT_ORIGIN_SUPPLIED) in lines
    assert lines[-1] == msg.READINESS_CHANNELS_LINE.format(count=2, languages="en, ru, uk")


def test_the_summary_of_an_empty_vault_says_no_for_every_field(livecraft_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(livecraft_paths).summary_lines
    for field in SecretField:
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
    assert all(readiness.vault.origin_of(field) is VaultOrigin.SUPPLIED for field in SecretField)
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
    assert readiness.problems[-1] == msg.VAULT_FILE_BROKEN.format(error=readiness.vault_error)
    assert "vault=broken" in readiness.log_line


NOT_UTF8_BYTES: bytes = b"\xff\xfe\x00vault\x80\x81"


def _assert_broken_local_file(paths: LivecraftPaths, readiness: Readiness) -> None:
    """Повреждённый личный файл — не «чужой сейф»: отказ с именем файла, а не предупреждение и поставка."""
    assert not readiness.is_ready
    assert readiness.vault_error is not None
    assert readiness.vault is None
    assert any(paths.vault_local_file.name in line for line in readiness.problems)
    assert readiness.problems[-1] == msg.VAULT_FILE_BROKEN.format(error=readiness.vault_error)
    assert readiness.warnings == ()


def test_a_local_vault_file_that_is_not_utf8_stops_the_run(ready_paths: LivecraftPaths) -> None:
    ready_paths.vault_local_file.write_bytes(NOT_UTF8_BYTES)
    _assert_broken_local_file(ready_paths, Readiness.check(ready_paths))


def test_a_local_vault_file_that_does_not_open_stops_the_run(ready_paths: LivecraftPaths) -> None:
    ready_paths.vault_local_file.mkdir()
    _assert_broken_local_file(ready_paths, Readiness.check(ready_paths))


def test_the_config_problem_comes_before_the_vault_problem(livecraft_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.problems[0] == str(readiness.config_error)
    assert readiness.problems[1] == Vault.empty().admission_reason


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
    write_supplied_vault(ready_paths, {k: v for k, v in SUPPLIED_VALUES.items() if k is not SecretField.KEY_FORM_URL})
    readiness: Readiness = Readiness.check(ready_paths)
    assert not readiness.is_ready
    text: str = _every_text(readiness)
    for value in SUPPLIED_VALUES.values():
        assert value not in text
    assert SecretField.KEY_FORM_URL.human_label in readiness.problems[0]


def test_the_log_line_carries_labels_and_state_only(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.vault is not None
    line: str = readiness.log_line
    assert line.startswith("config=ok channels=2 local=absent vault=")
    assert readiness.vault.log_line in line
    assert line.isascii()


def test_check_prints_nothing(livecraft_paths: LivecraftPaths, capsys: pytest.CaptureFixture[str]) -> None:
    """Печатает только main: Readiness лишь читает и отвечает на вопросы о себе."""
    Readiness.check(livecraft_paths)
    captured: pytest.CaptureResult[str] = capsys.readouterr()
    assert captured.out == "" and captured.err == ""


def test_the_readiness_object_is_frozen(ready_paths: LivecraftPaths) -> None:
    with pytest.raises(Exception):
        Readiness.check(ready_paths).config = None     # type: ignore[misc]
