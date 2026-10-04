"""Все тексты для оператора на русском: консоль, отчёт, файл ключей, настройщик (CLAUDE.md §11, §14 решение 24).

В коде — только эти константы; английских текстов для человека в коде нет. Модули берут не этот модуль, а
`msg` из `app\\ui\\messages.py` — каталог языка Windows; `messages_uk.py` и `messages_en.py` — те же имена,
ключи словарей и подстановки. Здесь же объяснено, зачем каждая строка; замок эталона кода говорит только
по-русски и берёт этот модуль напрямую.
"""
from __future__ import annotations

from typing import Final

# --- общий словарь текстов для людей: перечисление, части строки, «ничего нет»
LIST_JOINER: Final[str] = ", "      # элементы одного перечня: языки, поля, модели
ITEM_JOINER: Final[str] = "; "      # самостоятельные части одной строки
NONE_TEXT: Final[str] = "нет"       # значения нет: не задано, не пришло, пусто

# --- командная строка (CLAUDE.md §10)
CLI_DESCRIPTION: Final[str] = (
    "Livecraft: план стримов из Google Sheets → эфиры на YouTube → ключи потоков стримеру."
)
HELP_SETUP: Final[str] = "открыть настройщик: ключи и ссылки, каналы YouTube, настройки запуска"
HELP_DRY_RUN: Final[str] = (
    "прочитать таблицу, собрать слоты и сверить их с YouTube; ничего не создавать, "
    "в форму не отправлять, keys.txt не менять"
)
HELP_CHECK: Final[str] = "проверить каждый канал: вход, ник и название, языки, число запланированных эфиров"
HELP_AUTH: Final[str] = (
    "заново авторизовать канал (ник handle из channels.json, например @MyChannel) или all — все каналы"
)
HELP_STATUS: Final[str] = "сверка эфиров livecraft, keys.txt и отчёт — без таблицы и без LLM"
HELP_PACKAGE_FILE: Final[str] = "пакет .bcast: копируется в папку пакетов, затем обычный запуск по включённым линиям"
CLI_PACKAGE_WITH_MODE: Final[str] = (
    "пакет .bcast открывается только обычным запуском — без --setup, --check, --auth и --status"
)
HELP_DEBUG: Final[str] = "подробный лог в терминал"
HELP_VERSION: Final[str] = "показать номер версии и выйти"
VERSION_TEXT: Final[str] = "Livecraft {version}"
# Подписи значений в справке argparse: их видит человек, поэтому они здесь, а не в app\run\request.py (§11).
CLI_METAVAR_HANDLE: Final[str] = "НИК"
CLI_METAVAR_PACKAGE: Final[str] = "ПАКЕТ"

# --- шапка запуска: первая строка любого запуска, время — то же, что в отчёте этого запуска
CONSOLE_TITLE: Final[str] = "Livecraft {version} — {generated_at}"

# --- настройка программы (CLAUDE.md §8): без сейфа и конфига --check, --auth и --status не начинаются
# Что именно не так, перечислено строками выше (сейф и конфиги называют свои причины сами) — здесь только что делать.
SETUP_REQUIRED: Final[str] = "Запустите .\\livecraft.bat --setup и заполните настройки."
SERVICE_NEED_BLOCKED: Final[str] = "Не готово: {gap}."
# Запуск не может сделать ничего (app\run\line_plan.py::ModeReadiness.step): программа сама открывает окно настройки.
SETUP_OPENING: Final[str] = "Не хватает настроек — открываю окно настройки."

# --- линии работы и их готовность (app\run\mode.py, app\run\line_plan.py, app\setup\readiness.py, §10, §14
# решение 37). Ключи — значения RunPart: названия линий «Главной» окна; чтение пакетов — не линия.
RUN_PART_LABELS: Final[dict[str, str]] = {
    "plan": "Таблица плана",
    "local_previews": "Превью на диске",
    "drive_previews": "Превью на Google Диске",
    "merge": "Нейросеть",
    "package": "Пакет",
    "doc": "Google-документ",
    "doc_copy": "Копия документа",
    "announce": "Telegram",
    "packages_in": "Чтение пакетов",
    "broadcast": "Эфиры YouTube",
    "keys": "Ключи в форму",
}
# Одна строка на нужду, которой не хватает (app\run\mode.py::Need): {parts} — части режима, которым она нужна,
# {gap} — что задать и где (Readiness.gap).
RUN_NEED_BLOCKED: Final[str] = "Не готово — {parts}: {gap}."
# Не работает ни одна линия: окно настройки и код 2.
LINES_NONE_WORKING: Final[str] = (
    "Не включено ни одной линии работы: включите их в окне настройки (.\\livecraft.bat --setup)."
)
# Включённые линии, опора которых выключена (app\run\line_plan.py::LinePlan.summary_lines): не ошибка — строка сводки.
LINES_NO_SUPPORT: Final[str] = "  не работают без «{support}»: {lines}"
LINES_NO_SUPPORT_MERGE: Final[str] = (
    "  не работают без «{support}»: {lines} — от таблицы плана они работают только с нейросетью: тексты «по "
    "номерам» на YouTube и в пакет не идут"
)
# Что задать и где: {what} — чего не хватает, {tab} — вкладка настройщика (SETUP_TAB_TITLES).
READINESS_GAP_IN_SETUP: Final[str] = "{what} — «Livecraft — настройка», вкладка «{tab}»"
READINESS_GAP_SETTINGS: Final[str] = "дополнительные настройки ({key} — {problem})"
READINESS_GAP_FORM: Final[str] = "ссылка на Google форму для ключей стрима"
READINESS_GAP_TELEGRAM: Final[str] = "бот Telegram и чат для объявлений"
READINESS_GAP_CHANNELS_MISSING: Final[str] = "каналы YouTube не заданы"
READINESS_GAP_CHANNELS: Final[str] = "каналы YouTube ({key} — {problem})"
# {problem} — VaultFormatError.problem: файл и причина.
READINESS_GAP_VAULT_BROKEN: Final[str] = "ключи и ссылки не читаются: {problem}. {advice}"
# client_secret.json в настройщике не задаётся (§9): это файл OAuth-клиента, его кладут рядом с программой.
READINESS_GAP_CLIENT_SECRET: Final[str] = "нет файла входа в Google client_secret.json — положите его сюда: {path}"
# Однократный перенос ссылки на папку Google Диска из livecraft.json к скрытым значениям (§14 решение 39): самой ссылки
# в строках нет.
DRIVE_FOLDER_MIGRATED: Final[str] = (
    "Ссылка на папку Google Диска теперь хранится скрытой, как ссылка на таблицу плана, — вводить её заново не нужно."
)
DRIVE_FOLDER_MIGRATION_FAILED: Final[str] = (
    "ВНИМАНИЕ: ссылку на папку Google Диска из прежних настроек перенести не удалось ({reason}). "
    "Вставьте её на вкладке «Превью»: .\\livecraft.bat --setup."
)
DRIVE_FOLDER_MIGRATION_LOCAL_UNREAD: Final[str] = (
    "введённые раньше ключи и ссылки не прочитались, а запись поверх них стёрла бы их"
)

# livecraft.json в git нет (§5): нет файла — программа сама кладёт поставочный вид (ресурс settings_shipped.json).
SETTINGS_FILE_CREATED: Final[str] = "Настройки программы созданы из поставочного шаблона: {path}"
# Новая версия добавила раздел настроек, которого в файле ещё нет: программа дописала его сама (SettingsFile).
SETTINGS_SECTIONS_ADDED: Final[str] = "В настройки программы дописан из поставочного шаблона новый раздел: {sections}"
# Чистка старья по keep_days (app\runtime\retention.py, §3 шаг 12) — строка «Запуск», когда удалено хоть что-то.
RETENTION_REMOVED: Final[str] = "Удалены старые файлы программы (старше {days} дн.): {count}."

# --- yt-dlp и deno в папке tools обновляются сами, cookies проверяются (app\runtime\ytdlp_updater.py,
# deno_updater.py, cookies_updater.py) — строки «Запуск», только когда что-то обновлено или требует действия.
# {tool} — имя программы (yt-dlp, deno), {before} и {after} — номера версий.
TOOL_UPDATED: Final[str] = "{tool} обновлён: {before} → {after}."
TOOL_DOWNLOADED: Final[str] = "{tool} {after} скачан в папку tools."
TOOL_MISSING: Final[str] = (
    "{tool}: в папке tools нет файла программы — видео таблицы не прочитаются. Поставьте Livecraft поверх: установщик "
    "вернёт файл, настройки и данные останутся."
)
# {reason} — TOOL_PROBLEMS, {version} — версия, на которой идёт работа.
TOOL_NOT_CHECKED: Final[str] = (
    "{tool}: новая версия не проверена — {reason}. Работа идёт на версии {version}, следующий запуск проверит снова."
)
TOOL_UNUSABLE: Final[str] = (
    "{tool}: в папке tools нет рабочего файла, а скачать его не вышло — {reason}. Видео YouTube могут не прочитаться; "
    "следующий запуск попробует снова."
)
# Ключи — значения ToolProblem (app\runtime\deno_updater.py).
TOOL_PROBLEMS: Final[dict[str, str]] = {
    "no_answer": "нет связи с GitHub",
    "refused": "GitHub отказал в ответе",
    "no_version": "GitHub не назвал номер последней версии",
    "broken_download": "скачанный файл повреждён",
    "not_written": "новый файл не встал на место прежнего",
    "self_update_failed": "yt-dlp не смог обновиться сам",
}
# Файл cookies YouTube (secrets\cookies.txt) — по желанию; строки — только когда его нужно выгрузить заново.
# {path} — путь файла от корня программы, {header} — первая строка файла Netscape.
COOKIES_BAD_FORMAT: Final[str] = (
    "Файл cookies {path} — не того вида: первой строкой в нём должна быть «{header}». С таким файлом yt-dlp не "
    "прочитает ни одного видео, поэтому таблица плана не обрабатывается."
)
# {reason} — COOKIES_LOGIN_FAILURES.
COOKIES_LOGIN_FAILED: Final[str] = "yt-dlp не входит в YouTube по cookies: {reason}."
# Ключи — значения CookiesLogin, при которых вход не удался (app\runtime\cookies_updater.py).
COOKIES_LOGIN_FAILURES: Final[dict[str, str]] = {
    "invalid": "cookies больше не действуют (обычно браузер обновил их после выгрузки)",
    "no_auth": "в файле нет cookies входа в аккаунт YouTube",
}
# {date} — дата выгрузки (время последней записи файла), {days} — сколько суток прошло, {limit} — срок.
COOKIES_STALE: Final[str] = "Cookies YouTube выгружены {date} — {days} сут. назад, срок {limit} сут."
COOKIES_REEXPORT: Final[str] = (
    "Выгрузите cookies заново: окно инкогнито → вход в YouTube → выгрузка cookies youtube.com в формате Netscape "
    "расширением браузера → окно закрыть; файл положить в {path}."
)

# --- готовность к запуску (app\setup\readiness.py): сводка без значений — только откуда что взялось (§7.4)
READINESS_SUMMARY_TITLE: Final[str] = "Настройки livecraft:"
READINESS_FIELD_LINE: Final[str] = "  {label}: {origin}"
# Линии работы в сводке (§14 решение 37): {lines} — названия через запятую.
READINESS_LINES_WORKING: Final[str] = "  линии работы: {lines}"
READINESS_LINES_OFF: Final[str] = "  выключены: {lines}"
# Форма ключей — открытая настройка livecraft.json (§14 решение 15): сводка говорит, задана ли ссылка, но не её саму.
FORM_URL_LABEL: Final[str] = "Google форма для ключей стрима (эфира)"
# Контакты документа объявлений — открытая настройка: подпись поля окна и названия в токене доступа.
DOCS_CONTACTS_LABEL: Final[str] = "контакты для стримеров в документе объявлений"
READINESS_FORM_CONFIGURED: Final[str] = "настроена"
READINESS_FORM_NOT_CONFIGURED: Final[str] = "не настроена"
READINESS_CHANNELS_LINE: Final[str] = "  каналов: {count}, языки стримов: {languages}"
READINESS_CHANNELS_ABSENT: Final[str] = "  каналы: не прочитаны"
# Сводка настроек запуска: откуда тексты эфиров — по линиям запуска (app\run\line_plan.py::RunTexts, §14 решение 50;
# ключи — значения RunTextSource), и повторная передача ключей — раздел broadcasts livecraft.json (решение 36).
READINESS_TEXTS_LABEL: Final[str] = "тексты эфиров"
RUN_TEXT_SOURCES: Final[dict[str, str]] = {
    "llm": "от нейросети",
    "videos": "тексты видео, у эфира из нескольких видео — «по номерам», только для людей",
    "packages": "из пакетов",
}
READINESS_RESEND_KEYS_LABEL: Final[str] = "повторная передача ключей"
READINESS_RESEND_KEYS_OFF: Final[str] = "выключена"
READINESS_RESEND_KEYS_ON: Final[str] = "включена — ключи уйдут при этом запуске"
READINESS_RESEND_KEYS_DRY_RUN: Final[str] = "включена — в пробном запуске ключи не уходят"
# Файл слоя сейфа есть, но не читается (§16): молча работать без своих значений или без значений токена нельзя.
# {fields} — названия полей сейфа (SecretField).
VAULT_LOCAL_UNREADABLE: Final[str] = (
    "ВНИМАНИЕ: собственные ключи и ссылки не прочитаны ({fields}) — так бывает после переноса программы на другой "
    "компьютер или смены пользователя Windows. Введите свои значения заново: .\\livecraft.bat --setup."
)
VAULT_TOKEN_UNREADABLE: Final[str] = (
    "ВНИМАНИЕ: значения из токена доступа не прочитаны — так бывает после переноса программы на другой компьютер или "
    "смены пользователя Windows. Загрузите токен заново: .\\livecraft.bat --setup, вкладка «Токены»."
)
# Файл ключей и ссылок не читается (app\secretsafe\crypto.py::VaultFormatError): причина — по-русски, английская
# подробность — только в лог. Ключи VAULT_FORMAT_REASON_TEXT — значения VaultFormatReason. {problem} —
# VAULT_FILE_PROBLEM или одна причина, когда файл неизвестен; {advice} — одно действие: свой файл заменяет
# настройщик, файл программы — только установка.
VAULT_FORMAT_REASON_TEXT: Final[dict[str, str]] = {
    "file_unreadable": "файл не открывается — его держит другая программа, нет прав или на его месте папка",
    "not_text": "файл повреждён — это не текст",
    "damaged": "файл повреждён — внутри не то, что записывает программа",
    "unsupported_version": "файл записан другой версией программы",
    "key_invalid": "ключ файла неверной длины",
}
VAULT_FILE_PROBLEM: Final[str] = "{file} — {reason}"
VAULT_FILE_BROKEN: Final[str] = "Ключи и ссылки не читаются: {problem}. {advice}."
VAULT_FILE_ADVICE_LOCAL: Final[str] = (
    "Откройте «Livecraft — настройка» и введите свои значения заново — сохранение заменит этот файл"
)
VAULT_FILE_ADVICE_TOKEN: Final[str] = "Загрузите токен заново: «Livecraft — настройка», вкладка «Токены»"
# Блоб поля сейфа не расшифровался (app\secretsafe\crypto.py::VaultDecryptError). Ключи — значения DecryptReason.
VAULT_DECRYPT_FAILED: Final[str] = "Значение «{field}» не расшифровывается: {reason}"
VAULT_DECRYPT_REASON_TEXT: Final[dict[str, str]] = {
    "tag_mismatch": "файл изменён или записан другим ключом",
    "not_text": "внутри не текст",
}
# DPAPI недоступен (app\secretsafe\dpapi.py::DpapiUnavailable). Ключи — значения DpapiReason.
DPAPI_UNAVAILABLE: Final[str] = "Свои ключи и ссылки на этом компьютере не сохранить: {reason}"
DPAPI_REASON_TEXT: Final[dict[str, str]] = {
    "not_loaded": "защита данных Windows (DPAPI) не загрузилась — нужна Windows",
    "call_failed": "защита данных Windows (DPAPI) отказала",
}

