from __future__ import annotations

import base64
import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from app.config.broadcasts import BroadcastSettings
from app.config.files import SettingsFile, ShippedSettings
from app.config.folders import FolderSettings
from app.config.json_node import ConfigError, ConfigProblem
from app.config.telegram import ChatTarget, TelegramSettings
from app.core.text_format import NEWLINE, TEXT_ENCODING
from app.observability.log_event import LogArea, get_logger
from app.paths import DataDir, FileName, LivecraftPaths
from app.run.exit_code import RunOutcome
from app.run.line_plan import LinePlan, ModeReadiness, RunScope
from app.run.mode import LINE_ORDER, ModeStep, Need, NeedGap, PartReadiness, PartState, RunMode, RunPart
from app.secretsafe.crypto import SALT_BYTES, VaultFileKey
from app.secretsafe.field import SecretField, VaultOrigin
from app.secretsafe.store import VaultLayerState, VaultStore
from app.secretsafe.value import SecretValue
from app.secretsafe.vault import Vault
from app.setup.readiness import ChannelBasis, Readiness, RunBasis, RunSnapshot, ServiceReadiness
from app.tests.conftest import FORM_URL, REPO_CHANNELS_EXAMPLE, SHIPPED_SETTINGS_FILE
from app.tests.fixtures.logs import LogCapture
from app.tests.fixtures.settings import (
    lines_on,
    lines_without,
    set_drive_folder,
    set_folders,
    set_form_url,
    set_lines,
)
from app.tests.fixtures.telegram import BOT_TOKEN
from app.tests.fixtures.vault import TOKEN_VALUES, save_own_values, write_token_vault
from app.ui import messages_ru as msg

OWN_SHEETS_ID: str = "1own-B3c4D5e6F7g8H9i0JkLmNoPqRsTuVwXyZ-own-table"
NOT_UTF8_BYTES: bytes = b"\xff\xfe\x00vault\x80\x81"
SETTINGS_TEMPLATE: str = ShippedSettings().template.rstrip(NEWLINE)
SETUP_WINDOW_NAME: str = "«Livecraft — настройка»"
PRIVATE_ID: str = "111000111"
ALL_LINES: LinePlan = LinePlan(frozenset(LINE_ORDER))
PACKAGE_LINES: LinePlan = LinePlan(frozenset({RunPart.BROADCAST, RunPart.KEYS}))    # таблица выключена — режим Б
# Запуск, в котором идут все линии: сводка говорит о настройках как есть.
FULL_RUN: RunScope = RunScope(parts=frozenset(LINE_ORDER))


def _copy_configs(paths: LivecraftPaths) -> None:
    shutil.copyfile(SHIPPED_SETTINGS_FILE, paths.file(FileName.CONFIG))
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, paths.file(FileName.CHANNELS))


def _break_setting(paths: LivecraftPaths, key: str, value: Any) -> None:
    data: dict[str, Any] = json.loads(paths.file(FileName.CONFIG).read_text(encoding=TEXT_ENCODING))
    data[key] = value
    paths.file(FileName.CONFIG).write_text(json.dumps(data, ensure_ascii=False), encoding=TEXT_ENCODING)


def _save_own_sheets_id(paths: LivecraftPaths) -> None:
    """Личный сейф пишется тем же путём, что и настройщиком: VaultStore.save_local."""
    own: Vault = Vault.empty().with_field(
        SecretField.SHEETS_ID, SecretValue(field=SecretField.SHEETS_ID, value=OWN_SHEETS_ID), VaultOrigin.OWN
    )
    VaultStore.open(paths).save_local(own)


def _set_links(paths: LivecraftPaths) -> None:
    """Ссылка на форму ключей в livecraft.json и папка материалов на Google Диске в сейфе."""
    set_form_url(paths, FORM_URL)
    set_drive_folder(paths)


def _configured(paths: LivecraftPaths) -> Readiness:
    """Всё настроено, и форма с папкой Диска тоже: готовы все реализованные части."""
    _set_links(paths)
    return Readiness.check(paths)


def _with_telegram(paths: LivecraftPaths, telegram: TelegramSettings) -> None:
    """Свой токен бота в сейфе и раздел telegram в livecraft.json — так их записывает вкладка «Telegram»."""
    save_own_values(paths, {SecretField.TELEGRAM_BOT_TOKEN: BOT_TOKEN})
    file: SettingsFile = SettingsFile.of(paths)
    file.save(file.load().with_telegram(telegram))


def _with_private_chat(paths: LivecraftPaths) -> None:
    """Бот и подключённый личный чат: объявлениям в Telegram есть куда уходить."""
    _with_telegram(paths, TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, ""))


def _announcing(paths: LivecraftPaths) -> Readiness:
    """Всё настроено, и Telegram тоже: готовы все реализованные части, объявления в Telegram — в том числе."""
    _with_private_chat(paths)
    return _configured(paths)


def _gaps_text(part: PartReadiness) -> str:
    return NEWLINE.join(gap.text for gap in part.unmet)


def _gap_text(readiness: Readiness, need: Need) -> str:
    """Строка нужды для консоли; нужды должно не хватать."""
    gap: NeedGap | None = readiness.gap(need)
    assert gap is not None
    return gap.text


def _mode_texts(readiness: Readiness) -> tuple[str, ...]:
    """Строки нужд, строка лога и снимок линий запуска."""
    mode: ModeReadiness = readiness.for_run()
    return (*mode.lines, mode.event.text, mode.snapshot.text)


def _every_text(readiness: Readiness) -> str:
    """Всё, что Readiness отдаёт наружу — людям и в лог."""
    return NEWLINE.join(
        (*readiness.summary_lines(FULL_RUN), readiness.window_line, *readiness.warnings,
         *readiness.template_lines, readiness.event.text, *_mode_texts(readiness))
    )


# --- чистая установка: файлы читаются независимо друг от друга


def test_a_clean_root_is_not_ready(livecraft_paths: LivecraftPaths) -> None:
    """Ни конфигов, ни сейфа: окно говорит строками нужд работающих линий — те же строки, что у запуска; шаблонов нет
    (файлов нет)."""
    readiness: Readiness = Readiness.check(livecraft_paths)
    settings_error: ConfigError | None = readiness.settings.error
    assert not readiness.is_ready
    assert readiness.settings.value is None and readiness.channels.value is None
    assert settings_error is not None and settings_error.config_path == livecraft_paths.file(FileName.CONFIG)
    assert readiness.channels.is_missing and readiness.channels.error is not None
    assert readiness.channels.error.reason is ConfigProblem.FILE_MISSING
    assert readiness.window_line == NEWLINE.join(readiness.for_run().lines)
    assert _gap_text(readiness, Need.SETTINGS) in readiness.window_line
    assert _gap_text(readiness, Need.CHANNELS) in readiness.window_line
    assert readiness.template_lines == ()


def test_settings_are_read_without_channels(livecraft_paths: LivecraftPaths) -> None:
    """Боевой случай 24-09-2026: нет channels.json — livecraft.json всё равно прочитан."""
    shutil.copyfile(SHIPPED_SETTINGS_FILE, livecraft_paths.file(FileName.CONFIG))
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.settings.value is not None and readiness.settings.error is None
    assert readiness.channels.value is None
    assert msg.READINESS_FIELD_LINE.format(
        label=msg.FORM_URL_LABEL, origin=msg.READINESS_FORM_NOT_CONFIGURED
    ) in readiness.summary_lines(FULL_RUN)


