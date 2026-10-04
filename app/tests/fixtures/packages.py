"""Пакеты plan_*.bcast в тестах: настройки пакета без диска, настоящие JPEG-обложки, записи слотов и манифесты схемы 1
(как у planers `make_slot` / `make_package`) и архив из манифеста — годный или сломанный нарочно.

Момент тестов режима Б — 16.03.2027 12:00 по Киеву (как у контура B): 17.03.2027 — будущее, 15.03.2027 — прошлое.
"""
from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from PIL import Image

from app.config.files import ShippedSettings
from app.config.settings import LivecraftSettings
from app.tests.fixtures.settings import with_form_url

KYIV: ZoneInfo = ZoneInfo("Europe/Kyiv")
PACKAGE_NOW: datetime = datetime(2027, 3, 16, 12, 0, tzinfo=KYIV)
PACKAGE_FORM_URL: str = "https://docs.google.com/forms/d/e/1FAIpQLSf-package-form/viewform"
PACKAGE_SOURCE: str = "https://www.youtube.com/watch?v=abcdefghijk"


def package_settings(form_url: str) -> LivecraftSettings:
    """Поставочные настройки со ссылкой на форму ключей `form_url`; пустая ссылка — форма не настроена."""
    return with_form_url(ShippedSettings().settings, form_url)


def jpeg(width: int = 16, height: int = 9) -> bytes:
    """Настоящий JPEG этих размеров: обложку из пакета программа открывает картинкой."""
    output: io.BytesIO = io.BytesIO()
    Image.new("RGB", (width, height), (200, 30, 30)).save(output, format="JPEG")
    return output.getvalue()


def slot_record(
    date: str = "17-03-2027",
    time: str = "19:00",
    language: str = "uk",
    title: str = "Эфир из пакета",
    previews: Sequence[str] = (),
) -> dict[str, Any]:
    """Запись слота схемы 1: start — ISO-8601 по Киеву, slot_id — по дате, времени и языку."""
    start: datetime = datetime.strptime(f"{date} {time}", "%d-%m-%Y %H:%M").replace(tzinfo=KYIV)
    return {
        "slot_id": f"{date}_{time.replace(':', '')}_{language}",
        "date": date,
        "time": time,
        "start": start.isoformat(timespec="seconds"),
        "language": language,
        "title": title,
        "description": "Описание эфира из пакета",
        "previews": list(previews),
        "sources": [PACKAGE_SOURCE],
    }


def manifest(
    *slots: dict[str, Any], generated_at: str = "15-03-2027 10:00", form_url: str = PACKAGE_FORM_URL
) -> dict[str, Any]:
    """Манифест схемы 1 с формой поставки и ссылкой `form_url`."""
    return {
        "schema_version": 1,
        "package_id": "test-package",
        "generated_at": generated_at,
        "generator": {"project": "Livecraft", "version": "0.0.1", "run_id": "test-package"},
        "timezone": "Europe/Kyiv",
        "period": {"from": "17-03-2027", "to": "17-03-2027"},
        "form": package_settings(form_url).form.to_data(),
        "slots": list(slots),
    }


def write_package(
    folder: Path,
    content: Mapping[str, Any] | None = None,
    name: str = "plan_test.bcast",
    files: Mapping[str, bytes] | None = None,
) -> Path:
    """Архив пакета: manifest.json (по умолчанию — один будущий слот) и обложки; обложки, названные в записях слотов
    и не заданные в `files`, — настоящие JPEG."""
    body: Mapping[str, Any] = content if content is not None else manifest(slot_record())
    slots: Any = body.get("slots")
    records: list[Any] = slots if isinstance(slots, list) else []
    previews: dict[str, bytes] = {
        name: jpeg() for slot in records if isinstance(slot, dict) for name in slot.get("previews", [])
    }
    previews.update(files or {})
    folder.mkdir(parents=True, exist_ok=True)
    path: Path = folder / name
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("manifest.json", json.dumps(body, ensure_ascii=False))
        for file_name, data in previews.items():
            archive.writestr(file_name, data)
    return path