# --- конфиги (CLAUDE.md §5): два JSON, все поля обязательные, умолчаний и копирования примеров нет
CONFIG_ERROR: Final[str] = "Ошибка в конфиге {path}: {key} — {problem}"
CONFIG_ROOT_KEY: Final[str] = "(корень файла)"
# Что вписать в каждое поле channels.json: идёт в лог (DEBUG) перед шаблоном, когда файл сломан.
# {languages} — CONFIG_LANGUAGES_RULE, {privacy} и {platform} — допустимые значения из config\channel.py.
CONFIG_CHANNELS_FIELDS: Final[tuple[str, ...]] = (
    "  account_name — название канала как на YouTube: оно уходит в форму как «Название канала»;",
    "  handle — ник канала на YouTube, начинается с @ (Студия -> аватар вверху справа); "
    "ник и название программа потом выравнивает сама;",
    "  google_account — почта аккаунта Google, в котором этот канал;",
    "  languages — языки стримов этого канала: {languages};",
    "  privacy — видимость эфиров: {privacy};",
    "  platform — {platform}.",
)
CONFIG_LANGUAGES_RULE: Final[str] = 'непустой список двухбуквенных кодов ISO 639-1 без повторов, например ["uk"]'
# Точный шаблон channels.json: идёт в лог (DEBUG), когда файл сломан. Шаблон livecraft.json — ресурс
# settings_shipped.json (app\config\files.py::ShippedSettings). В код как умолчания не идут.
CONFIG_CHANNELS_TEMPLATE: Final[str] = """{
  "channels": [
    {"platform": "youtube", "account_name": "Название канала на YouTube", "handle": "@ник_канала", "google_account": "you@gmail.com",
     "languages": ["ru"], "privacy": "unlisted"}
  ]
}"""
CONFIG_PROBLEM_FILE_MISSING: Final[str] = "файла нет"
CONFIG_PROBLEM_JSON: Final[str] = "файл не читается как JSON: {error}"
CONFIG_PROBLEM_NOT_MAPPING: Final[str] = "нужен объект JSON в фигурных скобках"
CONFIG_PROBLEM_MISSING_KEY: Final[str] = "обязательное поле отсутствует"
CONFIG_PROBLEM_UNKNOWN_KEY: Final[str] = "неизвестное поле"
CONFIG_PROBLEM_DUPLICATE_KEY: Final[str] = "поле указано дважды"
CONFIG_PROBLEM_NON_EMPTY_STRING: Final[str] = "нужна непустая строка в кавычках"
CONFIG_PROBLEM_STRING: Final[str] = 'нужна строка в кавычках; пустая строка "" — не настроено'
# Правило ссылки на форму (FormSettings.url_problem); перенесено со вкладки ключей (§14 решение 15).
CONFIG_PROBLEM_FORM_URL: Final[str] = (
    "нужна ссылка на Google-форму: https://docs.google.com/forms/… или https://forms.gle/…, без пробелов; "
    "пустая строка — форма не настроена"
)
CONFIG_PROBLEM_TEXT_OR_NULL: Final[str] = "нужно название вопроса формы в кавычках или null, если такого вопроса в форме нет"
CONFIG_PROBLEM_TEXT_MAPPING: Final[str] = (
    'нужен непустой объект «код — текст варианта», например {"uk": "Украинский ( Ukranian)"}'
)
CONFIG_PROBLEM_INT_MIN: Final[str] = "нужно целое число не меньше {minimum}"
CONFIG_PROBLEM_NUMBER_MIN: Final[str] = "нужно число не меньше {minimum:g}, можно дробное, например 0.5"
CONFIG_PROBLEM_NUMBER_FINITE: Final[str] = "нужно обычное число: NaN и бесконечность не годятся"
CONFIG_PROBLEM_BOOL: Final[str] = "нужно true или false"
CONFIG_PROBLEM_CHOICE: Final[str] = "допустимо: {allowed}"
CONFIG_PROBLEM_CHAT_ID: Final[str] = (
    "нужен id чата Telegram — целое число, например -1001234567890; пустая строка — чат не задан"
)
CONFIG_PROBLEM_GROUP_CHAT_ID: Final[str] = "id группы Telegram — отрицательное число, например -1001234567890"
CONFIG_PROBLEM_FORM_PLATFORM: Final[str] = "среди вариантов площадки обязан быть «{platform}»"
CONFIG_PROBLEM_FORM_DATE_FORMAT: Final[str] = "в формате даты обязательны {required}; нет {absent}"
CONFIG_PROBLEM_IMAGE_TEMPLATE_PLACEHOLDERS: Final[str] = (
    "в шаблоне папки превью обязательны {{date}} и {{language}}; нет: {absent}"
)
CONFIG_PROBLEM_IMAGE_TEMPLATE_ABSOLUTE: Final[str] = (
    "шаблон папки превью должен быть относительным, например {date}/{language}: корень задаёт сама программа"
)
CONFIG_PROBLEM_IMAGE_TEMPLATE_FORMAT: Final[str] = (
    "в шаблоне папки превью есть подстановка, которой программа не знает; допустимы только {date} и {language}"
)
CONFIG_PROBLEM_TIMEZONE_UNKNOWN: Final[str] = (
    "часовой пояс не распознан: нужно имя зоны из базы IANA с учётом регистра, например Europe/Kyiv"
)
CONFIG_PROBLEM_CHANNELS_EMPTY: Final[str] = "нужен непустой список каналов"
CONFIG_PROBLEM_ACCOUNT_NAME_TOO_LONG: Final[str] = (
    "название канала длиннее {maximum} символов (сейчас {length}): на YouTube таких названий нет"
)
CONFIG_PROBLEM_ACCOUNT_NAME_CONTROL: Final[str] = "в названии канала есть управляющий символ (перевод строки, табуляция)"
CONFIG_PROBLEM_ACCOUNT_NAME_SPACE_EDGE: Final[str] = (
    "название канала начинается или заканчивается пробелом: «{value}»; на YouTube таких названий нет — уберите пробел"
)
CONFIG_PROBLEM_HANDLE_PREFIX: Final[str] = "ник «{value}» должен начинаться с {prefix}, как на YouTube"
CONFIG_PROBLEM_HANDLE_LENGTH: Final[str] = (
    "в нике «{value}» после @ нужно от {minimum} до {maximum} символов (сейчас {length})"
)
CONFIG_PROBLEM_HANDLE_CHAR: Final[str] = (
    "в нике «{value}» недопустимый символ {char}: пробелы, управляющие символы и < > : \" / \\ | ? * в нике не бывают"
)
CONFIG_PROBLEM_HANDLE_DUPLICATE: Final[str] = (
    "ник «{value}» уже есть у другого канала («{other}»); большие и маленькие буквы в нике не различаются"
)
CONFIG_PROBLEM_GOOGLE_ACCOUNT: Final[str] = (
    "«{value}» не похоже на почту аккаунта Google: нужен вид имя@домен, ровно один @ и без пробелов"
)
CONFIG_PROBLEM_PLATFORM_UNKNOWN: Final[str] = "неизвестная площадка «{value}»; допустимо: {allowed}"
CONFIG_PROBLEM_LANGUAGES: Final[str] = "нужен " + CONFIG_LANGUAGES_RULE
CONFIG_PROBLEM_LANGUAGE_DUPLICATE: Final[str] = "язык «{value}» указан дважды"
CONFIG_PROBLEM_LANGUAGE_UNKNOWN: Final[str] = (
    "«{value}» — не код языка: нужен двухбуквенный код ISO 639-1 строчными буквами, например uk, en, ru"
)

# --- один экземпляр на машину (CLAUDE.md §6, инвариант 12): замок занят — работать нельзя
LOCK_REJECTED: Final[str] = (
    "Livecraft уже работает на этой машине: процесс {pid}, запущен {started_at}. "
    "Дождитесь окончания первого запуска или закройте его окно."
)
LOCK_REJECTED_UNKNOWN_OWNER: Final[str] = (
    "Livecraft уже работает на этой машине, но какой именно процесс держит запуск — определить не удалось. "
    "Закройте открытые окна Livecraft и запустите заново."
)

# --- сейф (CLAUDE.md §7): названия полей и маска, которую человек видит вместо значения.
# Само значение не показывается нигде, кроме поля настройщика, куда его ввёл сам пользователь (§8.2).
VAULT_FIELD_OPENAI_API_KEY: Final[str] = "ключ OpenAI"
VAULT_FIELD_SHEETS_ID: Final[str] = "Google таблица контент-плана"
VAULT_FIELD_TELEGRAM_BOT_TOKEN: Final[str] = "токен бота Telegram"
VAULT_FIELD_DRIVE_FOLDER: Final[str] = "папка Google Диска для материалов"
VAULT_FIELD_SUPPORT_BOT_TOKEN: Final[str] = "токен бота поддержки"
# Маска по отпечатку: название поля и четыре знака sha256 — различить два значения можно, восстановить нет.
VAULT_MASK_FINGERPRINT: Final[str] = "{label} (…{fingerprint})"
# Происхождение поля: пришло с токеном доступа или его ввёл сам пользователь в окне настройки (§7.3).
VAULT_ORIGIN_TOKEN: Final[str] = "получено с токеном"
VAULT_ORIGIN_OWN: Final[str] = "введено в окне настройки"

# --- настройщик, поля сейфа (CLAUDE.md §8.2, п.2, п.3): что не так с введённым значением.
# Само введённое значение в строки не подставляется: это секрет, и он не должен попасть ни в один вывод (§7.4).
# Пустой ввод: у строки со своим значением есть кнопка сброса, {button} — её подпись (KeyRow.reset_label).
SETUP_INPUT_EMPTY: Final[str] = "пусто — введите значение"
SETUP_INPUT_EMPTY_RESET: Final[str] = "пусто: чтобы убрать своё значение, нажмите «{button}»"
SETUP_INPUT_OPENAI_API_KEY: Final[str] = (
    "ключ OpenAI начинается с sk-, пишется без пробелов и переводов строк и длиной не меньше {minimum} символов"
)
SETUP_INPUT_SHEETS_ID: Final[str] = (
    "нужна ссылка на Google-таблицу вида https://docs.google.com/spreadsheets/d/<id>/edit или сам id: "
    "латинские буквы, цифры, - и _, не меньше {minimum} символов"
)
SETUP_INPUT_TELEGRAM_BOT_TOKEN: Final[str] = (
    "нужен токен бота, который выдал @BotFather: число, двоеточие и не меньше {minimum} латинских букв, цифр, "
    "_ и -, без пробелов"
)
SETUP_INPUT_DRIVE_FOLDER: Final[str] = (
    "нужна ссылка на папку Google Диска вида https://drive.google.com/drive/folders/… или сам id папки: латинские "
    "буквы, цифры, - и _"
)
# Тексты для человека без знания устройства программы: ни где лежат файлы, ни как шифруется (смотр окна 23-09-2026).
SETUP_INPUT_OWN_UNAVAILABLE: Final[str] = (
    "на этом компьютере ключи и ссылки сохранить нельзя: Windows не даёт привязать их к учётной записи"
)
# Оговорка §7.2 и §14 решения 6: вкладка показывает её, когда на ней есть значение из токена.
# «Специалист может их достать» — обязательно; где лежит ключ и как шифруется — не говорим.
SETUP_KEYS_NOTICE_PROTECTION: Final[str] = (
    "Значения из токена скрыты от просмотра и копирования, но специалист может их достать. Свои значения действуют "
    "только на этом компьютере под той же учётной записью Windows."
)
SETUP_KEYS_NOTICE_NO_OWN: Final[str] = (
    "На этом компьютере ключи и ссылки сохранить нельзя: Windows не даёт привязать их к учётной записи."
)
SETUP_KEYS_NOTICE_LOCAL_UNREADABLE: Final[str] = (
    "Введённые раньше значения не прочитались — так бывает после переноса программы на другой компьютер или смены "
    "пользователя Windows. Первое сохранение заменит их новыми."
)
SETUP_KEYS_NOTICE_LOCAL_BROKEN: Final[str] = (
    "Файл с введёнными ключами и ссылками повреждён — введите значения заново: сохранение заменит его."
)
SETUP_KEYS_NOTICE_TOKEN_UNREADABLE: Final[str] = (
    "Значения из токена не прочитались — загрузите токен заново на вкладке «Токены»."
)

# --- настройщик, вкладка «Эфиры YouTube» (CLAUDE.md §8.2, п.4). {key} и {problem} — из ConfigError загрузчика.
SETUP_CHANNELS_NOTICE_FILE_MISSING: Final[str] = (
    "Файла secrets\\channels.json ещё нет: добавьте хотя бы один канал и сохраните."
)
SETUP_CHANNELS_NOTICE_UNREADABLE: Final[str] = (
    "Файл secrets\\channels.json не прочитался: {key} — {problem}. Сохранение заменит его списком этой вкладки, "
    "а прежний файл останется в secrets\\channels.previous.json."
)

# --- настройщик, настройки livecraft.json (CLAUDE.md §8.2). {key} и {problem} — из ConfigError загрузчика.
SETUP_SETTINGS_NOTICE_UNREADABLE: Final[str] = (
    "Файл secrets\\livecraft.json не прочитался: {key} — {problem}. Окно открыто на поставочных значениях программы; "
    "файл будет записан первым сохранением настроек."
)

# --- окно настройщика (CLAUDE.md §8, app\setup\app.py и app\setup\tabs\): вкладки, подписи, кнопки, диалоги.
# Значения сейфа сюда не подставляются никогда: окно показывает только маски из модели вкладки (§7.4).
SETUP_WINDOW_TITLE: Final[str] = "Livecraft {version} — настройка"
SETUP_WINDOW_FAILED: Final[str] = (
    "Окно настройщика не открылось ({error}). Нужен рабочий стол Windows и Python с компонентом tcl/tk."
)
# Ошибка программы в обработчике окна настройщика (app\setup\app.py::ActionFailure): окно работает дальше.
SETUP_ACTION_FAILED: Final[str] = (
    "Действие окна не выполнилось из-за ошибки программы — подробности в логе {log}. Окно работает дальше; "
    "лог передаёт в поддержку «Отправить логи» на вкладке «Логи»."
)
# Вкладки по порядку окна — по значениям SetupPage (app\setup\page.py, §14 решение 37).
SETUP_TAB_TITLES: Final[dict[str, str]] = {
    "home": "Главная",
    "plan": "Таблица плана",
    "merge": "Нейросеть",
    "previews": "Превью",
    "doc": "Google-документ",
    "package": "Пакет",
    "telegram": "Telegram",
    "broadcasts": "Эфиры YouTube",
    "keys": "Форма",
    "tokens": "Токены",
    "logs": "Логи",
    "advanced": "Дополнительно",
}
SETUP_READY: Final[str] = "Готово к запуску."
SETUP_BUTTON_SAVE: Final[str] = "Сохранить"
SETUP_PROBLEM_LINE: Final[str] = "{label}: {text}"
SETUP_SAVE_FAILED_TITLE: Final[str] = "Не сохранено"
SETUP_CLOSE_DIRTY_TITLE: Final[str] = "Несохранённые изменения"
SETUP_CLOSE_DIRTY_TEXT: Final[str] = "Есть несохранённые изменения. Закрыть без сохранения?"
# Задано поле или нет — видно сразу (app\setup\panels\keys_panel.py::KeyRow, link_panel.py::SettingLink): {mask} —
# короткая маска значения (SecretValue.short_mask), без названия поля; ссылка — открытая настройка, показывается как есть.
SETUP_KEY_STATUS_OWN: Final[str] = "✓ задано ({mask})"
SETUP_KEY_STATUS_TOKEN: Final[str] = "✓ получено с токеном ({mask})"
SETUP_LINK_STATUS_SET: Final[str] = "✓ задано: {url}"
SETUP_STATUS_NOT_SET: Final[str] = "✗ не задано"
# Знаки строк итога проверок окна (app\setup\tabs\check_line.py::ResultRow): «✓» — годится (зелёная строка), «✗» —
# проблема (красная); строка без знака — справка. {line} — строка, которой окно ставит знак.
CHECK_MARK_OK: Final[str] = "✓"
CHECK_MARK_PROBLEM: Final[str] = "✗"
CHECK_OK_LINE: Final[str] = "✓ {line}"
CHECK_PROBLEM_LINE: Final[str] = "✗ {line}"

# --- «Главная» (§14 решение 37, app\setup\panels\lines_panel.py): линии работы. Ключи SETUP_LINE_DOES — значения
# RunPart; {lines} — названия линий через запятую, {line} — линия-опора, {gaps} — строки нужд Readiness.gap.
SETUP_HOME_INTRO: Final[str] = (
    "Livecraft готовит эфиры: берёт план из Google-таблицы или из пакетов, пишет нейросетью название и описание "
    "эфира, готовит превью, документ объявлений и пакет, присылает объявления в Telegram, создаёт эфиры на каналах "
    "YouTube и передаёт ключи стримеру."
)
SETUP_HOME_HOWTO: Final[str] = (
    "Каждая строка ниже — подключение и настройка функции работы приложения. Знак ✗ обозначает необходимость "
    "настроить определённый функционал работы приложения."
)
SETUP_HOME_GO: Final[str] = "Перейти"
SETUP_HOME_RUNS: Final[str] = "Запуск сделает (эфиры {source}): {lines}"
SETUP_HOME_RUNS_NOTHING: Final[str] = "Запуск ничего не сделает: не включено ни одной линии."
SETUP_HOME_RUN_SOURCES: Final[dict[str, str]] = {
    "plan": "из таблицы плана",
    "packages_in": "из пакетов",
}
SETUP_HOME_RUNS_KEYS_ALL: Final[str] = "{line} — ключи всех эфиров запуска заново"
# Этапы «Главной» — по значениям LineStage (app\run\mode.py, §14 решение 48); вход — по значениям RunPart.
SETUP_LINE_STAGES: Final[dict[str, str]] = {
    "input": "1. Вход — откуда эфиры",
    "processing": "2. Обработка",
    "output": "3. Вывод",
    "broadcasts": "4. Эфиры",
}
SETUP_HOME_INPUTS: Final[dict[str, str]] = {
    "plan": "Таблица плана",
    "packages_in": "Пакеты",
}
SETUP_LINE_DOES: Final[dict[str, str]] = {
    "plan": "читает план эфиров из Google-таблицы",
    "merge": "пишет одно название и одно описание на эфир",
    "local_previews": "сохраняет превью видео в папку на этом компьютере",
    "drive_previews": "копирует превью в папку на Google Диске и ставит ссылки в таблицу",
    "doc": "создаёт документ объявлений на каждую дату",
    "doc_copy": "сохраняет копию документа .docx на этом компьютере",
    "package": "собирает файл пакета для эфиров на других компьютерах",
    "announce": "отправляет объявления и пакет в Telegram",
    "broadcast": "создаёт и правит эфиры на каналах YouTube",
    "keys": "передаёт ключи эфиров стримеру через Google-форму",
    "packages_in": "берёт эфиры из пакетов в папке пакетов — с их текстами и формой ключей",
}
SETUP_LINE_READY: Final[str] = "✓ готово"
SETUP_LINE_BLOCKED: Final[str] = "✗ не хватает: {gaps}"
SETUP_LINE_GAP_JOINER: Final[str] = "; "
SETUP_LINE_OFF: Final[str] = "выключена"
SETUP_LINE_WITH_SUPPORT: Final[str] = "не работает без «{line}»"
# Почему линия без опоры не работает — по значению опоры (RunPart); прочие опоры — SETUP_LINE_WITH_SUPPORT.
SETUP_LINE_SUPPORT_REASONS: Final[dict[str, str]] = {
    "plan": "работает только от таблицы плана",
    "merge": "от таблицы плана работает только с нейросетью: тексты «по номерам» на YouTube и в пакет не идут",
}
# Название строки линии, если оно не название линии: ползунок передачи ключей на вкладке «Форма».
SETUP_LINE_TITLES: Final[dict[str, str]] = {
    "keys": "Передавать ключи в форму",
}
# Строка «Ключи в форму» на «Главной» (§14 решения 47, 49): кнопки — по значениям KeysChoice, строка под ними — что
# делает выбранное или почему выбор недоступен (по значениям KeysReason, app\setup\panels\lines_panel.py).
SETUP_KEYS_CHOICES: Final[dict[str, str]] = {
    "new": "новые",
    "all": "все",
}
SETUP_KEYS_HINTS: Final[dict[str, str]] = {
    "new": (
        "Уйдут ключи эфиров, которые запуск поставит на YouTube, и один повтор ключа, который форма в прошлый раз не "
        "подтвердила."
    ),
    "all": (
        "Ключи всех эфиров запуска уйдут ещё раз: у стримера появятся повторные строки, он берёт последнюю. После "
        "полного запуска, где форма подтвердила все ключи, выбор сам вернётся на «новые»."
    ),
}
SETUP_KEYS_INACTIVE: Final[dict[str, str]] = {
    "off": "Передача ключей выключена — ползунок «Передавать ключи в форму» на вкладке «Форма».",
    "no_broadcasts": "Эфиры YouTube выключены — передавать нечего.",
    "no_merge": "Эфиры не работают: от таблицы плана они идут только с нейросетью.",
    "no_form": "Не задана ссылка на форму ключей — вкладка «Форма».",
}
# Поле, которое не нужно ни одной работающей линии (app\setup\fields\field_use.py): оно бледное, под ним — эта строка.
SETUP_FIELD_NEEDED_BY: Final[str] = "Нужно линиям: {lines}"
# Поле, нужду которого при входе «Пакеты» закрывают сами пакеты (app\setup\fields\field_use.py): по значениям Need.
SETUP_FIELD_FROM_PACKAGES: Final[dict[str, str]] = {
    "form": "При входе «Пакеты» форма ключей у каждого эфира — из его пакета.",
    "sheets_vault": "При входе «Пакеты» таблица плана не читается.",
}