def test_channels_are_read_without_settings(livecraft_paths: LivecraftPaths) -> None:
    shutil.copyfile(REPO_CHANNELS_EXAMPLE, livecraft_paths.file(FileName.CHANNELS))
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.channels.value is not None and len(readiness.channels.value.channels) == 2
    assert readiness.settings.value is None and readiness.settings.error is not None
    assert readiness.summary_lines(FULL_RUN)[-1] == msg.READINESS_CHANNELS_LINE.format(count=2, languages="ru, uk")


# --- конфиги на месте, сейфа нет


def test_configs_without_a_vault_name_the_vault_fields_of_the_working_lines(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert not readiness.is_ready
    assert readiness.settings.error is None and readiness.channels.error is None and readiness.vault.error is None
    for field in (SecretField.SHEETS_ID, SecretField.OPENAI_API_KEY, SecretField.DRIVE_FOLDER):
        assert field.human_label in readiness.window_line
    assert readiness.template_lines == ()


def test_a_broken_config_field_is_named_with_where_to_fix_it(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    _break_setting(livecraft_paths, "keep_days", 0)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.settings.error is not None and readiness.settings.error.key_path == "keep_days"
    line: str = readiness.window_line
    assert "keep_days" in line and msg.SETUP_TAB_TITLES["advanced"] in line
    assert readiness.channels.value is not None                  # каналы от сломанных настроек не зависят
    assert readiness.template_lines == (SETTINGS_TEMPLATE,)      # только для лога


def test_a_broken_channels_file_is_named_with_its_tab_and_template(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    livecraft_paths.file(FileName.CHANNELS).write_text('{"channels": []}', encoding=TEXT_ENCODING)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.channels.is_broken
    assert msg.SETUP_TAB_TITLES["broadcasts"] in readiness.window_line
    lines: tuple[str, ...] = readiness.template_lines
    assert lines[-1] == msg.CONFIG_CHANNELS_TEMPLATE
    assert len(lines) == len(msg.CONFIG_CHANNELS_FIELDS) + 1
    body: str = NEWLINE.join(lines[:-1])
    assert msg.CONFIG_LANGUAGES_RULE in body and "public, unlisted" in body and "youtube" in body


def test_a_missing_config_field_brings_the_template_for_the_log(livecraft_paths: LivecraftPaths) -> None:
    _copy_configs(livecraft_paths)
    data: dict[str, Any] = json.loads(livecraft_paths.file(FileName.CONFIG).read_text(encoding=TEXT_ENCODING))
    del data["timezone"]
    livecraft_paths.file(FileName.CONFIG).write_text(json.dumps(data, ensure_ascii=False), encoding=TEXT_ENCODING)
    readiness: Readiness = Readiness.check(livecraft_paths)
    assert readiness.settings.error is not None and readiness.settings.error.key_path == "timezone"
    assert readiness.template_lines == (SETTINGS_TEMPLATE,)


# --- готово


def test_everything_the_working_lines_need_is_ready(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = _announcing(ready_paths)
    assert readiness.is_ready
    assert readiness.warnings == () and readiness.template_lines == ()
    assert readiness.window_line == msg.SETUP_READY
    assert readiness.vault.load is not None and readiness.vault.load.token_state is VaultLayerState.READ


def test_the_window_is_ready_by_the_working_lines_like_the_run(ready_paths: LivecraftPaths) -> None:
    """Всё настроено, кроме формы, папки Диска и бота: линии, которым они нужны, не готовы — окно не «готово» (§14
    решение 37); выключены они — «готово»."""
    readiness: Readiness = Readiness.check(ready_paths)
    assert not readiness.is_ready and readiness.window_line == NEWLINE.join(readiness.for_run().lines)
    set_lines(ready_paths, lines_on(RunPart.PLAN, RunPart.LOCAL_PREVIEWS, RunPart.MERGE, RunPart.DOC_COPY))
    ready: Readiness = Readiness.check(ready_paths)
    assert ready.is_ready and ready.window_line == msg.SETUP_READY


def test_a_channel_owner_without_table_and_key_is_ready(ready_paths: LivecraftPaths) -> None:
    """Владелец канала без таблицы и ключа OpenAI: работают только эфиры (и ключи в форму) — «готово» (§13 задача 7.1)."""
    set_lines(ready_paths, lines_on(RunPart.BROADCAST, RunPart.KEYS))
    ready_paths.file(FileName.VAULT_TOKEN).unlink()
    readiness: Readiness = Readiness.check(ready_paths)
    vault: Vault | None = readiness.vault.vault
    assert vault is not None and vault.entries == {}
    assert readiness.is_ready and readiness.window_line == msg.SETUP_READY
    assert "ready=yes" in readiness.event.text


def test_the_summary_names_every_field_and_its_origin(ready_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines(FULL_RUN)
    assert lines[0] == msg.READINESS_SUMMARY_TITLE
    for field in TOKEN_VALUES:
        assert msg.READINESS_FIELD_LINE.format(label=field.human_label, origin=msg.VAULT_ORIGIN_TOKEN) in lines
    assert lines[-1] == msg.READINESS_CHANNELS_LINE.format(count=2, languages="ru, uk")


def test_the_summary_of_an_empty_vault_says_no_for_every_field(livecraft_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(livecraft_paths).summary_lines(FULL_RUN)
    for field in tuple(SecretField):
        assert msg.READINESS_FIELD_LINE.format(label=field.human_label, origin=msg.NONE_TEXT) in lines
    assert lines[-1] == msg.READINESS_CHANNELS_ABSENT


def test_an_own_value_shows_as_own_in_the_summary(ready_paths: LivecraftPaths) -> None:
    """Своё перекрывает значение из токена — сводка говорит «введено в окне настройки» у перекрытого поля (§7.3) и
    «получено с токеном» у остальных: слова «своё» и «из токена» человеку ничего не говорили (§13 задача 9.6)."""
    _save_own_sheets_id(ready_paths)
    readiness: Readiness = Readiness.check(ready_paths)
    assert msg.READINESS_FIELD_LINE.format(
        label=SecretField.SHEETS_ID.human_label, origin=msg.VAULT_ORIGIN_OWN
    ) in readiness.summary_lines(FULL_RUN)
    assert msg.READINESS_FIELD_LINE.format(
        label=SecretField.OPENAI_API_KEY.human_label, origin=msg.VAULT_ORIGIN_TOKEN
    ) in readiness.summary_lines(FULL_RUN)
    assert "  Google таблица контент-плана: введено в окне настройки" in readiness.summary_lines(FULL_RUN)
    assert "  ключ OpenAI: получено с токеном" in readiness.summary_lines(FULL_RUN)
    assert readiness.vault.load is not None and readiness.vault.load.local_state is VaultLayerState.READ


# --- личный сейф не читается: громко, но работа идёт


def test_an_unreadable_own_vault_warns_and_runs_on_token_values(ready_paths: LivecraftPaths) -> None:
    """§16: молчаливый откат недопустим — человек незаметно работал бы без своих значений."""
    _save_own_sheets_id(ready_paths)
    data: dict[str, Any] = json.loads(ready_paths.file(FileName.VAULT_LOCAL).read_text(encoding=TEXT_ENCODING))
    key: str = VaultFileKey.WRAPPED_KEY.value
    wrapped: bytes = base64.b64decode(data[key], validate=True)
    data[key] = base64.b64encode(wrapped[:-1] + bytes([wrapped[-1] ^ 0xFF])).decode("ascii")
    ready_paths.file(FileName.VAULT_LOCAL).write_text(json.dumps(data), encoding=TEXT_ENCODING)
    readiness: Readiness = Readiness.check(ready_paths)
    fields: str = msg.LIST_JOINER.join(field.human_label for field in tuple(SecretField))
    assert readiness.warnings == (msg.VAULT_LOCAL_UNREADABLE.format(fields=fields),)
    vault: Vault | None = readiness.vault.vault                # запуск идёт — на значениях из токена
    assert vault is not None and all(vault.origin_of(field) is VaultOrigin.TOKEN for field in TOKEN_VALUES)
    assert "local=unreadable" in readiness.event.text


def test_no_warning_without_an_own_vault(ready_paths: LivecraftPaths) -> None:
    assert Readiness.check(ready_paths).warnings == ()


# --- файл сейфа чужого формата


def test_a_vault_file_of_an_unknown_format_is_named(ready_paths: LivecraftPaths) -> None:
    """§7.3: неизвестная версия формата — ошибка с именем файла и код 2, а не тихое игнорирование."""
    ready_paths.file(FileName.VAULT_LOCAL).write_text(
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
    assert ready_paths.file(FileName.VAULT_LOCAL).name in readiness.window_line
    assert msg.VAULT_FILE_ADVICE_LOCAL in readiness.window_line
    assert error.detail not in readiness.window_line
    assert "vault=broken" in readiness.event.text


def _assert_broken_local_file(paths: LivecraftPaths, readiness: Readiness) -> None:
    """Повреждённый личный файл — не «чужой сейф»: отказ с именем файла, а не предупреждение."""
    assert not readiness.is_ready
    assert readiness.vault.error is not None and readiness.vault.vault is None
    assert paths.file(FileName.VAULT_LOCAL).name in readiness.window_line
    assert readiness.warnings == ()


def test_a_local_vault_file_that_is_not_utf8_stops_the_run(ready_paths: LivecraftPaths) -> None:
    ready_paths.file(FileName.VAULT_LOCAL).write_bytes(NOT_UTF8_BYTES)
    _assert_broken_local_file(ready_paths, Readiness.check(ready_paths))


def test_a_local_vault_file_that_does_not_open_stops_the_run(ready_paths: LivecraftPaths) -> None:
    ready_paths.file(FileName.VAULT_LOCAL).mkdir()
    _assert_broken_local_file(ready_paths, Readiness.check(ready_paths))


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
    for value in (*TOKEN_VALUES.values(), OWN_SHEETS_ID):     # и перекрытое поставочное тоже
        assert value not in text


def test_no_value_leaves_readiness_when_things_are_broken(ready_paths: LivecraftPaths) -> None:
    """И при поломке: удалили одно поле из токена — строка нужды и сводка говорят о поле, не о значениях."""
    write_token_vault(ready_paths, {k: v for k, v in TOKEN_VALUES.items() if k is not SecretField.SHEETS_ID})
    readiness: Readiness = Readiness.check(ready_paths)
    assert not readiness.is_ready
    text: str = _every_text(readiness)
    for value in TOKEN_VALUES.values():
        assert value not in text
    assert SecretField.SHEETS_ID.human_label in readiness.window_line


def test_without_the_form_url_only_the_lines_that_need_it_wait(ready_paths: LivecraftPaths) -> None:
    """form.url пуст — пакету, документу, объявлениям и ключам не хватает формы (§14 решение 15); таблице — нет."""
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.settings.value is not None and not readiness.settings.value.form.is_configured
    assert readiness.gap(Need.FORM) is not None
    assert readiness.part(RunPart.PLAN, ALL_LINES).state is PartState.READY


def test_the_log_line_carries_labels_and_state_only(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.vault.vault is not None
    line: str = readiness.event.text
    assert line.startswith("readiness settings=ok channels=2 local=absent vault=")
    assert readiness.vault.vault.log_line in line
    assert line.endswith(" ready=no")                          # формы, папки Диска и бота ещё нет
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

def _write_form_url(paths: LivecraftPaths, url: str) -> None:
    """Ссылка в файле как есть, в обход разбора: так в файле оказывается и негодная ссылка."""
    data: dict[str, Any] = json.loads(paths.file(FileName.CONFIG).read_text(encoding=TEXT_ENCODING))
    data["form"]["url"] = url
    paths.file(FileName.CONFIG).write_text(json.dumps(data, ensure_ascii=False), encoding=TEXT_ENCODING)


def test_the_summary_says_the_form_is_not_configured_on_the_shipped_settings(ready_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines(FULL_RUN)
    assert msg.READINESS_FIELD_LINE.format(label=msg.FORM_URL_LABEL, origin=msg.READINESS_FORM_NOT_CONFIGURED) in lines
    assert lines[-1] == msg.READINESS_CHANNELS_LINE.format(count=2, languages="ru, uk")


def _source_line(origin: str) -> str:
    return msg.READINESS_FIELD_LINE.format(label=msg.READINESS_TEXTS_LABEL, origin=origin)


def _resend_line(origin: str) -> str:
    return msg.READINESS_FIELD_LINE.format(label=msg.READINESS_RESEND_KEYS_LABEL, origin=origin)


def test_the_summary_names_the_texts_and_the_resend_of_the_shipped_settings(ready_paths: LivecraftPaths) -> None:
    """Всё включено (§14 решения 36, 50): тексты — от нейросети, повторная передача выключена."""
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines(FULL_RUN)
    assert _source_line("от нейросети") in lines and _resend_line("выключена") in lines


def test_the_summary_says_the_keys_go_out_when_resend_is_on(ready_paths: LivecraftPaths) -> None:
    SettingsFile.of(ready_paths).save_broadcasts(BroadcastSettings(resend_keys=True))
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines(FULL_RUN)
    assert _resend_line("включена — ключи уйдут при этом запуске") in lines


def test_the_summary_of_a_dry_run_says_the_keys_do_not_go_out(ready_paths: LivecraftPaths) -> None:
    SettingsFile.of(ready_paths).save_broadcasts(BroadcastSettings(resend_keys=True))
    dry: RunScope = RunScope(parts=frozenset(LINE_ORDER), dry_run=True)
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines(dry)
    assert _resend_line("включена — в пробном запуске ключи не уходят") in lines
    assert msg.READINESS_RESEND_KEYS_ON not in NEWLINE.join(lines)


def test_the_summary_names_the_texts_by_the_lines_of_the_run(ready_paths: LivecraftPaths) -> None:
    """Откуда тексты — по линиям запуска (`RunTexts`, §14 решение 50): таблица без нейросети — тексты видео, вход
    «Пакеты» — из пакетов."""
    without_ai: RunScope = RunScope(parts=frozenset(LINE_ORDER) - {RunPart.MERGE})
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines(without_ai)
    assert _source_line(msg.RUN_TEXT_SOURCES["videos"]) in lines
    packages: RunScope = RunScope(parts=frozenset({RunPart.PACKAGES_IN, RunPart.DOC}))
    assert _source_line("из пакетов") in Readiness.check(ready_paths).summary_lines(packages)


@pytest.mark.parametrize("url", ["https://docs.google.com]/forms/x", "https://[bad"])
def test_an_unparsable_form_url_is_a_settings_problem_not_a_crash(ready_paths: LivecraftPaths, url: str) -> None:
    _write_form_url(ready_paths, url)
    readiness: Readiness = Readiness.check(ready_paths)
    error: ConfigError | None = readiness.settings.error
    assert readiness.settings.value is None and error is not None
    assert (error.key_path, error.problem) == ("form.url", msg.CONFIG_PROBLEM_FORM_URL)


def test_the_summary_says_the_form_is_configured_and_hides_the_link(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = _configured(ready_paths)
    lines: tuple[str, ...] = readiness.summary_lines(FULL_RUN)
    assert msg.READINESS_FIELD_LINE.format(label=msg.FORM_URL_LABEL, origin=msg.READINESS_FORM_CONFIGURED) in lines
    assert FORM_URL not in NEWLINE.join(lines) + readiness.event.text


def test_without_readable_settings_there_is_no_form_line(livecraft_paths: LivecraftPaths) -> None:
    lines: tuple[str, ...] = Readiness.check(livecraft_paths).summary_lines(FULL_RUN)
    assert not any(msg.FORM_URL_LABEL in line for line in lines)


# --- нужды частей: одна строка «что задать и где» на нужду (Readiness.gap)


def test_a_fully_configured_root_has_every_part_ready(ready_paths: LivecraftPaths) -> None:
    _with_telegram(ready_paths, TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, ""))
    readiness: Readiness = _configured(ready_paths)
    for need in Need:
        assert readiness.gap(need) is None
    for part in RunPart:
        state: PartReadiness = readiness.part(part, ALL_LINES)
        assert state.state is PartState.READY and state.unmet == ()


def test_without_channels_the_table_and_package_are_ready_and_only_broadcasts_wait(ready_paths: LivecraftPaths) -> None:
    """Каналы нужны только эфирам: без них таблица и пакет готовы, а об эфирах — одна строка «задайте каналы»."""
    set_form_url(ready_paths, FORM_URL)
    ready_paths.file(FileName.CHANNELS).unlink()
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.part(RunPart.PLAN, ALL_LINES).state is PartState.READY
    assert readiness.part(RunPart.PACKAGE, ALL_LINES).state is PartState.READY
    assert readiness.part(RunPart.BROADCAST, ALL_LINES).state is PartState.BLOCKED
    gap: NeedGap | None = readiness.gap(Need.CHANNELS)
    text: str = msg.READINESS_GAP_IN_SETUP.format(what=msg.READINESS_GAP_CHANNELS_MISSING, tab=msg.SETUP_TAB_TITLES["broadcasts"])
    assert gap == NeedGap(Need.CHANNELS, text, msg.READINESS_GAP_CHANNELS_MISSING)
    mode: ModeReadiness = readiness.for_run()
    assert msg.RUN_NEED_BLOCKED.format(parts=RunPart.BROADCAST.human_label, gap=text) in mode.lines
    basis: RunBasis | None = readiness.run_basis(mode, dry_run=False)
    assert basis is not None and basis.channels is None and not basis.runs(RunPart.KEYS)


def test_without_the_openai_key_only_the_merge_waits(ready_paths: LivecraftPaths) -> None:
    """Без ключа OpenAI нейросеть не готова — одна строка «Не готово», исход — ошибка, таблица прогоняется без merge,
    а пакет от таблицы без нейросети не идёт (§14 решение 50)."""
    _set_links(ready_paths)
    _with_private_chat(ready_paths)
    write_token_vault(ready_paths, {k: v for k, v in TOKEN_VALUES.items() if k is not SecretField.OPENAI_API_KEY})
    readiness: Readiness = Readiness.check(ready_paths)
    gap: NeedGap | None = readiness.gap(Need.OPENAI_VAULT)
    assert gap is not None and readiness.part(RunPart.MERGE, ALL_LINES).state is PartState.BLOCKED
    assert gap.what == SecretField.OPENAI_API_KEY.human_label and gap.window_text == gap.what
    with_llm: ModeReadiness = readiness.for_run()
    assert [part.part for part in with_llm.in_state(PartState.BLOCKED)] == [RunPart.MERGE]
    assert with_llm.lines[0] == msg.RUN_NEED_BLOCKED.format(parts=RunPart.MERGE.human_label, gap=gap.text)
    assert with_llm.step is ModeStep.RUN_PLAN and with_llm.outcome is RunOutcome.FAILED
    basis: RunBasis | None = readiness.run_basis(with_llm, dry_run=False)
    assert basis is not None and not basis.runs(RunPart.MERGE) and not basis.runs(RunPart.PACKAGE)   # решение 50


def test_without_the_form_the_package_and_the_keys_wait(ready_paths: LivecraftPaths) -> None:
    readiness: Readiness = Readiness.check(ready_paths)       # поставочная ссылка на форму пуста
    state: PartReadiness = readiness.part(RunPart.PACKAGE, ALL_LINES)
    assert state.state is PartState.BLOCKED and [gap.need for gap in state.unmet] == [Need.FORM]
    assert _gaps_text(state) == msg.READINESS_GAP_IN_SETUP.format(what=msg.READINESS_GAP_FORM, tab=msg.SETUP_TAB_TITLES["keys"])
    assert readiness.part(RunPart.PLAN, ALL_LINES).state is PartState.READY
    assert readiness.part(RunPart.BROADCAST, ALL_LINES).state is PartState.READY          # эфирам форма не нужна
    assert [gap.need for gap in readiness.part(RunPart.KEYS, ALL_LINES).unmet] == [Need.FORM]


def test_without_the_drive_folder_only_the_drive_previews_and_the_document_wait(ready_paths: LivecraftPaths) -> None:
    """§14 решение 27: без папки Google Диска копиям превью и документу объявлений некуда ложиться — не готовы
    только эти части; копия документа не идёт без документа."""
    set_form_url(ready_paths, FORM_URL)                  # поставочная ссылка на папку пуста
    _with_private_chat(ready_paths)
    set_lines(ready_paths, lines_without(RunPart.BROADCAST, RunPart.KEYS))
    readiness: Readiness = Readiness.check(ready_paths)
    state: PartReadiness = readiness.part(RunPart.DRIVE_PREVIEWS, ALL_LINES)
    assert state.state is PartState.BLOCKED and [gap.need for gap in state.unmet] == [Need.DRIVE_FOLDER]
    assert _gaps_text(state) == msg.READINESS_GAP_IN_SETUP.format(
        what=msg.VAULT_FIELD_DRIVE_FOLDER, tab=msg.SETUP_TAB_TITLES["previews"]
    )
    mode: ModeReadiness = readiness.for_run()
    assert [part.part for part in mode.in_state(PartState.BLOCKED)] == [RunPart.DRIVE_PREVIEWS, RunPart.DOC]
    assert mode.step is ModeStep.RUN_PLAN and mode.outcome is RunOutcome.FAILED
    basis: RunBasis | None = readiness.run_basis(mode, dry_run=False)
    assert basis is not None and not basis.runs(RunPart.DRIVE_PREVIEWS) and not basis.runs(RunPart.DOC)
    assert not basis.runs(RunPart.DOC_COPY) and basis.runs(RunPart.LOCAL_PREVIEWS)
    set_drive_folder(ready_paths)
    configured: Readiness = Readiness.check(ready_paths)
    assert configured.gap(Need.DRIVE_FOLDER) is None
    ready_basis: RunBasis | None = configured.run_basis(configured.for_run(), dry_run=True)
    assert ready_basis is not None and ready_basis.runs(RunPart.DRIVE_PREVIEWS) and ready_basis.runs(RunPart.DOC_COPY)
    assert ready_basis.scope.dry_run


def test_without_client_secret_the_table_waits(ready_paths: LivecraftPaths) -> None:
    ready_paths.file(FileName.CLIENT_SECRET).unlink()
    readiness: Readiness = _configured(ready_paths)
    plan: PartReadiness = readiness.part(RunPart.PLAN, ALL_LINES)
    assert plan.state is PartState.BLOCKED
    assert _gaps_text(plan) == msg.READINESS_GAP_CLIENT_SECRET.format(path=ready_paths.file(FileName.CLIENT_SECRET))
    assert readiness.for_run().is_nothing_ready     # основа — таблица — не готова


def test_without_the_table_one_line_names_it(ready_paths: LivecraftPaths) -> None:
    """Нужда «сейф таблицы» — одна строка о таблице; диапазона она не требует (§14 решение 26)."""
    write_token_vault(ready_paths, {SecretField.OPENAI_API_KEY: TOKEN_VALUES[SecretField.OPENAI_API_KEY]})
    plan: PartReadiness = _configured(ready_paths).part(RunPart.PLAN, ALL_LINES)
    assert plan.state is PartState.BLOCKED and len(plan.unmet) == 1
    assert _gaps_text(plan) == msg.READINESS_GAP_IN_SETUP.format(
        what=SecretField.SHEETS_ID.human_label, tab=msg.SETUP_TAB_TITLES["plan"]
    )


def test_a_broken_settings_file_blocks_the_parts_that_need_it_with_the_key(ready_paths: LivecraftPaths) -> None:
    set_drive_folder(ready_paths)                      # папка Диска — в сейфе: сломанные настройки её не трогают
    _break_setting(ready_paths, "keep_days", 0)
    readiness: Readiness = Readiness.check(ready_paths)
    for part in (RunPart.PLAN, RunPart.PACKAGE):
        action: str = _gaps_text(readiness.part(part, ALL_LINES))
        assert "keep_days" in action and msg.SETUP_TAB_TITLES["advanced"] in action
    assert readiness.gap(Need.FORM) is None           # о сломанных настройках говорит их собственная нужда
    assert readiness.gap(Need.DRIVE_FOLDER) is None


def test_a_broken_settings_file_is_one_line_for_every_line_that_needs_it(ready_paths: LivecraftPaths) -> None:
    """Сломанный livecraft.json: линии — поставочные (все включены), одна строка про настройки, в ней все линии, которым
    нужны настройки, в порядке работы."""
    _break_setting(ready_paths, "keep_days", 0)
    mode: ModeReadiness = Readiness.check(ready_paths).for_run()
    settings_lines: list[str] = [line for line in mode.lines if "keep_days" in line]
    assert len(settings_lines) == 1
    labels: tuple[str, ...] = tuple(
        part.human_label for part in RunPart if Need.SETTINGS in part.needs and part is not RunPart.PACKAGES_IN
    )
    assert settings_lines[0] == msg.RUN_NEED_BLOCKED.format(
        parts=msg.LIST_JOINER.join(labels),
        gap=_gap_text(Readiness.check(ready_paths), Need.SETTINGS),
    )
    assert mode.step is ModeStep.OPEN_SETUP


def test_without_the_table_the_broadcasts_and_keys_do_not_need_the_form_of_the_settings(
    ready_paths: LivecraftPaths,
) -> None:
    """Ссылки на форму в настройках нет, таблица выключена: эфиры и ключи готовы — форма приходит в пакете."""
    set_lines(ready_paths, lines_on(RunPart.BROADCAST, RunPart.KEYS))
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.part(RunPart.KEYS, ALL_LINES).state is PartState.BLOCKED
    assert readiness.part(RunPart.KEYS, PACKAGE_LINES).state is PartState.READY
    assert readiness.part(RunPart.PACKAGES_IN, PACKAGE_LINES).state is PartState.READY
    mode: ModeReadiness = readiness.for_run()
    assert mode.step is ModeStep.RUN_PACKAGES and mode.runs(RunPart.PACKAGES_IN) and mode.outcome is RunOutcome.DONE
    assert mode.runs(RunPart.KEYS)


def test_the_announcements_with_everything_set_block_nothing(ready_paths: LivecraftPaths) -> None:
    set_lines(ready_paths, lines_without(RunPart.BROADCAST, RunPart.KEYS))
    mode: ModeReadiness = _announcing(ready_paths).for_run()
    assert [part.part for part in mode.in_state(PartState.READY)] == [
        RunPart.PLAN, RunPart.LOCAL_PREVIEWS, RunPart.DRIVE_PREVIEWS, RunPart.MERGE, RunPart.PACKAGE, RunPart.DOC,
        RunPart.DOC_COPY, RunPart.ANNOUNCE,
    ]
    assert mode.in_state(PartState.BLOCKED) == ()
    assert mode.lines == () and mode.outcome is RunOutcome.DONE
    assert not mode.is_nothing_ready
    assert mode.runs(RunPart.PLAN) and mode.runs(RunPart.MERGE) and not mode.runs(RunPart.BROADCAST)
    assert mode.event.text == (
        "mode_readiness ready=plan,local_previews,drive_previews,merge,package,doc,doc_copy,announce blocked=- "
        "runs=plan,local_previews,drive_previews,merge,package,doc,doc_copy,announce no_support=-"
    )


def test_the_broadcasts_from_packages_need_no_table_and_no_key(ready_paths: LivecraftPaths) -> None:
    """Вход «Пакеты»: таблица и ключ OpenAI не нужны; эфирам без client_secret.json не войти в каналы — они не готовы,
    ключи без них не идут; пакеты читаются — основа готова."""
    set_lines(ready_paths, lines_on(RunPart.BROADCAST, RunPart.KEYS))
    ready_paths.file(FileName.VAULT_TOKEN).unlink()
    ready_paths.file(FileName.CLIENT_SECRET).unlink()
    readiness: Readiness = _configured(ready_paths)
    mode: ModeReadiness = readiness.for_run()
    assert [part.part for part in mode.in_state(PartState.READY)] == [RunPart.PACKAGES_IN, RunPart.KEYS]
    [broadcast] = mode.in_state(PartState.BLOCKED)
    assert broadcast.part is RunPart.BROADCAST and [gap.need for gap in broadcast.unmet] == [Need.CLIENT_SECRET]
    assert mode.step is ModeStep.RUN_PACKAGES and mode.runs(RunPart.PACKAGES_IN) and not mode.runs(RunPart.KEYS)
    basis: RunBasis | None = readiness.run_basis(mode, dry_run=False)
    assert basis is not None and basis.channels is None


def test_a_clean_root_has_nothing_ready(livecraft_paths: LivecraftPaths) -> None:
    """Настроек нет — линии поставочные (все включены), основе не хватает настроек: не готово ничего."""
    state: ModeReadiness = Readiness.check(livecraft_paths).for_run()
    assert state.is_nothing_ready and state.step is ModeStep.OPEN_SETUP


def test_no_line_on_opens_the_window_with_one_line(ready_paths: LivecraftPaths) -> None:
    set_lines(ready_paths, lines_on())
    mode: ModeReadiness = _configured(ready_paths).for_run()
    assert mode.step is ModeStep.OPEN_SETUP and mode.lines == (msg.LINES_NONE_WORKING,)


def _labels(*parts: RunPart) -> str:
    return msg.LIST_JOINER.join(part.human_label for part in parts)


def test_the_need_lines_follow_the_work_order(ready_paths: LivecraftPaths) -> None:
    """Нужда нескольких частей — одна строка на месте первой из них, в строке — все её части."""
    ready_paths.file(FileName.CHANNELS).unlink()
    readiness: Readiness = Readiness.check(ready_paths)
    mode: ModeReadiness = readiness.for_run()
    assert mode.lines == (
        msg.RUN_NEED_BLOCKED.format(
            parts=_labels(RunPart.DRIVE_PREVIEWS, RunPart.DOC), gap=_gap_text(readiness, Need.DRIVE_FOLDER)
        ),
        msg.RUN_NEED_BLOCKED.format(
            parts=_labels(RunPart.PACKAGE, RunPart.DOC, RunPart.ANNOUNCE, RunPart.KEYS), gap=_gap_text(readiness, Need.FORM)
        ),
        msg.RUN_NEED_BLOCKED.format(parts=_labels(RunPart.ANNOUNCE), gap=_gap_text(readiness, Need.TELEGRAM)),
        msg.RUN_NEED_BLOCKED.format(parts=_labels(RunPart.BROADCAST), gap=_gap_text(readiness, Need.CHANNELS)),
    )


@pytest.mark.parametrize(("name", "advice"), [
    (FileName.VAULT_LOCAL, msg.VAULT_FILE_ADVICE_LOCAL), (FileName.VAULT_TOKEN, msg.VAULT_FILE_ADVICE_TOKEN),
])
def test_a_broken_vault_file_blocks_the_table_and_opens_the_window(
    ready_paths: LivecraftPaths, name: FileName, advice: str
) -> None:
    """Свой повреждённый файл окно заменяет сохранением, файл токена — загрузкой токена: окно открывается всегда."""
    _set_links(ready_paths)
    ready_paths.file(name).write_bytes(NOT_UTF8_BYTES)
    readiness: Readiness = Readiness.check(ready_paths)
    mode: ModeReadiness = readiness.for_run()
    assert mode.is_nothing_ready and mode.step is ModeStep.OPEN_SETUP
    assert readiness.vault.error is not None
    gap: str = msg.READINESS_GAP_VAULT_BROKEN.format(problem=readiness.vault.error.problem, advice=advice)
    assert _gaps_text(mode.parts[0]) == gap
    assert ready_paths.file(name).name in gap


# --- строка готовности окна настройщика: окно уже открыто


def test_the_window_line_names_the_tab_to_fix_the_settings(ready_paths: LivecraftPaths) -> None:
    _break_setting(ready_paths, "keep_days", 0)
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.settings.error is not None
    assert _gap_text(readiness, Need.SETTINGS) in readiness.window_line
    assert msg.SETUP_TAB_TITLES["advanced"] in readiness.window_line


# --- что делает запуск (ModeReadiness.step), с чем идёт прогон и что уходит в лог


def test_a_clean_root_opens_the_setup_window(livecraft_paths: LivecraftPaths) -> None:
    mode: ModeReadiness = Readiness.check(livecraft_paths).for_run()
    assert mode.step is ModeStep.OPEN_SETUP


def test_a_ready_table_runs_the_plan_and_a_missing_form_fails_the_package(ready_paths: LivecraftPaths) -> None:
    """Таблица готова — прогон; без ссылок на форму и папку Диска пакет и превью не готовы — исход «ошибка»
    (код 1)."""
    unformed: ModeReadiness = Readiness.check(ready_paths).for_run()
    assert unformed.step is ModeStep.RUN_PLAN and unformed.outcome is RunOutcome.FAILED
    formed: ModeReadiness = _announcing(ready_paths).for_run()
    assert formed.step is ModeStep.RUN_PLAN and formed.outcome is RunOutcome.DONE


def test_without_the_table_the_run_gets_the_settings_and_the_channels(ready_paths: LivecraftPaths) -> None:
    """Вход «Пакеты»: работе — настройки, сейф и каналы (эфиры идут)."""
    set_lines(ready_paths, lines_on(RunPart.BROADCAST, RunPart.KEYS))
    readiness: Readiness = _configured(ready_paths)
    mode: ModeReadiness = readiness.for_run()
    assert mode.step is ModeStep.RUN_PACKAGES and mode.outcome is RunOutcome.DONE
    basis: RunBasis | None = readiness.run_basis(mode, dry_run=False)
    assert basis is not None and basis.settings == readiness.settings.value
    assert basis.channels == readiness.channels.value


def test_without_the_table_and_the_broadcasts_the_output_runs_without_channels(ready_paths: LivecraftPaths) -> None:
    """Вход «Пакеты» только с пакетом: пакеты читаются, каналов у работы нет — эфиры не идут; форма настроек не нужна
    (§14 решение 51)."""
    set_lines(ready_paths, lines_on(RunPart.PACKAGE))
    readiness: Readiness = Readiness.check(ready_paths)       # поставочная ссылка на форму пуста
    mode: ModeReadiness = readiness.for_run()
    assert mode.step is ModeStep.RUN_PACKAGES and mode.outcome is RunOutcome.DONE
    basis: RunBasis | None = readiness.run_basis(mode, dry_run=False)
    assert basis is not None and basis.channels is None
    assert basis.scope.parts == frozenset({RunPart.PACKAGES_IN, RunPart.PACKAGE})


def test_a_broken_vault_leaves_the_packages_an_empty_vault(ready_paths: LivecraftPaths) -> None:
    """Вход «Пакеты» не требует сейфа: он не читается — работе пустой сейф, частям, которым он нужен, не хватает нужд."""
    set_lines(ready_paths, lines_on(RunPart.PACKAGE))
    ready_paths.file(FileName.VAULT_TOKEN).write_text("{", encoding=TEXT_ENCODING)
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.vault.vault is None
    basis: RunBasis | None = readiness.run_basis(readiness.for_run(), dry_run=False)
    assert basis is not None and basis.vault == Vault.empty() and basis.runs(RunPart.PACKAGE)


# --- служебные запуски по каналам (--check, --auth, --status): только свои нужды


@pytest.mark.parametrize("mode", [RunMode.CHECK, RunMode.AUTH, RunMode.STATUS])
def test_a_channel_service_needs_no_vault_and_no_form(ready_paths: LivecraftPaths, mode: RunMode) -> None:
    """Сейфа нет, ссылки на форму нет — служебному запуску по каналам хватает каналов, настроек и client_secret.json."""
    ready_paths.file(FileName.VAULT_TOKEN).unlink()
    readiness: Readiness = Readiness.check(ready_paths)
    service: ServiceReadiness = ServiceReadiness(readiness, mode)
    assert service.lines == ()
    assert service.basis == ChannelBasis.of(readiness) and service.basis is not None


def test_a_channel_service_names_each_missing_need(livecraft_paths: LivecraftPaths) -> None:
    """Чистый корень: нет каналов, настроек и client_secret.json — строка на каждую нужду, основы нет."""
    readiness: Readiness = Readiness.check(livecraft_paths)
    service: ServiceReadiness = ServiceReadiness(readiness, RunMode.CHECK)
    gaps: tuple[str, ...] = tuple(_gap_text(readiness, need) for need in RunMode.CHECK.service_needs)
    assert service.lines == tuple(msg.SERVICE_NEED_BLOCKED.format(gap=gap) for gap in gaps)
    secret: NeedGap | None = readiness.gap(Need.CLIENT_SECRET)
    assert secret is not None and secret.what is None and secret.window_text == secret.text    # у строки нет вкладки
    assert service.basis is None


def test_a_ready_table_gives_the_run_its_settings_vault_and_parts_at_once(ready_paths: LivecraftPaths) -> None:
    """Прогону — настройки, сейф и части, которые идут: с ключом OpenAI merge идёт; без ссылок на папку Диска и форму
    и без бота — ни превью на Диске, ни документа, ни пакета, ни Telegram, ни ключей в форму."""
    readiness: Readiness = Readiness.check(ready_paths)
    basis: RunBasis | None = readiness.run_basis(readiness.for_run(), dry_run=False)
    expected: RunBasis = RunBasis(
        settings=readiness.settings.value,  # type: ignore[arg-type]
        vault=readiness.vault.vault,  # type: ignore[arg-type]
        scope=RunScope(
            parts=frozenset({RunPart.PLAN, RunPart.LOCAL_PREVIEWS, RunPart.MERGE, RunPart.BROADCAST}), dry_run=False
        ),
        channels=readiness.channels.value,
    )
    assert basis == expected


def test_the_broadcasts_get_the_channels_only_when_they_run(ready_paths: LivecraftPaths) -> None:
    """Каналы — прогону эфиров, когда их линия идёт; линия выключена — каналов нет."""
    readiness: Readiness = _configured(ready_paths)
    basis: RunBasis | None = readiness.run_basis(readiness.for_run(), dry_run=False)
    assert basis is not None and basis.channels == readiness.channels.value
    set_lines(ready_paths, lines_without(RunPart.BROADCAST, RunPart.KEYS))
    announcing: Readiness = Readiness.check(ready_paths)
    announce: RunBasis | None = announcing.run_basis(announcing.for_run(), dry_run=False)
    assert announce is not None and announce.channels is None


def test_a_run_without_any_line_gets_no_basis(ready_paths: LivecraftPaths) -> None:
    set_lines(ready_paths, lines_on(RunPart.MERGE))          # нейросеть без таблицы не работает
    ready: Readiness = _configured(ready_paths)
    assert ready.run_basis(ready.for_run(), dry_run=False) is None


def test_a_table_that_is_not_ready_gets_no_plan_run(livecraft_paths: LivecraftPaths) -> None:
    clean: Readiness = Readiness.check(livecraft_paths)
    assert clean.run_basis(clean.for_run(), dry_run=False) is None


# --- папки ролей из настроек (§14 решение 37)


def test_the_folders_of_the_settings_go_into_the_paths(ready_paths: LivecraftPaths, tmp_path: Path) -> None:
    """Относительная папка — от корня программы, абсолютная — как есть; остальные роли — по имени в корне."""
    outside: Path = tmp_path / "elsewhere" / "packages"
    set_folders(ready_paths, FolderSettings(packages=str(outside), docs="copies/docs", images="image"))
    paths: LivecraftPaths = Readiness.check(ready_paths).paths
    assert paths.bcast_dir == outside
    assert paths.dir(DataDir.DOCS) == ready_paths.root / "copies" / "docs"
    assert paths.dir(DataDir.IMAGE) == ready_paths.root / "image"
    assert paths.logs_dir == ready_paths.logs_dir and paths.root == ready_paths.root
    assert paths.shown(outside / "plan.bcast") == str(outside / "plan.bcast")


def test_unreadable_settings_keep_the_folders_by_their_names(ready_paths: LivecraftPaths) -> None:
    ready_paths.file(FileName.CONFIG).write_bytes(b"{ broken")
    assert Readiness.check(ready_paths).paths == LivecraftPaths(ready_paths.root)


# --- сводка и снимок запуска (§14 решения 37, 38)


def test_the_summary_names_the_working_and_the_switched_off_lines(ready_paths: LivecraftPaths) -> None:
    set_lines(ready_paths, lines_without(RunPart.ANNOUNCE))
    lines: tuple[str, ...] = Readiness.check(ready_paths).summary_lines(FULL_RUN)
    assert lines[1].startswith("  линии работы: Таблица плана, Нейросеть, ") and "Telegram" not in lines[1]
    assert lines[2] == msg.READINESS_LINES_OFF.format(lines="Telegram")


def test_the_snapshot_is_five_events_without_a_value_of_the_vault(ready_paths: LivecraftPaths) -> None:
    """Настройки целиком, линии, папки, каналы (с тем, есть ли файл токена) и сейф — ярлыками с отпечатками."""
    readiness: Readiness = _configured(ready_paths)
    events: tuple[str, ...] = tuple(event.text for event in RunSnapshot(readiness).events)
    assert [text.split(" ", 1)[0] for text in events] == [
        "run_snapshot_settings", "run_snapshot_lines", "run_snapshot_folders", "run_snapshot_channels",
        "run_snapshot_vault",
    ]
    assert FORM_URL in events[0] and '\\"lines\\"' in events[0] and "Язык стрима" in events[0]
    assert f"packages={ready_paths.bcast_dir} docs={ready_paths.dir(DataDir.DOCS)} " in events[2]
    assert '\\"handle\\": \\"@kanal_ua\\"' in events[3] and '\\"token\\": false' in events[3]
    vault: Vault | None = readiness.vault.vault
    assert vault is not None and vault.log_line in events[4]
    text: str = NEWLINE.join(events)
    for value in TOKEN_VALUES.values():
        assert value not in text and repr(value) not in text


def test_the_snapshot_of_unreadable_files_says_error(livecraft_paths: LivecraftPaths) -> None:
    events: tuple[str, ...] = tuple(event.text for event in RunSnapshot(Readiness.check(livecraft_paths)).events)
    assert events[0] == "run_snapshot_settings settings=error"
    assert events[3] == "run_snapshot_channels channels=error"


def _logged(readiness: Readiness) -> list[str]:
    with LogCapture.on(LogArea.MAIN) as capture:
        readiness.log(get_logger(LogArea.MAIN))
    return capture.messages()


def test_the_log_names_missing_files_and_broken_fields_without_values(livecraft_paths: LivecraftPaths) -> None:
    """Нет файла — «ещё не настроено» (INFO); сломанное поле — ключ, вид и причина (ERROR) и шаблон (DEBUG)."""
    livecraft_paths.file(FileName.CONFIG).write_text("{}", encoding=TEXT_ENCODING)
    readiness: Readiness = Readiness.check(livecraft_paths)
    lines: list[str] = _logged(readiness)
    assert lines[0] == readiness.event.text and lines[0].endswith(" ready=no")
    assert any(line.startswith(f"config_error path={livecraft_paths.file(FileName.CONFIG)} key=") for line in lines)
    assert f"config_missing path={livecraft_paths.file(FileName.CHANNELS)}" in lines
    assert any(line.startswith("config_template template=") for line in lines)


def test_the_log_names_a_broken_vault_file_with_its_reason(ready_paths: LivecraftPaths) -> None:
    ready_paths.file(FileName.VAULT_TOKEN).write_text("{", encoding=TEXT_ENCODING)
    lines: list[str] = _logged(Readiness.check(ready_paths))
    vault_line: str = "vault_error file=vault.token.dat source=token reason=damaged detail=vault file is not valid JSON"
    assert any(line.startswith(vault_line) for line in lines)
    for value in TOKEN_VALUES.values():
        assert value not in NEWLINE.join(lines)


# --- токен бота Telegram необязателен (§13 задача 4.1)


def test_without_announcements_no_bot_is_needed_and_the_summary_says_none(ready_paths: LivecraftPaths) -> None:
    """Объявления в Telegram выключены — бот не нужен: окно — «готово», строка лога — ready=yes, сводка — токен «нет»."""
    set_lines(ready_paths, lines_without(RunPart.ANNOUNCE))
    readiness: Readiness = _configured(ready_paths)
    vault: Vault | None = readiness.vault.vault
    assert vault is not None and vault.get(SecretField.TELEGRAM_BOT_TOKEN) is None
    assert readiness.is_ready and readiness.window_line == msg.SETUP_READY
    assert "ready=yes" in readiness.event.text
    label: str = msg.VAULT_FIELD_TELEGRAM_BOT_TOKEN
    assert msg.READINESS_FIELD_LINE.format(label=label, origin=msg.NONE_TEXT) in readiness.summary_lines(FULL_RUN)


def test_an_own_bot_token_shows_as_own_without_its_value(ready_paths: LivecraftPaths) -> None:
    save_own_values(ready_paths, {SecretField.TELEGRAM_BOT_TOKEN: BOT_TOKEN})
    readiness: Readiness = Readiness.check(ready_paths)
    label: str = msg.VAULT_FIELD_TELEGRAM_BOT_TOKEN
    own: str = msg.READINESS_FIELD_LINE.format(label=label, origin=msg.VAULT_ORIGIN_OWN)
    assert own in readiness.summary_lines(FULL_RUN)
    for text in (*readiness.summary_lines(FULL_RUN), readiness.event.text, readiness.window_line):
        assert BOT_TOKEN not in text


# --- Telegram (§14 решение 19): токен бота и чат выбранного назначения — нужда части «объявления в Telegram»

TELEGRAM_GAP: NeedGap = NeedGap(
    Need.TELEGRAM,
    msg.READINESS_GAP_IN_SETUP.format(what=msg.READINESS_GAP_TELEGRAM, tab=msg.SETUP_TAB_TITLES["telegram"]),
    msg.READINESS_GAP_TELEGRAM,
)


def test_without_a_bot_token_telegram_is_not_ready(ready_paths: LivecraftPaths) -> None:
    assert Readiness.check(ready_paths).gap(Need.TELEGRAM) == TELEGRAM_GAP


def test_a_token_without_the_chat_of_the_target_is_not_ready(ready_paths: LivecraftPaths) -> None:
    """Назначение — группа, а подключён только личный чат: объявлениям уходить некуда."""
    _with_telegram(ready_paths, TelegramSettings(ChatTarget.GROUP, "", PRIVATE_ID, ""))
    assert Readiness.check(ready_paths).gap(Need.TELEGRAM) == TELEGRAM_GAP


def test_a_token_and_the_chat_of_the_target_make_telegram_ready(ready_paths: LivecraftPaths) -> None:
    _with_telegram(ready_paths, TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, ""))
    assert Readiness.check(ready_paths).gap(Need.TELEGRAM) is None


def test_unreadable_settings_leave_telegram_without_a_chat(ready_paths: LivecraftPaths) -> None:
    _with_telegram(ready_paths, TelegramSettings(ChatTarget.PRIVATE, "", PRIVATE_ID, ""))
    ready_paths.file(FileName.CONFIG).write_bytes(b"{ broken")
    assert Readiness.check(ready_paths).gap(Need.TELEGRAM) == TELEGRAM_GAP


def test_a_broken_vault_file_is_the_telegram_gap_too(ready_paths: LivecraftPaths) -> None:
    ready_paths.file(FileName.VAULT_TOKEN).write_bytes(b"\xff\xfe\x00vault")
    readiness: Readiness = Readiness.check(ready_paths)
    assert readiness.vault.error is not None
    broken: str = msg.READINESS_GAP_VAULT_BROKEN.format(
        problem=readiness.vault.error.problem, advice=msg.VAULT_FILE_ADVICE_TOKEN
    )
    assert readiness.gap(Need.TELEGRAM) == NeedGap(Need.TELEGRAM, broken)          # сейф не задаётся в окне: вкладки нет


def test_telegram_is_needed_by_the_announce_part_only(ready_paths: LivecraftPaths) -> None:
    """Бот и чат нужны только объявлениям в Telegram: без них не готова только эта линия."""
    assert [part for part in RunPart if Need.TELEGRAM in part.needs] == [RunPart.ANNOUNCE]
    mode: ModeReadiness = _configured(ready_paths).for_run()
    assert [part.part for part in mode.in_state(PartState.BLOCKED)] == [RunPart.ANNOUNCE]


def test_without_the_bot_the_announce_part_waits_and_the_document_is_made(ready_paths: LivecraftPaths) -> None:
    """Режим «объявления» без бота: одна строка нужды Telegram, документ объявлений готов, прогон идёт, исход — ошибка
    (код 1); с ботом и чатом объявления в прогоне есть."""
    set_lines(ready_paths, lines_without(RunPart.BROADCAST, RunPart.KEYS))
    readiness: Readiness = _configured(ready_paths)
    mode: ModeReadiness = readiness.for_run()
    assert [part.part for part in mode.in_state(PartState.BLOCKED)] == [RunPart.ANNOUNCE]
    assert mode.lines == (msg.RUN_NEED_BLOCKED.format(parts=_labels(RunPart.ANNOUNCE), gap=TELEGRAM_GAP.text),)
    assert mode.step is ModeStep.RUN_PLAN and mode.outcome is RunOutcome.FAILED
    basis: RunBasis | None = readiness.run_basis(mode, dry_run=False)
    assert basis is not None and basis.runs(RunPart.DOC) and not basis.runs(RunPart.ANNOUNCE)
    announcing: Readiness = _announcing(ready_paths)
    ready_basis: RunBasis | None = announcing.run_basis(announcing.for_run(), dry_run=False)
    assert ready_basis is not None and ready_basis.runs(RunPart.DOC) and ready_basis.runs(RunPart.ANNOUNCE)


def test_without_the_form_the_announce_part_waits_for_it(ready_paths: LivecraftPaths) -> None:
    """Объявление ведёт стримеров к форме ключей: без ссылки на неё часть не готова, даже с ботом и чатом."""
    _with_private_chat(ready_paths)
    readiness: Readiness = Readiness.check(ready_paths)        # поставочная ссылка на форму пуста
    state: PartReadiness = readiness.part(RunPart.ANNOUNCE, ALL_LINES)
    assert state.state is PartState.BLOCKED and [gap.need for gap in state.unmet] == [Need.FORM]
