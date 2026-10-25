# Livecraft

*English first; the Russian version follows below.*

Livecraft prepares YouTube live broadcasts end to end on one Windows computer. It reads a content plan from Google Sheets, collects the metadata and thumbnails of the source videos with yt-dlp, writes one title and one description per broadcast with an LLM (OpenAI), publishes announcements to Google Docs and Telegram, schedules the broadcasts on YouTube channels and hands the stream keys to the streamers through a Google Form.

## What it does

- **Two inputs.** The content plan (a Google Sheet: video link, date, time) or packages — `*.bcast` files written by another Livecraft run. A package lets a channel owner schedule the same broadcasts without the sheet and without the LLM.
- **Work lines.** The settings window has a switch for every line: content plan or packages, AI texts, thumbnails on disk and on Google Drive, the Google Doc of announcements and its `.docx` copy, the package, Telegram announcements, YouTube broadcasts, stream keys to the form. A run does exactly what is switched on.
- **Reconciliation with YouTube.** An existing broadcast is recognised by its start minute (UTC) and the broadcast marker in the stream title. Differences are fixed in place with the minimal set of API calls; broadcasts are never deleted automatically, and broadcasts that do not belong to the plan are never touched.
- **Stream keys** are read only from YouTube and sent only through the Google Form; every submission is checked against the form's confirmation page.
- **Results:** a short console summary, a Markdown report and a full debug log per run, and `keystreams\keys.txt` for manual handover.

Livecraft does not stream, does not run a schedule of its own (the plan lives in the sheet), does not accept commands in Telegram (it only sends) and does not store passwords.

## Requirements

- Windows 10 or 11 (the vault uses Windows DPAPI).
- From source: Python 3.13 and the packages from `requirements.txt` in the virtual environment `.venv_livecraft`.
- A Google project — a Google Cloud OAuth client of type *Desktop*: choose its JSON file in the settings window (see *Google project* below) or get it with an access token.
- yt-dlp and deno: the setup window downloads them to `tools\` itself on its first opening (a line at the bottom of the window shows the download); the run keeps them up to date.
- Cookies — optional (see *Cookies* below).
- Depending on the lines in use: an OpenAI API key, a Telegram bot, a Google Sheet with the plan, Google Drive folders, a Google Form for the keys, YouTube channels to sign in to.

## Install

The installer `livecraft-setup-<version>.exe` from the Releases page carries only the program — nobody's data, no Google project, no yt-dlp or deno. It installs without administrator rights to `%LOCALAPPDATA%\Programs\Livecraft`. The installer has no digital signature, so Windows SmartScreen may warn: choose *More info* → *Run anyway*.

Update: install the new version over the old one; settings and data stay.

## Google project

1. Create a project in Google Cloud Console.
2. Enable YouTube Data API v3, Google Sheets API, Google Docs API and Google Drive API.
3. Set up the OAuth consent screen, user type *External*.
4. Create an OAuth client ID of type *Desktop app*.
5. Download its JSON right when the client is created: Google will not show the client secret later. The file may lie anywhere and have any name: Livecraft remembers the path to it (`google.project_file` in `secrets\livecraft.json`; inside the program folder — from its root) and does not copy it.
6. In the settings window, at the top of *Home*: *Google project* → *Choose a file…*. The window checks with Google that it knows the client and says which sign-ins of this computer were made through this project; only sign-ins made through the chosen project work: a sign-in made through another project is replaced by a new sign-in through the chosen one when it is needed (a browser opens). To change the project, choose another file. A Google project that comes with an access token lands in `secrets\google_project_<ID>.json` and becomes the working one unless a project chosen on this computer is already working.

While the app is in *Testing* status, add the Google accounts that sign in to *Test users*; their sign-ins then last 7 days. A published unverified app (*In production*) shows a Google warning at sign-in, and its sign-ins do not expire.

## Cookies (optional)

Livecraft does not need a YouTube sign-in: it reads only the video data — title, description, thumbnail, language — and gets it without signing in, 18+ videos included; when yt-dlp cannot read a video, the title comes from YouTube's open oEmbed answer and the thumbnail by the video id. Cookies are still accepted and help where YouTube asks a signed-in account (a private video your account can see, “confirm you are not a bot”). Export the youtube.com cookies in Netscape format from a private browser window — sign in to YouTube, open `https://www.youtube.com/robots.txt` in the same tab, export, close the window — and load the file on the “YouTube cookies” tab of the setup window: “Load file…” copies it to `secrets\cookies.txt` and checks it. “Check” asks YouTube whether the sign-in works and says so in blue: with or without it the program works. A run says nothing about cookies. Cookies are personal: tokens never carry them.