# --- вкладки линий (§8.2, §14 решение 37): строки полей сейфа, открытых ссылок и папок.
# Подписи и серые подсказки строк сейфа — по значениям SecretField.
SETUP_KEY_FIELD_LABELS: Final[dict[str, str]] = {
    "openai_api_key": "Ключ OpenAI",
    "sheets_id": "Google-таблица с планом стримов",
    "drive_folder": "Папка Google Диска для материалов",
    "telegram_bot_token": "Токен бота",
    "support_bot_token": "Токен бота поддержки",
}
SETUP_KEY_FIELD_HINTS: Final[dict[str, str]] = {
    "openai_api_key": "platform.openai.com → API keys → Create new secret key; ключ начинается с sk-",
    "sheets_id": "откройте таблицу в браузере и скопируйте ссылку из адресной строки",
    "drive_folder": (
        "папка на Google Диске, куда программа складывает Google-документы объявлений и копии превью (подпапки превью "
        "она создаёт сама): откройте папку в браузере и скопируйте ссылку вида https://drive.google.com/drive/folders/…"
    ),
}
# Какой должна быть таблица плана (§14 решение 26): образец — шапка из названий колонок плана
# (SHEET_PLAN_COLUMN_NAMES) и строка по колонкам; {timezone} — часовой пояс программы из livecraft.json.
SETUP_TABLE_TITLE: Final[str] = "Какой должна быть таблица"
SETUP_TABLE_TEXT_BEFORE: Final[str] = (
    "Первая строка — названия колонок. Программе нужны три колонки — в любом месте и порядке, остальные она не "
    "читает. Лист программа находит сама: тот, где в первой строке есть эти три названия."
)
SETUP_TABLE_SAMPLE_ROW: Final[dict[str, str]] = {
    "link": "https://www.youtube.com/watch?v=…",
    "date": "28.09.2026",
    "time": "19:00",
}
# Колонки, которые пишет программа (язык и превью), и колонка чипа видео в образце таблицы: заголовки языка и превью —
# содержимое таблицы (app\sheets\preview.py::LANGUAGE_HEADER, PREVIEW_HEADER), чип — для человека, программа его не читает.
SETUP_TABLE_SAMPLE_BY_PROGRAM: Final[str] = "(впишет программа)"
SETUP_TABLE_SAMPLE_CHIP_HEADER: Final[str] = "видео (чип)"
SETUP_TABLE_SAMPLE_CHIP: Final[str] = "▶ Название видео"
SETUP_TABLE_TEXT_AFTER: Final[str] = (
    "Одна строка — одно видео. Видео на одно время и одного языка программа собирает в один эфир. Дата — 28.09.2026, "
    "28-09-2026 или 2026-09-28; время — 19:00, по часовому поясу программы: {timezone}. Строки с прошедшей датой "
    "пропускаются. В строку видео программа сама пишет язык, который определила по самому видео, — в колонку «Lang», и "
    "ссылку на копию превью — в колонку «Preview (Google Drive)»; нет таких колонок — добавит их. Колонка «видео "
    "(чип)» — для человека; остальное в таблице программа только читает."
)
# Проверка таблицы в окне: тем же чтением, что при запуске; значений сейфа в строках нет (§7.4).
SETUP_TABLE_BUTTON_CHECK: Final[str] = "Проверить таблицу"
SETUP_TABLE_CHECKING: Final[str] = "Проверяю таблицу…"
SETUP_TABLE_LOGIN: Final[str] = (
    "Открылся браузер — войдите аккаунтом Google, которому открыта таблица плана (это не аккаунт канала YouTube), "
    "и отметьте все разрешения."
)
SETUP_TABLE_OK_NEAREST: Final[str] = (
    "✓ Лист «{sheet}»: ссылка — колонка {link}, дата — {date}, время — {time}. Будущих эфиров в таблице: {count}, "
    "ближайший — {nearest}."
)
SETUP_TABLE_OK_NONE: Final[str] = (
    "✓ Лист «{sheet}»: ссылка — колонка {link}, дата — {date}, время — {time}. Строк с будущими эфирами пока нет."
)
SETUP_TABLE_FAILED: Final[str] = "✗ {problem}"
# Фоновая проверка оборвалась непредвиденной ошибкой (app\setup\tabs\table_block.py): трассировка — в лог запуска.
SETUP_TABLE_INTERRUPTED: Final[str] = "Проверка прервалась — подробности в логе."
# Открытые ссылки livecraft.json (§14 решение 15) — по пути ключа (SettingKey).
SETUP_LINK_LABELS: Final[dict[str, str]] = {
    "form.url": "Google-форма для ключей стримов",
}
SETUP_LINK_HINTS: Final[dict[str, str]] = {
    "form.url": (
        "форма, через которую программа передаёт стримеру ключи стримов: ссылка вида https://forms.gle/…"
    ),
}
# Проверка папки материалов на Google Диске (app\setup\panels\folder_check.py, §14 решение 27): тем же клиентом Диска,
# что при запуске; {name} — название папки на Диске.
SETUP_FOLDER_BUTTON_CHECK: Final[str] = "Проверить папку"
SETUP_FOLDER_CHECKING: Final[str] = "Проверяю папку…"
SETUP_FOLDER_LOGIN: Final[str] = (
    "Открылся браузер — войдите в аккаунт Google, у которого есть доступ к папке, и отметьте все разрешения."
)
SETUP_FOLDER_OK: Final[str] = "✓ Папка «{name}»: программа может складывать в неё файлы."
SETUP_FOLDER_FAILED: Final[str] = "✗ {problem}"
SETUP_FOLDER_NOT_FOLDER: Final[str] = "Ссылка ведёт не на папку, а на файл «{name}» — нужна ссылка на папку."
SETUP_FOLDER_READ_ONLY: Final[str] = (
    "Папка «{name}»: программе нельзя добавлять в неё файлы — дайте аккаунту Google, под которым вошли, право "
    "редактора."
)
# Проверка ключа OpenAI на вкладке «Нейросеть» (app\setup\panels\llm_key_check.py): тот же выбор модели, что у запуска;
# {choice} — строка выбора модели (LLM_CHOICE_LINE, LLM_CHOICE_REFUSED), {reason} — отказ пробы. Значения ключа нет.
SETUP_LLM_KEY_BUTTON_CHECK: Final[str] = "Проверить ключ"
SETUP_LLM_KEY_CHECKING: Final[str] = "Проверяю ключ…"
SETUP_LLM_KEY_OK: Final[str] = "✓ Ключ принят. {choice}"
SETUP_LLM_KEY_UNCHECKED: Final[str] = "✗ Ключ проверить не удалось: {reason} {choice}"
SETUP_LLM_KEY_FAILED: Final[str] = "✗ {problem}"
# Проверка формы ключей на вкладке «Форма» (app\setup\panels\form_check.py): форма читается тем же кодом, что у
# запуска; {questions} — названия вопросов в кавычках; даты — 17.03.2027; покрытие дат будущих эфиров таблицы плана —
# строкой запуска FORM_DATES_* или строками ниже.
SETUP_FORM_BUTTON_CHECK: Final[str] = "Проверить форму"
SETUP_FORM_CHECKING: Final[str] = "Проверяю форму…"
SETUP_FORM_OK: Final[str] = "✓ Форма «{form}»: вопросы на месте — {questions}."
SETUP_FORM_QUESTIONS_MISSING: Final[str] = (
    "✗ В форме «{form}» нет вопросов {questions} — названия вопросов в livecraft.json (раздел form) должны совпадать с "
    "формой."
)
SETUP_FORM_QUESTION: Final[str] = "«{title}»"
SETUP_FORM_DATES: Final[str] = "Даты «{question}» от сегодня: {dates}."
SETUP_FORM_NO_DATES: Final[str] = (
    "✗ В «{question}» нет дат от сегодня — эфиры не допускаются, пока владелец формы их не добавит."
)
SETUP_FORM_DATE_ANY: Final[str] = "«{question}»: дата вводится текстом — подходит любая."
SETUP_FORM_TABLE_EMPTY: Final[str] = "В таблице плана нет будущих эфиров — покрытие дат проверять не на чем."
SETUP_FORM_TABLE_UNREAD: Final[str] = "✗ Покрытие дат таблицы плана не проверено: {problem}"
SETUP_FORM_FAILED: Final[str] = "✗ {problem}"
SETUP_FORM_NOT_SET: Final[str] = "Не задана ссылка на форму — впишите её выше и нажмите «Сохранить»."
# Вход в канал и проверка всех каналов на вкладке «Эфиры YouTube» (app\setup\panels\channels_check.py): строки итога —
# те же, что у .\livecraft.bat --auth и --check.
SETUP_CHANNELS_BUTTON_LOGIN: Final[str] = "Войти в выбранный канал"
SETUP_CHANNELS_BUTTON_CHECK: Final[str] = "Проверить все каналы"
SETUP_CHANNELS_CHECKING: Final[str] = "Проверяю каналы…"
# Папки ролей (§14 решение 37, app\setup\fields\folder_field.py) — по пути ключа раздела folders; {path} — где папка.
SETUP_FOLDER_LABELS: Final[dict[str, str]] = {
    "folders.packages": "Папка пакетов",
    "folders.docs": "Папка копий документов",
    "folders.images": "Папка превью",
}
SETUP_FOLDER_HINTS: Final[dict[str, str]] = {
    "folders.packages": (
        "куда программа кладёт пакеты plan_*.bcast; когда таблица плана выключена, из неё берут эфиры все линии"
    ),
    "folders.docs": "куда программа сохраняет копии документов объявлений .docx — по папке на дату",
    "folders.images": "куда программа сохраняет превью видео; подпапки — по шаблону ниже",
}
SETUP_FOLDER_STATUS: Final[str] = "✓ папка: {path}"
SETUP_FOLDER_BUTTON_CHOOSE: Final[str] = "Выбрать…"
SETUP_FOLDER_BUTTON_DEFAULT: Final[str] = "По умолчанию"
# Сброс своего значения называется по итогу (KeyRow.reset_label): под своим есть значение программы — оно
# вернётся; нет — поле останется пустым.
SETUP_KEYS_BUTTON_RESET_TO_TOKEN: Final[str] = "Вернуть значение из токена"
SETUP_KEYS_BUTTON_DELETE_OWN: Final[str] = "Удалить"

# --- вкладка «Токены» (§8.2 п.10, §14 решения 16, 44; app\setup\tabs\tokens_tab.py). Значений в строках нет: только
# названия того, что входит в токен.
SETUP_TOKENS_INTRO: Final[str] = (
    "Токен передаёт другому человеку ключи, ссылки, ботов и чаты Telegram и контакты документа объявлений, заданные "
    "на этом компьютере своими: получатель работает на них, но не видит их. Каналы YouTube, входы в Google и "
    "значения, пришедшие в чужом токене, в токен не входят."
)
SETUP_TOKENS_CREATE_TITLE: Final[str] = "Новый токен"
SETUP_TOKENS_CREATE_TEXT: Final[str] = (
    "Токен — один файл (.lctoken): ключ к значениям — внутри него. Передать его можно любым путём; загрузит его любой, "
    "у кого он окажется, поэтому передавать — только тому, кому он предназначен."
)
SETUP_TOKENS_DAYS_LABEL: Final[str] = "Срок действия, суток:"
SETUP_TOKENS_DAYS_HINT: Final[str] = (
    "до конца срока токен можно загрузить; загруженные значения работают и после него"
)
SETUP_TOKENS_DAYS_PROBLEM: Final[str] = "срок — целое число суток от 1 до {maximum}"
SETUP_TOKENS_CONTENTS: Final[str] = "В токен войдут: {items}."
SETUP_TOKENS_NOTHING: Final[str] = (
    "Передавать нечего: своих ключей, ссылок и чатов ещё не задано — их задают на вкладках линий."
)
SETUP_TOKENS_BUTTON_CREATE: Final[str] = "Создать токен"
SETUP_TOKENS_CREATING: Final[str] = "Создаю токен…"
SETUP_TOKENS_CREATED: Final[str] = "✓ Создан токен {token}."
SETUP_TOKENS_VALID_UNTIL: Final[str] = "Загрузить его можно до {until}."
SETUP_TOKENS_INSIDE: Final[str] = "В токене: {items}."
SETUP_TOKENS_WRITE_FAILED: Final[str] = "файл токена не записался: {reason}"
SETUP_TOKENS_LOAD_TITLE: Final[str] = "Полученный токен"
SETUP_TOKENS_LOAD_TEXT: Final[str] = (
    "Нажмите «Загрузить токен…» и выберите файл токена (.lctoken). Значения из токена заменяют прежние значения из "
    "токена; свои значения остаются главными."
)
SETUP_TOKENS_BUTTON_LOAD: Final[str] = "Загрузить токен…"
SETUP_TOKENS_LOADING: Final[str] = "Загружаю токен…"
SETUP_TOKENS_PICK_TOKEN: Final[str] = "Файл токена Livecraft"
SETUP_TOKENS_LOADED: Final[str] = "✓ Токен загружен: {items}."
SETUP_TOKENS_LOADED_UNTIL: Final[str] = (
    "Токен действовал до {until}; загруженные значения работают и после этого срока."
)
SETUP_TOKENS_SAVE_FAILED: Final[str] = "значения токена не записались: {reason}"
SETUP_TOKENS_SETTINGS_FAILED: Final[str] = "настройки из токена не подошли: {problem}"
SETUP_TOKENS_INTERRUPTED: Final[str] = "Работа с токеном прервалась — подробности в логе."
# Открытые настройки в токене — по значениям SettingKey (app\config\setting_key.py).
TOKEN_SETTING_LABELS: Final[dict[str, str]] = {
    "form.url": FORM_URL_LABEL,
    "telegram.target": "куда слать объявления",
    "telegram.group_chat_id": "группа с ботом для объявлений",
    "telegram.private_chat_id": "чат с ботом для объявлений",
    "telegram.support_chat_id": "чат поддержки",
    "docs.contacts": DOCS_CONTACTS_LABEL,
}
# Почему токен не создан или не загружен — по значениям TokenProblem (app\secretsafe\token.py).
TOKEN_PROBLEM_TEXT: Final[dict[str, str]] = {
    "no_network": (
        "нет связи с Google: время создания и срок токена берутся из ответа Google — подключите интернет и повторите"
    ),
    "file_unreadable": "файл не открывается — его держит другая программа, нет прав или на его месте папка",
    "not_token": "это не файл токена Livecraft (.lctoken)",
    "version": "токен другой версии программы — создайте новый токен в этой версии",
    "damaged": "файл токена повреждён или изменён",
    "expired": "срок токена истёк — нужен новый токен",
}
# «Показать своё» (§14 решение 11): только значение, которое пользователь ввёл сам, только на экран.
SETUP_KEYS_BUTTON_REVEAL: Final[str] = "показать"
SETUP_KEYS_BUTTON_HIDE: Final[str] = "скрыть"
SETUP_KEYS_SAVE_FAILED_OS: Final[str] = (
    "Не удалось записать файл с введёнными значениями. Проверьте, не занят ли он другой программой (антивирус, "
    "синхронизация), и нажмите «Сохранить» ещё раз."
)

# --- вкладка «Эфиры YouTube» (§8.2 п.4): подписи по ключам SettingProblem (имя поля строки канала) и по полям
# ChannelDraft. Название канала не вводится (§14 решение 25): у нового канала оно берётся из ника, поэтому его
# проблема называется ником.
SETUP_CHANNELS_INTRO: Final[str] = (
    "Каналы YouTube, на которых Livecraft создаёт эфиры. На каждый канал программа ставит эфиры на языке его стримов."
)
SETUP_CHANNEL_FIELD_LABELS: Final[dict[str, str]] = {
    "account_name": "Ник канала",
    "handle": "Ник канала",
    "google_account": "Почта аккаунта Google",
    "languages": "Язык стримов",
    "privacy": "Видимость стримов на YouTube",
    "platform": "площадка",
    "channels": "список каналов",
}
# Серые подсказки с примерами — справа от полей ввода.
SETUP_CHANNEL_FIELD_HINTS: Final[dict[str, str]] = {
    "handle": (
        "как в YouTube, с @, например @Lena. Где взять: YouTube → аватар вверху справа → ник под названием канала"
    ),
    "google_account": (
        "почта аккаунта Google, под которым входят в этот канал, например lena@gmail.com — при входе откроется нужный "
        "аккаунт"
    ),
    "languages": "на каком языке идут эфиры канала",
    "privacy": (
        "– видимость стримов «для всех» — эфир видят все, подписчики получают уведомление;\n"
        "– видимость стримов «по ссылке» — эфир видят только те, у кого есть ссылка."
    ),
}
# Колонки таблицы каналов — по полям ChannelDraft.
SETUP_CHANNEL_COLUMNS: Final[dict[str, str]] = {
    "handle": "ник",
    "google_account": "почта Google",
    "languages": "язык стримов",
    "privacy": "видимость на YouTube",
}
# Видимость словами — по значениям Privacy; в channels.json пишется само значение.
SETUP_PRIVACY_LABELS: Final[dict[str, str]] = {
    "public": "для всех",
    "unlisted": "по ссылке",
}
SETUP_CHANNELS_BUTTON_ADD: Final[str] = "Добавить"
SETUP_CHANNELS_BUTTON_UPDATE: Final[str] = "Изменить выбранный"
SETUP_CHANNELS_BUTTON_REMOVE: Final[str] = "Удалить выбранный"
SETUP_CHANNELS_NOTHING_SELECTED: Final[str] = "Сначала выберите канал в таблице."
SETUP_CHANNELS_SAVE_FAILED: Final[str] = "Не удалось записать secrets\\channels.json: {error}"
# Язык канала — один, выбор в выпадающем поле по названию (app\setup\fields\language_choice.py); языки формы — первыми.
SETUP_LANGUAGE_OPTION: Final[str] = "{name} ({code})"
SETUP_LANGUAGE_OPTION_IN_FORM: Final[str] = "{name} ({code}) — есть в форме"
# Код, которого нет в справочнике ISO 639-1 (вариант формы или язык старого channels.json): загрузчик его не примет.
SETUP_LANGUAGE_OPTION_NOT_ISO: Final[str] = "{code} (не код ISO 639-1)"
SETUP_LANGUAGE_OPTION_NOT_ISO_IN_FORM: Final[str] = "{code} (не код ISO 639-1) — есть в форме"
# Текст в поле, который не совпадает ни с одной строкой списка: в черновик канала он не уходит.
SETUP_LANGUAGE_PICK_FROM_LIST: Final[str] = "выберите язык из списка"
# Канал, записанный раньше с несколькими языками: у канала теперь один язык (решение 21, 24-09-2026).
SETUP_LANGUAGE_SEVERAL: Final[str] = "у канала несколько языков — при сохранении останется {name}"
SETUP_LANGUAGE_NOT_IN_FORM: Final[str] = (
    "язык {names} нет среди вариантов Google-формы — эфиры на нём не будут допущены"
)

