# Livecraft

*English first; the Russian version follows below.*

Livecraft prepares YouTube live broadcasts end to end on one Windows computer. It reads a content plan from Google Sheets, collects the metadata and thumbnails of the source videos with yt-dlp, writes one title and one description per broadcast slot with an LLM (OpenAI), publishes announcements to Google Docs and Telegram, schedules the broadcasts on YouTube channels and hands the stream keys to the streamers through a Google Form.

## What it does

- **Two inputs.** The content plan (a Google Sheet: video link, date, time) or packages — `*.bcast` files written by another Livecraft run. A package lets a channel owner schedule the same broadcasts without the sheet and without the LLM.
- **Work lines.** The settings window has a switch for every line: content plan or packages, AI texts, thumbnails on disk and on Google Drive, the Google Doc of announcements and its `.docx` copy, the package, Telegram announcements, YouTube broadcasts, stream keys to the form. A run does exactly what is switched on.
- **Reconciliation with YouTube.** An existing broadcast is recognised by its start minute (UTC) and the slot marker in the stream title. Differences are fixed in place with the minimal set of API calls; broadcasts are never deleted automatically, and broadcasts that do not belong to any slot are never touched.
- **Stream keys** are read only from YouTube and sent only through the Google Form; every submission is checked against the form's confirmation page.
- **Results:** a short console summary, a Markdown report and a full debug log per run, and `keystreams\keys.txt` for manual handover.

Livecraft does not stream, does not run a schedule of its own (the plan lives in the sheet), does not accept commands in Telegram (it only sends) and does not store passwords.

## Requirements

