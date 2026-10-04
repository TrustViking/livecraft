"""Какие линии пользуются полем окна (app\\setup\\fields\\field_use.py; CLAUDE.md §14 решения 37, 51): поле активно, если
работает хоть одна его линия и его нужду не закрывают сами пакеты, иначе бледное со строкой под ним."""
from __future__ import annotations

import pytest

from app.config.setting_key import SettingKey
from app.run.line_plan import LinePlan
from app.run.mode import LINE_ORDER, Need, RunPart
from app.secretsafe.field import SecretField
from app.setup.fields.field_use import FIELD_USES, FieldUse
from app.setup.fields.settings_draft import SettingsDraft
from app.ui import messages_ru as msg

ALL_ON: frozenset[RunPart] = frozenset(LINE_ORDER)
FORM_LINES: tuple[RunPart, ...] = (RunPart.DOC, RunPart.PACKAGE, RunPart.ANNOUNCE, RunPart.KEYS)


def _plan(*parts: RunPart) -> LinePlan:
    return LinePlan(frozenset(parts))


def _without(*parts: RunPart) -> LinePlan:
    return LinePlan(ALL_ON - frozenset(parts))


def test_the_form_is_used_by_the_package_the_document_telegram_and_the_keys() -> None:
    use: FieldUse = FieldUse.of(SettingKey.FORM_URL)
    assert use.lines == FORM_LINES
    assert use == FieldUse.of(Need.FORM)
    for part in FORM_LINES:
        assert use.is_active(_without(*(line for line in FORM_LINES if line is not part)))
    assert not use.is_active(_without(*FORM_LINES))
    assert use.note(_without(*FORM_LINES)) == msg.SETUP_FIELD_NEEDED_BY.format(
        lines="Google-документ, Пакет, Telegram, Ключи в форму"
    )
    assert use.note(LinePlan(ALL_ON)) == ""


def test_the_form_counts_a_line_only_while_it_works() -> None:
    """Пакет включён, но от таблицы без нейросети он не работает — форма ему не нужна."""
    use: FieldUse = FieldUse.of(SettingKey.FORM_URL)
    assert not use.is_active(_plan(RunPart.PLAN, RunPart.PACKAGE))
    assert use.is_active(_plan(RunPart.PLAN, RunPart.DOC))


@pytest.mark.parametrize("key", [SettingKey.FORM_URL, Need.FORM, Need.SHEETS_VAULT, SecretField.SHEETS_ID])
def test_with_the_packages_input_the_packages_meet_the_form_and_the_table(key: SettingKey | SecretField | Need) -> None:
    """Вход «Пакеты» (таблица выключена): форма ключей у каждого эфира — из его пакета, таблица не читается; поле
    бледное, строка под ним говорит, откуда нужда, хотя его линии работают."""
    use: FieldUse = FieldUse.of(key)
    plan: LinePlan = _plan(RunPart.PACKAGE, RunPart.DOC, RunPart.ANNOUNCE, RunPart.DRIVE_PREVIEWS, RunPart.KEYS)
    assert plan.source is RunPart.PACKAGES_IN and any(plan.works(part) for part in use.parts)
    assert not use.is_active(plan)
    need: Need | None = use.need
    assert need is not None and use.note(plan) == msg.SETUP_FIELD_FROM_PACKAGES[need.value]


@pytest.mark.parametrize("key", [
    SettingKey.LLM_MODEL, SettingKey.LLM_FALLBACK_MODEL, SettingKey.LLM_REASONING_EFFORT, SettingKey.LLM_SERVICE_TIER,
    SettingKey.LLM_TIMEOUT_SEC, SettingKey.LLM_MAX_OUTPUT_TOKENS,
])
def test_the_model_settings_are_pale_without_the_ai(key: SettingKey) -> None:
    use: FieldUse = FieldUse.of(key)
    assert use.lines == (RunPart.MERGE,)
    assert use.is_active(LinePlan(ALL_ON)) and not use.is_active(_without(RunPart.MERGE))
    assert use.note(_without(RunPart.MERGE)) == msg.SETUP_FIELD_NEEDED_BY.format(lines="Нейросеть")