# --- настройки livecraft.json на вкладках линий и «Дополнительно» (§8.2 п.6): подписи по ключам SettingProblem (путь поля).
SETUP_ADVANCED_INTRO: Final[str] = (
    "Часовой пояс программы и срок хранения старых файлов нужны при любых линиях работы; остальные настройки — на "
    "вкладках линий. Значения по умолчанию подходят — меняйте, только если знаете зачем."
)
SETUP_SETTINGS_FIELD_LABELS: Final[dict[str, str]] = {
    "min_lead_minutes": "минимальный запас до старта эфира (минут)",
    "keep_days": "хранить старые файлы программы (дней)",
    "auto_start": "эфир стартует сам, когда пошёл видеопоток",
    "set_thumbnail": "ставить обложку эфира",
    "category_id": "категория видео на YouTube",
    "youtube_pause_seconds": "пауза между обращениями к YouTube (секунд)",
    "image_dir_template": "шаблон подпапок превью",
    "timezone": "часовой пояс",
    "llm.model": "модель OpenAI",
    "llm.fallback_model": "запасная модель OpenAI",
    "llm.reasoning_effort": "глубина рассуждений модели",
    "llm.service_tier": "тариф OpenAI",
    "llm.timeout_sec": "сколько ждать ответа модели (секунд)",
    "llm.max_output_tokens": "наибольшая длина ответа модели (токенов)",
    "drive.preview_path_template": "шаблон подпапок превью на Google Диске",
    "docs.access": "доступ к документу объявлений по ссылке",
    "docs.contacts": DOCS_CONTACTS_LABEL,
}
# Серые подсказки справа от поля — по тем же ключам, что подписи; есть не у всех полей. Строки не проходят
# через .format: {date} и {language} здесь — буквальный текст шаблона папки.
SETUP_SETTINGS_FIELD_HINTS: Final[dict[str, str]] = {
    "category_id": (
        "номер категории YouTube: 22 — «Люди и блоги», 24 — «Развлечения», 25 — «Новости и политика», "
        "27 — «Образование»"
    ),
    "image_dir_template": (
        "шаблон подпапки внутри папки превью: вместо {date} программа подставит дату эфира, вместо {language} — "
        "язык. {date}/{language} даёт image\\23-09-2026\\uk"
    ),
    "youtube_pause_seconds": "сколько ждать между обращениями к YouTube; 0.5 — обычно достаточно",
    "llm.model": "модель OpenAI для текстов эфира, например gpt-5.6-sol",
    "llm.fallback_model": "если основная модель недоступна, например gpt-5.4",
    "llm.service_tier": "flex — дешевле и медленнее, default — обычный",
    "timezone": "Europe/Kyiv — киевское время",
    "drive.preview_path_template": (
        "шаблон подпапки превью внутри папки материалов на Google Диске: вместо {date} программа подставит дату "
        "эфира, вместо {language} — язык. preview/{date}/{language} даёт preview\\28-09-2026\\uk"
    ),
    "docs.access": "кому открыт документ объявлений по ссылке на него",
    "docs.contacts": (
        "строка «Contact:» в шапке документа объявлений, например @nick или адрес почты; пусто — блока "
        "контактов нет"
    ),
}
# Доступ к документу объявлений по ссылке (app\config\docs.py::DocAccess): ключи — значения в livecraft.json.
SETUP_DOC_ACCESS_LABELS: Final[dict[str, str]] = {
    "private": "только тем, кому документ открыт на Диске",
    "reader": "все по ссылке — только чтение",
    "commenter": "все по ссылке — комментарии",
    "writer": "все по ссылке — правка",
}
SETUP_SETTINGS_SAVE_FAILED: Final[str] = "Не удалось записать secrets\\livecraft.json: {error}"

# --- вкладка «Логи» (§8.2 п.11, §14 решения 20, 43; app\setup\tabs\logs_tab.py): чат поддержки и «Отправить логи».
# Значений сейфа в строках нет; {megabytes} — размер архива в МБ, {limit} — предел архива в МБ.
SETUP_LOGS_INTRO: Final[str] = (
    "Что-то пошло не так — логи Livecraft одним нажатием уходят в чат поддержки: там по ним разберутся, что случилось, "
    "без переписки и поиска файлов."
)
SETUP_LOGS_BOT_TITLE: Final[str] = "Бот поддержки"
SETUP_LOGS_BOT_TEXT: Final[str] = (
    "Логи приносит бот поддержки — отдельный от бота объявлений: логи доходят до поддержки, какой бы бот ни слал "
    "объявления. Обычно бот поддержки приходит с токеном доступа. Свой бот — у @BotFather: /newbot, токен вставьте "
    "сюда и нажмите «Сохранить»."
)
SETUP_LOGS_CHAT_TITLE: Final[str] = "Чат поддержки"
SETUP_LOGS_CHAT_TEXT: Final[str] = (
    "Откройте бота поддержки в Telegram и нажмите «Старт» (или добавьте его в группу поддержки и отправьте в ней "
    "/start@имя_бота), затем нажмите «Подключить чат поддержки»."
)
SETUP_LOGS_SEND_TITLE: Final[str] = "Отправить логи"
SETUP_LOGS_SEND_TEXT: Final[str] = (
    "Архив ложится в папку logs: файлы этой папки, новые первыми, до {limit} МБ, и diagnostics.txt — версия программы, "
    "система и готовность линий, без ключей и ссылок. Не уходят никогда: secrets, keystreams, tokens."
)
SETUP_LOGS_BUTTON_SEND: Final[str] = "Отправить логи"
SETUP_LOGS_BUTTON_SAVE: Final[str] = "Сохранить архив логов"
SETUP_LOGS_BUTTON_CONNECT: Final[str] = "Подключить чат поддержки"
SETUP_LOGS_BUTTON_RECONNECT: Final[str] = "Подключить другой чат поддержки"
SETUP_LOGS_NO_SUPPORT_BOT: Final[str] = "Бот поддержки не задан — архив логов остаётся в папке logs."
SETUP_LOGS_ROUTE_SEND: Final[str] = "Архив ляжет в папку logs и уйдёт ботом поддержки в чат поддержки."
SETUP_LOGS_WORKING: Final[str] = "Собираю архив логов…"
SETUP_LOGS_INTERRUPTED: Final[str] = "Отправка логов прервалась — подробности в логе."
# Подпись архива в чате поддержки: {moment} — DD.MM.YYYY HH:MM по поясу программы.
SETUP_LOGS_CAPTION: Final[str] = "🛠 Логи Livecraft {version} на {moment} — файлов: {files}"
SETUP_LOGS_SENT: Final[str] = "Логи отправлены в чат поддержки: файлов {files}, {megabytes:.1f} МБ."
SETUP_LOGS_SAVED: Final[str] = "Архив логов сохранён: {path} (файлов {files}, {megabytes:.1f} МБ)."
SETUP_LOGS_NOT_SENT: Final[str] = "Логи не отправлены: {reason}"
SETUP_LOGS_NOT_SAVED: Final[str] = "Архив логов не сохранился в папку logs: {reason}"
SETUP_LOGS_SKIPPED: Final[str] = "Старые файлы логов не вошли в архив — предел {limit} МБ: {count}."
# Чат поддержки — те же шаги, что у чата объявлений (ChatRole.SUPPORT): {destination} — вид и чат в винительном падеже.
# Строка чата поддержки — слова строк объявлений (SETUP_TELEGRAM_CHAT_CONNECTED); ниже — строка над кнопкой отправки,
# когда бот поддержки задан, а чата поддержки нет (LogsPanel.route).
SETUP_LOGS_CHAT_NOT_CONNECTED: Final[str] = "Чат поддержки ещё не подключён — архив логов сохраняется в папку logs."
SETUP_LOGS_CHAT_CONNECTED: Final[str] = (
    "Готово: логи будут приходить в {destination}. Пробное сообщение уже там — загляните в Telegram."
)
SETUP_LOGS_CHAT_CHOOSE: Final[str] = "Бот видит несколько чатов — нажмите в списке на тот, куда слать логи."
SETUP_LOGS_CHAT_NO_CHATS: Final[str] = (
    "Бот поддержки @{username} пока не видит ни одного чата: откройте его в Telegram и нажмите «Старт» (для группы "
    "— добавьте бота в группу и отправьте в ней /start@{username}), затем ещё раз «{button}»."
)
SETUP_LOGS_BOT_FIRST: Final[str] = "Сначала бот поддержки: вставьте его токен выше и нажмите «Сохранить»."
SETUP_LOGS_CHAT_CONNECT_TEXT: Final[str] = "Livecraft: чат подключён. Сюда будут приходить логи Livecraft."

# --- вкладка «Telegram» (§8.2 п.3, §14 решения 19, 20): объявления в три шага. id чатов вручную не вводятся.
# Токена бота в строках нет: он показывается только маской (§7.4).
SETUP_TELEGRAM_INTRO: Final[str] = (
    "Перед эфирами Livecraft присылает объявления — название, описание, превью и время эфира — в Telegram от имени "
    "бота: в чат с ботом или в группу с ботом. Настройка — три шага."
)
SETUP_TELEGRAM_STEP_1_TITLE: Final[str] = "Шаг 1. Бот"
SETUP_TELEGRAM_STEP_1_TEXT: Final[str] = (
    "Нет своего бота в Telegram — создайте его: найдите @BotFather, отправьте ему /newbot и придумайте имя — "
    "BotFather пришлёт токен. Вставьте токен бота сюда и нажмите «Сохранить»."
)
SETUP_TELEGRAM_STEP_2_TITLE: Final[str] = "Шаг 2. Чат"
SETUP_TELEGRAM_STEP_2_TEXT: Final[str] = (
    "Чат с ботом: откройте бота в Telegram и нажмите «Старт» (или отправьте /start). Группа с ботом: добавьте бота в "
    "группу и отправьте в ней /start@имя_бота — обычные сообщения группы бот не видит."
)
SETUP_TELEGRAM_STEP_3_TITLE: Final[str] = "Шаг 3. Подключение"
SETUP_TELEGRAM_STEP_3_TEXT: Final[str] = (
    "Нажмите кнопку подключения у чата с ботом или у группы с ботом — программа найдёт чат, запомнит и пришлёт туда "
    "пробное сообщение. Объявления уходят в один чат — выбор ниже."
)
SETUP_TELEGRAM_BUTTON_OPEN_BOT: Final[str] = "Открыть бота в Telegram"
# Статус шага 1 после сохранения токена (getMe): {name} — имя бота, {username} — его @имя без «@».
SETUP_TELEGRAM_BOT_READY: Final[str] = "✓ бот «{name}» @{username}"
# Чаты объявлений — по строке на вид чата (ChatTarget.search, §14 решение 57); ключи — значения ChatTarget.
SETUP_TELEGRAM_TARGET_TITLES: Final[dict[str, str]] = {
    "private": "Чат с ботом",
    "group": "Группа с ботом",
}
SETUP_TELEGRAM_TARGET_CONNECT: Final[dict[str, str]] = {
    "private": "Подключить чат с ботом",
    "group": "Подключить группу с ботом",
}
SETUP_TELEGRAM_TARGET_RECONNECT: Final[dict[str, str]] = {
    "private": "Подключить другой чат с ботом",
    "group": "Подключить другую (новую) группу с ботом",
}
# Подсказка под неподключённой группой, над кнопкой (§14 решение 58): {username} — @имя бота без «@»; бот ещё не
# назван — без имени. У чата с ботом подсказки нет: её даёт шаг 2.
SETUP_TELEGRAM_TARGET_HINTS: Final[dict[str, str]] = {
    "group": (
        "Сначала добавьте бота @{username} в группу и отправьте в ней /start@{username}, затем нажмите «Подключить "
        "группу с ботом»."
    ),
}
SETUP_TELEGRAM_TARGET_HINTS_UNNAMED: Final[dict[str, str]] = {
    "group": (
        "Сначала добавьте бота в группу и отправьте в ней /start@имя_бота, затем нажмите «Подключить группу с ботом»."
    ),
}
SETUP_TELEGRAM_TARGET_CHOOSE: Final[dict[str, str]] = {
    "private": "Бот видит несколько чатов с ботом — нажмите в списке на свой.",
    "group": "Бот видит несколько групп — нажмите в списке на нужную.",
}
# {username} — @имя бота без «@», {button} — надпись кнопки подключения сейчас.
SETUP_TELEGRAM_TARGET_NO_CHATS: Final[dict[str, str]] = {
    "private": (
        "Бот @{username} пока не видит ни одного чата с ботом: откройте его в Telegram (кнопка «Открыть бота в "
        "Telegram»), нажмите «Старт», затем ещё раз «{button}»."
    ),
    "group": (
        "Бот @{username} пока не видит ни одной группы: добавьте его в группу, отправьте в ней /start@{username}, затем "
        "ещё раз «{button}»."
    ),
}
# Строка вида чата: {chat} — название чата, подключённого в этом сеансе, или «id …» по файлу (SETUP_TELEGRAM_CHAT_BY_ID).
SETUP_TELEGRAM_CHAT_CONNECTED: Final[str] = "подключён: {chat}"
SETUP_TELEGRAM_CHAT_NOT_CONNECTED: Final[str] = "не подключён"
SETUP_TELEGRAM_CHAT_BY_ID: Final[str] = "id {chat_id}"
SETUP_TELEGRAM_TARGET_CHOICE: Final[str] = "Куда слать объявления:"
SETUP_TELEGRAM_TARGET_LABELS: Final[dict[str, str]] = {
    "private": "в чат с ботом",
    "group": "в группу с ботом",
}
# Подключённый чат в винительном падеже — по значениям ChatTarget: по файлу — с id, подключённый в этом сеансе — с
# названием.
SETUP_TELEGRAM_TARGETS_INTO: Final[dict[str, str]] = {
    "private": "чат с ботом",
    "group": "группу с ботом",
}
# Куда объявления уходят сейчас — строка под выбором назначения: {destination} — вид и чат в винительном падеже.
SETUP_TELEGRAM_DESTINATION_NOW: Final[str] = "Сейчас объявления уходят в {destination}."
SETUP_TELEGRAM_DESTINATION_NONE: Final[str] = (
    "Объявлениям пока некуда уходить: подключите чат с ботом или группу с ботом."
)
SETUP_TELEGRAM_DESTINATION_BY_ID: Final[str] = "{into} (id {chat_id})"
SETUP_TELEGRAM_DESTINATION_BY_TITLE: Final[str] = "{into} «{title}»"
# Чат подключён: {destination} — вид и чат в винительном падеже («чат с ботом …», «группу с ботом …»).
SETUP_TELEGRAM_CONNECTED: Final[str] = (
    "Готово: объявления будут приходить в {destination}. Пробное сообщение уже там — загляните в Telegram."
)
SETUP_TELEGRAM_STEP_1_FIRST: Final[str] = "Сначала шаг 1: вставьте токен бота и нажмите «Сохранить»."
SETUP_TELEGRAM_CHAT_OPTION: Final[str] = "{kind}: {title} (id {chat_id})"
TELEGRAM_CHAT_KINDS: Final[dict[str, str]] = {
    "private": "личный чат",
    "group": "группа",
    "supergroup": "супергруппа",
    "channel": "канал",
}
SETUP_TELEGRAM_CONNECT_TEXT: Final[str] = "Livecraft: чат подключён. Сюда будут приходить объявления об эфирах."
TELEGRAM_CHAT_MIGRATED: Final[str] = "Группа стала супергруппой: её новый id {new_chat_id} записан вместо {old_chat_id}."
# livecraft.json не читается: подключение чата пишет раздел telegram поверх поставочного вида (SettingsFile.latest).
SETUP_TELEGRAM_NOTICE_UNREADABLE: Final[str] = (
    "Файл secrets\\livecraft.json не прочитался: {key} — {problem}. Подключение чата запишет его заново, а остальные "
    "настройки в нём будут значениями программы по умолчанию."
)

# --- Telegram (app\publish\telegram_bot.py): почему бот не смог. Ключи — значения TelegramProblem; токена нет нигде.
# {description} — пояснение Telegram к отказу: в нём токена нет, Bot API его не повторяет.
TELEGRAM_PROBLEMS: Final[dict[str, str]] = {
    "bad_token": (
        "Telegram не принял токен бота: проверьте токен — бота объявлений на вкладке «Telegram», бота поддержки на "
        "вкладке «Логи»."
    ),
    "chat_not_found": (
        "Telegram не знает такого чата: напишите боту в этот чат и подключите чат заново — чат объявлений на вкладке "
        "«Telegram», чат поддержки на вкладке «Логи»."
    ),
    "forbidden": "Боту запрещено писать в этот чат: бот удалён из группы или заблокирован в личке — верните его.",
    "other_poller": "Бота опрашивает другая программа (например, restreamer) — остановите её и повторите.",
    "webhook": (
        "У бота задан webhook: сообщения боту забирает другая программа, и чаты не видны. Снимите webhook "
        "(deleteWebhook) или остановите ту программу, затем повторите."
    ),
    "rate_limited": "Telegram просит подождать: слишком много сообщений подряд. Повторите через минуту.",
    "network": "Нет связи с Telegram: проверьте интернет и повторите.",
    "server": "Сервер Telegram сейчас не отвечает — повторите позже.",
    "rejected": "Telegram отказал: {description}",
}

# --- план из таблицы (app\sheets\): причины отсева ряда и проблемы плана. Ключи словаря — значения
# RowSkipReason; заголовки шапки — текст оператора, значений ключей и ссылок настроек здесь нет (§7.4).
SHEET_ROW_SKIP_REASONS: Final[dict[str, str]] = {
    "empty_link": "нет ссылки на видео",
    "missing_date_time": "не заполнена дата или время",
    "bad_date_time": "дата или время не разобрались",
    "nonexistent_time": "такого времени нет: в эту ночь часы переводят вперёд на летнее время",
    "in_past": "время эфира уже прошло",
    "bad_link": "в ссылке не найдено видео YouTube",
    "duplicate": "повтор: та же ссылка на то же время уже есть в таблице выше",
}
# Колонки плана (PlanColumn) — ими же подписана шапка образца таблицы в настройщике, и план их узнаёт.
SHEET_PLAN_COLUMN_NAMES: Final[dict[str, str]] = {
    "link": "ссылка",
    "date": "дата",
    "time": "время",
}
SHEET_PLAN_EMPTY: Final[str] = "На листе «{sheet}» под названиями колонок нет ни одной строки."
SHEET_PLAN_HEADER_UNKNOWN: Final[str] = (
    "Ни на одном листе таблицы в первой строке нет всех трёх колонок: ссылка, дата, время. Ближе всего лист "
    "«{sheet}» — не хватает: {missing}. Заголовки этого листа: {headers}."
)
SHEET_PLAN_HEADER_NONE: Final[str] = "нет ни одного"

# --- вход в Google (app\google\auth.py): строка в консоли — формат библиотеки, плейсхолдер {url};
# страница в браузере после входа. Ключи AUTH_REASON_TEXT — значения AuthErrorReason, {minutes} — время ожидания.
AUTH_OPEN_LINK: Final[str] = "Если браузер не открылся — откройте ссылку: {url}"
AUTH_BROWSER_DONE: Final[str] = "Вход выполнен. Вернитесь в окно Livecraft."
AUTH_REASON_TEXT: Final[dict[str, str]] = {
    "client_secret_missing": "нет файла client_secret.json рядом с программой",
    "token_unreadable": "файл входа в Google не читается; удалите его и войдите заново",
    "token_unwritable": (
        "файл входа в Google не удаётся записать или удалить — проверьте, что папка программы доступна "
        "для записи и файл не занят другой программой"
    ),
    "flow_failed": "браузер не вернул разрешение",
    "refresh_failed": "не удалось обновить вход (нет связи с Google)",
    "login_required": "нужен вход в Google: входа ещё не было или он отозван",
    "login_timeout": (
        "вход не завершён за {minutes} минут — браузер закрыт или аккаунт не выбран; "
        "при следующем запуске программа снова предложит вход"
    ),
    "scopes_not_granted": (
        "в окне входа Google отмечены не все разрешения, которые просит программа, — без них вход не принимается; "
        "повторите вход и отметьте все разрешения"
    ),
}

# --- чтение таблицы плана (app\sheets\client.py): {label} — ярлык таблицы с отпечатком, не её адрес (§7.4).
# Ключи SHEETS_READ_REASON_TEXT — значения SheetsReadReason; {detail} — подробность без значений.
SHEETS_READ_FAILED: Final[str] = "Таблица плана {label} не прочиталась: {reason}."
SHEETS_READ_FAILED_STATUS: Final[str] = "Таблица плана {label} не прочиталась: {reason} (код ответа {status})."
# Запись языка видео и ссылок на превью в таблицу плана (app\sheets\client.py::SheetsWriteError, §14 решения 27, 29).
SHEETS_WRITE_FAILED: Final[str] = "Таблица плана {label}: язык видео и ссылки на превью не записались: {reason}."
SHEETS_WRITE_FAILED_STATUS: Final[str] = (
    "Таблица плана {label}: язык видео и ссылки на превью не записались: {reason} (код ответа {status})."
)
# Нет интернета — одними словами у таблицы, Google Диска и Google Docs (ключ no_network их причин).
GOOGLE_NO_NETWORK_TEXT: Final[str] = (
    "компьютер не находит серверы Google — нет интернета или связь с перебоями; запустите ещё раз, когда связь "
    "появится"
)
SHEETS_READ_REASON_TEXT: Final[dict[str, str]] = {
    "not_configured": "не задана ссылка на таблицу — «Livecraft — настройка», вкладка «Таблица плана»",
    "auth": "не удалось войти в Google — {detail}",
    "no_access": "нет доступа — откройте таблицу аккаунту Google, под которым вошли",
    "account_refused": (
        "аккаунту {detail} таблица не открыта — войдите аккаунтом, которому она открыта, или попросите владельца "
        "таблицы открыть её этому аккаунту"
    ),
    "not_found": "такой таблицы нет — проверьте ссылку на таблицу в настройках",
    "bad_range": "Google не принял запрос к таблице — проверьте ссылку на таблицу",
    "rejected": "Google отказал в чтении",
    "unavailable": "Google не ответил и после повторов — проверьте связь и запустите ещё раз",
    "no_network": GOOGLE_NO_NETWORK_TEXT,
}

