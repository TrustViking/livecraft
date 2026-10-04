# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec livecraft (CLAUDE.md §13 этап 8, §15). Лежит в корне репо, собирается build_release.bat из
единственного окружения .venv_livecraft.

Режим — одна папка (COLLECT): onefile распаковывался бы во временный каталог при каждом запуске. Точка входа одна —
app/main.py, exe два, на общих библиотеках одной папки:
  livecraft.exe  — консольный: ярлыки «Livecraft» и «пробный запуск» (через livecraft.bat), двойной щелчок по .bcast;
  livecraftw.exe — оконный, без консоли: ярлык «настройка» (--setup); отказ замка он показывает окном-сообщением.
Номер версии — только из app/version.py (печатается в лог сборки).

Иконка (§14 решение 53) — app/resources/icon/livecraft.ico: у обоих exe, от них — у ярлыков и файлов .bcast; она же в
datas (окно настройки ставит её себе, ResourceBundle.icon_file). Делается из картинки livecraft.png рядом с ней:
прозрачные поля срезаны, картинка по центру прозрачного квадрата, размеры 16–256. Новая картинка — та же команда из
корня репо:
  .\\.venv_livecraft\\Scripts\\python.exe -c "from PIL import Image; p=Image.open('app/resources/icon/livecraft.png'); c=p.crop(p.getbbox()); s=max(c.size); q=Image.new('RGBA',(s,s)); q.paste(c,((s-c.width)//2,(s-c.height)//2)); q.save('app/resources/icon/livecraft.ico',sizes=[(n,n) for n in (16,20,24,32,40,48,64,96,128,256)])"

tkinter в сборке нужен (окно настройщика, §8.1) — в excludes его нет, в отличие от planer.spec.
datas: тексты программы app/resources/text (TextResource читает их из sys._MEIPASS), база часовых поясов tzdata
(на Windows у Python своей нет, §14 решение 10) и документы описания API googleapiclient ровно четырёх API программы:
build(..., cache_discovery=False) берёт их из googleapiclient/discovery_cache/documents/. Остальные ~600 документов
(~100 МБ) вычищаются из a.datas; без любого из четырёх его линия отказывала бы только в собранной программе.
Конфигов, сейфа и прочих данных человека в сборке нет (§14 решение 16): client_secret.json и бинарники tools\\ кладёт
рядом с exe build_release.bat.
"""
import sys
from pathlib import Path

import googleapiclient
from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve()                 # SPECPATH — корень репо, где лежит livecraft.spec
sys.path.insert(0, str(ROOT))
from app.version import APP_VERSION  # noqa: E402  (печатается в лог сборки, чтобы версия была видна)

print(f"[livecraft.spec] APP_VERSION={APP_VERSION}")

DISCOVERY_DOCUMENTS = "googleapiclient/discovery_cache/documents"
API_DOCUMENTS = ("youtube.v3.json", "sheets.v4.json", "drive.v3.json", "docs.v1.json")
documents_dir = Path(googleapiclient.__file__).parent / "discovery_cache" / "documents"
TEXT_RESOURCES = "app/resources/text"
ICON_RESOURCES = "app/resources/icon"
ICON_FILE = ROOT / "app" / "resources" / "icon" / "livecraft.ico"


def _is_other_discovery_document(dest: str) -> bool:
    normalized = dest.replace("\\", "/")
    if not normalized.startswith(DISCOVERY_DOCUMENTS + "/"):
        return False
    return normalized.rsplit("/", 1)[-1] not in API_DOCUMENTS


a = Analysis(
    [str(ROOT / "app" / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        (str(ROOT / "app" / "resources" / "text"), TEXT_RESOURCES),
        (str(ICON_FILE), ICON_RESOURCES),
        *collect_data_files("tzdata"),
        *((str(documents_dir / name), DISCOVERY_DOCUMENTS) for name in API_DOCUMENTS),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest",
        "_pytest",
        "pluggy",
        "iniconfig",
        "pygments",
        "app.tests",
        "app.tools",
    ],
    noarchive=False,
)
a.datas = [entry for entry in a.datas if not _is_other_discovery_document(entry[0])]

pyz = PYZ(a.pure)


def _exe(name, console):
    return EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name=name,
        icon=str(ICON_FILE),
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=console,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )


console_exe = _exe("livecraft", True)
window_exe = _exe("livecraftw", False)

coll = COLLECT(
    console_exe,
    window_exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="livecraft",
)