- Windows 10 or 11 (the vault uses Windows DPAPI).
- From source: Python 3.13 and the packages from `requirements.txt` in the virtual environment `.venv_livecraft`.
- A Google Cloud OAuth client of type *Desktop*: `secrets\client_secret.json`.
- External binaries in `tools\`: `yt-dlp.exe` and `deno.exe` (Livecraft keeps them up to date itself).
- Depending on the lines you use: an OpenAI API key, a Telegram bot, a Google Sheet with the plan, a Google Drive folder, a Google Form for the keys, YouTube channels you can sign in to.

## Quick start from source

```powershell
py -3.13 -m venv .venv_livecraft
.\.venv_livecraft\Scripts\python.exe -m pip install -r requirements.txt
# put secrets\client_secret.json, tools\yt-dlp.exe and tools\deno.exe in place
.\livecraft.bat --setup      # settings window
.\livecraft.bat --dry-run    # trial run: reads everything, changes nothing outside
.\livecraft.bat              # run the lines that are switched on
```

Other commands: `--status` (broadcasts with the program marker, `keys.txt`, report), `--check` (channels: sign-in, handle, id), `--auth "@handle"` or `--auth all` (sign in to a channel again), `--debug`, `--version`. Opening a `.bcast` file copies it to the packages folder and starts a run.

Exit codes: `0` — everything that could be done is done; `1` — there are errors; `2` — configuration, vault or sign-in error, nothing was done; `3` — no future slots.

## Settings and secrets

- Secret values — the OpenAI key, the sheet id, the Telegram bot tokens, the Drive folder — are kept in an encrypted vault (AES-256-GCM; the key is wrapped with Windows DPAPI for the current Windows user, so a copied vault file is useless elsewhere). They never appear in the console, reports or logs.
- An **access token** (`*.lctoken`) passes values to another user, who can work with them but not read them. This protects against casual copying, not against a specialist: a program that uses a value has it in memory.
- Open settings: `secrets\livecraft.json` (created from the shipped template on the first run) and `secrets\channels.json` (channels: handle, Google account hint, language, visibility).
- The repository contains no personal data: `secrets\`, logs, packages, tokens and the other data folders are ignored by git.

## Data folders

Next to `livecraft.exe` (or in the repository root when run from source): `secrets\` — vault and settings, `tools\` — external binaries, `image\` — thumbnails, `bcast\` — packages, `docs\` — `.docx` copies of the announcement documents, `tokens\` — created access tokens, `keystreams\` — stream keys, `state\` — lock file and caches, `logs\` — reports and logs.

## Interface languages

The settings window and the console speak Russian, Ukrainian or English, chosen by the Windows display language. Texts for broadcasts and announcements follow the language of each slot.

## Development

- Tests: `.\.venv_livecraft\Scripts\python.exe -m pytest app\tests -q`
- Code standard (rules E1–E21, layered imports, no new or grown violations): `.\.venv_livecraft\Scripts\python.exe -m app.tools.code_standard`
- Design: domain objects own their rules (OOP); `StreamSlot` (`app\slots\`) is the only seam between contour A (plan → slots: sheet, sources, LLM, announcements) and contour B (slots → YouTube broadcasts, form, memory).
- Build: `build_release.bat` (PyInstaller and Inno Setup) → `dist\livecraft\` and the installer `dist\installer\livecraft-setup-<version>.exe`; the default install folder is `%LOCALAPPDATA%\Programs\Livecraft`.


---

# Livecraft

Livecraft готовит эфиры YouTube «под ключ» на одном компьютере с Windows. Программа читает план стримов из Google Таблицы, собирает данные и превью исходных видео через yt-dlp, пишет нейросетью (OpenAI) одно название и одно описание на слот эфира, публикует объявления в Google Docs и Telegram, ставит эфиры на каналах YouTube и передаёт ключи потоков стримерам через Google-форму.

## Что делает

- **Два входа.** План стримов (Google Таблица: ссылка на видео, дата, время) или пакеты — файлы `*.bcast`, которые пишет другой запуск Livecraft. По пакету владелец канала ставит те же эфиры без таблицы и без нейросети.
- **Линии работы.** В окне настройки у каждой линии свой переключатель: план или пакеты, тексты нейросети, превью на диске и на Google Диске, Google-документ объявлений и его копия `.docx`, пакет, объявления в Telegram, эфиры YouTube, ключи в форму. Запуск делает ровно то, что включено.
- **Сверка с YouTube.** Свой эфир узнаётся по минуте старта (UTC) и метке слота в названии потока. Расхождения исправляются на месте минимальным набором вызовов API; эфиры не удаляются автоматически, а чужие эфиры программа не трогает.
- **Ключи потоков** читаются только с YouTube и уходят только через Google-форму; каждая отправка сверяется со страницей подтверждения формы.
- **Итог:** короткая сводка в консоли, отчёт Markdown и полный лог на каждый запуск, `keystreams\keys.txt` для ручной передачи.

Livecraft не стримит, не ведёт своё расписание (план — в таблице), не принимает команд в Telegram (только отправляет) и не хранит пароли.

## Что нужно

- Windows 10 или 11 (сейф использует DPAPI Windows).
- Для запуска из исходников: Python 3.13 и пакеты из `requirements.txt` в окружении `.venv_livecraft`.
- OAuth-клиент Google Cloud типа *Desktop*: `secrets\client_secret.json`.
- Внешние программы в `tools\`: `yt-dlp.exe` и `deno.exe` (Livecraft обновляет их сам).
- В зависимости от линий: ключ OpenAI, бот Telegram, Google Таблица с планом, папка на Google Диске, Google-форма для ключей, каналы YouTube с доступом для входа.

## Быстрый старт из исходников

```powershell
py -3.13 -m venv .venv_livecraft
.\.venv_livecraft\Scripts\python.exe -m pip install -r requirements.txt
# положите secrets\client_secret.json, tools\yt-dlp.exe и tools\deno.exe
.\livecraft.bat --setup      # окно настройки
.\livecraft.bat --dry-run    # пробный запуск: читает всё, снаружи ничего не меняет
.\livecraft.bat              # запуск включённых линий
```

Другие команды: `--status` (эфиры с меткой программы, `keys.txt`, отчёт), `--check` (каналы: вход, ник, id), `--auth "@handle"` или `--auth all` (вход в канал заново), `--debug`, `--version`. Открытие файла `.bcast` копирует его в папку пакетов и запускает программу.

Коды выхода: `0` — сделано всё, что можно; `1` — есть ошибки; `2` — ошибка настроек, сейфа или входа, ничего не делалось; `3` — нет будущих слотов.

## Настройки и секреты

- Секретные значения — ключ OpenAI, id таблицы, токены ботов Telegram, папка Google Диска — хранятся в зашифрованном сейфе (AES-256-GCM; ключ завёрнут DPAPI под текущего пользователя Windows, поэтому копия файла сейфа в другом месте бесполезна). В консоль, отчёты и логи они не попадают.
- **Токен доступа** (`*.lctoken`) передаёт значения другому человеку: он работает на них, но не видит их. Это защита от случайного копирования, а не от специалиста: значение, которым программа пользуется, есть в её памяти.
- Открытые настройки: `secrets\livecraft.json` (создаётся из поставочного шаблона при первом запуске) и `secrets\channels.json` (каналы: ник, подсказка аккаунта Google, язык, видимость).
- Личных данных в репозитории нет: `secrets\`, логи, пакеты, токены и остальные папки данных git не видит.

## Папки данных

Рядом с `livecraft.exe` (или в корне репозитория при запуске из исходников): `secrets\` — сейф и настройки, `tools\` — внешние программы, `image\` — превью, `bcast\` — пакеты, `docs\` — копии документов объявлений `.docx`, `tokens\` — созданные токены доступа, `keystreams\` — ключи потоков, `state\` — файл-замок и кэши, `logs\` — отчёты и логи.

## Языки интерфейса

Окно настройки и консоль — на русском, украинском или английском, по языку отображения Windows. Тексты эфиров и объявлений — на языке своего слота.

## Разработка

- Тесты: `.\.venv_livecraft\Scripts\python.exe -m pytest app\tests -q`
- Эталон кода (правила E1–E21, слои импорта, без новых и выросших нарушений): `.\.venv_livecraft\Scripts\python.exe -m app.tools.code_standard`
- Устройство: правила живут в объектах предметной области (ООП); `StreamSlot` (`app\slots\`) — единственный шов между контуром A (план → слоты: таблица, источники, нейросеть, объявления) и контуром B (слоты → эфиры YouTube, форма, память).
- Сборка: `build_release.bat` (PyInstaller и Inno Setup) → `dist\livecraft\` и установщик `dist\installer\livecraft-setup-<версия>.exe`; папка установки по умолчанию — `%LOCALAPPDATA%\Programs\Livecraft`.