# Вход оператора (app\sheets\operator.py): перед тем как откроется браузер — каким аккаунтом входить (Google
# предлагает последний аккаунт браузера, часто это аккаунт канала); после входа — каким аккаунтом вошли; аккаунту
# входа таблица не открыта — перед повторным входом. {account} — почта аккаунта, как её называет Google Диск.
SHEETS_LOGIN_BROWSER: Final[str] = (
    "Нужен вход в Google для таблицы плана и Google Диска — сейчас откроется браузер. Войдите аккаунтом Google, "
    "которому открыта таблица плана (это не аккаунт канала YouTube), и отметьте все разрешения."
)
OPERATOR_LOGGED_IN: Final[str] = "Вход в Google: {account}"
OPERATOR_ACCESS_REFUSED: Final[str] = (
    "Аккаунту Google {account} таблица плана не открыта — нужен вход аккаунтом, которому она открыта."
)
OPERATOR_ACCOUNT_UNKNOWN: Final[str] = "(почта не определена)"

# --- папка материалов на Google Диске (app\google\drive.py, §14 решение 27): без адресов. Ключи DRIVE_REASON_TEXT —
# значения DriveReason; {detail} — подробность без значений.
DRIVE_FAILED: Final[str] = "Google Диск: {reason}."
DRIVE_FAILED_STATUS: Final[str] = "Google Диск: {reason} (код ответа {status})."
DRIVE_REASON_TEXT: Final[dict[str, str]] = {
    "auth": "не удалось войти в Google — {detail}",
    "no_access": "нет доступа к папке — откройте её аккаунту Google, под которым вошли, с правом редактора",
    "not_found": (
        "такой папки нет или она не видна аккаунту, под которым вошли, — проверьте ссылку на папку в настройках"
    ),
    "bad_request": "Google не принял запрос — проверьте ссылку на папку в настройках",
    "rejected": "Google отказал",
    "unavailable": "Google не ответил и после повторов — проверьте связь и запустите ещё раз",
    "unknown": (
        "Google не ответил, выполнено ли действие, — повтор мог бы его задвоить; незаконченное никуда не уходит, "
        "достаточно запустить ещё раз"
    ),
    "not_configured": "папка материалов не задана — вставьте ссылку на неё выше и нажмите «Сохранить»",
    "no_network": GOOGLE_NO_NETWORK_TEXT,
}

# --- документ объявлений в Google Docs (app\google\docs.py, app\publish\doc_stage.py, §13 задача 4.4): без
# значений сейфа. Ключи DOCS_REASON_TEXT — значения DocsReason; {detail} — подробность без значений.
DOCS_FAILED: Final[str] = "Google Docs: {reason}{status}."
DOCS_FAILED_STATUS: Final[str] = " (код ответа {status})"
DOCS_REASON_TEXT: Final[dict[str, str]] = {
    "auth": "не удалось войти в Google — {detail}",
    "no_access": "нет доступа к документу — нужен вход аккаунтом Google, которому открыта папка материалов",
    "not_found": "документ не найден",
    "bad_request": "Google Docs не принял запрос — подробности в логе",
    "rejected": "Google Docs отказал",
    "unavailable": "Google Docs не ответил и после повторов — проверьте связь и запустите ещё раз",
    "unknown": (
        "Google Docs не ответил, выполнена ли правка, — повтор мог бы задвоить текст; незаконченный документ "
        "никуда не уходит, достаточно запустить ещё раз"
    ),
    "no_network": GOOGLE_NO_NETWORK_TEXT,
}
# Строки консоли части «документ объявлений»: {url} — ссылка на документ, это не секрет.
DOC_LINE: Final[str] = "Документ объявлений на {date}: {url} — превью {placed} из {total}."
DOC_DRY_RUN_LINE: Final[str] = "Документ объявлений: пробный запуск — документ не создаётся."
DOC_FAILED_LINE: Final[str] = "Документ объявлений на {date} не готов — {reason}"
DOC_SKIPPED_LINE: Final[str] = "Документы следующих дат ({count}) не создавались."
# Копия документа в формате Word (app\publish\doc_copy.py, §14 решение 33) — продолжение DOC_LINE: {path} — путь
# относительно корня программы (docs\<DD-MM-YYYY>\…docx), {reason} — отказ Диска или сбой записи файла.
DOC_COPY_SAVED: Final[str] = " Копия .docx: {path}."
DOC_COPY_NOT_SAVED: Final[str] = " Копия .docx не сохранена — {reason}"
DOC_COPY_WRITE_FAILED: Final[str] = "файл не записался: {reason}."

# Строки консоли части «объявления в Telegram» (app\publish\announce_stage.py, §13 задача 4.5): без токена бота и
# текстов слотов; {name} — имя файла пакета.
ANNOUNCE_DAY_LINE: Final[str] = "Объявления на {date} отправлены в Telegram: слотов {slots}, превью {previews}."
ANNOUNCE_PACKAGE_LINE: Final[str] = "Пакет {name} отправлен в Telegram."
ANNOUNCE_FAILED_LINE: Final[str] = "Объявления на {date} отправлены не до конца — {reason}"
ANNOUNCE_PACKAGE_FAILED_LINE: Final[str] = "Пакет не отправлен в Telegram — {reason}"
ANNOUNCE_SKIPPED_LINE: Final[str] = "Объявления следующих дат ({count}) не отправлялись."
ANNOUNCE_DRY_RUN_LINE: Final[str] = "Объявления в Telegram: пробный запуск — ничего не отправляется."

# --- пробник чтения таблицы (app\tools\sheets_probe.py): только счётчики, ни адреса таблицы, ни ссылок рядов
SHEETS_PROBE_TITLE: Final[str] = "Проверка чтения таблицы плана"
SHEETS_PROBE_LOGIN: Final[str] = SHEETS_LOGIN_BROWSER
SHEETS_PROBE_COLUMNS: Final[str] = "Лист «{sheet}». Колонки: ссылка — {link}, дата — {date}, время — {time}."
SHEETS_PROBE_COLUMN: Final[str] = "«{name}» (колонка {letters})"
SHEETS_PROBE_ROWS: Final[str] = "Рядов прочитано: {rows}, допущено: {admitted}, отсеяно: {skipped}."
SHEETS_PROBE_SKIP_LINE: Final[str] = "  {name}: {count}"
SHEETS_PROBE_RELOGIN_HELP: Final[str] = "войти в Google заново в браузере и выбрать другой аккаунт"
SHEETS_PROBE_RELOGIN_HINT: Final[str] = (
    "Вошли не тем аккаунтом? Запустите с --relogin и выберите аккаунт, у которого есть доступ к таблице."
)

# --- источники (app\sources\): данные видео через yt-dlp и обложка. Ключи словарей — значения
# SourceFailureReason и PreviewProblem; ссылки на видео YouTube — не секрет, их можно показывать.
SOURCE_FAILURE_REASONS: Final[dict[str, str]] = {
    "tool_missing": "нет программы yt-dlp.exe в папке tools — без неё данные видео не получить",
    "private": "видео приватное или требует входа: cookies не подошли или их нет",
    "unavailable": "видео недоступно: удалено или заблокировано",
    "timeout": "yt-dlp не ответил вовремя",
    "bad_output": "yt-dlp вернул ответ, который не разбирается",
    "no_title": "у видео нет названия",
    "failed": "yt-dlp не смог получить данные видео — подробности в логе",
    "no_language": "язык видео не определился ни по данным YouTube, ни по названию и описанию",
}
PREVIEW_PROBLEMS: Final[dict[str, str]] = {
    "no_url": "источник не дал адреса превью",
    "not_found": "превью по адресу нет",
    "rejected": "сервер превью отказал в скачивании",
    "unavailable": "превью не скачалось и после повторов",
    "not_image": "скачанный файл — не картинка",
    "too_large": "превью больше 2 МБ и после сжатия",
}

# --- слоты (app\slots\): тексты эфира под правила YouTube
# Ключи словаря — значения SlotProblem.
SLOT_PROBLEMS: Final[dict[str, str]] = {
    "empty_title": "Название эфира пустое после подгонки под правила YouTube — слот дальше не идёт.",
}

# --- пакет plan_*.bcast (app\packages\, §14 решение 13): куда записан или что сделать, чтобы записался.
# Ключи словаря — значения PackageProblem.
PACKAGE_PROBLEMS: Final[dict[str, str]] = {
    "no_slots": "в запуске нет годных слотов — записывать нечего",
    "form_not_configured": (
        "не задана ссылка на форму ключей — задайте ссылку на форму в настройщике, "
        "вкладка «Форма»"
    ),
}
PACKAGE_WRITTEN: Final[str] = "Пакет записан: {path} (слотов: {slots}, превью: {previews})."
PACKAGE_NOT_WRITTEN: Final[str] = "Пакет не записан: {reason}."
# Чтение пакетов bcast\ — режим Б (app\packages\package_file.py, package_shelf.py, package_drop.py).
PACKAGE_REASON_WITH_DETAIL: Final[str] = "{reason} ({detail})"
PACKAGE_LINE_TEMPLATES: Final[dict[str, str]] = {
    "accepted": "{file} — принят, слотов {total}, из них языков каналов {mine}",
    "damaged": "{file} — пакет повреждён: {detail}; файл не тронут",
    "unsupported_schema": "{file} — версия пакета {detail} не поддерживается (нужна {supported}); файл не тронут",
    "all_past": "{file} — все слоты в прошлом, ничего из него не планируется",
}
PACKAGE_REASON_TEXT: Final[dict[str, str]] = {
    "not_zip": "не ZIP-архив",
    "no_manifest": "нет manifest.json",
    "bad_json": "manifest.json не читается",
    "unsupported_schema": "неизвестная версия пакета",
    "missing_key": "в манифесте нет обязательного поля",
    "bad_value": "неверное значение в манифесте",
    "duplicate_slot": "slot_id повторяется",
    "preview_missing": "в архиве нет файла превью",
    "preview_not_image": "файл превью в архиве — не картинка",
}
SHELF_PACKAGE_ACCEPTED: Final[str] = "{file} — принят, будущих слотов {slots}"
# Консоль при входе «Пакеты» без эфиров: пакеты по одному называет отчёт.
SHELF_SUMMARY: Final[str] = "Пакеты в {path}: файлов {packages}, будущих слотов {slots} (список — в отчёте)."
BCAST_EMPTY: Final[str] = "В {path} нет пакетов *.bcast — сохраните туда пакет от оператора и запустите снова."
BCAST_NO_FUTURE_SLOTS: Final[str] = (
    "В пакетах {path} нет будущих слотов — сохраните туда свежий пакет от оператора и "
    "запустите снова."
)
PACKAGE_DROP_COPIED: Final[str] = "Пакет скопирован: {path}."
PACKAGE_DROP_IN_PLACE: Final[str] = "Пакет уже на месте: {path}."
# Настройки не прочитаны — папка пакетов неизвестна (§14 решение 37); о настройках скажут строки ниже.
PACKAGE_DROP_NO_SETTINGS: Final[str] = (
    "Пакет {file} не скопирован: настройки программы не прочитаны — папка пакетов неизвестна."
)
PACKAGE_DROP_PROBLEMS: Final[dict[str, str]] = {
    "not_package": "Файл {path} — не пакет .bcast: открыть можно только пакет *.bcast.",
    "missing": "Файла {path} нет — пакет не открыт.",
}

# --- форма ключей (app\form\, §6 инвариант 2): {form} — заголовок формы, а пока форма не прочиталась — её ссылка
# (открытая настройка). Ключи FORM_PROBLEMS — значения FormProblem; {detail} — FORM_PROBLEM_DETAIL или пусто.
FORM_PROBLEMS: Final[dict[str, str]] = {
    "structure_unreadable": "Форма ключей «{form}» не прочиталась: на странице не нашлось вопросов формы{detail}.",
    "missing_option": (
        "В форме ключей «{form}» нет нужного варианта ответа{detail} — попросите владельца формы добавить его."
    ),
    "required_missing": "В форме ключей «{form}» остались обязательные вопросы без ответа{detail}.",
    "transport_failed": "Форма ключей «{form}» недоступна{detail}.",
    "not_confirmed": "Форма ключей «{form}» не подтвердила запись ответа{detail}.",
}
FORM_PROBLEM_DETAIL: Final[str] = " ({detail})"
FORM_STATUS_DETAIL: Final[str] = "код ответа {status}"
# Проверка дат формы до входов (app\form\coverage.py, §3 шаг 7): даты — 17.03.2027.
FORM_DATES_OK: Final[str] = (
    "Форма ключей «{form}»: все даты запуска в ней есть — нужно {wanted}, форма принимает {accepted}."
)
FORM_DATES_ANY: Final[str] = "Форма ключей «{form}»: дата вводится текстом — подходит любая."
FORM_DATES_MISSING: Final[str] = (
    "Форма ключей «{form}»: нет дат {dates} — эфиры на эти даты не создаются, ключи стримеру не уйдут."
)

# --- память программы (app\records\, §6 инварианты 0, 1a, 10): {path} — файл памяти, {renamed} — имя переименованного
# файла, {error} — причина сбоя базы. Значений сейфа и ключей потока нет.
RECORDS_BROKEN: Final[str] = (
    "Память программы {path} не читалась — файл переименован в {renamed}, создана новая; "
    "эфиры с меткой программы записаны как уже переданные стримеру."
)
RECORDS_BROKEN_READ_ONLY: Final[str] = (
    "Память программы {path} не читается — в этом режиме программа работает без неё; обычный запуск создаст новую."
)
RECORDS_WRITE_FAILED: Final[str] = (
    "Память программы {path} не записывается ({error}) — работа продолжается, но подтверждения этого запуска "
    "следующий запуск не увидит и может отправить ключи повторно."
)

# --- площадка YouTube (app\platforms\, §6 инварианты 1, 9): причина отказа по коду — errors[0].reason Google
# или свой код программы (PlatformCode). Ключа потока и значений сейфа нет. Неизвестный код — YOUTUBE_REASON_UNKNOWN.
_YOUTUBE_RATE_LIMIT_TEXT: Final[str] = (
    "YouTube отклонил слишком частые запросы, повторы не помогли — запустите программу позже "
    "или увеличьте паузу между обращениями к YouTube на вкладке «Эфиры YouTube» настройщика"
)
_YOUTUBE_ACCESS_TEXT: Final[str] = (
    "доступ к каналу отозван или недостаточен — войдите в канал заново: .\\livecraft.bat --auth \"@ник канала\""
)
_YOUTUBE_CLOSED_TEXT: Final[str] = "канал или аккаунт закрыт на YouTube"
_YOUTUBE_SUSPENDED_TEXT: Final[str] = "канал или аккаунт заблокирован YouTube"
YOUTUBE_REASON_TEXT: Final[dict[str, str]] = {
    "quotaExceeded": (
        "исчерпана суточная квота YouTube API (одна на проект Google — на все каналы); остальные обращения к YouTube "
        "в этом запуске не делались; квота обновляется около 10:00 по Киеву — запустите программу после этого"
    ),
    "rateLimitExceeded": _YOUTUBE_RATE_LIMIT_TEXT,
    "userRateLimitExceeded": _YOUTUBE_RATE_LIMIT_TEXT,
    "userRequestsExceedRateLimit": _YOUTUBE_RATE_LIMIT_TEXT,
    "liveStreamingNotEnabled": (
        "на канале не включены прямые трансляции — включите их в Студии (YouTube включает до 24 часов)"
    ),
    "livePermissionBlocked": "YouTube запретил трансляции на канале — причина указана в Студии",
    "insufficientLivePermissions": "аккаунт не может создавать трансляции на этом канале",
    "userBroadcastsExceedLimit": (
        "на канале слишком много запланированных эфиров, YouTube не даёт создать новые — удалите лишние в Студии"
    ),
    "authError": _YOUTUBE_ACCESS_TEXT,
    "insufficientPermissions": _YOUTUBE_ACCESS_TEXT,
    "channelClosed": _YOUTUBE_CLOSED_TEXT,
    "authenticatedUserAccountClosed": _YOUTUBE_CLOSED_TEXT,
    "channelSuspended": _YOUTUBE_SUSPENDED_TEXT,
    "authenticatedUserAccountSuspended": _YOUTUBE_SUSPENDED_TEXT,
    "authenticatedUserNotChannel": "у аккаунта нет канала YouTube — при входе выберите канал",
    "channelNotFound": "у аккаунта нет канала YouTube — при входе выберите канал",
    "videoNotFound": "эфир не найден на YouTube — возможно, удалён во время запуска",
    "notListed": (
        "YouTube не отдал эфир или поток по его id и после повторов — после записи площадка иногда отстаёт; "
        "следующий запуск прочитает его снова"
    ),
    "invalidScheduledStartTime": "YouTube не принял время старта эфира",
    "transportFailed": (
        "YouTube недоступен (сеть или сбой на стороне YouTube), повторы не помогли — запустите программу позже"
    ),
    "authFailed": "вход в канал не удался — войдите в канал заново: .\\livecraft.bat --auth \"@ник канала\"",
    "loginRequired": "нужен вход в канал в браузере — войдите в канал: .\\livecraft.bat --auth \"@ник канала\"",
    "badResponse": "YouTube прислал ответ, который программа не разобрала; следующий запуск спросит снова",
    "unexpectedStreamKeyFormat": (
        "YouTube выдал ключ потока непривычного вида — эфир не засчитан, ключ стримеру не ушёл; "
        "следующий запуск создаст поток заново"
    ),
    "unknown": "YouTube отказал, не назвав причины; следующий запуск спросит снова",
}
YOUTUBE_REASON_UNKNOWN: Final[str] = "YouTube отказал ({code}); следующий запуск спросит снова"
# Описание ключа потока в Студии (app\platforms\youtube_description.py): дата — 17.03.2027; хвост — метка заглушки.
STREAM_DESCRIPTION: Final[str] = (
    "Ключ Livecraft: канал «{account_name}» {handle}, эфир {date} {time}, язык {language}; "
    "записано программой {written_at}"
)
STREAM_DESCRIPTION_PLACEHOLDER: Final[str] = "; заглушка обложки {token}"