def test_the_packages_folder_is_active_while_something_takes_or_writes_packages() -> None:
    """Без таблицы из папки пакетов берут слоты все линии (§14 решение 51); с таблицей её пишет пакет, а эфиры берут из
    неё известные слоты сверки; одной таблице без них папка не нужна."""
    use: FieldUse = FieldUse.of(SettingKey.FOLDERS_PACKAGES)
    assert use.is_active(_plan(RunPart.BROADCAST, RunPart.KEYS))
    assert use.is_active(_plan(RunPart.DOC))
    assert use.is_active(_plan(RunPart.PLAN, RunPart.MERGE, RunPart.PACKAGE))
    assert not use.is_active(_plan(RunPart.PLAN))
    assert not use.is_active(_plan(RunPart.KEYS))
    assert not use.is_active(_plan())


@pytest.mark.parametrize(("key", "line"), [
    (SettingKey.FOLDERS_IMAGES, RunPart.LOCAL_PREVIEWS),
    (SettingKey.IMAGE_DIR_TEMPLATE, RunPart.LOCAL_PREVIEWS),
    (SettingKey.DRIVE_PREVIEW_PATH_TEMPLATE, RunPart.DRIVE_PREVIEWS),
    (SettingKey.DOCS_ACCESS, RunPart.DOC),
    (SettingKey.DOCS_CONTACTS, RunPart.DOC),
    (SettingKey.FOLDERS_DOCS, RunPart.DOC_COPY),
    (SettingKey.CATEGORY_ID, RunPart.BROADCAST),
    (SettingKey.AUTO_START, RunPart.BROADCAST),
    (SettingKey.SET_THUMBNAIL, RunPart.BROADCAST),
    (SettingKey.MIN_LEAD_MINUTES, RunPart.BROADCAST),
    (SettingKey.YOUTUBE_PAUSE_SECONDS, RunPart.BROADCAST),
])
def test_a_field_named_by_its_line(key: SettingKey, line: RunPart) -> None:
    assert FieldUse.of(key).lines == (line,)


@pytest.mark.parametrize(("key", "lines"), [
    (Need.SHEETS_VAULT, (RunPart.PLAN, RunPart.DRIVE_PREVIEWS)),
    (SecretField.SHEETS_ID, (RunPart.PLAN, RunPart.DRIVE_PREVIEWS)),
    (SecretField.OPENAI_API_KEY, (RunPart.MERGE,)),
    (SecretField.TELEGRAM_BOT_TOKEN, (RunPart.ANNOUNCE,)),
    (Need.TELEGRAM, (RunPart.ANNOUNCE,)),
    (Need.CHANNELS, (RunPart.BROADCAST,)),
    (SecretField.DRIVE_FOLDER, (RunPart.DRIVE_PREVIEWS, RunPart.DOC)),
])
def test_a_field_of_a_need_is_used_by_every_line_that_needs_it(
    key: SettingKey | SecretField | Need, lines: tuple[RunPart, ...]
) -> None:
    assert FieldUse.of(key).lines == lines


@pytest.mark.parametrize("key", [SettingKey.TIMEZONE, SettingKey.KEEP_DAYS])
def test_the_time_zone_and_the_keep_days_are_needed_always(key: SettingKey) -> None:
    use: FieldUse = FieldUse.of(key)
    assert use.lines == () and use.is_active(_plan()) and use.note(_plan()) == ""


def test_every_field_of_the_window_has_its_lines() -> None:
    """Каждое поле дополнительных настроек, каждое поле сейфа и папка роли — со своими линиями."""
    keys: set[object] = {field.key for field in SettingsDraft.FIELDS}
    keys |= {SettingKey.FOLDERS_PACKAGES, SettingKey.FOLDERS_DOCS, SettingKey.FOLDERS_IMAGES}
    keys |= set(tuple(SecretField))
    assert keys <= set(FIELD_USES)