## Quick start from source

```powershell
py -3.13 -m venv .venv_livecraft
.\.venv_livecraft\Scripts\python.exe -m pip install -r requirements.txt
.\livecraft.bat --setup      # settings window: Google project at the top of Home, then the lines
.\livecraft.bat --dry-run    # trial run: reads everything, changes nothing outside
.\livecraft.bat              # run the lines that are switched on
```

Other commands: `--status` (broadcasts with the program marker, `keys.txt`, report), `--check` (channels: sign-in, handle, id), `--auth "@handle"` or `--auth all` (sign in to a channel again), `--debug`, `--version`. Opening a `.bcast` file copies it to the packages folder and starts a run.

Exit codes: `0` — everything that could be done is done; `1` — there are errors; `2` — configuration, vault or sign-in error, nothing was done; `3` — no future broadcasts.

## Settings and secrets

- Secret values — the OpenAI key, the sheet id, the Telegram bot token, the two Google Drive folders (one for thumbnails, one for the announcement documents; they may be the same folder) — are kept in an encrypted vault (AES-256-GCM; the key is wrapped with Windows DPAPI for the current Windows user, so a copied vault file is useless elsewhere). They never appear in the console, reports or logs.
- An **access token** (`*.lctoken`) passes to another user what was set by hand; the receiver can work with it but not read it. What goes in is chosen value by value: the *Tokens* tab has a switch for each value a token can carry, grouped by work line — the OpenAI key, the plan spreadsheet, the two Google Drive folders, the document contacts, the Telegram bot token, the private chat and the group with the bot, the key form link, **Google project** — the Google project chosen on *Home* and the operator sign-in made through it (access to the plan spreadsheet, the documents and the whole Google Drive of the operator account) — and **YouTube channels** — the channels and the sign-ins to them made through the chosen project (a channel without such a sign-in goes without one). All switches are off when the tab opens; a value missing on this computer has a pale switch; *where to send announcements* goes along with the chat it points to. Local settings — lines, folders, terms, time zone — never go into a token: they are the receiver's choice. With the project and channels switches on, the receiver works without signing in in a browser, so turn them on only for own computers and trusted people. What came with a token never goes into the receiver's own tokens, and the receiver's own values, Google project, channels with an own sign-in and own operator sign-in stay first. The token file is named by its content: `lvc_<Google project ID>_channels_<DD-MM-YYYY>_<HHMMSS>.lctoken` — without `_channels` when it carries no channels, without the project ID when it carries no Google project. Livecraft does not read the name: a token may be renamed as long as it keeps the `.lctoken` extension.
- This protects against casual copying, not against a specialist: a program that uses a value has it in memory; after loading, the sign-ins lie in `secrets\` as ordinary files. To take access back, revoke the app's access in the Google account.
- Open settings: `secrets\livecraft.json` (created from the shipped template on the first run) and `secrets\channels.json` (channels: handle, Google account hint, language, visibility).
- The repository contains no personal data: `secrets\`, logs, packages, tokens and the other data folders are ignored by git.

## Data folders

Next to `livecraft.exe` (or in the repository root when run from source): `secrets\` — vault and settings, `tools\` — yt-dlp and deno (Livecraft downloads and updates them), `image\` — thumbnails, `bcast\` — packages, `docs\` — `.docx` copies of the announcement documents, `tokens\` — created access tokens, `keystreams\` — stream keys, `state\` — lock file and caches, `logs\` — reports and logs.

## Interface languages

The settings window and the console speak Russian, Ukrainian or English, chosen by the Windows display language. Texts for broadcasts and announcements follow the language of each broadcast.

## Development

- Tests: `.\.venv_livecraft\Scripts\python.exe -m pytest app\tests -q`
- Code standard (rules E1–E21, layered imports, no new or grown violations): `.\.venv_livecraft\Scripts\python.exe -m app.tools.code_standard`
- Design: domain objects own their rules (OOP); `StreamSlot` (`app\slots\`) is the only seam between contour A (plan → planned broadcasts: sheet, sources, LLM, announcements) and contour B (planned broadcasts → YouTube broadcasts, form, memory).
- Build: `build_release.bat` (PyInstaller and Inno Setup) → `dist\livecraft\` and the installer `dist\installer\livecraft-setup-<version>.exe`; the default install folder is `%LOCALAPPDATA%\Programs\Livecraft`.

## License

MIT — see the file `LICENSE`.

---

# Livecraft

Livecraft готовит эфиры YouTube «под ключ» на одном компьютере с Windows. Программа читает план стримов из Google Таблицы, собирает данные и превью исходных видео через yt-dlp, пишет нейросетью (OpenAI) одно название и одно описание на эфир, публикует объявления в Google Docs и Telegram, ставит эфиры на каналах YouTube и передаёт ключи потоков стримерам через Google-форму.

## Что делает

- **Два входа.** План стримов (Google Таблица: ссылка на видео, дата, время) или пакеты — файлы `*.bcast`, которые пишет другой запуск Livecraft. По пакету владелец канала ставит те же эфиры без таблицы и без нейросети.
- **Линии работы.** В окне настройки у каждой линии свой переключатель: план или пакеты, тексты нейросети, превью на диске и на Google Диске, Google-документ объявлений и его копия `.docx`, пакет, объявления в Telegram, эфиры YouTube, ключи в форму. Запуск делает ровно то, что включено.
- **Сверка с YouTube.** Свой эфир узнаётся по минуте старта (UTC) и метке эфира в названии потока. Расхождения исправляются на месте минимальным набором вызовов API; эфиры не удаляются автоматически, а чужие эфиры программа не трогает.
- **Ключи потоков** читаются только с YouTube и уходят только через Google-форму; каждая отправка сверяется со страницей подтверждения формы.
- **Итог:** короткая сводка в консоли, отчёт Markdown и полный лог на каждый запуск, `keystreams\keys.txt` для ручной передачи.

Livecraft не стримит, не ведёт своё расписание (план — в таблице), не принимает команд в Telegram (только отправляет) и не хранит пароли.

## Что нужно

- Windows 10 или 11 (сейф использует DPAPI Windows).
- Для запуска из исходников: Python 3.13 и пакеты из `requirements.txt` в окружении `.venv_livecraft`.
- Проект Google — OAuth-клиент Google Cloud типа *Desktop*: его файл JSON выбирается в окне настройки (раздел *Проект Google* ниже) или приходит с токеном доступа.
- yt-dlp и deno: окно настройки само скачивает их в `tools\` при первом открытии (ход загрузки — строкой внизу окна); обновляет их запуск.
- Cookies — по желанию (раздел *Cookies* ниже).
- В зависимости от линий: ключ OpenAI, бот Telegram, Google Таблица с планом, папки на Google Диске, Google-форма для ключей, каналы YouTube с доступом для входа.

## Установка

Установщик `livecraft-setup-<версия>.exe` со страницы Releases несёт только программу — ничьих данных, проекта Google, yt-dlp и deno в нём нет. Ставится без прав администратора в `%LOCALAPPDATA%\Programs\Livecraft`. У установщика нет цифровой подписи, поэтому Windows SmartScreen может предупредить: «Подробнее» → «Выполнить в любом случае».

Обновление — новая версия ставится поверх прежней; настройки и данные остаются.

## Проект Google

1. Создайте проект в Google Cloud Console.
2. Включите YouTube Data API v3, Google Sheets API, Google Docs API и Google Drive API.
3. Настройте экран согласия OAuth, тип пользователей *External*.
4. Создайте OAuth client ID типа *Desktop app*.
5. Скачайте его JSON сразу при создании клиента — позже Google секрет клиента не покажет. Файл может лежать где угодно и называться как угодно: Livecraft запоминает путь к нему (`google.project_file` в `secrets\livecraft.json`; внутри папки программы — от её корня) и не копирует его.
6. В окне настройки, первым на «Главной»: «Проект Google» → «Выбрать файл…». Окно спрашивает Google, знает ли он клиент, и говорит, какие входы этого компьютера сделаны через этот проект; работают только входы, сделанные через выбранный проект: вход через другой проект программа заменяет новым входом через выбранный, когда этот вход понадобится (откроется браузер). Сменить проект — выбрать другой файл. Проект Google, полученный с токеном доступа, ложится в `secrets\google_project_<ID>.json` и становится рабочим, если рабочим уже не стоит проект, выбранный на этом компьютере.

Пока приложение в статусе *Testing*, добавьте аккаунты Google, которыми выполняется вход, в *Test users*; входы тогда живут 7 дней. Опубликованное непроверенное приложение (*In production*) показывает при входе предупреждение Google, а входы не истекают.

## Cookies (по желанию)

Входить в YouTube Livecraft не нужно: ему нужны только данные видео — название, описание, превью, язык, — и он берёт их без входа, в том числе у видео 18+; если yt-dlp видео не прочитал, название приходит открытым ответом YouTube (oEmbed), превью — по id видео. Cookies по-прежнему принимаются и помогают там, где YouTube спрашивает вошедший аккаунт (приватное видео, доступное вашему аккаунту, «подтвердите, что не бот»). Выгружайте cookies youtube.com в формате Netscape из приватного окна браузера — войдите в YouTube, в той же вкладке откройте `https://www.youtube.com/robots.txt`, выгрузите, закройте окно — и загрузите файл на вкладке «Cookies YouTube» окна настройки: «Загрузить файл…» копирует его в `secrets\cookies.txt` и проверяет. «Проверить» спрашивает YouTube, работает ли вход, и пишет итог синим: с входом и без него программа работает. Запуск о cookies ничего не пишет. Cookies у каждого свои: в токен они не входят.