# --- каналы YouTube (app\platforms\channel*.py, verified.py): вход в канал, проверка ник → id → название,
# выравнивание по id YouTube и паспорт каналов (§6 инвариант 5, §14 решение 25).
AUTH_STARTING: Final[str] = (
    "Канал «{account_name}» {handle}: нужен вход в Google — {reason}. Сейчас откроется браузер."
)
# Почему каналу нужен вход — по значениям LoginNeed (app\platforms\channel.py).
AUTH_LOGIN_NEEDS: Final[dict[str, str]] = {
    "no_token": "токена канала ещё нет — первый вход",
    "token_revoked": "Google больше не принимает токен канала",
    "foreign_token": "прежний токен вёл на другой канал и удалён",
    "forced": "вход заново по --auth",
}
AUTH_CHOOSE_ACCOUNT: Final[str] = (
    "Войдите в аккаунт Google {google_account} — это аккаунт канала «{account_name}» {handle}."
)
AUTH_CHOOSE_RIGHT_CHANNEL: Final[str] = (
    "Если в этом аккаунте несколько каналов, выберите канал с ником {handle} («{account_name}»)."
)
AUTH_UNVERIFIED_APP_WARNING: Final[str] = (
    "Google покажет предупреждение «Google hasn't verified this app» — это ожидаемо: приложение ещё не проходило "
    "проверку Google. Нажмите Advanced, затем ссылку Go to ... (unsafe), затем Continue. На экране согласия отметьте "
    "пункт про управление аккаунтом YouTube и подтвердите."
)
AUTH_OK: Final[str] = (
    "Канал «{account_name}» {handle}: вход выполнен — «{title}» {youtube_handle} (id {youtube_channel_id})."
)
AUTH_WRONG_CHANNEL_RETRY: Final[str] = (
    "Канал «{account_name}» {handle}: в браузере выбран канал «{youtube_title}» {youtube_handle} — "
    "нужен «{account_name}» {handle}; вход ещё раз."
)
AUTH_WRONG_CHANNEL_GIVE_UP: Final[str] = (
    "Канал «{account_name}» {handle}: в браузере снова выбран канал «{youtube_title}» {youtube_handle} — "
    "нужен «{account_name}» {handle}; попытки входа кончились, в этом запуске канал пропущен."
)
AUTH_NEXT_RUN_HINT: Final[str] = (
    "при следующем запуске программа снова предложит вход; если ник канала сменился на YouTube — "
    "впишите новый ник на вкладке «Эфиры YouTube» настройщика"
)
# Отказы проверки канала: значение из списка каналов и то, что прислал YouTube.
AUTH_CHANNEL_HANDLE_MISSING: Final[str] = (
    "канал «{account_name}» {handle}: у канала YouTube «{youtube_title}» (id {youtube_channel_id}) нет ника; "
    "канал пропущен. Заведите каналу ник в Студии YouTube и впишите его на вкладке «Эфиры YouTube» настройщика; "
    "если выбран не тот канал — " + AUTH_NEXT_RUN_HINT
)
AUTH_CHANNEL_HANDLE_MISMATCH: Final[str] = (
    "канал «{account_name}» {handle}: вход выполнен в канал YouTube «{youtube_title}» {youtube_handle} "
    "(id {youtube_channel_id}), а в списке каналов записан ник {handle}, и паспорт каналов не подтверждает, "
    "что это тот же канал; канал пропущен; " + AUTH_NEXT_RUN_HINT
)
AUTH_CHANNEL_ID_MISMATCH: Final[str] = (
    "канал «{account_name}» {handle}: в паспорте каналов у ника {handle} id {passport_channel_id}, "
    "а YouTube прислал канал «{youtube_title}» {youtube_handle} с id {youtube_channel_id}; канал пропущен; "
    + AUTH_NEXT_RUN_HINT
)
AUTH_YOUTUBE_HANDLE_MISSING: Final[str] = "без ника"
AUTH_FAILED: Final[str] = "Канал «{account_name}» {handle}: вход не удался — {reason}."
AUTH_SCOPE_HINT: Final[str] = (
    "Если на экране согласия не было пункта про управление аккаунтом YouTube — в настройках доступа приложения "
    "в Google Cloud не добавлено разрешение youtube."
)
WARNING_CHANNEL_ALIGNED: Final[str] = (
    "канал выровнен по YouTube (id {youtube_channel_id}): «{title_before}» {handle_before} -> "
    "«{title_after}» {handle_after}; список каналов, файл входа и паспорт каналов обновлены, входить заново не нужно; "
    "прежний список каналов — secrets\\channels.previous.json"
)
WARNING_TOKEN_RENAME_SKIPPED: Final[str] = (
    "канал «{account_name}» {handle}: YouTube подтвердил канал (id {youtube_channel_id}) с ником {handle_after}, "
    "но файл {target} уже есть — файлы не тронуты; если канала с ником {handle_after} нет в списке каналов, "
    "удалите этот файл — следующий запуск выровняет канал сам"
)
WARNING_CHANNEL_ALIGN_FAILED: Final[str] = (
    "канал «{account_name}» {handle}: YouTube подтвердил канал (id {youtube_channel_id}), "
    "но выровнять файлы не удалось — {reason}; файлы не тронуты, следующий запуск попробует снова"
)
CHANNEL_ALIGN_TITLE_EMPTY: Final[str] = "YouTube прислал пустое название канала"
WARNING_TOKEN_REJECTED: Final[str] = (
    "вход канала «{account_name}» {handle} вёл на канал «{youtube_title}» {youtube_handle} "
    "(id {youtube_channel_id}) — файл входа удалён, программа предложит вход в «{account_name}» {handle}"
)
WARNING_TOKEN_SAVE_FAILED: Final[str] = (
    "канал «{account_name}» {handle}: вход выполнен, но файл входа не записан ({error}) — "
    "в этом запуске канал работает, при следующем запуске программа снова предложит вход"
)
WARNING_PASSPORT_UNREADABLE: Final[str] = (
    "паспорт каналов {path} не читается — он будет записан заново; "
    "канал с новым ником до его первой проверки по старому паспорту не узнаётся"
)
WARNING_PASSPORT_WRITE_FAILED: Final[str] = (
    "паспорт каналов {path} не записан ({error}); работа продолжается, паспорт запишет следующий запуск"
)

# --- план и сверка эфиров (app\pipeline\): причина недопуска по статусу канала и чтение каналов на площадке.
# Ключи ADMISSION_CHANNEL_TEXT — значения ChannelStatus, кроме ready; полный текст отказа канала — в объекте канала.
ADMISSION_CHANNEL_TEXT: Final[dict[str, str]] = {
    "refused": "не тот канал",
    "failed": "площадка не ответила",
    "needs_login": "вход не выполнен",
}
# Перед сверкой каналов при старте (app\platforms\channel_book.py): она идёт по сети и без браузера.
PROGRESS_CHANNELS_CHECK: Final[str] = "Проверка каналов YouTube по сохранённым входам: {count}."
# Перед вопросом YouTube о каждом канале с файлом входа (app\platforms\channel_sync.py::StartCheck).
PROGRESS_CHANNEL_CHECK_STARTED: Final[str] = "Канал «{account_name}» {handle}: проверка по сохранённому входу."
PROGRESS_CHANNEL_READ_STARTED: Final[str] = "Канал «{account_name}» {handle}: запрос запланированных эфиров."
PROGRESS_CHANNEL_READ_DONE: Final[str] = "Канал «{account_name}» {handle}: запланированных эфиров — {count}."
PROGRESS_BROADCAST_CREATE: Final[str] = "Канал «{account_name}» {handle}: создание эфира {date} {time} {language}."
PROGRESS_BROADCAST_FIX: Final[str] = "Канал «{account_name}» {handle}: исправление эфира {date} {time} {language}."
PROGRESS_KEY_SEND: Final[str] = (
    "Канал «{account_name}» {handle}: отправка ключа в форму — эфир {date} {time} {language}."
)
PROGRESS_REPORT: Final[str] = "Запись отчёта."
PROGRESS_PACKAGES_READ: Final[str] = (
    "Пакетов прочитано: {packages}; слотов — {slots_total}, из них языков каналов — "
    "{slots_mine}."
)
# Строки хода таблицы и вывода (app\run\progress.py): перед каждым долгим шагом — что делается и какой он по счёту.
PROGRESS_SHEETS_RETRY: Final[str] = "Google не ответил — повтор {place} из {total}."
PROGRESS_VIDEO: Final[str] = "Чтение видео {place} из {total}: {link}"
PROGRESS_DRIVE_PREVIEW: Final[str] = "Копия превью на Google Диск: {place} из {total}."
PROGRESS_MERGE_SLOT: Final[str] = "Нейросеть: слот {place} из {total} — {date} {time} {language}."
PROGRESS_DOC: Final[str] = "Создание документа объявлений {place} из {total}: {date}."
PROGRESS_ANNOUNCE: Final[str] = "Отправка объявлений в Telegram {place} из {total}: {date}."
PROGRESS_ANNOUNCE_PACKAGE: Final[str] = "Отправка пакета в Telegram: {name}."
# Часть «эфиры» (app\broadcasts\): расход YouTube за часть, эфиры старше памяти, нет слотов для YouTube.
YOUTUBE_USAGE_LINE: Final[str] = "YouTube: обращений {calls}, квота ≈ {units} ед."
BROADCASTS_NO_SLOTS: Final[str] = "Эфиры: слотов для YouTube нет — к YouTube программа не обращалась."
# Ключ, который форма не подтвердила ни в первый раз, ни повтором (§14 решение 49): что сделать человеку.
KEYS_SEND_ALL_ACTION: Final[str] = (
    "передать: «все» (выбор «новые | все» в строке «Ключи в форму» на «Главной» окна настройки)"
)
KEYS_GIVEN_UP: Final[str] = (
    "{prefix}: ключ дважды не дошёл до формы и сам больше не уйдёт — " + KEYS_SEND_ALL_ACTION
)
# Повторная передача ключей после полного запуска (app\broadcasts\key_resend.py, §14 решение 36).
KEYS_RESEND_SWITCHED_OFF: Final[str] = "Ключи эфиров переданы повторно: {sent}. Повторная передача выключена."
KEYS_RESEND_KEPT: Final[str] = (
    "Ключи эфиров переданы повторно: {sent}, не дошло {undelivered} — повторная передача остаётся включённой."
)
KEYS_RESEND_WRITE_FAILED: Final[str] = (
    "Ключи эфиров переданы повторно: {sent}, но повторная передача не выключена — файл настроек не записался: "
    "{reason}. Верните выбор ключей на «новые» — строка «Ключи в форму» на «Главной»: .\\livecraft.bat --setup."
)
# --check и --auth (app\broadcasts\service.py; поведение planers main.py).
CHECK_HEADER: Final[str] = "Проверка каналов по {path}:"
CHECK_CHANNEL_OK: Final[str] = (
    "- «{account_name}» {handle}: «{title}» {youtube_handle} (id {youtube_channel_id}), "
    "язык канала на YouTube: {channel_language}; "
    "языки стримов из channels.json: {languages}; запланированных эфиров: {upcoming}"
)
CHECK_CHANNEL_LANGUAGE_UNSET: Final[str] = "не указан"
CHECK_CHANNEL_LANGUAGE_NOTE: Final[str] = (
    "Язык канала на YouTube — справочный, на решения программы он не влияет: "
    "язык стрима задаёт оператор в channels.json."
)
CHECK_CHANNEL_FAILED: Final[str] = "- «{account_name}» {handle}: {reason}"
CHECK_CHANNEL_REFUSED: Final[str] = "- {message}"
CHANNEL_LISTED: Final[str] = "{handle} «{account_name}»"
CHECK_ALL_OK: Final[str] = "Все каналы на месте, трансляции включены."
CHECK_HAS_PROBLEMS: Final[str] = "Часть каналов не прошла проверку — см. строки выше."
AUTH_UNKNOWN_CHANNEL: Final[str] = "В {path} нет канала с ником {handle}. Каналы в файле: {known}."
# Причина недопуска словами человека (`AdmissionReason.wording`): чего не хватает и что сделать — по предложению;
# один текст для отчёта, консоли и keys.txt. Ключи словарей канала — значения ChannelStatus, кроме ready; полный
# текст отказа или сбоя канала — строкой ошибки канала, один раз на канал.
ADMISSION_CHANNEL_PROBLEM: Final[dict[str, str]] = {
    "refused": "Канал не подтверждён: при входе выбран другой канал (подробности — в строке ошибки канала).",
    "failed": "Канал не проверен: YouTube не ответил (подробности — в строке ошибки канала).",
    "needs_login": "Вход в канал не выполнен.",
}
ADMISSION_CHANNEL_ACTION: Final[dict[str, str]] = {
    "refused": "При входе выберите в браузере нужный канал.",
    "failed": "Если сбой повторяется — перешлите отчёт оператору.",
    "needs_login": "Войдите в канал, когда программа откроет браузер.",
}
ADMISSION_MISSING_OPTION: Final[str] = "В форме «{form}» в вопросе «{question}» нет варианта «{value}»."
ADMISSION_ACTION_MISSING_OPTION: Final[str] = "Добавьте вариант в форму."
# Настройки формы (раздел form файла livecraft.json) не дали текста варианта: форме тут не поможешь.
ADMISSION_MISSING_SETTINGS_TEXT: Final[str] = (
    "В настройках формы нет текста ответа на вопрос «{question}» формы «{form}»."
)
ADMISSION_ACTION_MISSING_SETTINGS_TEXT: Final[str] = (
    "Оператору — вписать текст варианта в раздел form файла secrets\\livecraft.json; эфиры из пакета получат его "
    "со следующим пакетом."
)
ADMISSION_REQUIRED_MISSING: Final[str] = (
    "В форме «{form}» обязательный вопрос «{question}», на который у программы нет ответа."
)
ADMISSION_ACTION_REQUIRED_MISSING: Final[str] = "Сделайте этот вопрос в форме необязательным или сообщите оператору."
ADMISSION_ACTION_FORM_UNREADABLE: Final[str] = "Проверьте, что форма ключей открывается по своей ссылке."

# --- вывод контура B (app\output\, §3 шаг 12): отчёт logs\{дата}_{время}_report.md, итог в консоли, keys.txt.
# Дата для людей — 17.03.2027, время — по поясу программы (§6 инвариант 4, §14 решение 31); ключ потока в отчёте и
# консоли — только маской, полностью — только в keys.txt (§6 инвариант 6).
# Канал для людей — название и ник рядом (ChannelConfig.label).
CHANNEL_LABEL: Final[str] = "{account_name} {handle}"
# Пропущенные слоты (раздел «Пропущено»).
SKIP_PAST: Final[str] = "{date} {time} {language} — уже прошло"
SKIP_TOO_LATE: Final[str] = "{date} {time} {language} — до старта меньше {minutes} минут"
SKIP_NO_CHANNEL: Final[str] = "{date} {time} {language} — нет канала для языка {language}"
# Итог эфира (BroadcastResult) — одинаково в отчёте и консоли.
OUTCOME_SLOT_PREFIX: Final[str] = "{date} {time} {language} -> {channel}"
OUTCOME_CREATED: Final[str] = "{prefix} — эфир создан, {form}"
OUTCOME_CREATE_PLANNED: Final[str] = "{prefix} — эфира нет, будет создан"
OUTCOME_FIXED: Final[str] = "{prefix} — на YouTube отличалось: {what}; исправлено, ключ и ссылка прежние{form}"
OUTCOME_FIXED_FORM: Final[str] = ", {mark}"
OUTCOME_FIX_PLANNED: Final[str] = "{prefix} — на YouTube отличается: {what}; будет исправлено, ключ уйдёт в форму"
OUTCOME_MATCHED: Final[str] = "{prefix} — {url}"
OUTCOME_MATCHED_FORM: Final[str] = "; {mark}"
# Поле надо было исправить, а не удалось (FieldFixes.unfixed); причина — в предупреждении.
UNFIXED_FIELD_TEXT: Final[dict[str, str]] = {"thumbnail": "обложка эфира не поставлена"}
OUTCOME_UNFIXED: Final[str] = "; {what}"
OUTCOME_NO_STREAM: Final[str] = (
    "{prefix} — эфир на канале есть ({url}), но к нему не привязан поток: ключ взять неоткуда. "
    "Привяжите поток в YouTube Studio или удалите эфир — программа создаст его заново"
)
OUTCOME_STREAM_ATTACHED: Final[str] = "{prefix} — эфир был без потока, поток привязан, {form}"
OUTCOME_AMBIGUOUS: Final[str] = (
    "{prefix} — на канале несколько эфиров на эту минуту без маркера программы, не могу различить — "
    "разберитесь вручную"
)
# Ошибка эфира: текст для человека — у самой ошибки (OutcomeError.human).
OUTCOME_ERROR: Final[str] = "{prefix} — {text}"
OUTCOME_DRY_RUN_SUFFIX: Final[str] = " — не выполнено (dry-run)"
# Сбой без слота (RunFailure): канал или файл программы — и что случилось.
RUN_FAILURE_LINE: Final[str] = "{subject} — {text}"
KEYS_WRITE_FAILED: Final[str] = "файл ключей не записан: {detail}"
# Предупреждения эфиров: шаг, который не удался, а эфир и ключ в силе. Ключи WARNING_STEP_TEXT — значения WarningStep.
WARNING_LINE: Final[str] = "{prefix}: {step} — {code} ({message})"
WARNING_REASON_LINE: Final[str] = "{prefix}: {step} — {reason}"   # причина отказа известна: текст вместо кода
WARNING_STEP_TEXT: Final[dict[str, str]] = {
    "thumbnail": "обложка эфира не поставлена; эфир и ключ в силе",
    "language": "язык эфира не записан; эфир и ключ в силе",
    "audience": "аудитория эфира была «для детей» (настройка канала) — программа сняла её; проверьте настройки канала",
    "settings": "не удалось применить настройки эфира (язык, категория, аудитория); эфир и ключ в силе",
    "age_restricted": "на эфире стоит возрастное ограничение 18+; через API оно не снимается — снимите вручную в Студии",
    "facts": "не удалось перечитать эфир после планирования; на сам эфир это не влияет",
}
# Причины отказа обложки главнее общих YOUTUBE_REASON_TEXT; причины нет в обоих — код и сообщение Google.
THUMBNAIL_REASON_TEXT: Final[dict[str, str]] = {
    "uploadRateLimitExceeded": (
        "YouTube временно ограничил загрузку обложек эфиров на этом канале и срок не сообщает; остальные обложки "
        "эфиров канала в этом запуске не ставились — следующий запуск доставит их сам, запустите через несколько часов"
    ),
    "forbidden": (
        "YouTube не разрешает этому каналу свои обложки эфиров — подтвердите канал по телефону в Студии "
        "(расширенные функции)"
    ),
    "invalidImage": "YouTube не принял картинку превью из плана",
}
WARNING_REPORTED_FIELD: Final[str] = (
    "не можем исправить: {prefix} — {field}: нужно {wanted}, на площадке {actual}; через API это не исправляется "
    "(нужен monitorStream) — поправьте в Студии; эфир и ключ в силе"
)
WARNING_AMBIGUOUS: Final[str] = (
    "не можем выбрать эфир: {prefix} — на канале несколько эфиров без метки программы на эту минуту; "
    "программа не выбирает и не удаляет — оставьте один: {urls}"
)
# Страница формы, сохранённая в logs\ при отказе чтения или отправки (FormFailure.diagnostic).
WARNING_FORM_DIAGNOSTIC: Final[str] = "ответ формы сохранён для разбора: {path}"
# Поведение программы: пояснение под заголовком «Уже запланировано, совпадает» (PlannedBroadcast.has_kept_key).
WARNING_KEPT_KEY: Final[str] = (
    "ключ совпавшего эфира форма уже подтверждала раньше (память программы) — повторно он не отправляется. "
    "Если стример ключа не получил — передайте его из keys.txt вручную или удалите эфир на YouTube: "
    "программа создаст его заново с новым ключом и отправит"
)
# Особенности площадки — только в отчёте, разделом «Особенности площадки»: так устроена площадка, это не про запуск.
WARNING_LIVE_CHAT: Final[str] = (
    "у эфиров YouTube всегда включён живой чат. Через API он не отключается: если чат не нужен, "
    "выключите его один раз в Студии на весь канал (Settings -> Community)"
)
NOTE_UNDATED_BROADCAST: Final[str] = (
    "на канале {channel} есть служебный эфир площадки без даты и времени — «{title}». YouTube заводит такой эфир "
    "сам при заходе в панель трансляций канала; программа его со слотами не сверяет и не трогает, в списке "
    "трансляций Студии он не виден"
)
# Расхождения с площадкой после действий: что хотели и что лежит на платформе.
MISMATCH_LINE: Final[str] = "{prefix}: {field} — хотели: {wanted}; на платформе: {actual}"
# Поля спеки называются по CHANGED_FIELD_TEXT; здесь — только то, чего в спеке нет.
MISMATCH_FIELD_START: Final[str] = "время старта"
MISMATCH_FIELD_LANGUAGE: Final[str] = "язык"
MISMATCH_FIELD_AUDIENCE: Final[str] = "аудитория"
MISMATCH_DESCRIPTION: Final[str] = "{length} символов, начало «{head}»"
AUDIENCE_NOT_FOR_KIDS: Final[str] = "не для детей"
AUDIENCE_FOR_KIDS: Final[str] = "для детей"
SPEC_VALUE_TRUE: Final[str] = "да"
SPEC_VALUE_FALSE: Final[str] = "нет"
# Обложка в «было / стало»: отпечатки картинок человеку ничего не говорят.
THUMBNAIL_BEFORE: Final[str] = "заглушка канала"
THUMBNAIL_AFTER: Final[str] = "из плана"
# Ключи — значения ChangedField.
CHANGED_FIELD_TEXT: Final[dict[str, str]] = {
    "title": "название",
    "description": "описание",
    "category": "категория",
    "privacy": "видимость",
    "marker": "маркер потока",
    "thumbnail": "обложка эфира",
    "auto_start": "автостарт",
    "auto_stop": "автостоп",
    "latency": "задержка трансляции",
}
# Эфиры с меткой программы без своего слота; {actual} — где эфир стоит на площадке.
ORPHAN_LINE: Final[str] = "{date} {time} {language} -> {channel} — {url} — эфир не удалён"
ORPHAN_MOVED_LINE: Final[str] = (
    "{date} {time} {language} -> {channel} — {url} — стоит на {actual}: время эфира менял владелец, "
    "программа его не трогает"
)
# Отчёт logs\{дата}_{время}_report.md: сначала итог и то, ради чего его открывают, потом справка.
REPORT_TITLE: Final[str] = "# Livecraft {version} — отчёт {generated_at}"
REPORT_TITLE_DRY_RUN: Final[str] = " (dry-run)"
REPORT_ITEM: Final[str] = "- {text}"
REPORT_SECTION_CREATED: Final[str] = "### Создано ({count})"
REPORT_SECTION_FIXED: Final[str] = "### Исправлено ({count})"
REPORT_SECTION_MATCHED: Final[str] = "### Уже запланировано, совпадает ({count})"
REPORT_SECTION_ORPHANS: Final[str] = "### Перенесён или отменён? ({count})"
REPORT_SECTION_SCHEDULED: Final[str] = "### Запланировано на каналах ({count})"
REPORT_SECTION_SKIPPED: Final[str] = "### Пропущено"
REPORT_SECTION_PACKAGES: Final[str] = "### Пакеты"
REPORT_SECTION_WARNINGS: Final[str] = "### Предупреждения"
REPORT_SECTION_MISMATCHES: Final[str] = "### Расхождения с платформой"
REPORT_SECTION_ERRORS: Final[str] = "### Ошибки"
REPORT_SECTION_NOT_DELIVERED: Final[str] = "### Ключ не дошёл до стримера"
REPORT_SECTION_TWO_KEYS: Final[str] = "### В форме два ключа на один слот ({count})"
REPORT_SECTION_NOT_ADMITTED: Final[str] = "### Не допущено к публикации ({count})"
REPORT_SECTION_NOTES: Final[str] = "### Особенности площадки — так устроена площадка, это не про этот запуск"
REPORT_TOTAL_KEYS_FILE: Final[str] = "Файл ключей: {path}"
# Части отчёта запуска: «## <часть>», под ней строки части и её разделы уровнем «###».
REPORT_PART: Final[str] = "## {title}"
REPORT_PART_RUN: Final[str] = "Запуск"
REPORT_PART_INTAKE: Final[str] = "Таблица плана и тексты"
REPORT_PART_SHELF: Final[str] = "Пакеты"
REPORT_PART_PREVIEWS: Final[str] = "Превью"
REPORT_SECTION_SKIPPED_ROWS: Final[str] = "### Отсеянные строки таблицы ({count})"
REPORT_SECTION_VIDEOS: Final[str] = "### Видео ({count})"
REPORT_SECTION_SLOTS: Final[str] = "### Слоты ({count})"
# Строка таблицы плана: {text} — причина отсева, причина отказа видео или язык и превью годного видео.
REPORT_ROW_LINE: Final[str] = "строка {row}: {link} — {text}"
REPORT_VIDEO_READY: Final[str] = "язык {language}, {preview}"
REPORT_VIDEO_PREVIEW: Final[str] = "превью есть"
REPORT_VIDEO_NO_PREVIEW: Final[str] = "превью нет"
REPORT_SLOT: Final[str] = "{date} {time} {language} — видео: {videos}, тексты: {origin} — «{title}»"
REPORT_SLOT_REFUSED: Final[str] = "{date} {time} {language} — видео: {videos} — {problem}"
# Откуда тексты слота; ключи — значения SlotTextOrigin (app\slots\texts.py).
REPORT_TEXT_ORIGINS: Final[dict[str, str]] = {
    "source_single": "тексты видео",
    "source_composed": "тексты видео",
    "merged": "от нейросети",
    "numbered": "по номерам — на YouTube не идёт",
    "package": "из пакета",
}
TWO_KEYS_LINE: Final[str] = (
    "{prefix} — прежний эфир {old_url} на времени слота не найден (удалён или перенесён), поставлен новый "
    "{new_url}. Действующий ключ {new_key}; прежний {old_key} тоже передан в форму на эту дату — "
    "для этого слота он больше не действует"
)
# Ключ не дошёл до стримера: {reason} — отказ формы, предложением.
NOT_DELIVERED_LINE: Final[str] = (
    "{prefix} — {reason} Эфир на канале стоит — передайте ключ стримеру из keys.txt вручную"
)
# Не допущено к публикации — одинаково в отчёте и консоли: чего не хватает, что из-за этого не сделано, что сделать
# и что программа сделает сама. {problems} и {actions} — предложения AdmissionWording.
NOT_ADMITTED_LINE: Final[str] = "{prefix} — {problems} {consequence}. {actions} {next_run}."
NOT_ADMITTED_CONSEQUENCE_NO_BROADCAST: Final[str] = "Эфир не создан, ключ стримеру не передан"
NOT_ADMITTED_CONSEQUENCE_BROADCAST: Final[str] = (
    "Эфир на канале есть ({url}), но не исправлялся, ключ стримеру не передан"
)
NOT_ADMITTED_CONSEQUENCE_CHANNEL: Final[str] = "Эфиры на канале не проверялись, ключ стримеру не передан"
NOT_ADMITTED_NEXT_NO_BROADCAST: Final[str] = "Программа создаст эфир на следующем запуске"
NOT_ADMITTED_NEXT_BROADCAST: Final[str] = "Программа передаст ключ на следующем запуске"
NOT_ADMITTED_NEXT_CHANNEL: Final[str] = "Программа проверит канал на следующем запуске"
# Ключ этого запуска и форма: отправлен, будет отправлен (dry-run), НЕ отправлен — {reason}: отказ формы предложением.
FORM_MARK_SENT: Final[str] = "ключ отправлен в форму"
FORM_MARK_PLANNED: Final[str] = "ключ будет отправлен в форму"
FORM_MARK_FAILED: Final[str] = (
    "ключ в форму НЕ отправлен. {reason} Следующий запуск отправит его снова, "
    "а пока передайте ключ стримеру из keys.txt вручную"
)
# Ключ должен был уйти, а причины отказа формы у эфира нет.
FORM_FAILURE_UNKNOWN: Final[str] = "Форма ключей не подтвердила запись ответа."
# «Итог» — одинаково в консоли и в отчёте; первая строка — эфиры (слот × канал), слагаемые дают число в скобках.
SUMMARY_BROADCASTS: Final[str] = (
    "Итог по эфирам (всего {total}): опубликовано {created}, исправлено {fixed}, уже стояло {matched}, "
    "не допущено {not_admitted}, ошибок {errors}."
)
SUMMARY_BROADCASTS_DRY_RUN: Final[str] = (
    "Итог по эфирам (всего {total}): опубликуем {created}, исправим {fixed}, уже стояло {matched}, "
    "не допущено {not_admitted}, ошибок {errors}."
)
SUMMARY_BROADCASTS_STATUS: Final[str] = "Итог по эфирам (всего {total}): уже стояло {matched}, ошибок {errors}."
# Слоты, которые до эфиров не дошли (раздел «Пропущено»); строка — только если такие есть.
SUMMARY_SLOTS_OUT: Final[str] = "Слоты вне работы: {count} — {reasons}."
# Ключи — значения SkipKind.
SUMMARY_SLOTS_REASON: Final[dict[str, str]] = {
    "past": "время старта уже прошло",
    "too_late": "до старта меньше {minutes} минут",
    "no_channel": "нет канала для языка {language}",
}
SUMMARY_SLOTS_REASON_COUNTED: Final[str] = "{reason} {count}"
# Код выхода и его причины (RunExit) — одни и те же в консоли, отчёте и строке лога; при коде 0 строки нет.
SUMMARY_EXIT_FAILED: Final[str] = "Код выхода {code} — не всё выполнено: {reasons}."
# Ключи — значения ExitReasonKind.
EXIT_REASON_TEXT: Final[dict[str, str]] = {
    "errors": "ошибок по эфирам {count}",
    "failures": "ошибок каналов и файлов программы {count}",
    "key_undelivered": "ключ не дошёл до стримера {count}",
    "packages": "пакетов не прочитано {count}",
}
# Консоль после запуска: блоки сверху вниз, разделитель — название блока посередине строки из CONSOLE_RULE_CHAR.
CONSOLE_RULE_CHAR: Final[str] = "="
CONSOLE_RULE_TITLE: Final[str] = " {title} "
CONSOLE_BLOCK_COUNTED: Final[str] = "{title} ({count})"
CONSOLE_BLOCK_ATTENTION: Final[str] = "ВНИМАНИЕ"
CONSOLE_BLOCK_CREATED: Final[str] = "ОПУБЛИКОВАЛИ"
CONSOLE_BLOCK_CREATED_DRY_RUN: Final[str] = "ОПУБЛИКУЕМ"
CONSOLE_BLOCK_FIXED: Final[str] = "ИСПРАВИЛИ"
CONSOLE_BLOCK_FIXED_DRY_RUN: Final[str] = "ИСПРАВИМ"
CONSOLE_BLOCK_KEYS: Final[str] = "КЛЮЧИ СТРИМЕРУ"
CONSOLE_BLOCK_MATCHED: Final[str] = "УЖЕ СТОЯЛО"
CONSOLE_BLOCK_SKIPPED: Final[str] = "НЕ ПУБЛИКОВАЛИ"
CONSOLE_CHANNEL_GROUP: Final[str] = "  {account_name} {handle} ({google_account})"
CONSOLE_BROADCAST_LINE: Final[str] = "    {date}  {time}  {language}  {title}"
CONSOLE_FIXED_LINE: Final[str] = "    {date}  {time}  {language}  {title} — обновлено: {what}"
CONSOLE_FIX_PLANNED_LINE: Final[str] = "    {date}  {time}  {language}  {title} — будет обновлено: {what}"
CONSOLE_KEY_LINE: Final[str] = "    {date}  {time}  {language}  {key}  {state}"
CONSOLE_SKIP_GROUP_TOO_LATE: Final[str] = "  до старта меньше {minutes} минут"
CONSOLE_SKIP_GROUP_NO_CHANNEL: Final[str] = "  нет канала для языка {language}"
CONSOLE_ATTENTION_ERROR: Final[str] = "  ошибка: {text}"
CONSOLE_ATTENTION_NOT_DELIVERED: Final[str] = "  ключ не дошёл до стримера: {prefix} — {reason}"
CONSOLE_ATTENTION_TWO_KEYS: Final[str] = (
    "  {prefix}: прежний эфир на времени слота не найден — поставлен новый; "
    "в форме на эту дату два ключа: действующий {new_key}, прежний {old_key}"
)
CONSOLE_ATTENTION_NOT_ADMITTED: Final[str] = "  не допущено: {text}"
CONSOLE_ATTENTION_TEXT: Final[str] = "  {text}"
CONSOLE_ATTENTION_PACKAGE: Final[str] = "  пакет: {text}"
# Настройки эфира, которые программа вернула к плану (или вернёт в dry-run): видимость, категория, метка.
CONSOLE_ATTENTION_RESTORED: Final[str] = "  вернули к плану: {prefix} — {field}: было {before}, стало {after}"
CONSOLE_ATTENTION_RESTORED_UNKNOWN: Final[str] = "  вернули к плану: {prefix} — {field}: стало {after}"
CONSOLE_ATTENTION_RESTORE_PLANNED: Final[str] = "  вернём к плану: {prefix} — {field}: сейчас {before}, будет {after}"
CONSOLE_ATTENTION_RESTORE_PLANNED_UNKNOWN: Final[str] = "  вернём к плану: {prefix} — {field}: будет {after}"
CONSOLE_PATH: Final[str] = "  {label:<8}{path}"
CONSOLE_LABEL_KEYS: Final[str] = "ключи"
CONSOLE_LABEL_REPORT: Final[str] = "отчёт"
CONSOLE_LABEL_LOG: Final[str] = "лог"
# Файл ключей keystreams\keys.txt: блок на стрим, ключ — первой строкой блока. Начала строк «форма» — одни и те же
# в шапке файла и в самих строках.
KEY_FORM_SENT_LEAD: Final[str] = "отправлен в форму"
KEY_FORM_CONFIRMED_LEAD: Final[str] = "передан в форму"
KEY_FORM_GIVEN_UP_LEAD: Final[str] = "дважды не дошёл до формы"
KEY_FORM_FAILED_LEAD: Final[str] = "НЕ отправлен"
KEY_FORM_NOT_ADMITTED_LEAD: Final[str] = KEY_FORM_FAILED_LEAD + ": не допущено"
KEY_FORM_UNKNOWN_LEAD: Final[str] = "нет подтверждения в памяти программы"
KEY_FORM_LINE_OFF_LEAD: Final[str] = "не отправлялся"
# Консоль, блок КЛЮЧИ СТРИМЕРУ: те же слова, что в keys.txt; {reason} — отказ формы предложением.
CONSOLE_KEY_FAILED: Final[str] = KEY_FORM_FAILED_LEAD + " — {reason}"
KEYS_FILE_HEADER: Final[tuple[str, ...]] = (
    "# Ключи трансляций. Сгенерировано программой {generated_at}.",
    "# Файл перезаписывается на каждом запуске — не править.",
    "# Строка «форма»:",
    "#   «" + KEY_FORM_SENT_LEAD + "» — форма подтвердила ключ в этом запуске;",
    "#   «" + KEY_FORM_CONFIRMED_LEAD + "» — форма подтвердила этот ключ раньше (память программы);",
    "#   «" + KEY_FORM_FAILED_LEAD + "» — ключ должен был уйти и не ушёл: передайте его стримеру вручную;",
    "#   «" + KEY_FORM_NOT_ADMITTED_LEAD + "» — форма этот эфир не принимает (нет даты или варианта) "
    "или канал не подтверждён: эфир стоит, ключ стримеру не передан — передайте вручную;",
    "#   «" + KEY_FORM_LINE_OFF_LEAD + "» — линия «Ключи в форму» выключена: передайте ключ стримеру вручную;",
    "#   «" + KEY_FORM_GIVEN_UP_LEAD + "» — "
    "ключ уходил в форму дважды — первый раз и повтором — и форма его не подтвердила; сам он больше не уйдёт — " + KEYS_SEND_ALL_ACTION + ";",
    "#   «" + KEY_FORM_UNKNOWN_LEAD + "» — программа не знает, получил ли стример этот ключ.",
)
KEYS_BLOCK_TITLE: Final[str] = "{date} {time}  {language}  {account_name} {handle}"
KEYS_BLOCK_KEY: Final[str] = "  ключ   {value}"
KEYS_BLOCK_STREAM: Final[str] = "  поток  {value}"
KEYS_BLOCK_BROADCAST: Final[str] = "  эфир   {value}"
KEYS_BLOCK_FORM: Final[str] = "  форма  {value}"
KEY_FORM_SENT: Final[str] = KEY_FORM_SENT_LEAD + " {sent_at}"
KEY_FORM_CONFIRMED: Final[str] = KEY_FORM_CONFIRMED_LEAD + " {confirmed_at}"
KEY_FORM_GIVEN_UP: Final[str] = KEY_FORM_GIVEN_UP_LEAD + " — " + KEYS_SEND_ALL_ACTION
KEY_FORM_FAILED: Final[str] = KEY_FORM_FAILED_LEAD + " — {reason} Передайте стримеру вручную."
KEY_FORM_NOT_ADMITTED: Final[str] = KEY_FORM_NOT_ADMITTED_LEAD + " — {reasons}"
KEY_FORM_UNKNOWN: Final[str] = KEY_FORM_UNKNOWN_LEAD
KEY_FORM_LINE_OFF: Final[str] = KEY_FORM_LINE_OFF_LEAD + ": линия «{line}» выключена"