## Быстрый старт из исходников

```powershell
py -3.13 -m venv .venv_livecraft
.\.venv_livecraft\Scripts\python.exe -m pip install -r requirements.txt
.\livecraft.bat --setup      # окно настройки: проект Google первым на «Главной», затем линии
.\livecraft.bat --dry-run    # пробный запуск: читает всё, снаружи ничего не меняет
.\livecraft.bat              # запуск включённых линий
```

Другие команды: `--status` (эфиры с меткой программы, `keys.txt`, отчёт), `--check` (каналы: вход, ник, id), `--auth "@handle"` или `--auth all` (вход в канал заново), `--debug`, `--version`. Открытие файла `.bcast` копирует его в папку пакетов и запускает программу.

Коды выхода: `0` — сделано всё, что можно; `1` — есть ошибки; `2` — ошибка настроек, сейфа или входа, ничего не делалось; `3` — нет будущих эфиров.

## Настройки и секреты

- Секретные значения — ключ OpenAI, id таблицы, токен бота Telegram, две папки Google Диска (для превью и для документов объявлений; может быть одна и та же папка) — хранятся в зашифрованном сейфе (AES-256-GCM; ключ завёрнут DPAPI под текущего пользователя Windows, поэтому копия файла сейфа в другом месте бесполезна). В консоль, отчёты и логи они не попадают.
- **Токен доступа** (`*.lctoken`) передаёт другому человеку заданное руками: получатель работает на этом, но не видит значений. Что войдёт, выбирается по одному значению: на вкладке «Токены» у каждого значения, которое может нести токен, свой ползунок, группами по линиям работы — ключ OpenAI, таблица плана, две папки Google Диска, контакты документа, токен бота Telegram, чат и группа с ботом, ссылка на форму ключей, **«Проект Google»** — проект Google, выбранный на «Главной», и вход оператора, сделанный через него (доступ к таблице плана, документам и всему Google Диску аккаунта оператора), — и **«Каналы YouTube»** — каналы и входы в них, сделанные через выбранный проект (канал без такого входа едет без входа). При открытии вкладки все ползунки выключены; у значения, которого на этом компьютере нет, ползунок бледный; «куда слать объявления» едет вместе с чатом, на который указывает. Локальные настройки — линии, папки, сроки, часовой пояс — в токен не идут никогда: это выбор получателя. С ползунками проекта и каналов получатель работает без входов в браузере — включать их только для своих компьютеров и доверенных людей. Полученное с токеном в токены получателя не идёт; своё у получателя — значения, проект Google, каналы со своим входом и свой вход оператора — остаётся главным. Имя файла токена — по содержимому: `lvc_<ID проекта Google>_channels_<DD-MM-YYYY>_<HHMMSS>.lctoken`, без `_channels`, когда каналов в нём нет, без ID проекта, когда нет проекта Google. Имя программа не читает: токен можно переименовать, сохранив расширение `.lctoken`.
- Это защита от случайного копирования, а не от специалиста: значение, которым программа пользуется, есть в её памяти; после загрузки входы лежат в `secrets\` обычными файлами. Забрать доступ — отозвать доступ приложения в Google-аккаунте.
- Открытые настройки: `secrets\livecraft.json` (создаётся из поставочного шаблона при первом запуске) и `secrets\channels.json` (каналы: ник, подсказка аккаунта Google, язык, видимость).
- Личных данных в репозитории нет: `secrets\`, логи, пакеты, токены и остальные папки данных git не видит.

## Папки данных

Рядом с `livecraft.exe` (или в корне репозитория при запуске из исходников): `secrets\` — сейф и настройки, `tools\` — yt-dlp и deno (их скачивает и обновляет Livecraft), `image\` — превью, `bcast\` — пакеты, `docs\` — копии документов объявлений `.docx`, `tokens\` — созданные токены доступа, `keystreams\` — ключи потоков, `state\` — файл-замок и кэши, `logs\` — отчёты и логи.

## Языки интерфейса

Окно настройки и консоль — на русском, украинском или английском, по языку отображения Windows. Тексты эфиров и объявлений — на языке своего эфира.

## Разработка

- Тесты: `.\.venv_livecraft\Scripts\python.exe -m pytest app\tests -q`
- Эталон кода (правила E1–E21, слои импорта, без новых и выросших нарушений): `.\.venv_livecraft\Scripts\python.exe -m app.tools.code_standard`
- Устройство: правила живут в объектах предметной области (ООП); `StreamSlot` (`app\slots\`) — единственный шов между контуром A (план → эфиры по плану: таблица, источники, нейросеть, объявления) и контуром B (эфиры по плану → эфиры YouTube, форма, память).
- Сборка: `build_release.bat` (PyInstaller и Inno Setup) → `dist\livecraft\` и установщик `dist\installer\livecraft-setup-<версия>.exe`; папка установки по умолчанию — `%LOCALAPPDATA%\Programs\Livecraft`.


## Лицензия

MIT — см. файл `LICENSE`.