# --- прогон режима А (app\intake\intake.py, §3 шаги 2.3–2.6): по строке на шаг, только счётчики и причины.
# Ни значений сейфа, ни ссылки на форму, ни названий и описаний видео (§7.4).
INTAKE_TABLE_LINE: Final[str] = "Таблица плана: рядов {rows}, допущено {admitted}, отсеяно {skipped}{reasons}."
INTAKE_TABLE_REASONS: Final[str] = " — {items}"
INTAKE_COUNT_ITEM: Final[str] = "{name}: {count}"
INTAKE_NO_FUTURE_ROWS: Final[str] = "Будущих эфиров в таблице нет — слоты и пакет в этом запуске не собираются."
INTAKE_SOURCES_LINE: Final[str] = "Видео: годных {ready} из {total}, без превью {no_preview}{failures}."
INTAKE_SOURCES_FAILURES: Final[str] = "; не годны — {items}"
# Этап «превью» (app\intake\preview_stage.py): копии в папке превью и на Google Диске — по линиям работы.
PREVIEWS_LINE: Final[str] = (
    "Превью: сохранено в папке превью — {saved}; на Google Диске — загружено {uploaded}, уже было {kept}."
)
PREVIEWS_DRY_RUN_LINE: Final[str] = (
    "Превью: сохранено в папке превью — {saved}; на Google Диск в пробном запуске ничего не загружено."
)
PREVIEWS_LOCAL_LINE: Final[str] = "Превью: сохранено в папке превью — {saved}."
PREVIEWS_DRIVE_LINE: Final[str] = "Превью: на Google Диске — загружено {uploaded}, уже было {kept}."
# Шаг «запись в таблицу» (app\intake\table_stage.py, §14 решения 27, 29): язык видео и ссылки на превью в строках видео.
INTAKE_SHEET_WRITE_LINE: Final[str] = (
    "Таблица плана: языков видео записано {languages}, уже стояли {languages_kept}; ссылок на превью записано {links}, "
    "уже стояли {links_kept}."
)
# Превью на Google Диске в запуске не идут: ссылок на превью программа не пишет.
INTAKE_SHEET_WRITE_LANGUAGES_LINE: Final[str] = "Таблица плана: языков видео записано {languages}, уже стояли {languages_kept}."
INTAKE_SHEET_WRITE_DRY_RUN_LINE: Final[str] = "Таблица плана: пробный запуск — ничего не записано."
INTAKE_SLOTS_LINE: Final[str] = "Слоты эфиров: {count}{languages}{refused}."
INTAKE_SLOTS_LANGUAGES: Final[str] = " ({items})"
INTAKE_SLOTS_REFUSED: Final[str] = ", отказано: {count} — причины в логе"
INTAKE_NO_SLOTS: Final[str] = "Годных слотов нет — выводу и эфирам нечего делать."
# Слот не для YouTube (§14 решение 32): {language} — код языка, {time} — HH:MM, {date} — DD.MM.YYYY.
INTAKE_SLOT_NOT_FOR_YOUTUBE: Final[str] = (
    "Эфир {language} {time} {date} на YouTube не пойдёт — нейросеть не объединила описания видео; в документе и "
    "Telegram — описания по номерам."
)
PACKAGE_NO_YOUTUBE_SLOTS: Final[str] = "Слотов для YouTube нет — пакет не записан."
# Стадия нейросети (app\intake\merge_stage.py): модель — строкой LLM_CHOICE_*, затем итог по слотам, расход и
# остановка. Ключи INTAKE_MERGE_VIDEO_REASONS — значения VideoTextReason. Ни названий, ни описаний, ни ключа.
INTAKE_MERGE_LINE: Final[str] = "Нейросеть: слотов {total}, тексты модели {merged}, тексты видео {video}{reasons}."
INTAKE_MERGE_REASONS: Final[str] = " — {items}"
INTAKE_MERGE_VIDEO_REASONS: Final[dict[str, str]] = {
    "few_descriptions": "меньше двух описаний у видео",
    "not_accepted": "ответ модели не принят",
    "publish_blocked": "не прошли проверку перед публикацией",
    "stopped": "нейросеть остановлена",
    "no_model": "модель не выбрана",
}
INTAKE_MERGE_COST: Final[str] = "Расход нейросети: запросов {requests}, ${cost}."
INTAKE_MERGE_COST_UNKNOWN: Final[str] = (
    "Расход нейросети: запросов {requests}, не меньше ${cost} — цена части ответов неизвестна."
)
INTAKE_MERGE_STOPPED: Final[str] = (
    "Нейросеть остановлена до конца запуска — остальные слоты, которым нужно объединение описаний, получат "
    "описания по номерам. {failure}"
)

# --- пробник источников (app\tools\source_probe.py): {…} — данные видео, их можно показывать
SOURCE_PROBE_TITLE: Final[str] = "Проверка источников через yt-dlp"
SOURCE_PROBE_USAGE: Final[str] = "Укажите одну или несколько ссылок: python -m app.tools.source_probe <ссылка> …"
SOURCE_PROBE_SOURCE: Final[str] = "Источник {link}"
SOURCE_PROBE_BAD_LINK: Final[str] = "  в ссылке не найдено видео YouTube: {raw}"
SOURCE_PROBE_ID: Final[str] = "  id: {value}"
SOURCE_PROBE_NAME: Final[str] = "  название: {value}"
SOURCE_PROBE_DURATION: Final[str] = "  длительность: {value}"
SOURCE_PROBE_LANGUAGE: Final[str] = "  язык видео: {video}; язык канала: {channel}"
SOURCE_PROBE_AUDIO: Final[str] = "  языки аудио: {value}"
SOURCE_PROBE_SUBTITLES: Final[str] = "  субтитры: {value}"
SOURCE_PROBE_AUTO_CAPTIONS: Final[str] = "  автосубтитры: {value}"
SOURCE_PROBE_SOURCE_LANGUAGE: Final[str] = "  язык источника: {code} ({source})"
SOURCE_PROBE_SOURCE_LANGUAGE_NONE: Final[str] = "  язык источника: не определился"
SOURCE_PROBE_MORE: Final[str] = "{shown} … и ещё {more}"
SOURCE_PROBE_PREVIEW_OK: Final[str] = "  превью: {width}×{height}, {kilobytes} КБ — годится для YouTube"
SOURCE_PROBE_PREVIEW_BAD: Final[str] = "  превью: не годится — {reason}"
SOURCE_PROBE_PREVIEW_SKIPPED: Final[str] = (
    "  превью: не скачивалось — язык не определился, в запуске такой источник не идёт"
)
SOURCE_PROBE_FAILED: Final[str] = "  отказ: {reason}"
SOURCE_PROBE_DETAIL: Final[str] = "  подробно: {detail}"
SOURCE_PROBE_SUMMARY: Final[str] = "Источников: {total}, получено: {ok}, отказов: {failed}."

# --- нейросеть (app\llm\): ни ключа, ни текста промта. Ключи LLM_ERROR_KIND_TEXT — значения LlmErrorKind,
# {provider} — название нейросети из LLM_BACKEND_TITLE (ключи — LlmBackend.name); ключи LLM_CHOICE_REASON_TEXT —
# значения ChoiceReason; ключи LLM_REQUEST_LABEL_TEXT — ярлыки запросов (LlmRequest.label).
LLM_BACKEND_TITLE: Final[dict[str, str]] = {
    "openai": "OpenAI",
}
LLM_REQUEST_FAILED: Final[str] = "Запрос к нейросети не удался: {reason}."
LLM_REQUEST_FAILED_STATUS: Final[str] = "Запрос к нейросети не удался: {reason} (код ответа {status})."
LLM_ERROR_KIND_TEXT: Final[dict[str, str]] = {
    "timeout": "{provider} не ответил вовремя",
    "connection_error": "нет связи с {provider} — проверьте интернет",
    "quota_exhausted": "на счёте {provider} кончились деньги или лимит — пополните баланс в кабинете {provider}",
    "rate_limit": "{provider} перегружен или превышен лимит запросов — запустите позже",
    "server_error": "сбой на стороне {provider} — запустите позже",
    "authentication_failed": "{provider} не принял ключ — проверьте ключ {provider} в настройках",
    "model_access_denied": "у ключа {provider} нет доступа к этой модели",
    "model_not_found": "такой модели нет или она недоступна этому ключу — проверьте имя модели в настройках",
    "incompatible_request_shape": "модель не умеет отвечать по заданной схеме JSON",
    "unsupported_parameter": "модель не принимает один из параметров запроса",
    "bad_request": "{provider} отклонил запрос",
    "request_failed": "{provider} не выполнил запрос",
    "empty_output": "модель вернула пустой ответ",
    "not_configured": "не задан ключ {provider} — задайте его на вкладке «Нейросеть» настройщика",
}
LLM_REQUEST_LABEL_TEXT: Final[dict[str, str]] = {
    "model_probe": "проверка",
    "startup_ping": "проба",
}
LLM_CHOICE_REASON_TEXT: Final[dict[str, str]] = {
    "primary_confirmed": "основная, ответила на проверку",
    "primary_unchecked": "основная; проверить не удалось, работаем на ней",
    "fallback_confirmed": "запасная: основная недоступна этому ключу",
    "fallback_unchecked": "запасная: основная недоступна этому ключу, запасную проверить не удалось",
    "refused": "подходящей модели нет",
}
LLM_CHOICE_LINE: Final[str] = "Модель: {model} — {reason}."
LLM_CHOICE_REFUSED: Final[str] = "Модель не выбрана. {reason}"

# --- ответ модели на merge (app\llm\merges\): причина отказа по коду; ключи — значения MergeRejectCode
MERGE_REJECT_TEXT: Final[dict[str, str]] = {
    "not_json_object": "модель ответила не одним объектом JSON",
    "missing_keys": "в ответе модели нет названия или описания",
    "extra_keys": "в ответе модели есть лишние поля кроме названия и описания",
    "invalid_title": "название пустое или содержит эмодзи",
    "invalid_description": "описание пустое",
    "cta_as_first_paragraph": "описание начинается с призыва подписаться или написать комментарий",
    "duplicate_paragraph": "в описании повторяются абзацы или тезис",
    "empty": "в описании не осталось текста после удаления служебных строк",
    "paragraph_underflow": "в описании слишком мало абзацев",
    "paragraph_overflow": "в описании слишком много абзацев",
    "unexpected_error": "модель вернула название или описание не текстом",
    "per_source_enumeration": "описание пересказывает источники по очереди, а не сводит их",
    "hook_echo_in_body": "начало описания повторяет тезис, и убрать повтор не удалось",
    "cta_in_hook": "первый абзац описания — призыв или служебная строка, а не тезис",
    "insufficient_bullet_coverage": "в описании слишком мало пунктов для числа источников",
    "compact_bullet_overflow": "в описании больше семи пунктов при одном-двух источниках",
    "excessive_emoji_usage": "в описании больше десяти эмодзи вне маркеров пунктов",
    "overloaded_bullet": "в описании несколько перегруженных пунктов",
    "numbered_title_dump": "название перечисляет темы под номерами",
    "semantic_gate": "описание не прошло проверку языка и алфавита",
}
# Ресурс строк промта merge (app\llm\merges\prompt_texts.py): у каждого ключа — список строк.
RESOURCE_PROBLEM_LINES: Final[str] = "нужен непустой список строк"

# --- пробник нейросети (app\tools\llm_probe.py): модель, токены, стоимость; ни ключа, ни промта
LLM_PROBE_TITLE: Final[str] = "Проверка нейросети OpenAI"
LLM_PROBE_SETTINGS: Final[str] = "Основная модель: {primary}; запасная: {fallback}; тариф: {tier}; рассуждение: {effort}."
LLM_PROBE_ANSWER: Final[str] = "Ответ модели: {text}"
LLM_PROBE_ANSWER_CUT: Final[str] = "{text}…"
LLM_PROBE_TOKENS: Final[str] = (
    "Токены: вход {input} (из кеша {cached}), выход {output} (из них рассуждение {thinking}), всего {total}."
)
LLM_PROBE_TOKENS_UNKNOWN: Final[str] = "Токены: нейросеть не сообщила расход по части запросов."
LLM_PROBE_REQUESTS: Final[str] = "Запросов: {requests}; тарифы: {tiers}."
LLM_PROBE_TIER_ENTRY: Final[str] = "{label} — {tier}"
LLM_PROBE_COST: Final[str] = "Стоимость: ${cost}."
LLM_PROBE_COST_UNKNOWN: Final[str] = "Стоимость: не меньше ${cost} — цены части моделей ({models}) в программе нет."

# --- обрыв и падение запуска (app\main.py::Launch.run)
RUN_INTERRUPTED: Final[str] = (
    "Запуск прерван. Что уже сделано на YouTube, найдёт и учтёт следующий запуск."
)
RUN_CRASHED: Final[str] = (
    "Livecraft аварийно остановился — подробности в логе {log}. "
    "Что уже сделано на YouTube, найдёт и учтёт следующий запуск; перешлите лог оператору."
)

# --- замок эталона кода (app\tools\code_standard, CLAUDE.md §11): инструмент разработки,
# в поставку не идёт. Ключи словарей — коды правил (Rule), признаков (Sign) и видов изменений (ChangeKind).
CODE_STANDARD_DESCRIPTION: Final[str] = (
    "Замок эталона кода livecraft: отчёт по правилам E1–E21 и реестр долгов, который может только сокращаться."
)
CODE_STANDARD_HELP_INIT: Final[str] = (
    "создать реестр долгов по текущему коду, если его нет; в существующий реестр — только добавить разделы "
    "правил, которых в нём ещё нет"
)
CODE_STANDARD_HELP_WRITE_DEBT: Final[str] = (
    "переписать реестр по текущему коду — только если ни один долг не появился и не вырос"
)
CODE_STANDARD_HELP_COMPARE: Final[str] = (
    "сравнить реестр с прежней версией: git-ссылка (HEAD, хеш коммита) или путь к файлу реестра"
)
CODE_STANDARD_HELP_FILES: Final[str] = "показать долги реестра в этих файлах или папках (путь от корня репозитория)"
CODE_STANDARD_METAVAR_VERSION: Final[str] = "ВЕРСИЯ"
CODE_STANDARD_METAVAR_PATH: Final[str] = "ПУТЬ"
CODE_STANDARD_RULE_LABELS: Final[dict[str, str]] = {
    "E1": "свободные функции",
    "E2": "статические методы",
    "E3": "длина определения",
    "E4": "число параметров",
    "E5": "литералы в телах функций",
    "E6": "кириллица в коде",
    "E7": "текст в исключениях",
    "E8": "одно значение — одно объявление",
    "E9": "регулярные выражения",
    "E10": "логгеры",
    "E11": "структурные клоны",
    "E12": "пустые обёртки",
    "E13": "кортежи-состояния",
    "E14": "сырые данные",
    "E15": "защитные преобразования",
    "E16": "слои и кольца импорта",
    "E17": "время",
    "E18": "размеры модулей и классов",
    "E19": "код в __init__.py",
    "E20": "тесты",
    "E21": "имя определено в модуле дважды",
}
CODE_STANDARD_SIGN_LABELS: Final[dict[str, str]] = {
    "names_app_class": "(а) в аннотациях класс app",
    "one_class_use": "(б) нужна одному классу",
    "unused": "(в) никто не использует",
    "forwarding": "(а) пересылка",
    "two_layers": "(б) два слоя",
    "foreign_body": "(в) чужое тело",
    "module": "модулей",
    "class": "классов",
    "number": "числа",
    "log": "лог",
    "separator": "разделители",
    "identifier": "идентификаторы",
    "text": "текст",
    "text_constant": "строки",
    "number_constant": "числа",
    "repeated_pattern": "повторы шаблона",
    "pattern_in_function": "шаблон в функции",
    "area_missing": "get_logger без LogArea",
    "raw_logger": "logging.getLogger вне пакета логов",
    "edge": "рёбра",
    "ring": "кольца",
    "unmapped": "пакеты вне карты",
    "test_import": "импорт модуля тестов",
    "logger_name": "имя логгера строкой",
    "private_patch": "подмена приватного имени",
    "global_patch": "подмена os / shutil",
    "dataclass_replace": "dataclasses.replace вне заготовок",
}
# Ключи реестра E16, которые не называют пакеты парой «пакет -> пакет».
CODE_STANDARD_RING_KEY: Final[str] = "кольцо: {modules}"
CODE_STANDARD_UNMAPPED_KEY: Final[str] = "вне карты: {package}"
CODE_STANDARD_REPORT_TITLE: Final[str] = "Эталон кода livecraft: нарушения, долги реестра и исключения"
CODE_STANDARD_REPORT_ROW: Final[str] = "{rule:<4} {label:<34} {now:>7} {ledger:>10} {exempt:>11} {goal:>5}"
CODE_STANDARD_REPORT_COLUMNS: Final[dict[str, str]] = {
    "rule": "код",
    "label": "правило",
    "now": "сейчас",
    "ledger": "в реестре",
    "exempt": "исключений",
    "goal": "цель",
}
CODE_STANDARD_REPORT_NO_VALUE: Final[str] = "—"
CODE_STANDARD_REPORT_SIGNS: Final[str] = "     {signs}"
CODE_STANDARD_REPORT_SIGN: Final[str] = "{label}: {count}"
CODE_STANDARD_REPORT_STATE: Final[str] = (
    "Код против реестра: новых {new}, выросших {grown}, уменьшившихся {shrunk}, снятых {gone}."
)
CODE_STANDARD_REPORT_NO_LEDGER: Final[str] = (
    "Реестра долгов нет — создайте его: python -m app.tools.code_standard --init"
)
CODE_STANDARD_CHANGE_LINES: Final[dict[str, str]] = {
    "new": "  {rule} {key} — новое: {after}",
    "grown": "  {rule} {key} — выросло: было {before}, стало {after}",
    "shrunk": "  {rule} {key} — уменьшилось: было {before}, стало {after}",
    "gone": "  {rule} {key} — снято (было {before})",
    "same": "  {rule} {key} — без изменений: {after}",
}
CODE_STANDARD_EXEMPTION_NO_REASON: Final[str] = "Исключение {rule} {key}: пустое обоснование."
CODE_STANDARD_EXEMPTION_NOT_CAUGHT: Final[str] = (
    "Исключение {rule} {key}: правило его больше не ловит — уберите его из exceptions.json."
)
CODE_STANDARD_STALE_ENTRIES: Final[str] = (
    "В реестре устаревшие записи — долг снят или уменьшился в коде. "
    "Обновите реестр: python -m app.tools.code_standard --write-debt"
)
CODE_STANDARD_GROWTH: Final[str] = (
    "Появились или выросли нарушения эталона кода. Уберите их из кода — в реестр новые долги не записываются:"
)
CODE_STANDARD_INIT_CREATED: Final[str] = "Реестр долгов создан: {file}; записей: {count}."
CODE_STANDARD_INIT_EXTENDED: Final[str] = "В реестр добавлены разделы правил {rules}; записей: {count}."
CODE_STANDARD_INIT_EXISTS: Final[str] = (
    "Реестр {file} уже есть и покрывает все проверяемые правила — переписать его может только --write-debt."
)
CODE_STANDARD_NO_LEDGER: Final[str] = "Реестра долгов нет — сначала выполните --init."
CODE_STANDARD_WRITE_REFUSED: Final[str] = (
    "Реестр не переписан: долги появились или выросли. Уберите их из кода:"
)
CODE_STANDARD_WRITE_DONE: Final[str] = "Реестр {file} переписан по коду; снятых и уменьшившихся записей: {count}."
CODE_STANDARD_COMPARE_GROWN: Final[str] = "Против {target} в реестре появилось или выросло:"
CODE_STANDARD_COMPARE_REDUCED: Final[str] = "Против {target} из реестра снято или уменьшилось:"
CODE_STANDARD_COMPARE_SAME: Final[str] = "Против {target} реестр не вырос."
CODE_STANDARD_FILES_TITLE: Final[str] = "Долги реестра в {paths}:"
CODE_STANDARD_FILES_NONE: Final[str] = "Долгов реестра в {paths} нет."
CODE_STANDARD_FILES_LINE: Final[str] = "  {rule} {key} — {value}{signs}"
CODE_STANDARD_FILES_SIGNS: Final[str] = "; {signs}"
CODE_STANDARD_FILE_PROBLEMS: Final[dict[str, str]] = {
    "unreadable": "Файл замка {file} не читается.",
    "not_json": "Файл замка {file} — не JSON.",
    "not_object": "В файле замка {file} на месте «{key}» ожидается объект JSON.",
    "missing": "В файле замка {file} нет ключа «{key}».",
    "not_integer": "В файле замка {file} значение «{key}» — не целое число.",
    "not_text": "В файле замка {file} значение «{key}» — не строка.",
    "not_text_list": "В файле замка {file} значение «{key}» — не список строк.",
    "not_integer_list": "В файле замка {file} значение «{key}» — не список целых чисел.",
    "not_object_list": "В файле замка {file} значение «{key}» — не список объектов JSON.",
    "unknown_key": "В файле замка {file} неизвестный раздел «{key}».",
    "unknown_level": "В файле замка {file} карта слоёв ссылается на неизвестный уровень «{key}».",
    "git_failed": "git не отдал реестр версии {file}: проверьте ссылку или путь к файлу реестра.",
}
