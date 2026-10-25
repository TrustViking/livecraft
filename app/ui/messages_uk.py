"""Тексты для людей на украинском: консоль, отчёт, файл ключей, настройщик (CLAUDE.md §11, §14 решение 24).

Те же имена констант, ключи словарей и подстановки `{…}`, что в `app\\ui\\messages_ru.py`; зачем нужна каждая
строка, объясняют комментарии там. Каталог выбирает `app\\ui\\messages.py` по языку Windows.
"""
from __future__ import annotations

from typing import Final

# --- общий словарь
LIST_JOINER: Final[str] = ", "
ITEM_JOINER: Final[str] = "; "
NONE_TEXT: Final[str] = "немає"

# --- командная строка (§10)
CLI_DESCRIPTION: Final[str] = (
    "Livecraft: план стрімів із Google Sheets → ефіри на YouTube → ключі потоків стрімеру."
)
HELP_SETUP: Final[str] = "відкрити налаштування: ключі й посилання, канали YouTube, параметри запуску"
HELP_DRY_RUN: Final[str] = (
    "прочитати таблицю, зібрати ефіри й звірити їх із YouTube; нічого не створювати, "
    "у форму не надсилати, keys.txt не змінювати"
)
HELP_CHECK: Final[str] = "перевірити кожен канал: вхід, нік і назву, мови, кількість запланованих ефірів"
HELP_AUTH: Final[str] = (
    "заново авторизувати канал (нік handle з channels.json, наприклад @MyChannel) або all — усі канали"
)
HELP_STATUS: Final[str] = "звірка ефірів livecraft, keys.txt і звіт — без таблиці й без LLM"
HELP_PACKAGE_FILE: Final[str] = (
    "пакет .bcast: копіюється в папку пакетів, потім звичайний запуск за ввімкненими лініями"
)
CLI_PACKAGE_WITH_MODE: Final[str] = (
    "пакет .bcast відкривається лише звичайним запуском — без --setup, --check, --auth і --status"
)
HELP_DEBUG: Final[str] = "докладний журнал у терміналі"
HELP_VERSION: Final[str] = "показати номер версії й вийти"
VERSION_TEXT: Final[str] = "Livecraft {version}"
CLI_METAVAR_HANDLE: Final[str] = "НІК"
CLI_METAVAR_PACKAGE: Final[str] = "ПАКЕТ"

# --- шапка запуска
CONSOLE_TITLE: Final[str] = "Livecraft {version} — {generated_at}"

# --- настройка программы (§8)
SETUP_REQUIRED: Final[str] = "Запустіть .\\livecraft.bat --setup і заповніть налаштування."
SERVICE_NEED_BLOCKED: Final[str] = "Не готово: {gap}."
SETUP_OPENING: Final[str] = "Бракує налаштувань — відкриваю вікно налаштувань."

# --- готовность частей режима (§10)
RUN_PART_LABELS: Final[dict[str, str]] = {
    "plan": "Таблиця плану",
    "local_previews": "Прев’ю на диску",
    "drive_previews": "Прев’ю на Google Диску",
    "merge": "Нейромережа",
    "package": "Пакет",
    "doc": "Google-документ",
    "doc_copy": "Копія документа",
    "announce": "Telegram",
    "packages_in": "Читання пакетів",
    "broadcast": "Ефіри YouTube",
    "keys": "Ключі у форму",
}
RUN_NEED_BLOCKED: Final[str] = "Не готово — {parts}: {gap}."
LINES_NONE_WORKING: Final[str] = (
    "Не ввімкнено жодної лінії роботи: увімкніть їх у вікні налаштувань (.\\livecraft.bat --setup)."
)
LINES_NO_SUPPORT: Final[str] = "  не працюють без «{support}»: {lines}"
LINES_NO_SUPPORT_MERGE: Final[str] = (
    "  не працюють без «{support}»: {lines} — від таблиці плану вони працюють лише з нейромережею: тексти «за "
    "номерами» на YouTube і в пакет не йдуть"
)
READINESS_GAP_IN_SETUP: Final[str] = "{what} — «Livecraft — налаштування», вкладка «{tab}»"
READINESS_GAP_SETTINGS: Final[str] = "додаткові налаштування ({key} — {problem})"
READINESS_GAP_FORM: Final[str] = "посилання на Google-форму для ключів стріму"
READINESS_GAP_TELEGRAM: Final[str] = "бот Telegram і чат для оголошень"
READINESS_GAP_CHANNELS_MISSING: Final[str] = "канали YouTube не задано"
READINESS_GAP_CHANNELS: Final[str] = "канали YouTube ({key} — {problem})"
READINESS_GAP_VAULT_BROKEN: Final[str] = "ключі й посилання не читаються: {problem}. {advice}"
READINESS_GAP_CLIENT_SECRET: Final[str] = "не вибрано проєкт Google"
READINESS_GAP_PROJECT_MISSING: Final[str] = "файл проєкту Google не знайдено: {path}"
READINESS_GAP_PROJECT_UNFIT: Final[str] = "файл проєкту Google не годиться: {path}"
GOOGLE_PROJECT_CONNECTED: Final[str] = "Проєкт Google: підключено {path}"
DRIVE_LINK_MIGRATED: Final[str] = (
    "Посилання на папку Google Диска тепер зберігається прихованим — папкою прев’ю і папкою документів оголошень; "
    "вводити його заново не потрібно."
)
DRIVE_LINK_MIGRATION_FAILED: Final[str] = (
    "УВАГА: посилання на папку Google Диска з попередніх налаштувань перенести не вдалося ({reason}). "
    "Вставте його на вкладках «Прев’ю» і «Google-документ»: .\\livecraft.bat --setup."
)
DRIVE_LINK_MIGRATION_LOCAL_UNREAD: Final[str] = (
    "введені раніше ключі й посилання не прочиталися, а запис поверх них стер би їх"
)

SETTINGS_FILE_CREATED: Final[str] = "Налаштування програми створено з шаблону постачання: {path}"
SETTINGS_SECTIONS_ADDED: Final[str] = "До налаштувань програми дописано з шаблону постачання новий розділ: {sections}"
RETENTION_REMOVED: Final[str] = "Видалено старі файли програми (старші за {days} дн.): {count}."

# --- yt-dlp і deno в папці tools оновлюються самі, cookies перевіряються (app\runtime).
TOOL_UPDATED: Final[str] = "{tool} оновлено: {before} → {after}."
TOOL_DOWNLOADED: Final[str] = "{tool} {after} завантажено в папку tools."
TOOL_NOT_CHECKED: Final[str] = (
    "{tool}: нову версію не перевірено — {reason}. Робота йде на версії {version}, наступний запуск перевірить знову."
)
TOOL_UNUSABLE: Final[str] = (
    "{tool}: у папці tools немає робочого файлу, а завантажити його не вдалося — {reason}. Відео YouTube можуть не "
    "прочитатися; наступний запуск спробує знову."
)
TOOL_PROBLEMS: Final[dict[str, str]] = {
    "no_answer": "немає зв’язку з GitHub",
    "refused": "GitHub відмовив у відповіді",
    "no_version": "GitHub не назвав номер останньої версії",
    "broken_download": "завантажений файл пошкоджено",
    "not_written": "новий файл не став на місце попереднього",
    "self_update_failed": "yt-dlp не зміг оновитися сам",
}
COOKIES_WINDOW_ABSENT: Final[str] = "Файлу cookies немає ({path}) — завантажте його кнопкою «Завантажити файл…»."
COOKIES_WINDOW_FILE: Final[str] = "Файл cookies: {path}"
COOKIES_WINDOW_BAD_FORMAT: Final[str] = "Не той вигляд: першим рядком має бути «{header}»"
COOKIES_WINDOW_NETSCAPE: Final[str] = "Вигляд: Netscape"
COOKIES_WINDOW_EXPORTED: Final[str] = "Вивантажено {date}, {days} діб тому; строк нагадування — {limit} діб."
COOKIES_WINDOW_STALE: Final[str] = "Вивантажено {date} ({days} діб): строк нагадування {limit} діб закінчився — вивантажте нові"
COOKIES_WINDOW_NO_LOGIN: Final[str] = "Cookies входу в акаунт YouTube: немає — вивантажте їх після входу в YouTube"
COOKIES_WINDOW_LOGIN_SESSION: Final[str] = "Cookies входу в акаунт YouTube: є, до закриття браузера"
COOKIES_WINDOW_LOGIN_UNTIL: Final[str] = "Cookies входу в акаунт YouTube: є, діють до {date}"
COOKIES_WINDOW_LOGIN_EXPIRED: Final[str] = "Cookies входу в акаунт YouTube: строк минув {date}"
COOKIES_WINDOW_LOGIN_YES: Final[str] = "Вхід у YouTube є: yt-dlp прочитає й описи відео 18+."
COOKIES_WINDOW_LOGIN_NO: Final[str] = (
    "Входу в YouTube немає — роботі програми це не заважає:\nбез входу недоступні лише описи відео 18+."
)
COOKIES_WINDOW_LOGIN_UNKNOWN: Final[str] = (
    "Вхід у YouTube перевірити не вдалося — роботі програми це не заважає:\n"
    "без входу недоступні лише описи відео 18+."
)
COOKIES_PLACE_FAILED: Final[str] = "Файл не завантажено: {reason}."
COOKIES_PLACE_PROBLEMS: Final[dict[str, str]] = {
    "not_netscape": "не формат Netscape, попередній файл лишився",
    "unreadable": "вибраний файл не читається",
    "not_written": "копія не записалася (збій диска або файл зайнятий)",
}

# --- готовность к запуску (§7.4)
READINESS_SUMMARY_TITLE: Final[str] = "Налаштування livecraft:"
READINESS_FIELD_LINE: Final[str] = "  {label}: {origin}"
READINESS_LINES_WORKING: Final[str] = "  лінії роботи: {lines}"
READINESS_LINES_OFF: Final[str] = "  вимкнено: {lines}"
FORM_URL_LABEL: Final[str] = "Google-форма для ключів стріму (ефіру)"
DOCS_CONTACTS_LABEL: Final[str] = "контакти для стримерів у документі оголошень"
READINESS_FORM_CONFIGURED: Final[str] = "налаштовано"
READINESS_FORM_NOT_CONFIGURED: Final[str] = "не налаштовано"
READINESS_CHANNELS_LINE: Final[str] = "  каналів: {count}, мови стрімів: {languages}"
READINESS_CHANNELS_ABSENT: Final[str] = "  канали: не прочитано"
READINESS_CHANNELS_NONE: Final[str] = "  канали: не задано"
# Сводка настроек запуска: откуда тексты эфиров — по линиям запуска (app\run\line_plan.py::RunTexts, §14 решение 50;
# ключи — значения RunTextSource), и повторная передача ключей — раздел broadcasts livecraft.json (решение 36).
READINESS_TEXTS_LABEL: Final[str] = "тексти ефірів"
RUN_TEXT_SOURCES: Final[dict[str, str]] = {
    "llm": "від нейромережі",
    "videos": "тексти відео, в ефіру з кількох відео — «за номерами», лише для людей",
    "packages": "з пакетів",
}
READINESS_RESEND_KEYS_LABEL: Final[str] = "повторна передача ключів"
READINESS_RESEND_KEYS_OFF: Final[str] = "вимкнена"
READINESS_RESEND_KEYS_ON: Final[str] = "увімкнена — ключі підуть під час цього запуску"
READINESS_RESEND_KEYS_DRY_RUN: Final[str] = "увімкнена — у пробному запуску ключі не йдуть"
VAULT_LOCAL_UNREADABLE: Final[str] = (
    "УВАГА: власні ключі й посилання не прочитано ({fields}) — так буває після перенесення програми на інший "
    "комп’ютер або зміни користувача Windows. Введіть свої значення знову: .\\livecraft.bat --setup."
)
VAULT_TOKEN_UNREADABLE: Final[str] = (
    "УВАГА: значення з токена доступу не прочитано — так буває після перенесення програми на інший комп’ютер або "
    "зміни користувача Windows. Завантажте токен знову: .\\livecraft.bat --setup, вкладка «Токени»."
)
VAULT_FORMAT_REASON_TEXT: Final[dict[str, str]] = {
    "file_unreadable": "файл не відкривається — його тримає інша програма, немає прав або на його місці папка",
    "not_text": "файл пошкоджено — це не текст",
    "damaged": "файл пошкоджено — всередині не те, що записує програма",
    "unsupported_version": "файл записано іншою версією програми",
    "key_invalid": "ключ файлу неправильної довжини",
}
VAULT_FILE_PROBLEM: Final[str] = "{file} — {reason}"
VAULT_FILE_BROKEN: Final[str] = "Ключі й посилання не читаються: {problem}. {advice}."
VAULT_FILE_ADVICE_LOCAL: Final[str] = (
    "Відкрийте «Livecraft — налаштування» і введіть свої значення знову — збереження замінить цей файл"
)
VAULT_FILE_ADVICE_TOKEN: Final[str] = "Завантажте токен знову: «Livecraft — налаштування», вкладка «Токени»"
VAULT_DECRYPT_FAILED: Final[str] = "Значення «{field}» не розшифровується: {reason}"
VAULT_DECRYPT_REASON_TEXT: Final[dict[str, str]] = {
    "tag_mismatch": "файл змінено або записано іншим ключем",
    "not_text": "всередині не текст",
}
DPAPI_UNAVAILABLE: Final[str] = "Свої ключі й посилання на цьому комп’ютері не зберегти: {reason}"
DPAPI_REASON_TEXT: Final[dict[str, str]] = {
    "not_loaded": "захист даних Windows (DPAPI) не завантажився — потрібна Windows",
    "call_failed": "захист даних Windows (DPAPI) відмовив",
}

# --- конфиги (§5)
CONFIG_ERROR: Final[str] = "Помилка в конфігурації {path}: {key} — {problem}"
CONFIG_ROOT_KEY: Final[str] = "(корінь файлу)"
CONFIG_CHANNELS_FIELDS: Final[tuple[str, ...]] = (
    "  account_name — назва каналу як на YouTube: вона йде у форму як «Назва каналу»;",
    "  handle — нік каналу на YouTube, починається з @ (Студія -> аватар угорі праворуч); "
    "нік і назву програма потім вирівнює сама;",
    "  google_account — пошта облікового запису Google, у якому цей канал;",
    "  languages — мови стрімів цього каналу: {languages};",
    "  privacy — видимість ефірів: {privacy};",
    "  platform — {platform}.",
)
CONFIG_LANGUAGES_RULE: Final[str] = 'непорожній список двобуквених кодів ISO 639-1 без повторів, наприклад ["uk"]'
CONFIG_CHANNELS_TEMPLATE: Final[str] = """{
  "channels": [
    {"platform": "youtube", "account_name": "Назва каналу на YouTube", "handle": "@нік_каналу", "google_account": "you@gmail.com",
     "languages": ["ru"], "privacy": "unlisted"}
  ]
}"""
CONFIG_PROBLEM_FILE_MISSING: Final[str] = "файлу немає"
CONFIG_PROBLEM_JSON: Final[str] = "файл не читається як JSON: {error}"
CONFIG_PROBLEM_NOT_MAPPING: Final[str] = "потрібен об’єкт JSON у фігурних дужках"
CONFIG_PROBLEM_MISSING_KEY: Final[str] = "обов’язкове поле відсутнє"
CONFIG_PROBLEM_UNKNOWN_KEY: Final[str] = "невідоме поле"
CONFIG_PROBLEM_DUPLICATE_KEY: Final[str] = "поле вказано двічі"
CONFIG_PROBLEM_NON_EMPTY_STRING: Final[str] = "потрібен непорожній рядок у лапках"
CONFIG_PROBLEM_STRING: Final[str] = 'потрібен рядок у лапках; порожній рядок "" — не налаштовано'
CONFIG_PROBLEM_FORM_URL: Final[str] = (
    "потрібне посилання на Google-форму: https://docs.google.com/forms/… або https://forms.gle/…, без пробілів; "
    "порожній рядок — форму не налаштовано"
)
CONFIG_PROBLEM_TEXT_OR_NULL: Final[str] = "потрібна назва питання форми в лапках або null, якщо такого питання у формі немає"
CONFIG_PROBLEM_TEXT_MAPPING: Final[str] = (
    'потрібен непорожній об’єкт «код — текст варіанта», наприклад {"uk": "Украинский ( Ukranian)"}'
)
CONFIG_PROBLEM_INT_MIN: Final[str] = "потрібне ціле число, не менше за {minimum}"
CONFIG_PROBLEM_NUMBER_MIN: Final[str] = "потрібне число, не менше за {minimum:g}, можна дробове, наприклад 0.5"
CONFIG_PROBLEM_NUMBER_FINITE: Final[str] = "потрібне звичайне число: NaN і нескінченність не годяться"
CONFIG_PROBLEM_BOOL: Final[str] = "потрібно true або false"
CONFIG_PROBLEM_CHOICE: Final[str] = "допустимо: {allowed}"
CONFIG_PROBLEM_CHAT_ID: Final[str] = (
    "потрібен id чату Telegram — ціле число, наприклад -1001234567890; порожній рядок — чат не задано"
)
CONFIG_PROBLEM_GROUP_CHAT_ID: Final[str] = "id групи Telegram — від’ємне число, наприклад -1001234567890"
CONFIG_PROBLEM_FORM_PLATFORM: Final[str] = "серед варіантів платформи обов’язково має бути «{platform}»"
CONFIG_PROBLEM_FORM_DATE_FORMAT: Final[str] = "у форматі дати обов’язкові {required}; немає {absent}"
CONFIG_PROBLEM_IMAGE_TEMPLATE_PLACEHOLDERS: Final[str] = (
    "у шаблоні папки прев’ю обов’язкові {{date}} і {{language}}; немає: {absent}"
)
CONFIG_PROBLEM_IMAGE_TEMPLATE_ABSOLUTE: Final[str] = (
    "шаблон папки прев’ю має бути відносним, наприклад {date}/{language}: корінь задає сама програма"
)
CONFIG_PROBLEM_IMAGE_TEMPLATE_FORMAT: Final[str] = (
    "у шаблоні папки прев’ю є підстановка, якої програма не знає; допустимі лише {date} і {language}"
)
CONFIG_PROBLEM_TIMEZONE_UNKNOWN: Final[str] = (
    "часовий пояс не розпізнано: потрібна назва зони з бази IANA з урахуванням регістру, наприклад Europe/Kyiv"
)
CONFIG_PROBLEM_CHANNELS_LIST: Final[str] = "потрібен список каналів у квадратних дужках (без каналів — [])"
CONFIG_PROBLEM_ACCOUNT_NAME_TOO_LONG: Final[str] = (
    "назва каналу довша за {maximum} символів (зараз {length}): на YouTube таких назв немає"
)
CONFIG_PROBLEM_ACCOUNT_NAME_CONTROL: Final[str] = "у назві каналу є керівний символ (перенесення рядка, табуляція)"
CONFIG_PROBLEM_ACCOUNT_NAME_SPACE_EDGE: Final[str] = (
    "назва каналу починається або закінчується пробілом: «{value}»; на YouTube таких назв немає — приберіть пробіл"
)
CONFIG_PROBLEM_HANDLE_PREFIX: Final[str] = "нік «{value}» має починатися з {prefix}, як на YouTube"
CONFIG_PROBLEM_HANDLE_LENGTH: Final[str] = (
    "у ніку «{value}» після @ потрібно від {minimum} до {maximum} символів (зараз {length})"
)
CONFIG_PROBLEM_HANDLE_CHAR: Final[str] = (
    "у ніку «{value}» неприпустимий символ {char}: пробіли, керівні символи та < > : \" / \\ | ? * у ніку не бувають"
)
CONFIG_PROBLEM_HANDLE_DUPLICATE: Final[str] = (
    "нік «{value}» уже є в іншого каналу («{other}»); великі й малі літери в ніку не розрізняються"
)
CONFIG_PROBLEM_GOOGLE_ACCOUNT: Final[str] = (
    "«{value}» не схоже на пошту облікового запису Google: потрібен вигляд ім’я@домен, рівно один @ і без пробілів"
)
CONFIG_PROBLEM_PLATFORM_UNKNOWN: Final[str] = "невідома платформа «{value}»; допустимо: {allowed}"
CONFIG_PROBLEM_LANGUAGES: Final[str] = "потрібен " + CONFIG_LANGUAGES_RULE
CONFIG_PROBLEM_LANGUAGE_DUPLICATE: Final[str] = "мову «{value}» вказано двічі"
CONFIG_PROBLEM_LANGUAGE_UNKNOWN: Final[str] = (
    "«{value}» — не код мови: потрібен двобуквений код ISO 639-1 малими літерами, наприклад uk, en, ru"
)

# --- один экземпляр на машину (§6, инвариант 12)
LOCK_REJECTED: Final[str] = (
    "Livecraft уже працює на цьому комп’ютері: процес {pid}, запущено {started_at}. "
    "Дочекайтеся завершення першого запуску або закрийте його вікно."
)
LOCK_REJECTED_UNKNOWN_OWNER: Final[str] = (
    "Livecraft уже працює на цьому комп’ютері, але який саме процес тримає запуск — визначити не вдалося. "
    "Закрийте відкриті вікна Livecraft і запустіть знову."
)

# --- сейф (§7)
VAULT_FIELD_OPENAI_API_KEY: Final[str] = "ключ OpenAI"
VAULT_FIELD_SHEETS_ID: Final[str] = "Google-таблиця контент-плану"
VAULT_FIELD_TELEGRAM_BOT_TOKEN: Final[str] = "токен бота Telegram"
VAULT_FIELD_DRIVE_PREVIEWS_FOLDER: Final[str] = "папка Google Диска для прев’ю"
VAULT_FIELD_DRIVE_DOCS_FOLDER: Final[str] = "папка Google Диска для документів оголошень"
VAULT_MASK_FINGERPRINT: Final[str] = "{label} (…{fingerprint})"
VAULT_ORIGIN_TOKEN: Final[str] = "отримано з токеном"
VAULT_ORIGIN_OWN: Final[str] = "введено у вікні налаштування"

# --- настройщик, поля сейфа (§8.2)
SETUP_INPUT_EMPTY: Final[str] = "порожньо — введіть значення"
SETUP_INPUT_EMPTY_RESET: Final[str] = "порожньо: щоб прибрати своє значення, натисніть «{button}»"
SETUP_INPUT_OPENAI_API_KEY: Final[str] = (
    "ключ OpenAI починається з sk-, пишеться без пробілів і перенесень рядка й має довжину не менше за {minimum} символів"
)
SETUP_INPUT_SHEETS_ID: Final[str] = (
    "потрібне посилання на Google-таблицю вигляду https://docs.google.com/spreadsheets/d/<id>/edit або сам id: "
    "латинські літери, цифри, - і _, не менше за {minimum} символів"
)
SETUP_INPUT_TELEGRAM_BOT_TOKEN: Final[str] = (
    "потрібен токен бота, який видав @BotFather: число, двокрапка й не менше за {minimum} латинських літер, цифр, "
    "_ і -, без пробілів"
)
SETUP_INPUT_DRIVE_LINK: Final[str] = (
    "потрібне посилання на папку Google Диска вигляду https://drive.google.com/drive/folders/… або сам id папки: "
    "латинські літери, цифри, - і _"
)
SETUP_INPUT_OWN_UNAVAILABLE: Final[str] = (
    "на цьому комп’ютері ключі й посилання зберегти не можна: Windows не дає прив’язати їх до облікового запису"
)
SETUP_KEYS_NOTICE_PROTECTION: Final[str] = (
    "Значення з токена приховано від перегляду й копіювання, але фахівець може їх дістати. Власні значення діють "
    "лише на цьому комп’ютері під тим самим обліковим записом Windows."
)
SETUP_KEYS_NOTICE_NO_OWN: Final[str] = (
    "На цьому комп’ютері ключі й посилання зберегти не можна: Windows не дає прив’язати їх до облікового запису."
)
SETUP_KEYS_NOTICE_LOCAL_UNREADABLE: Final[str] = (
    "Введені раніше значення не прочиталися — так буває після перенесення програми на інший комп’ютер або зміни "
    "користувача Windows. Перше збереження замінить їх новими."
)
SETUP_KEYS_NOTICE_LOCAL_BROKEN: Final[str] = (
    "Файл із введеними ключами й посиланнями пошкоджено — введіть значення знову: збереження замінить його."
)
SETUP_KEYS_NOTICE_TOKEN_UNREADABLE: Final[str] = (
    "Значення з токена не прочиталися — завантажте токен знову на вкладці «Токени»."
)

# --- настройщик, вкладка «Эфиры YouTube» (§8.2 п.4)
SETUP_CHANNELS_NOTICE_UNREADABLE: Final[str] = (
    "Файл secrets\\channels.json не прочитався: {key} — {problem}. Збереження замінить його списком цієї вкладки, "
    "а попередній файл залишиться в secrets\\channels.previous.json."
)

# --- настройщик, вкладка «Дополнительно» (§8.2 п.6)
SETUP_SETTINGS_NOTICE_UNREADABLE: Final[str] = (
    "Файл secrets\\livecraft.json не прочитався: {key} — {problem}. Вікно відкрито на значеннях постачання "
    "програми; файл буде записано першим збереженням налаштувань."
)

# --- окно настройщика (§8)
SETUP_WINDOW_TITLE: Final[str] = "Livecraft {version} — налаштування"
SETUP_WINDOW_FAILED: Final[str] = (
    "Вікно налаштувань не відкрилося ({error}). Потрібен робочий стіл Windows і Python із компонентом tcl/tk."
)
SETUP_ACTION_FAILED: Final[str] = (
    "Дію вікна не виконано через помилку програми — подробиці в журналі {log}. Вікно працює далі; архів логів "
    "для того, хто допомагає з програмою, зберігає кнопка «Зберегти архів логів» на вкладці «Логи»."
)
SETUP_TAB_TITLES: Final[dict[str, str]] = {
    "home": "Головна",
    "plan": "Таблиця плану",
    "cookies": "Cookies YouTube",
    "merge": "Нейромережа",
    "previews": "Прев’ю",
    "doc": "Google-документ",
    "package": "Пакет",
    "telegram": "Telegram",
    "broadcasts": "Ефіри YouTube",
    "keys": "Форма",
    "tokens": "Токени",
    "logs": "Логи",
    "advanced": "Додатково",
}
SETUP_READY: Final[str] = "Готово до запуску."
SETUP_BUTTON_SAVE: Final[str] = "Зберегти"
SETUP_FIELD_SAVED: Final[str] = "✓ збережено"
SETUP_PROBLEM_LINE: Final[str] = "{label}: {text}"
SETUP_SAVE_FAILED_TITLE: Final[str] = "Не збережено"
SETUP_CLOSE_DIRTY_TITLE: Final[str] = "Незбережені зміни"
SETUP_CLOSE_DIRTY_TEXT: Final[str] = "Є незбережені зміни. Закрити без збереження?"
SETUP_KEY_STATUS_OWN: Final[str] = "✓ задано ({mask})"
SETUP_KEY_STATUS_TOKEN: Final[str] = "✓ отримано з токеном ({mask})"
SETUP_LINK_STATUS_SET: Final[str] = "✓ задано: {url}"
SETUP_STATUS_NOT_SET: Final[str] = "✗ не задано"
CHECK_MARK_OK: Final[str] = "✓"
CHECK_MARK_PROBLEM: Final[str] = "✗"
CHECK_OK_LINE: Final[str] = "✓ {line}"
CHECK_PROBLEM_LINE: Final[str] = "✗ {line}"

# --- «Главная» (§14 решение 37)
SETUP_HOME_INTRO: Final[str] = (
    "Livecraft готує ефіри: бере план із Google-таблиці або з пакетів, пише нейромережею назву й опис ефіру, "
    "готує прев’ю, документ оголошень і пакет, надсилає оголошення в Telegram, створює ефіри на каналах YouTube і "
    "передає ключі стримеру."
)
SETUP_HOME_HOWTO: Final[str] = (
    "Кожен рядок нижче — підключення й налаштування функції роботи застосунку. Знак ✗ означає, що певну функцію "
    "роботи застосунку потрібно налаштувати."
)
SETUP_HOME_GO: Final[str] = "Перейти"
SETUP_HOME_RUNS: Final[str] = "Запуск зробить (ефіри {source}): {lines}"
SETUP_HOME_RUNS_NOTHING: Final[str] = "Запуск нічого не зробить: не ввімкнено жодної лінії."
SETUP_HOME_RUN_SOURCES: Final[dict[str, str]] = {
    "plan": "з таблиці плану",
    "packages_in": "з пакетів",
}
SETUP_HOME_RUNS_KEYS_ALL: Final[str] = "{line} — ключі всіх ефірів запуску наново"
SETUP_LINE_STAGES: Final[dict[str, str]] = {
    "input": "1. Вхід — звідки ефіри",
    "processing": "2. Обробка",
    "output": "3. Вивід",
    "broadcasts": "4. Ефіри",
}
SETUP_HOME_INPUTS: Final[dict[str, str]] = {
    "plan": "Таблиця плану",
    "packages_in": "Пакети",
}
SETUP_LINE_DOES: Final[dict[str, str]] = {
    "plan": "читає план ефірів із Google-таблиці",
    "merge": "пише одну назву й один опис на ефір",
    "local_previews": "зберігає прев’ю відео в папку на цьому комп’ютері",
    "drive_previews": "копіює прев’ю в папку на Google Диску й ставить посилання в таблицю",
    "doc": "створює документ оголошень на кожну дату",
    "doc_copy": "зберігає копію документа .docx на цьому комп’ютері",
    "package": "збирає файл пакета для ефірів на інших комп’ютерах",
    "announce": "надсилає оголошення й пакет у Telegram",
    "broadcast": "створює й виправляє ефіри на каналах YouTube",
    "keys": "передає ключі ефірів стримеру через Google-форму",
    "packages_in": "бере ефіри з пакетів у папці пакетів — з їхніми текстами й формою ключів",
}
SETUP_LINE_READY: Final[str] = "✓ готово"
SETUP_LINE_BLOCKED: Final[str] = "✗ бракує: {gaps}"
SETUP_LINE_GAP_JOINER: Final[str] = "; "
SETUP_LINE_OFF: Final[str] = "вимкнено"
SETUP_LINE_WITH_SUPPORT: Final[str] = "не працює без «{line}»"
SETUP_LINE_SUPPORT_REASONS: Final[dict[str, str]] = {
    "plan": "працює лише від таблиці плану",
    "merge": "від таблиці плану працює лише з нейромережею: тексти «за номерами» на YouTube і в пакет не йдуть",
}
SETUP_LINE_TITLES: Final[dict[str, str]] = {
    "keys": "Передавати ключі у форму",
}
SETUP_KEYS_CHOICES: Final[dict[str, str]] = {
    "new": "нові",
    "all": "усі",
}
SETUP_KEYS_HINTS: Final[dict[str, str]] = {
    "new": (
        "Підуть ключі ефірів, які запуск поставить на YouTube, і один повтор ключа, який форма минулого разу не "
        "підтвердила."
    ),
    "all": (
        "Ключі всіх ефірів запуску підуть ще раз: у стримера з’являться повторні рядки, він бере останній. Після "
        "повного запуску, де форма підтвердила всі ключі, вибір сам повернеться на «нові»."
    ),
}
SETUP_KEYS_INACTIVE: Final[dict[str, str]] = {
    "off": "Передачу ключів вимкнено — повзунок «Передавати ключі у форму» на вкладці «Форма».",
    "no_broadcasts": "Ефіри YouTube вимкнено — передавати нічого.",
    "no_merge": "Ефіри не працюють: від таблиці плану вони йдуть лише з нейромережею.",
    "no_form": "Не задано посилання на форму ключів — вкладка «Форма».",
}
SETUP_FIELD_NEEDED_BY: Final[str] = "Потрібно лініям: {lines}"
SETUP_FIELD_FROM_PACKAGES: Final[dict[str, str]] = {
    "form": "Під час входу «Пакети» форма ключів у кожного ефіру — з його пакета.",
    "sheets_vault": "Під час входу «Пакети» таблиця плану не читається.",
}

# --- вкладки линий (§8.2, §14 решение 37)
SETUP_DRIVE_ACCOUNT_NOTE: Final[str] = (
    "Папка прев’ю і папка документів — та сама або різні, як зручно. В обидві пише один обліковий запис Google — той, "
    "яким програма входить для таблиці плану й документів; папку іншого облікового запису або спільного диска "
    "відкрийте цьому обліковому запису з правом «Редактор». «Перевірити папку» скаже, чи може програма в неї писати."
)
SETUP_KEY_FIELD_LABELS: Final[dict[str, str]] = {
    "openai_api_key": "Ключ OpenAI",
    "sheets_id": "Google-таблиця з планом стрімів",
    "drive_previews_folder": "Папка Google Диска для прев’ю",
    "drive_docs_folder": "Папка Google Диска для документів оголошень",
    "telegram_bot_token": "Токен бота",
}
SETUP_KEY_FIELD_HINTS: Final[dict[str, str]] = {
    "openai_api_key": "platform.openai.com → API keys → Create new secret key; ключ починається з sk-",
    "sheets_id": "відкрийте таблицю в браузері й скопіюйте посилання з адресного рядка",
    "drive_previews_folder": (
        "папка на Google Диску для копій прев’ю (підпапки за датами й мовами програма створює сама): відкрийте папку в "
        "браузері й скопіюйте посилання з адресного рядка (вигляду https://drive.google.com/drive/folders/…). "
        + SETUP_DRIVE_ACCOUNT_NOTE
    ),
    "drive_docs_folder": (
        "папка на Google Диску, куди програма кладе Google-документи оголошень: відкрийте папку в браузері й "
        "скопіюйте посилання з адресного рядка (вигляду https://drive.google.com/drive/folders/…). "
        + SETUP_DRIVE_ACCOUNT_NOTE
    ),
}
SETUP_TABLE_TITLE: Final[str] = "Якою має бути таблиця"
SETUP_TABLE_TEXT_BEFORE: Final[str] = (
    "Перший рядок — назви стовпців. Програмі потрібні три стовпці — у будь-якому місці й порядку, решту вона не "
    "читає. Аркуш програма знаходить сама: той, де в першому рядку є ці три назви."
)
SETUP_TABLE_SAMPLE_ROW: Final[dict[str, str]] = {
    "link": "https://www.youtube.com/watch?v=…",
    "date": "28.09.2026",
    "time": "19:00",
}
SETUP_TABLE_SAMPLE_BY_PROGRAM: Final[str] = "(впише програма)"
SETUP_TABLE_SAMPLE_CHIP_HEADER: Final[str] = "відео (чип)"
SETUP_TABLE_SAMPLE_CHIP: Final[str] = "▶ Назва відео"
SETUP_TABLE_TEXT_AFTER: Final[str] = (
    "Один рядок — одне відео. Відео на один час і однієї мови програма збирає в один ефір. Дата — 28.09.2026, "
    "28-09-2026 або 2026-09-28; час — 19:00, за часовим поясом програми: {timezone}. Рядки з минулою датою "
    "пропускаються. У рядок відео програма сама пише мову, яку визначила за самим відео, — у колонку «Lang», і посилання "
    "на копію прев’ю — у колонку «Preview (Google Drive)»; немає таких колонок — додасть їх. Колонка «відео (чип)» — "
    "для людини; решту в таблиці програма лише читає."
)
SETUP_TABLE_BUTTON_CHECK: Final[str] = "Перевірити таблицю"
SETUP_TABLE_CHECKING: Final[str] = "Перевіряю таблицю…"
SETUP_TABLE_LOGIN: Final[str] = (
    "Відкрився браузер — увійдіть обліковим записом Google, якому відкрито таблицю плану (це не обліковий запис "
    "каналу YouTube), і позначте всі дозволи."
)
SETUP_TABLE_OK_NEAREST: Final[str] = (
    "✓ Аркуш «{sheet}»: посилання — стовпець {link}, дата — {date}, час — {time}. Майбутніх ефірів у таблиці: "
    "{count}, найближчий — {nearest}."
)
SETUP_TABLE_OK_NONE: Final[str] = (
    "✓ Аркуш «{sheet}»: посилання — стовпець {link}, дата — {date}, час — {time}. Рядків із майбутніми ефірами "
    "поки немає."
)
SETUP_TABLE_FAILED: Final[str] = "✗ {problem}"
SETUP_TABLE_INTERRUPTED: Final[str] = "Перевірку перервано — подробиці в журналі."
SETUP_LINK_LABELS: Final[dict[str, str]] = {
    "form.url": "Google-форма для ключів стрімів",
}
SETUP_LINK_HINTS: Final[dict[str, str]] = {
    "form.url": (
        "форма, через яку програма передає стрімеру ключі стрімів: посилання вигляду https://forms.gle/…"
    ),
}
SETUP_FOLDER_BUTTON_CHECK: Final[str] = "Перевірити папку"
SETUP_FOLDER_CHECKING: Final[str] = "Перевіряю папку…"
SETUP_FOLDER_LOGIN: Final[str] = (
    "Відкрився браузер — увійдіть обліковим записом Google, яким програма працює з таблицею плану й документами "
    "(це не обліковий запис каналу YouTube), і позначте всі дозволи."
)
SETUP_FOLDER_OK: Final[str] = "✓ Папка «{name}»: програма може складати в неї файли."
SETUP_FOLDER_FAILED: Final[str] = "✗ {problem}"
SETUP_FOLDER_NOT_FOLDER: Final[str] = "Посилання веде не на папку, а на файл «{name}» — потрібне посилання на папку."
SETUP_FOLDER_READ_ONLY: Final[str] = (
    "Папка «{name}»: програмі не можна додавати в неї файли — дайте обліковому запису Google, під яким увійшли, "
    "право редактора."
)
SETUP_LLM_KEY_BUTTON_CHECK: Final[str] = "Перевірити ключ"
SETUP_LLM_KEY_CHECKING: Final[str] = "Перевіряю ключ…"
SETUP_LLM_KEY_OK: Final[str] = "✓ Ключ прийнято. {choice}"
SETUP_LLM_KEY_UNCHECKED: Final[str] = "✗ Ключ перевірити не вдалося: {reason} {choice}"
SETUP_LLM_KEY_FAILED: Final[str] = "✗ {problem}"
SETUP_FORM_BUTTON_CHECK: Final[str] = "Перевірити форму"
SETUP_FORM_CHECKING: Final[str] = "Перевіряю форму…"
SETUP_FORM_OK: Final[str] = "✓ Форма «{form}» читається: усі питання для ключів на місці."
SETUP_FORM_QUESTIONS_MISSING: Final[str] = (
    "✗ У формі «{form}» немає питань {questions} — назви питань у livecraft.json (розділ form) мають збігатися з "
    "формою."
)
SETUP_FORM_QUESTION: Final[str] = "«{title}»"
SETUP_FORM_FAILED: Final[str] = "✗ {problem}"
SETUP_FORM_NOT_SET: Final[str] = "Не задано посилання на форму — впишіть його вище й натисніть «Зберегти»."
SETUP_CHANNELS_BUTTON_LOGIN: Final[str] = "Увійти у вибраний канал"
SETUP_CHANNELS_BUTTON_CHECK: Final[str] = "Перевірити всі канали"
SETUP_CHANNELS_CHECKING: Final[str] = "Перевіряю канали…"
SETUP_FOLDER_LABELS: Final[dict[str, str]] = {
    "folders.packages": "Папка пакетів",
    "folders.docs": "Папка копій документів",
    "folders.images": "Папка прев’ю",
}
SETUP_FOLDER_HINTS: Final[dict[str, str]] = {
    "folders.packages": (
        "куди програма кладе пакети plan_*.bcast; коли таблицю плану вимкнено, з неї беруть ефіри всі лінії"
    ),
    "folders.docs": "куди програма зберігає копії документів оголошень .docx — по папці на дату",
    "folders.images": "куди програма зберігає прев’ю відео; підпапки — за шаблоном нижче",
}
SETUP_FOLDER_STATUS: Final[str] = "✓ папка: {path}"
SETUP_FOLDER_BUTTON_CHOOSE: Final[str] = "Вибрати…"
SETUP_FOLDER_BUTTON_DEFAULT: Final[str] = "За замовчуванням"
SETUP_KEYS_BUTTON_RESET_TO_TOKEN: Final[str] = "Повернути значення з токена"
SETUP_KEYS_BUTTON_DELETE_OWN: Final[str] = "Видалити"
SETUP_TOKENS_INTRO: Final[str] = (
    "Токен передає іншій людині те, що задано на цьому комп’ютері як власне. Що ввійде, вирішують повзунки "
    "нижче — по одному на значення, групами за лініями роботи; коли вікно відкривається, усі вимкнені. "
    "Повзунок значення, якого тут немає, блідий. З проєктом Google і каналами YouTube отримувач працює без "
    "входів у браузері. Значень він не бачить. Отримане в чужому токені до нового токена не входить."
)
SETUP_TOKENS_CREATE_TITLE: Final[str] = "Новий токен"
SETUP_TOKENS_CREATE_TEXT: Final[str] = (
    "Токен — один файл (.lctoken): ключ до значень — усередині нього. Передати його можна будь-яким шляхом; "
    "завантажить його будь-хто, у кого він опиниться, тож передавати — лише тому, кому він призначений."
)
SETUP_TOKENS_DAYS_LABEL: Final[str] = "Строк дії, діб:"
SETUP_TOKENS_DAYS_HINT: Final[str] = (
    "до кінця строку токен можна завантажити; завантажені значення працюють і після нього"
)
SETUP_TOKENS_ITEM_LABELS: Final[dict[str, str]] = {
    "google_project": "Проєкт і вхід оператора Google",
    "plan_sheet": "Посилання на таблицю плану",
    "openai_key": "Ключ OpenAI",
    "previews_folder": "Папка прев’ю на Google Диску",
    "docs_folder": "Папка документів на Google Диску",
    "doc_contacts": "Контакти в шапці документа",
    "bot_token": "Токен бота",
    "private_chat": "Чат із ботом",
    "group_chat": "Група з ботом",
    "youtube_channels": "Канали YouTube і входи в них",
    "form_link": "Посилання на форму ключів",
}
SETUP_TOKENS_ITEM_HINTS: Final[dict[str, str]] = {
    "google_project": (
        "Увімкнено — до токена ввійдуть проєкт Google, вибраний на «Головній», і вхід оператора Google, зроблений "
        "через нього. Із входом оператора отримувач без входу в браузері працює з таблицею плану, папками Google "
        "Диска й документами оголошень — і з усім Google Диском акаунта оператора."
    ),
    "group_chat": "Вибір «куди надсилати оголошення» їде разом із чатом, на який він указує.",
    "youtube_channels": (
        "Увімкнено — до токена ввійдуть канали YouTube і входи в них, зроблені через вибраний проєкт Google; канал "
        "без такого входу їде без входу. Отримувач без пароля керує цими каналами на YouTube; входи працюють у "
        "нього, коли в нього вибрано той самий проєкт."
    ),
}
TOKEN_FILE_LABELS: Final[dict[str, str]] = {
    "channels": "канали: {handles}",
    "logins": "входи каналів: {handles}",
    "operator": "вхід оператора Google",
}
SETUP_TOKENS_DAYS_PROBLEM: Final[str] = "строк — ціле число діб від 1 до {maximum}"
SETUP_TOKENS_CONTENTS: Final[str] = "До токена ввійдуть: {items}."
SETUP_TOKENS_NOTHING: Final[str] = "До токена нічого не ввійде: увімкніть повзунки того, що передати."
SETUP_TOKENS_BUTTON_CREATE: Final[str] = "Створити токен"
SETUP_TOKENS_CREATING: Final[str] = "Створюю токен…"
SETUP_TOKENS_CREATED: Final[str] = "✓ Створено токен {token}."
SETUP_TOKENS_VALID_UNTIL: Final[str] = "Завантажити його можна до {until}."
SETUP_TOKENS_INSIDE: Final[str] = "У токені: {items}."
SETUP_TOKENS_WRITE_FAILED: Final[str] = "файл токена не записався: {reason}"
SETUP_TOKENS_LOAD_TITLE: Final[str] = "Отриманий токен"
SETUP_TOKENS_LOAD_TEXT: Final[str] = (
    "Натисніть «Завантажити токен…» і виберіть файл токена (.lctoken). Отримане з токена замінює попереднє "
    "отримане з токена; власне — значення, проєкт Google, канали з власним входом і власний вхід оператора — "
    "лишається головним."
)
SETUP_TOKENS_BUTTON_LOAD: Final[str] = "Завантажити токен…"
SETUP_TOKENS_LOADING: Final[str] = "Завантажую токен…"
SETUP_TOKENS_PICK_TOKEN: Final[str] = "Файл токена Livecraft"
SETUP_TOKENS_LOADED: Final[str] = "✓ Токен завантажено: {items}."
SETUP_TOKENS_LOADED_UNTIL: Final[str] = (
    "Токен діяв до {until}; завантажені значення працюють і після цього строку."
)
SETUP_TOKENS_PROJECT_KEPT: Final[str] = (
    "Проєкт Google {project} з токена збережено в {file}; робочим залишився свій {own} — змінити можна на «Головній»."
)
SETUP_TOKENS_SAVE_FAILED: Final[str] = "значення токена не записалися: {reason}"
SETUP_TOKENS_SETTINGS_FAILED: Final[str] = "налаштування з токена не підійшли: {problem}"
SETUP_TOKENS_INTERRUPTED: Final[str] = "Роботу з токеном перервано — подробиці в журналі."
TOKEN_SETTING_LABELS: Final[dict[str, str]] = {
    "form.url": FORM_URL_LABEL,
    "telegram.target": "куди надсилати оголошення",
    "telegram.group_chat_id": "група з ботом для оголошень",
    "telegram.private_chat_id": "чат із ботом для оголошень",
    "docs.contacts": DOCS_CONTACTS_LABEL,
}
TOKEN_PROBLEM_TEXT: Final[dict[str, str]] = {
    "no_network": (
        "немає зв’язку з Google: час створення й строк токена беруться з відповіді Google — підключіть інтернет і "
        "повторіть"
    ),
    "file_unreadable": "файл не відкривається — його тримає інша програма, немає прав або на його місці папка",
    "not_token": "це не файл токена Livecraft (.lctoken)",
    "version": "токен іншої версії програми — створіть новий токен у цій версії",
    "damaged": "файл токена пошкоджено чи змінено",
    "expired": "строк токена минув — потрібен новий токен",
}
SETUP_KEYS_BUTTON_REVEAL: Final[str] = "показати"
SETUP_KEYS_BUTTON_HIDE: Final[str] = "сховати"
SETUP_KEYS_SAVE_FAILED_OS: Final[str] = (
    "Не вдалося записати файл із введеними значеннями. Перевірте, чи не зайнятий він іншою програмою (антивірус, "
    "синхронізація), і натисніть «Зберегти» ще раз."
)

# --- вкладка «Эфиры YouTube» (§8.2 п.4)
SETUP_CHANNELS_INTRO: Final[str] = (
    "Канали YouTube, на яких Livecraft створює ефіри. На кожен канал програма ставить ефіри мовою його стрімів."
)
SETUP_CHANNEL_FIELD_LABELS: Final[dict[str, str]] = {
    "account_name": "Нік каналу",
    "handle": "Нік каналу",
    "google_account": "Пошта облікового запису Google",
    "languages": "Мова стрімів",
    "privacy": "Видимість стрімів на YouTube",
    "platform": "платформа",
    "channels": "список каналів",
}
SETUP_CHANNEL_FIELD_HINTS: Final[dict[str, str]] = {
    "handle": (
        "як у YouTube, з @, наприклад @Lena. Де взяти: YouTube → аватар угорі праворуч → нік під назвою каналу"
    ),
    "google_account": (
        "пошта облікового запису Google, під яким входять у цей канал, наприклад lena@gmail.com — під час входу "
        "відкриється потрібний обліковий запис"
    ),
    "languages": "якою мовою йдуть ефіри каналу",
    "privacy": (
        "– видимість стримів «для всіх» — ефір бачать усі, підписники отримують сповіщення;\n"
        "– видимість стримів «за посиланням» — ефір бачать лише ті, хто має посилання."
    ),
}
SETUP_CHANNEL_COLUMNS: Final[dict[str, str]] = {
    "handle": "нік",
    "google_account": "пошта Google",
    "languages": "мова стрімів",
    "privacy": "видимість на YouTube",
}
SETUP_PRIVACY_LABELS: Final[dict[str, str]] = {
    "public": "для всіх",
    "unlisted": "за посиланням",
}
SETUP_CHANNELS_BUTTON_ADD: Final[str] = "Додати"
SETUP_CHANNELS_BUTTON_UPDATE: Final[str] = "Змінити вибраний"
SETUP_CHANNELS_BUTTON_REMOVE: Final[str] = "Видалити вибраний"
SETUP_CHANNELS_NOTHING_SELECTED: Final[str] = "Спочатку виберіть канал у таблиці."
SETUP_CHANNELS_SAVE_FAILED: Final[str] = "Не вдалося записати secrets\\channels.json: {error}"
SETUP_LANGUAGE_OPTION: Final[str] = "{name} ({code})"
SETUP_LANGUAGE_OPTION_IN_FORM: Final[str] = "{name} ({code}) — є у формі"
SETUP_LANGUAGE_OPTION_NOT_ISO: Final[str] = "{code} (не код ISO 639-1)"
SETUP_LANGUAGE_OPTION_NOT_ISO_IN_FORM: Final[str] = "{code} (не код ISO 639-1) — є у формі"
SETUP_LANGUAGE_PICK_FROM_LIST: Final[str] = "виберіть мову зі списку"
SETUP_LANGUAGE_SEVERAL: Final[str] = "у каналу кілька мов — після збереження залишиться {name}"
SETUP_LANGUAGE_NOT_IN_FORM: Final[str] = (
    "мови {names} немає серед варіантів Google-форми — ефіри нею не буде допущено"
)

# --- проект Google на вкладке «Дополнительно» (§9, §14 решение 66)
GOOGLE_PROJECT: Final[str] = "проєкт Google {project}"
GOOGLE_PROJECT_UNFIT: Final[str] = "файл проєкту Google, який не годиться"
GOOGLE_CLIENT_ANSWERS: Final[dict[str, str]] = {
    "known": "Google цей клієнт знає",
    "not_known": (
        "Google цей клієнт не знає — клієнта видалено в Google Cloud або секрет у файлі не той; потрібен новий файл "
        "клієнта"
    ),
    "no_network": "перевірити не вдалося: комп’ютер не знаходить сервери Google — немає інтернету",
    "unavailable": "перевірити не вдалося: Google не відповів — «Перевірити» ще раз пізніше",
}
SETUP_CLIENT_TITLE: Final[str] = "Проєкт Google"
SETUP_CLIENT_TEXT: Final[str] = (
    "Через проєкт Google програма входить у Google: оператор — до таблиці плану, Google Диска й документів, "
    "канали — до YouTube. Потрібен файл клієнта (JSON) з Google Cloud Console: Google Auth Platform → Clients → "
    "клієнт типу Desktop app → Download JSON. Завантажте JSON одразу під час створення клієнта — пізніше Google "
    "секрет не покаже. Файл може лежати будь-де й називатися як завгодно: програма запам’ятовує шлях до нього. "
    "Програма працює через вибраний проєкт: вхід, зроблений через інший проєкт, вона робить заново через цей."
)
SETUP_CLIENT_STATUS_SET: Final[str] = "✓ {project} — {path} — {origin}"
SETUP_CLIENT_BUTTON_PICK: Final[str] = "Вибрати файл…"
SETUP_CLIENT_BUTTON_CHECK: Final[str] = "Перевірити"
SETUP_CLIENT_CHECKING: Final[str] = "Перевіряю проєкт Google…"
SETUP_CLIENT_PICK_TITLE: Final[str] = "Файл клієнта проєкту Google (JSON)"
SETUP_CLIENT_INTERRUPTED: Final[str] = "Робота з проєктом Google перервалася — подробиці в журналі."
SETUP_COOKIES_INTRO: Final[str] = (
    "Cookies — файл, який браузер вивантажує після входу в YouTube. Програмі вхід не потрібен: назву, опис, прев’ю "
    "й мову відео вона отримує й без нього. З cookies yt-dlp читає й описи відео 18+. Cookies потрібні лише таблиці "
    "плану; у кожної людини свої, до токена вони не входять."
)
SETUP_COOKIES_HOWTO_TITLE: Final[str] = "Як вивантажити cookies"
SETUP_COOKIES_HOWTO: Final[str] = (
    "1. Вивантажити cookies youtube.com у форматі Netscape розширенням браузера (наприклад, «Get cookies.txt "
    "LOCALLY»).\n"
    "2. Завантажити файл кнопкою «Завантажити файл…».\n"
    "Вивантаження живе кілька днів: браузер оновлює cookies, і YouTube перестає приймати вивантажені — тоді "
    "вивантажити їх заново."
)
SETUP_COOKIES_STATUS_SET: Final[str] = "Файл cookies {path}: вивантажено {date}"
SETUP_COOKIES_STATUS_BAD: Final[str] = "Файл cookies {path}: не формат Netscape — завантажте інший"
SETUP_COOKIES_STATUS_STALE: Final[str] = "Файл cookies {path}: вивантажено {date} — строк нагадування закінчився"
SETUP_COOKIES_LOADED: Final[str] = "Файл завантажено: {path}"
SETUP_COOKIES_BUTTON_LOAD: Final[str] = "Завантажити файл…"
SETUP_COOKIES_BUTTON_CHECK: Final[str] = "Перевірити"
SETUP_COOKIES_CHECKING: Final[str] = "Перевіряю cookies…"
SETUP_COOKIES_PICK_TITLE: Final[str] = "Файл cookies YouTube (Netscape)"
SETUP_COOKIES_TEXT_FILES: Final[str] = "Текстові файли"
SETUP_COOKIES_ALL_FILES: Final[str] = "Усі файли"
SETUP_COOKIES_INTERRUPTED: Final[str] = "Перевірка cookies перервалася — подробиці в журналі."
SETUP_TOOLS_INSTALLING: Final[str] = "Немає {tools} у теці tools — триває завантаження, зачекайте…"
SETUP_TOOLS_VERSION: Final[str] = "{tool} {version}"
SETUP_TOOLS_DONE: Final[str] = "Завантажено: {versions}."
SETUP_TOOLS_FAILED: Final[str] = "{tool} не завантажено — {reason}.\nЙого завантажить запуск."
SETUP_TOOLS_INTERRUPTED: Final[str] = "Завантаження yt-dlp і deno перервалося — подробиці в журналі; їх завантажить запуск."
SETUP_CLIENT_UNREADABLE: Final[str] = "файл не читається: {reason}"
SETUP_CLIENT_NOT_DESKTOP: Final[str] = "файл — не клієнт проєкту Google типу Desktop; його не вибрано"
SETUP_CLIENT_WRITE_FAILED: Final[str] = "шлях до файлу проєкту Google не записався в налаштування: {reason}"
SETUP_CLIENT_CHOSEN: Final[str] = "✓ Вибрано {project}."
SETUP_CLIENT_ANSWER: Final[str] = "{project}: {answer}"
SETUP_CLIENT_WHO_OPERATOR: Final[str] = "вхід оператора"
SETUP_CLIENT_WHO_CHANNELS: Final[str] = "канали {handles}"
SETUP_CLIENT_WHO_JOINER: Final[str] = " і "
SETUP_CLIENT_LOGINS_THIS: Final[str] = "{who} — через цей проєкт"
SETUP_CLIENT_LOGINS_OTHER: Final[str] = (
    "{who} — через інший проєкт: під час запуску програма увійде заново через цей проєкт"
)
SETUP_CLIENT_LOGINS_RELOGIN: Final[str] = (
    "; увійти в канал через цей — кнопкою «Увійти у вибраний канал» на вкладці «Ефіри YouTube»"
)

# --- настройки livecraft.json на вкладках линий и «Дополнительно» (§8.2 п.6)
SETUP_ADVANCED_INTRO: Final[str] = (
    "Часовий пояс програми й строк зберігання старих файлів потрібні за будь-яких ліній роботи; решта "
    "налаштувань — на вкладках ліній. Типові значення підходять — змінюйте, лише якщо знаєте навіщо."
)
SETUP_SETTINGS_FIELD_LABELS: Final[dict[str, str]] = {
    "min_lead_minutes": "мінімальний запас до початку ефіру (хвилин)",
    "keep_days": "зберігати старі файли програми (днів)",
    "auto_start": "ефір починається сам, коли пішов відеопотік",
    "set_thumbnail": "ставити обкладинку ефіру",
    "category_id": "категорія відео на YouTube",
    "youtube_pause_seconds": "пауза між зверненнями до YouTube (секунд)",
    "image_dir_template": "шаблон підпапок прев’ю",
    "timezone": "часовий пояс",
    "llm.model": "модель OpenAI",
    "llm.fallback_model": "запасна модель OpenAI",
    "llm.reasoning_effort": "глибина міркувань моделі",
    "llm.service_tier": "тариф OpenAI",
    "llm.timeout_sec": "скільки чекати на відповідь моделі (секунд)",
    "llm.max_output_tokens": "найбільша довжина відповіді моделі (токенів)",
    "drive.preview_path_template": "шаблон підпапок прев’ю на Google Диску",
    "docs.access": "доступ до документа оголошень за посиланням",
    "docs.contacts": DOCS_CONTACTS_LABEL,
    "cookies.remind_days": "нагадати вивантажити cookies заново через (днів)",
}
SETUP_SETTINGS_FIELD_HINTS: Final[dict[str, str]] = {
    "category_id": (
        "номер категорії YouTube: 22 — «Люди та блоги», 24 — «Розваги», 25 — «Новини та політика», "
        "27 — «Освіта»"
    ),
    "image_dir_template": (
        "шаблон підпапки всередині папки прев’ю: замість {date} програма підставить дату ефіру, замість {language} — "
        "мову. {date}/{language} дає image\\23-09-2026\\uk"
    ),
    "youtube_pause_seconds": "скільки чекати між зверненнями до YouTube; 0.5 — зазвичай достатньо",
    "llm.model": "модель OpenAI для текстів ефіру; ціна — за 1 млн токенів: вхід / вихід, тариф flex — удвічі дешевше",
    "llm.fallback_model": "якщо основна модель недоступна; ціна — за 1 млн токенів: вхід / вихід, тариф flex — удвічі дешевше",
    "llm.service_tier": "flex — дешевше й повільніше, default — звичайний",
    "timezone": "Europe/Kyiv — київський час",
    "drive.preview_path_template": (
        "шаблон підпапки прев’ю всередині папки Google Диска для прев’ю: замість {date} програма підставить "
        "дату ефіру, замість {language} — мову. preview/{date}/{language} дає preview\\28-09-2026\\uk"
    ),
    "docs.access": "кому відкрито документ оголошень за посиланням на нього",
    "docs.contacts": (
        "рядок «Contact:» у шапці документа оголошень, наприклад @nick або адреса пошти; порожньо — блоку "
        "контактів немає"
    ),
    "cookies.remind_days": "вивантаження cookies живе кілька днів; 7 — зазвичай досить",
}
# Модель OpenAI у випадному списку (app\setup\fields\settings_draft.py): {input}, {output} — долари за 1 млн токенів.
SETUP_LLM_MODEL_OPTION: Final[str] = "{model} — ${input:.2f} / ${output:.2f} за 1 млн токенів"
SETUP_DOC_ACCESS_LABELS: Final[dict[str, str]] = {
    "private": "лише тим, кому документ відкрито на Диску",
    "reader": "усі за посиланням — лише читання",
    "commenter": "усі за посиланням — коментарі",
    "writer": "усі за посиланням — редагування",
}
SETUP_SETTINGS_SAVE_FAILED: Final[str] = "Не вдалося записати secrets\\livecraft.json: {error}"

# --- вкладка «Логи» (§8.2 п.11, §14 решения 20, 46, 62)
SETUP_LOGS_INTRO: Final[str] = (
    "«Зберегти архів логів» кладе в теку logs архів: файли цієї теки, нові першими, до {limit} МБ, і "
    "diagnostics.txt — версія програми, система й готовність ліній, без ключів і посилань. Не входять ніколи: "
    "secrets, keystreams, tokens. Після запису відкривається тека logs із виділеним архівом — його можна "
    "надіслати тому, хто допомагає з програмою."
)
SETUP_LOGS_BUTTON_SAVE: Final[str] = "Зберегти архів логів"
SETUP_LOGS_WORKING: Final[str] = "Збираю архів логів…"
SETUP_LOGS_INTERRUPTED: Final[str] = "Збереження архіву логів перервалося — подробиці в журналі."
SETUP_LOGS_SAVED: Final[str] = "Архів логів збережено: {path} (файлів {files}, {megabytes:.1f} МБ)."
SETUP_LOGS_NOT_SAVED: Final[str] = "Архів логів не зберігся в теку logs: {reason}"
SETUP_LOGS_SKIPPED: Final[str] = "Старі файли логів не ввійшли в архів — межа {limit} МБ: {count}."

# --- вкладка «Telegram» (§8.2 п.3, §14 решения 19, 20)
SETUP_TELEGRAM_INTRO: Final[str] = (
    "Перед ефірами Livecraft надсилає оголошення — назву, опис, прев’ю й час ефіру — у Telegram від імені бота: у чат "
    "із ботом або в групу з ботом. Налаштування — три кроки."
)
SETUP_TELEGRAM_STEP_1_TITLE: Final[str] = "Крок 1. Бот"
SETUP_TELEGRAM_STEP_1_TEXT: Final[str] = (
    "Немає свого бота в Telegram — створіть його: знайдіть @BotFather, надішліть йому /newbot і придумайте ім’я — "
    "BotFather надішле токен. Вставте токен бота сюди й натисніть «Зберегти»."
)
SETUP_TELEGRAM_STEP_2_TITLE: Final[str] = "Крок 2. Чат"
SETUP_TELEGRAM_STEP_2_TEXT: Final[str] = (
    "Чат із ботом: відкрийте бота в Telegram і натисніть «Почати» (або надішліть /start). Група з ботом: додайте бота "
    "до групи й надішліть у ній /start@ім’я_бота — звичайні повідомлення групи бот не бачить."
)
SETUP_TELEGRAM_STEP_3_TITLE: Final[str] = "Крок 3. Підключення"
SETUP_TELEGRAM_STEP_3_TEXT: Final[str] = (
    "Натисніть кнопку підключення біля чату з ботом або біля групи з ботом — програма знайде чат, запам’ятає й надішле "
    "туди пробне повідомлення. Оголошення надходять в один чат — вибір нижче."
)
SETUP_TELEGRAM_BUTTON_OPEN_BOT: Final[str] = "Відкрити бота в Telegram"
SETUP_TELEGRAM_BOT_READY: Final[str] = "✓ бот «{name}» @{username}"
SETUP_TELEGRAM_TARGET_TITLES: Final[dict[str, str]] = {
    "private": "Чат із ботом",
    "group": "Група з ботом",
}
SETUP_TELEGRAM_TARGET_CONNECT: Final[dict[str, str]] = {
    "private": "Підключити чат із ботом",
    "group": "Підключити групу з ботом",
}
SETUP_TELEGRAM_TARGET_RECONNECT: Final[dict[str, str]] = {
    "private": "Підключити інший чат із ботом",
    "group": "Підключити іншу (нову) групу з ботом",
}
SETUP_TELEGRAM_TARGET_HINTS: Final[dict[str, str]] = {
    "group": (
        "Спершу додайте бота @{username} до групи й надішліть у ній /start@{username}, потім натисніть «Підключити "
        "групу з ботом»."
    ),
}
SETUP_TELEGRAM_TARGET_HINTS_UNNAMED: Final[dict[str, str]] = {
    "group": (
        "Спершу додайте бота до групи й надішліть у ній /start@ім’я_бота, потім натисніть «Підключити групу з ботом»."
    ),
}
SETUP_TELEGRAM_TARGET_CHOOSE: Final[dict[str, str]] = {
    "private": "Бот бачить кілька чатів із ботом — натисніть у списку на свій.",
    "group": "Бот бачить кілька груп — натисніть у списку на потрібну.",
}
SETUP_TELEGRAM_TARGET_NO_CHATS: Final[dict[str, str]] = {
    "private": (
        "Бот @{username} поки не бачить жодного чату з ботом: відкрийте його в Telegram (кнопка «Відкрити бота в "
        "Telegram»), натисніть «Почати», потім ще раз «{button}»."
    ),
    "group": (
        "Бот @{username} поки не бачить жодної групи: додайте його до групи, надішліть у ній /start@{username}, потім "
        "ще раз «{button}»."
    ),
}
SETUP_TELEGRAM_CHAT_CONNECTED: Final[str] = "підключено: {chat}"
SETUP_TELEGRAM_CHAT_NOT_CONNECTED: Final[str] = "не підключено"
SETUP_TELEGRAM_CHAT_BY_ID: Final[str] = "id {chat_id}"
SETUP_TELEGRAM_TARGET_CHOICE: Final[str] = "Куди надсилати оголошення:"
SETUP_TELEGRAM_TARGET_LABELS: Final[dict[str, str]] = {
    "private": "у чат із ботом",
    "group": "у групу з ботом",
}
SETUP_TELEGRAM_TARGETS_INTO: Final[dict[str, str]] = {
    "private": "чат із ботом",
    "group": "групу з ботом",
}
SETUP_TELEGRAM_DESTINATION_NOW: Final[str] = "Зараз оголошення йдуть у {destination}."
SETUP_TELEGRAM_DESTINATION_NONE: Final[str] = (
    "Оголошенням поки нікуди йти: підключіть чат із ботом або групу з ботом."
)
SETUP_TELEGRAM_DESTINATION_BY_ID: Final[str] = "{into} (id {chat_id})"
SETUP_TELEGRAM_DESTINATION_BY_TITLE: Final[str] = "{into} «{title}»"
SETUP_TELEGRAM_STEP_1_FIRST: Final[str] = "Спочатку крок 1: вставте токен бота й натисніть «Зберегти»."
SETUP_TELEGRAM_CHAT_OPTION: Final[str] = "{kind}: {title} (id {chat_id})"
TELEGRAM_CHAT_KINDS: Final[dict[str, str]] = {
    "private": "особистий чат",
    "group": "група",
    "supergroup": "супергрупа",
    "channel": "канал",
}
SETUP_TELEGRAM_TEST_TEXT: Final[str] = "Livecraft: пробне повідомлення. Сюди надходять оголошення про ефіри."
SETUP_TELEGRAM_BUTTON_CHECK: Final[str] = "Перевірити"
SETUP_TELEGRAM_CHECKED: Final[str] = "пробне повідомлення дійшло в {destination}"
TELEGRAM_CHAT_MIGRATED: Final[str] = "Група стала супергрупою: її новий id {new_chat_id} записано замість {old_chat_id}."
SETUP_TELEGRAM_NOTICE_UNREADABLE: Final[str] = (
    "Файл secrets\\livecraft.json не прочитався: {key} — {problem}. Підключення чату запише його заново, а решта "
    "налаштувань у ньому матиме типові значення програми."
)

# --- Telegram (app\publish\telegram_bot.py)
TELEGRAM_PROBLEMS: Final[dict[str, str]] = {
    "bad_token": (
        "Telegram не прийняв токен бота: перевірте токен бота на вкладці «Telegram»."
    ),
    "chat_not_found": (
        "Telegram не знає такого чату: напишіть боту в цей чат і підключіть чат заново на вкладці «Telegram»."
    ),
    "forbidden": "Боту заборонено писати в цей чат: бота видалено з групи або заблоковано в особистих — поверніть його.",
    "other_poller": "Бота опитує інша програма (наприклад, restreamer) — зупиніть її й повторіть.",
    "webhook": (
        "У бота задано webhook: повідомлення боту забирає інша програма, і чати не видно. Зніміть webhook "
        "(deleteWebhook) або зупиніть ту програму, потім повторіть."
    ),
    "rate_limited": "Telegram просить зачекати: забагато повідомлень поспіль. Повторіть за хвилину.",
    "network": "Немає зв’язку з Telegram: перевірте інтернет і повторіть.",
    "server": "Сервер Telegram зараз не відповідає — повторіть пізніше.",
    "rejected": "Telegram відмовив: {description}",
}

# --- план из таблицы (app\sheets\)
SHEET_ROW_SKIP_REASONS: Final[dict[str, str]] = {
    "empty_link": "немає посилання на відео",
    "missing_date_time": "не заповнено дату або час",
    "bad_date_time": "дату або час не розпізнано",
    "nonexistent_time": "такого часу немає: цієї ночі годинники переводять уперед на літній час",
    "in_past": "час ефіру вже минув",
    "bad_link": "у посиланні не знайдено відео YouTube",
    "duplicate": "повтор: те саме посилання на той самий час уже є в таблиці вище",
}
SHEET_PLAN_COLUMN_NAMES: Final[dict[str, str]] = {
    "link": "посилання",
    "date": "дата",
    "time": "час",
}
SHEET_PLAN_HEADER_UNKNOWN: Final[str] = (
    "На жодному аркуші таблиці в першому рядку немає всіх трьох стовпців: посилання, дата, час. Найближче аркуш "
    "«{sheet}» — бракує: {missing}. Заголовки цього аркуша: {headers}."
)
SHEET_PLAN_HEADER_NONE: Final[str] = "жодного"

# --- вход в Google (app\google\auth.py)
AUTH_OPEN_LINK: Final[str] = "Якщо браузер не відкрився — відкрийте посилання: {url}"
AUTH_BROWSER_DONE: Final[str] = "Вхід виконано. Поверніться до вікна Livecraft."
AUTH_REASON_TEXT: Final[dict[str, str]] = {
    "client_secret_missing": (
        "проєкт Google не вибрано, його файл не знайдено або він не придатний — «Livecraft — налаштування», "
        "вкладка «Головна»"
    ),
    "token_unreadable": "файл входу в Google не читається; видаліть його й увійдіть знову",
    "token_unwritable": (
        "файл входу в Google не вдається записати або видалити — перевірте, що папка програми доступна "
        "для запису і файл не зайнятий іншою програмою"
    ),
    "flow_failed": "браузер не повернув дозвіл",
    "refresh_failed": "не вдалося оновити вхід (немає зв’язку з Google)",
    "login_required": "потрібен вхід у Google: входу ще не було або його відкликано",
    "login_timeout": (
        "вхід не завершено за {minutes} хвилин — браузер закрито або обліковий запис не вибрано; "
        "під час наступного запуску програма знову запропонує вхід"
    ),
    "scopes_not_granted": (
        "у вікні входу Google позначено не всі дозволи, які просить програма, — без них вхід не приймається; "
        "повторіть вхід і позначте всі дозволи"
    ),
    "other_project": "вхід зроблено через інший проєкт Google — потрібен вхід через вибраний",
}

# --- чтение таблицы плана (app\sheets\client.py)
SHEETS_READ_FAILED: Final[str] = "Таблиця плану {label} не прочиталася: {reason}."
SHEETS_READ_FAILED_STATUS: Final[str] = "Таблиця плану {label} не прочиталася: {reason} (код відповіді {status})."
SHEETS_WRITE_FAILED: Final[str] = (
    "Таблиця плану {label}: мову відео, посилання на прев’ю й посилання на відео не записано: {reason}."
)
SHEETS_WRITE_FAILED_STATUS: Final[str] = (
    "Таблиця плану {label}: мову відео, посилання на прев’ю й посилання на відео не записано: {reason} "
    "(код відповіді {status})."
)
GOOGLE_NO_NETWORK_TEXT: Final[str] = (
    "комп’ютер не знаходить сервери Google — немає інтернету або зв’язок із перебоями; запустіть ще раз, коли "
    "зв’язок з’явиться"
)
SHEETS_READ_REASON_TEXT: Final[dict[str, str]] = {
    "not_configured": "не задано посилання на таблицю — «Livecraft — налаштування», вкладка «Таблиця плану»",
    "auth": "не вдалося увійти в Google — {detail}",
    "no_access": "немає доступу — відкрийте таблицю обліковому запису Google, під яким увійшли",
    "account_refused": (
        "обліковому запису {detail} таблицю не відкрито — увійдіть обліковим записом, якому її відкрито, або "
        "попросіть власника таблиці відкрити її цьому обліковому запису"
    ),
    "not_found": "такої таблиці немає — перевірте посилання на таблицю в налаштуваннях",
    "bad_range": "Google не прийняв запит до таблиці — перевірте посилання на таблицю",
    "rejected": "Google відмовив у читанні",
    "unavailable": "Google не відповів і після повторів — перевірте зв’язок і запустіть ще раз",
    "no_network": GOOGLE_NO_NETWORK_TEXT,
}

SHEETS_LOGIN_BROWSER: Final[str] = (
    "Потрібен вхід у Google для таблиці плану й Google Диска — зараз відкриється браузер.\n"
    "Увійдіть обліковим записом Google, якому відкрито таблицю плану (не записом каналу),\n"
    "і позначте всі дозволи."
)
SHEETS_LOGIN_OTHER_PROJECT: Final[str] = (
    "Вхід у Google зроблено через інший проєкт Google — потрібен вхід через вибраний.\n"
    "Зараз відкриється браузер: увійдіть обліковим записом Google, якому відкрито таблицю\n"
    "плану, і позначте всі дозволи."
)
OPERATOR_LOGGED_IN: Final[str] = "Вхід у Google: {account}"
OPERATOR_ACCESS_REFUSED: Final[str] = (
    "Обліковому запису Google {account} таблицю плану не відкрито — потрібен вхід обліковим записом, якому її "
    "відкрито."
)
OPERATOR_ACCOUNT_UNKNOWN: Final[str] = "(пошту не визначено)"

DRIVE_FAILED: Final[str] = "Google Диск: {reason}."
DRIVE_FAILED_STATUS: Final[str] = "Google Диск: {reason} (код відповіді {status})."
DRIVE_REASON_TEXT: Final[dict[str, str]] = {
    "auth": "не вдалося увійти в Google — {detail}",
    "no_access": "немає доступу до папки — відкрийте її обліковому запису Google, під яким увійшли, з правом редактора",
    "not_found": (
        "такої папки немає або її не видно обліковому запису, під яким увійшли, — перевірте посилання на папку в "
        "налаштуваннях"
    ),
    "bad_request": "Google не прийняв запит — перевірте посилання на папку в налаштуваннях",
    "rejected": "Google відмовив",
    "unavailable": "Google не відповів і після повторів — перевірте зв’язок і запустіть ще раз",
    "unknown": (
        "Google не відповів, чи виконано дію, — повтор міг би її задвоїти; незакінчене нікуди не йде, "
        "досить запустити ще раз"
    ),
    "not_configured": "папку не задано — вставте посилання на неї вище й натисніть «Зберегти»",
    "no_network": GOOGLE_NO_NETWORK_TEXT,
}

DOCS_FAILED: Final[str] = "Google Docs: {reason}{status}."
DOCS_FAILED_STATUS: Final[str] = " (код відповіді {status})"
DOCS_REASON_TEXT: Final[dict[str, str]] = {
    "auth": "не вдалося увійти в Google — {detail}",
    "no_access": (
        "немає доступу до документа — потрібен вхід обліковим записом Google, якому відкрито папку документів"
    ),
    "not_found": "документ не знайдено",
    "bad_request": "Google Docs не прийняв запит — подробиці в журналі",
    "rejected": "Google Docs відмовив",
    "unavailable": "Google Docs не відповів і після повторів — перевірте зв’язок і запустіть ще раз",
    "unknown": (
        "Google Docs не відповів, чи виконано правку, — повтор міг би задвоїти текст; незакінчений документ "
        "нікуди не йде, досить запустити ще раз"
    ),
    "no_network": GOOGLE_NO_NETWORK_TEXT,
}
DOC_HEADER: Final[str] = "Документи оголошень — {count}:"
DOC_HEADER_WITH_COPIES: Final[str] = "Документи оголошень: {count}, копії .docx — у папці {folder}:"
DOC_DAY_LINE: Final[str] = "{date} — прев’ю {placed} з {total}"
DOC_LINK_ITEM: Final[str] = "{date} — {url}"
DOC_DRY_RUN_LINE: Final[str] = "Документ оголошень: пробний запуск — документ не створюється."
DOC_FAILED_LINE: Final[str] = "Документ оголошень на {date} не готовий — {reason}"
DOC_SKIPPED_LINE: Final[str] = "Документи наступних дат ({count}) не створювалися."
DOC_COPY_NOT_SAVED: Final[str] = "; копію .docx не збережено — {reason}"
DOC_COPY_SHOWN: Final[str] = " — копія {path}"
DOC_COPY_WRITE_FAILED: Final[str] = "файл не записано: {reason}."

ANNOUNCE_SENT_TO: Final[str] = "Оголошення в Telegram надіслано в {destination}:"
ANNOUNCE_NOT_SENT: Final[str] = "Оголошення в Telegram не надіслано в {destination}."
ANNOUNCE_DAY_LINE: Final[str] = "{date} — ефірів {slots}, прев’ю {previews}"
ANNOUNCE_PACKAGE_LINE: Final[str] = "пакет {name}"
ANNOUNCE_FAILED_LINE: Final[str] = "Оголошення на {date} надіслано не до кінця — {reason}"
ANNOUNCE_PACKAGE_FAILED_LINE: Final[str] = "Пакет не надіслано в Telegram — {reason}"
ANNOUNCE_SKIPPED_LINE: Final[str] = "Оголошення наступних дат ({count}) не надсилалися."
ANNOUNCE_DRY_RUN_LINE: Final[str] = "Оголошення в Telegram: пробний запуск — нічого не надсилається."

# --- пробник чтения таблицы (app\tools\sheets_probe.py)
SHEETS_PROBE_TITLE: Final[str] = "Перевірка читання таблиці плану"
SHEETS_PROBE_LOGIN: Final[str] = SHEETS_LOGIN_BROWSER
SHEETS_PROBE_COLUMNS: Final[str] = "Аркуш «{sheet}». Стовпці: посилання — {link}, дата — {date}, час — {time}."
SHEETS_PROBE_COLUMN: Final[str] = "«{name}» (стовпець {letters})"
SHEETS_PROBE_ROWS: Final[str] = "Рядків прочитано: {rows}, допущено: {admitted}, відсіяно: {skipped}."
SHEETS_PROBE_SKIP_LINE: Final[str] = "  {name}: {count}"
SHEETS_PROBE_RELOGIN_HELP: Final[str] = "увійти в Google заново в браузері й вибрати інший обліковий запис"
SHEETS_PROBE_RELOGIN_HINT: Final[str] = (
    "Увійшли не тим обліковим записом? Запустіть із --relogin і виберіть обліковий запис, який має доступ до таблиці."
)

# --- источники (app\sources\)
SOURCE_FAILURE_REASONS: Final[dict[str, str]] = {
    "tool_missing": "немає програми yt-dlp.exe в папці tools — запустіть знову з робочим інтернетом: програма завантажить її",
    "private": "відео приватне — відкрийте до нього доступ за посиланням або замініть посилання в таблиці",
    "age": "відео 18+: YouTube просить увійти — завантажте cookies акаунта 18+ на вкладці «Cookies YouTube»",
    "bot": "YouTube просить підтвердити, що запит не від бота — запустіть знову пізніше",
    "unavailable": "відео видалене або заблоковане — замініть посилання в таблиці",
    "timeout": "yt-dlp не відповів вчасно — запустіть знову",
    "bad_output": "yt-dlp повернув відповідь, яку не вдається розібрати — запустіть знову",
    "no_title": "у відео немає назви — замініть посилання в таблиці",
    "failed": "yt-dlp не зміг отримати дані відео — запустіть знову; подробиці в журналі",
    "no_language": "мову відео не визначено ні за даними YouTube, ні за назвою — замініть посилання в таблиці",
}
SOURCE_FAILURE_NAMES: Final[dict[str, str]] = {
    "tool_missing": "немає yt-dlp",
    "private": "приватне",
    "age": "18+",
    "bot": "перевірка на бота",
    "unavailable": "видалене",
    "timeout": "yt-dlp не відповів",
    "bad_output": "відповідь yt-dlp не розібрано",
    "no_title": "немає назви",
    "failed": "збій yt-dlp",
    "no_language": "мову не визначено",
}
PREVIEW_PROBLEMS: Final[dict[str, str]] = {
    "no_url": "джерело не дало адреси прев’ю",
    "not_found": "прев’ю за адресою немає",
    "rejected": "сервер прев’ю відмовив у завантаженні",
    "unavailable": "прев’ю не завантажилося і після повторів",
    "not_image": "завантажений файл — не зображення",
    "too_large": "прев’ю більше за 2 МБ і після стиснення",
}

# --- ефіри за планом (app\slots\)
SLOT_PROBLEMS: Final[dict[str, str]] = {
    "empty_title": "Назва ефіру порожня після припасування до правил YouTube — ефір далі не йде.",
}

# --- пакет plan_*.bcast (app\packages\)
PACKAGE_PROBLEMS: Final[dict[str, str]] = {
    "no_slots": "у запуску немає придатних ефірів — записувати нічого",
    "form_not_configured": (
        "не задано посилання на форму ключів — задайте посилання на форму в налаштуваннях, "
        "вкладка «Форма»"
    ),
}
PACKAGE_WRITTEN: Final[str] = "Пакет записано — ефірів {slots}, прев’ю {previews}:"
PACKAGE_NOT_WRITTEN: Final[str] = "Пакет не записано: {reason}."
# Чтение пакетов bcast\ — режим Б (app\packages\package_file.py, package_shelf.py, package_drop.py).
PACKAGE_REASON_WITH_DETAIL: Final[str] = "{reason} ({detail})"
PACKAGE_LINE_TEMPLATES: Final[dict[str, str]] = {
    "accepted": "{file} — прийнято, ефірів {total}, з них мовами каналів {mine}",
    "damaged": "{file} — пакет пошкоджено: {detail}; файл не змінено",
    "unsupported_schema": "{file} — версія пакета {detail} не підтримується (потрібна {supported}); файл не змінено",
    "all_past": "{file} — усі ефіри в минулому, з нього нічого не плануватиметься",
}
PACKAGE_REASON_TEXT: Final[dict[str, str]] = {
    "not_zip": "не ZIP-архів",
    "no_manifest": "немає manifest.json",
    "bad_json": "manifest.json не читається",
    "unsupported_schema": "невідома версія пакета",
    "missing_key": "у маніфесті немає обов’язкового поля",
    "bad_value": "хибне значення в маніфесті",
    "duplicate_slot": "slot_id повторюється",
    "preview_missing": "в архіві немає файлу прев’ю",
    "preview_not_image": "файл прев’ю в архіві — не зображення",
}
SHELF_PACKAGE_ACCEPTED: Final[str] = "{file} — прийнято, майбутніх ефірів {slots}"
SHELF_SUMMARY: Final[str] = "Пакети в {path}: файлів {packages}, майбутніх ефірів {slots} (список — у звіті)."
BCAST_EMPTY: Final[str] = "У {path} немає пакетів *.bcast — збережіть туди пакет від оператора і запустіть знову."
BCAST_NO_FUTURE_SLOTS: Final[str] = (
    "У пакетах {path} немає майбутніх ефірів — збережіть туди свіжий пакет від оператора і "
    "запустіть знову."
)
PACKAGE_DROP_COPIED: Final[str] = "Пакет скопійовано: {path}."
PACKAGE_DROP_IN_PLACE: Final[str] = "Пакет уже на місці: {path}."
PACKAGE_DROP_NO_SETTINGS: Final[str] = (
    "Пакет {file} не скопійовано: налаштування програми не прочитано — папка пакетів невідома."
)
PACKAGE_DROP_PROBLEMS: Final[dict[str, str]] = {
    "not_package": "Файл {path} — не пакет .bcast: відкрити можна лише пакет *.bcast.",
    "missing": "Файлу {path} немає — пакет не відкрито.",
}

# --- форма ключів (app\form\)
FORM_PROBLEMS: Final[dict[str, str]] = {
    "structure_unreadable": "Форму ключів «{form}» не прочитано: на сторінці не знайшлося питань форми{detail}.",
    "missing_option": (
        "У формі ключів «{form}» немає потрібного варіанта відповіді{detail} — попросіть власника форми додати його."
    ),
    "required_missing": "У формі ключів «{form}» лишилися обов'язкові питання без відповіді{detail}.",
    "transport_failed": "Форма ключів «{form}» недоступна{detail}.",
    "not_confirmed": "Форма ключів «{form}» не підтвердила запис відповіді{detail}.",
}
FORM_PROBLEM_DETAIL: Final[str] = " ({detail})"
FORM_STATUS_DETAIL: Final[str] = "код відповіді {status}"
FORM_DATES_OK: Final[str] = (
    "Форма ключів «{form}»: усі дати запуску в ній є — потрібно {wanted}, форма приймає {accepted}."
)
FORM_DATES_ANY: Final[str] = "Форма ключів «{form}»: дата вводиться текстом — підходить будь-яка."
FORM_DATES_MISSING: Final[str] = (
    "Форма ключів «{form}»: немає дат {dates} — ефіри на ці дати не створюються, ключі стримеру не підуть."
)

# --- пам'ять програми (app\records\)
RECORDS_BROKEN: Final[str] = (
    "Пам'ять програми {path} не читалася — файл перейменовано на {renamed}, створено нову; "
    "ефіри з міткою програми записано як уже передані стримеру."
)
RECORDS_BROKEN_READ_ONLY: Final[str] = (
    "Пам'ять програми {path} не читається — у цьому режимі програма працює без неї; звичайний запуск створить нову."
)
RECORDS_WRITE_FAILED: Final[str] = (
    "Пам'ять програми {path} не записується ({error}) — робота триває, але підтверджень цього запуску "
    "наступний запуск не побачить і може надіслати ключі повторно."
)

# --- майданчик YouTube (app\platforms\)
_YOUTUBE_RATE_LIMIT_TEXT: Final[str] = (
    "YouTube відхилив надто часті запити, повтори не допомогли — запустіть програму пізніше "
    "або збільште паузу між зверненнями до YouTube на вкладці «Ефіри YouTube» налаштувальника"
)
_YOUTUBE_ACCESS_TEXT: Final[str] = (
    "доступ до каналу відкликано або недостатній — увійдіть у канал заново: .\\livecraft.bat --auth \"@нік каналу\""
)
_YOUTUBE_CLOSED_TEXT: Final[str] = "канал або обліковий запис закрито на YouTube"
_YOUTUBE_SUSPENDED_TEXT: Final[str] = "канал або обліковий запис заблоковано YouTube"
YOUTUBE_REASON_TEXT: Final[dict[str, str]] = {
    "quotaExceeded": (
        "вичерпано добову квоту YouTube API (одна на проєкт Google — на всі канали); решту звернень до YouTube "
        "у цьому запуску не робили; квота оновлюється близько 10:00 за Києвом — запустіть програму після цього"
    ),
    "rateLimitExceeded": _YOUTUBE_RATE_LIMIT_TEXT,
    "userRateLimitExceeded": _YOUTUBE_RATE_LIMIT_TEXT,
    "userRequestsExceedRateLimit": _YOUTUBE_RATE_LIMIT_TEXT,
    "liveStreamingNotEnabled": (
        "на каналі не ввімкнено прямі трансляції — увімкніть їх у Студії (YouTube вмикає до 24 годин)"
    ),
    "livePermissionBlocked": "YouTube заборонив трансляції на каналі — причину вказано в Студії",
    "insufficientLivePermissions": "обліковий запис не може створювати трансляції на цьому каналі",
    "userBroadcastsExceedLimit": (
        "на каналі забагато запланованих ефірів, YouTube не дає створити нові — видаліть зайві в Студії"
    ),
    "authError": _YOUTUBE_ACCESS_TEXT,
    "insufficientPermissions": _YOUTUBE_ACCESS_TEXT,
    "channelClosed": _YOUTUBE_CLOSED_TEXT,
    "authenticatedUserAccountClosed": _YOUTUBE_CLOSED_TEXT,
    "channelSuspended": _YOUTUBE_SUSPENDED_TEXT,
    "authenticatedUserAccountSuspended": _YOUTUBE_SUSPENDED_TEXT,
    "authenticatedUserNotChannel": "в облікового запису немає каналу YouTube — під час входу виберіть канал",
    "channelNotFound": "в облікового запису немає каналу YouTube — під час входу виберіть канал",
    "videoNotFound": "ефір не знайдено на YouTube — можливо, його видалено під час запуску",
    "notListed": (
        "YouTube не віддав ефір або потік за його id і після повторів — після запису майданчик іноді відстає; "
        "наступний запуск прочитає його знову"
    ),
    "invalidScheduledStartTime": "YouTube не прийняв час старту ефіру",
    "transportFailed": (
        "YouTube недоступний (мережа або збій на боці YouTube), повтори не допомогли — запустіть програму пізніше"
    ),
    "authFailed": "вхід у канал не вдався — увійдіть у канал заново: .\\livecraft.bat --auth \"@нік каналу\"",
    "loginRequired": "потрібен вхід у канал у браузері — увійдіть у канал: .\\livecraft.bat --auth \"@нік каналу\"",
    "badResponse": "YouTube надіслав відповідь, яку програма не розібрала; наступний запуск запитає знову",
    "unexpectedStreamKeyFormat": (
        "YouTube видав ключ потоку незвичного вигляду — ефір не зараховано, ключ стримеру не пішов; "
        "наступний запуск створить потік заново"
    ),
    "unknown": "YouTube відмовив, не назвавши причини; наступний запуск запитає знову",
}
YOUTUBE_REASON_UNKNOWN: Final[str] = "YouTube відмовив ({code}); наступний запуск запитає знову"
STREAM_DESCRIPTION: Final[str] = (
    "Ключ Livecraft: канал «{account_name}» {handle}, ефір {date} {time}, мова {language}; "
    "записано програмою {written_at}"
)
STREAM_DESCRIPTION_PLACEHOLDER: Final[str] = "; заглушка обкладинки {token}"

# --- канали YouTube (app\platforms\channel*.py, verified.py): вхід у канал, перевірка нік → id → назва,
# вирівнювання за id YouTube і паспорт каналів (§6 інваріант 5, §14 рішення 25).
AUTH_STARTING: Final[str] = (
    "Канал «{account_name}» {handle}: потрібен вхід у Google — {reason}. Зараз відкриється браузер."
)
# Почему каналу нужен вход — по значениям LoginNeed (app\platforms\channel.py).
AUTH_LOGIN_NEEDS: Final[dict[str, str]] = {
    "no_token": "токена каналу ще немає — перший вхід",
    "token_revoked": "Google більше не приймає токен каналу",
    "foreign_token": "попередній токен вів на інший канал і його видалено",
    "forced": "вхід заново за --auth",
    "other_project": "вхід каналу зроблено через інший проєкт Google — вхід через вибраний",
}
AUTH_CHOOSE_ACCOUNT: Final[str] = (
    "Увійдіть в акаунт Google {google_account} — це акаунт каналу «{account_name}» {handle}."
)
AUTH_CHOOSE_RIGHT_CHANNEL: Final[str] = (
    "Якщо в цьому акаунті кілька каналів, оберіть канал із ніком {handle} («{account_name}»)."
)
AUTH_UNVERIFIED_APP_WARNING: Final[str] = (
    "Google покаже попередження «Google hasn't verified this app» — це очікувано: застосунок ще не проходив "
    "перевірку Google. Натисніть Advanced, потім посилання Go to ... (unsafe), потім Continue. На екрані згоди "
    "позначте пункт про керування акаунтом YouTube і підтвердьте."
)
AUTH_OK: Final[str] = (
    "Канал «{account_name}» {handle}: вхід виконано — «{title}» {youtube_handle} (id {youtube_channel_id})."
)
AUTH_WRONG_CHANNEL_RETRY: Final[str] = (
    "Канал «{account_name}» {handle}: у браузері обрано канал «{youtube_title}» {youtube_handle} — "
    "потрібен «{account_name}» {handle}; вхід ще раз."
)
AUTH_WRONG_CHANNEL_GIVE_UP: Final[str] = (
    "Канал «{account_name}» {handle}: у браузері знову обрано канал «{youtube_title}» {youtube_handle} — "
    "потрібен «{account_name}» {handle}; спроби входу скінчилися, у цьому запуску канал пропущено."
)
AUTH_NEXT_RUN_HINT: Final[str] = (
    "під час наступного запуску програма знову запропонує вхід; якщо нік каналу змінився на YouTube — "
    "впишіть новий нік на вкладці «Ефіри YouTube» налаштувальника"
)
# Відмови перевірки каналу: значення зі списку каналів і те, що надіслав YouTube.
AUTH_CHANNEL_HANDLE_MISSING: Final[str] = (
    "канал «{account_name}» {handle}: у каналу YouTube «{youtube_title}» (id {youtube_channel_id}) немає ніка; "
    "канал пропущено. Заведіть каналу нік у Студії YouTube і впишіть його на вкладці «Ефіри YouTube» "
    "налаштувальника; якщо обрано не той канал — " + AUTH_NEXT_RUN_HINT
)
AUTH_CHANNEL_HANDLE_MISMATCH: Final[str] = (
    "канал «{account_name}» {handle}: вхід виконано в канал YouTube «{youtube_title}» {youtube_handle} "
    "(id {youtube_channel_id}), а в списку каналів записано нік {handle}, і паспорт каналів не підтверджує, "
    "що це той самий канал; канал пропущено; " + AUTH_NEXT_RUN_HINT
)
AUTH_CHANNEL_ID_MISMATCH: Final[str] = (
    "канал «{account_name}» {handle}: у паспорті каналів у ніка {handle} id {passport_channel_id}, "
    "а YouTube надіслав канал «{youtube_title}» {youtube_handle} з id {youtube_channel_id}; канал пропущено; "
    + AUTH_NEXT_RUN_HINT
)
AUTH_YOUTUBE_HANDLE_MISSING: Final[str] = "без ніка"
AUTH_FAILED: Final[str] = "Канал «{account_name}» {handle}: вхід не вдався — {reason}."
AUTH_SCOPE_HINT: Final[str] = (
    "Якщо на екрані згоди не було пункту про керування акаунтом YouTube — у налаштуваннях доступу застосунку "
    "в Google Cloud не додано дозвіл youtube."
)
WARNING_CHANNEL_ALIGNED: Final[str] = (
    "канал вирівняно за YouTube (id {youtube_channel_id}): «{title_before}» {handle_before} -> "
    "«{title_after}» {handle_after}; список каналів, файл входу й паспорт каналів оновлено, входити заново не треба; "
    "попередній список каналів — secrets\\channels.previous.json"
)
WARNING_TOKEN_RENAME_SKIPPED: Final[str] = (
    "канал «{account_name}» {handle}: YouTube підтвердив канал (id {youtube_channel_id}) із ніком {handle_after}, "
    "але файл {target} уже є — файли не зачеплено; якщо каналу з ніком {handle_after} немає в списку каналів, "
    "видаліть цей файл — наступний запуск вирівняє канал сам"
)
WARNING_CHANNEL_ALIGN_FAILED: Final[str] = (
    "канал «{account_name}» {handle}: YouTube підтвердив канал (id {youtube_channel_id}), "
    "але вирівняти файли не вдалося — {reason}; файли не зачеплено, наступний запуск спробує знову"
)
CHANNEL_ALIGN_TITLE_EMPTY: Final[str] = "YouTube надіслав порожню назву каналу"
WARNING_TOKEN_REJECTED: Final[str] = (
    "вхід каналу «{account_name}» {handle} вів на канал «{youtube_title}» {youtube_handle} "
    "(id {youtube_channel_id}) — файл входу видалено, програма запропонує вхід у «{account_name}» {handle}"
)
WARNING_TOKEN_SAVE_FAILED: Final[str] = (
    "канал «{account_name}» {handle}: вхід виконано, але файл входу не записано ({error}) — "
    "у цьому запуску канал працює, під час наступного запуску програма знову запропонує вхід"
)
WARNING_PASSPORT_UNREADABLE: Final[str] = (
    "паспорт каналів {path} не читається — його буде записано заново; "
    "канал із новим ніком до його першої перевірки за старим паспортом не впізнається"
)
WARNING_PASSPORT_WRITE_FAILED: Final[str] = (
    "паспорт каналів {path} не записано ({error}); робота триває, паспорт запише наступний запуск"
)

# --- план і звірка ефірів (app\pipeline\)
ADMISSION_CHANNEL_TEXT: Final[dict[str, str]] = {
    "refused": "не той канал",
    "failed": "платформа не відповіла",
    "needs_login": "вхід не виконано",
}
PROGRESS_CHANNELS_CHECK: Final[str] = "Перевірка каналів YouTube за збереженими входами: {count}."
PROGRESS_CHANNEL_CHECK_STARTED: Final[str] = "Перевірка каналів {place} з {total}: «{account_name}» {handle}"
PROGRESS_CHANNEL_READ_STARTED: Final[str] = (
    "Ефіри на каналах {place} з {total}: «{account_name}» {handle} — запит запланованих"
)
PROGRESS_CHANNEL_READ_DONE: Final[str] = (
    "Ефіри на каналах {place} з {total}: «{account_name}» {handle} — заплановано {count}"
)
PROGRESS_BROADCAST_CREATE: Final[str] = (
    "Ефіри YouTube {place} з {total}: «{account_name}» {handle} — створення {date} {time} {language}"
)
PROGRESS_BROADCAST_FIX: Final[str] = (
    "Ефіри YouTube {place} з {total}: «{account_name}» {handle} — виправлення {date} {time} {language}"
)
PROGRESS_KEY_SEND: Final[str] = (
    "Ефіри YouTube {place} з {total}: «{account_name}» {handle} — ключ у форму {date} {time} {language}"
)
PROGRESS_REPORT: Final[str] = "Запис звіту."
PROGRESS_PACKAGES_READ: Final[str] = (
    "Пакетів прочитано: {packages}; ефірів — {slots_total}, з них мовами каналів — "
    "{slots_mine}."
)
PROGRESS_SHEETS_RETRY: Final[str] = "Google не відповів — повтор {place} з {total}."
PROGRESS_VIDEO: Final[str] = "Читання відео {place} з {total}: {link}"
PROGRESS_DRIVE_PREVIEW: Final[str] = "Копія прев’ю на Google Диск: {place} з {total}."
PROGRESS_MERGE_SLOT: Final[str] = "Нейромережа: ефір {place} з {total} — {date} {time} {language}."
PROGRESS_DOC: Final[str] = "Створення документа оголошень {place} з {total}: {date}."
PROGRESS_ANNOUNCE: Final[str] = "Надсилання оголошень у Telegram {place} з {total}: {date}."
PROGRESS_ANNOUNCE_PACKAGE: Final[str] = "Надсилання пакета в Telegram: {name}."
# Завантаження yt-dlp і deno з GitHub, самооновлення yt-dlp (app\runtime\github_release.py): розміри — цілі МБ.
PROGRESS_TOOL_DOWNLOAD: Final[str] = "Завантаження {tool} {version} з GitHub: {size} МБ…"
PROGRESS_TOOL_DOWNLOAD_NO_SIZE: Final[str] = "Завантаження {tool} {version} з GitHub…"
PROGRESS_TOOL_DOWNLOAD_PART: Final[str] = "{tool}: завантажено {done} з {size} МБ."
PROGRESS_TOOL_SELF_UPDATE: Final[str] = "Перевірка оновлення {tool}…"
YOUTUBE_USAGE_LINE: Final[str] = "YouTube: звернень {calls}, квота ≈ {units} од."
BROADCASTS_NO_SLOTS: Final[str] = "Ефіри: ставити на YouTube нічого — до YouTube програма не зверталася."
# Ключ, который форма не подтвердила ни в первый раз, ни повтором (§14 решение 49): что сделать человеку.
KEYS_SEND_ALL_ACTION: Final[str] = (
    "передати: «усі» (вибір «нові | усі» в рядку «Ключі у форму» на «Головній» вікна налаштування)"
)
KEYS_GIVEN_UP: Final[str] = (
    "{prefix}: ключ двічі не дійшов до форми й сам більше не піде — " + KEYS_SEND_ALL_ACTION
)
# Повторная передача ключей после полного запуска (app\broadcasts\key_resend.py, §14 решение 36).
KEYS_RESEND_SWITCHED_OFF: Final[str] = "Ключі ефірів передано повторно: {sent}. Повторну передачу вимкнено."
KEYS_RESEND_KEPT: Final[str] = (
    "Ключі ефірів передано повторно: {sent}, не дійшло {undelivered} — повторна передача лишається увімкненою."
)
KEYS_RESEND_WRITE_FAILED: Final[str] = (
    "Ключі ефірів передано повторно: {sent}, але повторну передачу не вимкнено — файл налаштувань не записався: "
    "{reason}. Поверніть вибір ключів на «нові» — рядок «Ключі у форму» на «Головній»: .\\livecraft.bat --setup."
)
# --check и --auth (app\broadcasts\service.py; поведение planers main.py).
CHECK_HEADER: Final[str] = "Перевірка каналів за {path}:"
CHECK_CHANNEL_OK: Final[str] = (
    "- «{account_name}» {handle}: «{title}» {youtube_handle} (id {youtube_channel_id}), "
    "мова каналу на YouTube: {channel_language}; "
    "мови стримів із channels.json: {languages}; запланованих ефірів: {upcoming}"
)
CHECK_CHANNEL_LANGUAGE_UNSET: Final[str] = "не вказано"
CHECK_CHANNEL_LANGUAGE_NOTE: Final[str] = (
    "Мова каналу на YouTube — довідкова, на рішення програми вона не впливає: "
    "мову стриму задає оператор у channels.json."
)
CHECK_CHANNEL_FAILED: Final[str] = "- «{account_name}» {handle}: {reason}"
CHECK_CHANNEL_REFUSED: Final[str] = "- {message}"
CHANNEL_LISTED: Final[str] = "{handle} «{account_name}»"
CHECK_ALL_OK: Final[str] = "Усі канали на місці, трансляції ввімкнено."
CHECK_HAS_PROBLEMS: Final[str] = "Частина каналів не пройшла перевірку — див. рядки вище."
AUTH_UNKNOWN_CHANNEL: Final[str] = "У {path} немає каналу з ніком {handle}. Канали у файлі: {known}."
# Причина недопуска словами человека (AdmissionReason.wording) — см. messages_ru.
ADMISSION_CHANNEL_PROBLEM: Final[dict[str, str]] = {
    "refused": "Канал не підтверджено: під час входу обрано інший канал (подробиці — у рядку помилки каналу).",
    "failed": "Канал не перевірено: YouTube не відповів (подробиці — у рядку помилки каналу).",
    "needs_login": "Вхід у канал не виконано.",
}
ADMISSION_CHANNEL_ACTION: Final[dict[str, str]] = {
    "refused": "Під час входу оберіть у браузері потрібний канал.",
    "failed": "Якщо збій повторюється — перешліть звіт операторові.",
    "needs_login": "Увійдіть у канал, коли програма відкриє браузер.",
}
ADMISSION_MISSING_OPTION: Final[str] = "У формі «{form}» у питанні «{question}» немає варіанта «{value}»."
ADMISSION_ACTION_MISSING_OPTION: Final[str] = "Додайте варіант у форму."
ADMISSION_MISSING_OPTIONS: Final[str] = "У формі «{form}» у питанні «{question}» немає варіантів: {values}."
ADMISSION_ACTION_MISSING_OPTIONS: Final[str] = "Додайте варіанти у форму."
ADMISSION_MISSING_SETTINGS_TEXT: Final[str] = (
    "У налаштуваннях форми немає тексту відповіді на питання «{question}» форми «{form}»."
)
ADMISSION_ACTION_MISSING_SETTINGS_TEXT: Final[str] = (
    "Операторові — вписати текст варіанта в розділ form файлу secrets\\livecraft.json; ефіри з пакета отримають його "
    "з наступним пакетом."
)
ADMISSION_REQUIRED_MISSING: Final[str] = (
    "У формі «{form}» обов'язкове питання «{question}», на яке у програми немає відповіді."
)
ADMISSION_ACTION_REQUIRED_MISSING: Final[str] = (
    "Зробіть це питання у формі необов'язковим або повідомте операторові."
)
ADMISSION_ACTION_FORM_UNREADABLE: Final[str] = "Перевірте, що форма ключів відкривається за своїм посиланням."

# --- вивід контуру B (app\output\) — див. messages_ru.
CHANNEL_LABEL: Final[str] = "{account_name} {handle}"
SKIP_PAST: Final[str] = "{date} {time} {language} — вже минуло"
SKIP_TOO_LATE: Final[str] = "{date} {time} {language} — до старту менше {minutes} хвилин"
SKIP_NO_CHANNEL: Final[str] = "{date} {time} {language} — немає каналу для мови {language}"
OUTCOME_SLOT_PREFIX: Final[str] = "{date} {time} {language} -> {channel}"
OUTCOME_CREATED: Final[str] = "{prefix} — ефір створено, {form}"
OUTCOME_CREATE_PLANNED: Final[str] = "{prefix} — ефіру немає, буде створено"
OUTCOME_FIXED: Final[str] = "{prefix} — на YouTube відрізнялося: {what}; виправлено, ключ і посилання попередні{form}"
OUTCOME_FIXED_FORM: Final[str] = ", {mark}"
OUTCOME_FIX_PLANNED: Final[str] = "{prefix} — на YouTube відрізняється: {what}; буде виправлено"
OUTCOME_MATCHED: Final[str] = "{prefix} — {url}"
OUTCOME_MATCHED_FORM: Final[str] = "; {mark}"
UNFIXED_FIELD_TEXT: Final[dict[str, str]] = {"thumbnail": "обкладинку ефіру не встановлено"}
OUTCOME_UNFIXED: Final[str] = "; {what}"
OUTCOME_NO_STREAM: Final[str] = (
    "{prefix} — ефір на каналі є ({url}), але до нього не прив'язано потік: ключ узяти нізвідки. "
    "Прив'яжіть потік у YouTube Studio або видаліть ефір — програма створить його заново"
)
OUTCOME_STREAM_ATTACHED: Final[str] = "{prefix} — ефір був без потоку, потік прив'язано, {form}"
OUTCOME_AMBIGUOUS: Final[str] = (
    "{prefix} — на каналі кілька ефірів на цю хвилину без маркера програми, не можу розрізнити — "
    "розберіться вручну"
)
OUTCOME_ERROR: Final[str] = "{prefix} — {text}"
OUTCOME_KEPT: Final[str] = "{prefix} — {url} — тексти на YouTube попередні"
OUTCOME_DRY_RUN_SUFFIX: Final[str] = " — не виконано (dry-run)"
RUN_FAILURE_LINE: Final[str] = "{subject} — {text}"
KEYS_WRITE_FAILED: Final[str] = "файл ключів не записано: {detail}"
WARNING_LINE: Final[str] = "{prefix}: {step} — {code} ({message})"
WARNING_REASON_LINE: Final[str] = "{prefix}: {step} — {reason}"
WARNING_STEP_TEXT: Final[dict[str, str]] = {
    "thumbnail": "обкладинку ефіру не встановлено; ефір і ключ чинні",
    "language": "мову ефіру не записано; ефір і ключ чинні",
    "audience": "аудиторія ефіру була «для дітей» (налаштування каналу) — програма зняла її; перевірте налаштування каналу",
    "settings": "не вдалося застосувати налаштування ефіру (мова, категорія, аудиторія); ефір і ключ чинні",
    "age_restricted": "на ефірі стоїть вікове обмеження 18+; через API воно не знімається — зніміть вручну в Студії",
    "facts": "не вдалося перечитати ефір після планування; на сам ефір це не впливає",
}
THUMBNAIL_REASON_TEXT: Final[dict[str, str]] = {
    "uploadRateLimitExceeded": (
        "YouTube тимчасово обмежив завантаження обкладинок ефірів на цьому каналі й термін не повідомляє; інші "
        "обкладинки ефірів каналу в цьому запуску не встановлювалися — наступний запуск доставить їх сам, запустіть "
        "за кілька годин"
    ),
    "forbidden": (
        "YouTube не дозволяє цьому каналу власні обкладинки ефірів — підтвердьте канал за телефоном у Студії "
        "(розширені функції)"
    ),
    "invalidImage": "YouTube не прийняв картинку прев'ю з плану",
}
WARNING_REPORTED_FIELD: Final[str] = (
    "не можемо виправити: {prefix} — {field}: потрібно {wanted}, на платформі {actual}; через API це не виправляється "
    "(потрібен monitorStream) — виправте в Студії; ефір і ключ чинні"
)
WARNING_AMBIGUOUS: Final[str] = (
    "не можемо обрати ефір: {prefix} — на каналі кілька ефірів без мітки програми на цю хвилину; "
    "програма не обирає й не видаляє — залиште один: {urls}"
)
WARNING_FORM_DIAGNOSTIC: Final[str] = "відповідь форми збережено для розбору: {path}"
WARNING_KEPT_KEY: Final[str] = (
    "ключ ефіру, що збігся, форма вже підтверджувала раніше (пам'ять програми) — повторно він не надсилається. "
    "Якщо стример ключа не отримав — передайте його з keys.txt вручну або видаліть ефір на YouTube: "
    "програма створить його заново з новим ключем і надішле"
)
WARNING_LIVE_CHAT: Final[str] = (
    "в ефірів YouTube завжди увімкнено живий чат. Через API він не вимикається: якщо чат не потрібен, "
    "вимкніть його один раз у Студії на весь канал (Settings -> Community)"
)
NOTE_UNDATED_BROADCAST: Final[str] = (
    "на каналі {channel} є службовий ефір платформи без дати й часу — «{title}». YouTube заводить такий ефір "
    "сам під час заходу в панель трансляцій каналу; програма його з планом не звіряє й не чіпає, у списку "
    "трансляцій Студії він не видний"
)
MISMATCH_LINE: Final[str] = "{prefix}: {field} — хотіли: {wanted}; на платформі: {actual}"
MISMATCH_FIELD_START: Final[str] = "час старту"
MISMATCH_FIELD_LANGUAGE: Final[str] = "мова"
MISMATCH_FIELD_AUDIENCE: Final[str] = "аудиторія"
MISMATCH_DESCRIPTION: Final[str] = "{length} символів, початок «{head}»"
AUDIENCE_NOT_FOR_KIDS: Final[str] = "не для дітей"
AUDIENCE_FOR_KIDS: Final[str] = "для дітей"
SPEC_VALUE_TRUE: Final[str] = "так"
SPEC_VALUE_FALSE: Final[str] = "ні"
THUMBNAIL_BEFORE: Final[str] = "заглушка каналу"
THUMBNAIL_AFTER: Final[str] = "з плану"
CHANGED_FIELD_TEXT: Final[dict[str, str]] = {
    "title": "назва",
    "description": "опис",
    "category": "категорія",
    "privacy": "видимість",
    "marker": "маркер потоку",
    "thumbnail": "обкладинка ефіру",
    "auto_start": "автостарт",
    "auto_stop": "автостоп",
    "latency": "затримка трансляції",
}
ORPHAN_LINE: Final[str] = "{date} {time} {language} -> {channel} — {url} — ефір не видалено"
ORPHAN_MOVED_LINE: Final[str] = (
    "{date} {time} {language} -> {channel} — {url} — стоїть на {actual}: час ефіру змінював власник, "
    "програма його не чіпає"
)
REPORT_TITLE: Final[str] = "# Livecraft {version} — звіт {generated_at}"
REPORT_TITLE_DRY_RUN: Final[str] = " (dry-run)"
REPORT_ITEM: Final[str] = "- {text}"
REPORT_SECTION_CREATED: Final[str] = "### Створено ({count})"
REPORT_SECTION_FIXED: Final[str] = "### Виправлено ({count})"
REPORT_SECTION_MATCHED: Final[str] = "### Уже заплановано, збігається ({count})"
REPORT_SECTION_ORPHANS: Final[str] = "### Перенесено чи скасовано? ({count})"
REPORT_SECTION_KEPT: Final[str] = "### Тексти не оновлювалися ({count})"
REPORT_KEPT_LEAD: Final[str] = (
    "Нейромережа не об’єднала описи відео цих ефірів — тексти цього запуску на YouTube не йдуть: на ефірах "
    "попередні тексти, програма їх не чіпала."
)
REPORT_SECTION_SCHEDULED: Final[str] = "### Заплановано на каналах ({count})"
REPORT_SECTION_SKIPPED: Final[str] = "### Пропущено"
REPORT_SECTION_PACKAGES: Final[str] = "### Пакети"
REPORT_SECTION_WARNINGS: Final[str] = "### Попередження"
REPORT_SECTION_MISMATCHES: Final[str] = "### Розбіжності з платформою"
REPORT_SECTION_ERRORS: Final[str] = "### Помилки"
REPORT_SECTION_NOT_DELIVERED: Final[str] = "### Ключ не дійшов до стримера"
REPORT_SECTION_TWO_KEYS: Final[str] = "### У формі два ключі на один ефір ({count})"
REPORT_SECTION_NOT_ADMITTED: Final[str] = "### Не допущено до публікації ({count})"
REPORT_SECTION_NOTES: Final[str] = "### Особливості платформи — так улаштована платформа, це не про цей запуск"
REPORT_TOTAL_KEYS_FILE: Final[str] = "Файл ключів: {path}"
REPORT_PART: Final[str] = "## {title}"
REPORT_PART_RUN: Final[str] = "Запуск"
REPORT_PART_INTAKE: Final[str] = "Таблиця плану й тексти"
REPORT_PART_SHELF: Final[str] = "Пакети"
REPORT_PART_PREVIEWS: Final[str] = "Прев’ю"
REPORT_SECTION_SKIPPED_ROWS: Final[str] = "### Відсіяні рядки таблиці ({count})"
REPORT_SECTION_VIDEOS: Final[str] = "### Відео ({count})"
REPORT_SECTION_SLOTS: Final[str] = "### Ефіри за планом ({count})"
REPORT_SECTION_DOC_LINKS: Final[str] = "### Посилання на документи"
REPORT_ROW_LINE: Final[str] = "рядок {row}: {link} — {text}"
REPORT_VIDEO_READY: Final[str] = "мова {language}, {preview}"
REPORT_VIDEO_PREVIEW: Final[str] = "прев’ю є"
REPORT_VIDEO_NO_PREVIEW: Final[str] = "прев’ю немає"
REPORT_SLOT: Final[str] = "{date} {time} {language} — відео: {videos}, тексти: {origin} — «{title}»"
REPORT_SLOT_REFUSED: Final[str] = "{date} {time} {language} — відео: {videos} — {problem}"
REPORT_TEXT_ORIGINS: Final[dict[str, str]] = {
    "source_single": "тексти відео",
    "source_composed": "тексти відео",
    "merged": "від нейромережі",
    "numbered": "за номерами — на YouTube не йде",
    "package": "з пакета",
}
TWO_KEYS_LINE: Final[str] = (
    "{prefix} — попередній ефір {old_url} на часі за планом не знайдено (видалено або перенесено), поставлено новий "
    "{new_url}. Чинний ключ {new_key}; попередній {old_key} теж передано у форму на цю дату — "
    "для цього ефіру він більше не діє"
)
NOT_DELIVERED_LINE: Final[str] = (
    "{prefix} — {reason} Ефір на каналі стоїть — передайте ключ стримерові з keys.txt вручну"
)
NOT_ADMITTED_LINE: Final[str] = "{prefix} — {problems} {consequence}. {actions} {next_run}."
NOT_ADMITTED_CONSEQUENCE_NO_BROADCAST: Final[str] = "Ефір не створено, ключ стримерові не передано"
NOT_ADMITTED_CONSEQUENCE_BROADCAST: Final[str] = (
    "Ефір на каналі є ({url}), але не виправлявся, ключ стримерові не передано"
)
NOT_ADMITTED_CONSEQUENCE_CHANNEL: Final[str] = "Ефіри на каналі не перевірялися, ключ стримерові не передано"
NOT_ADMITTED_NEXT_NO_BROADCAST: Final[str] = "Програма створить ефір на наступному запуску"
NOT_ADMITTED_NEXT_BROADCAST: Final[str] = "Програма передасть ключ на наступному запуску"
NOT_ADMITTED_NEXT_CHANNEL: Final[str] = "Програма перевірить канал на наступному запуску"
NOT_ADMITTED_GROUP_LINE: Final[str] = "{problem} {consequence}. {action} {next_run}."
NOT_ADMITTED_GROUP_BROADCASTS: Final[str] = "Ефіри: {broadcasts}."
NOT_ADMITTED_GROUP_CONSEQUENCE_NO_BROADCAST: Final[str] = "Ефіри не створено, ключі стримерові не передано"
NOT_ADMITTED_GROUP_CONSEQUENCE_BROADCAST: Final[str] = (
    "Ефіри на каналі є, але не виправлялися, ключі стримерові не передано"
)
NOT_ADMITTED_GROUP_CONSEQUENCE_CHANNEL: Final[str] = "Ефіри на каналах не перевірялися, ключі стримерові не передано"
NOT_ADMITTED_GROUP_NEXT_NO_BROADCAST: Final[str] = "Програма створить ефіри на наступному запуску"
NOT_ADMITTED_GROUP_NEXT_BROADCAST: Final[str] = "Програма передасть ключі на наступному запуску"
NOT_ADMITTED_GROUP_NEXT_CHANNEL: Final[str] = "Програма перевірить канали на наступному запуску"
FORM_MARK_SENT: Final[str] = "ключ надіслано у форму"
FORM_MARK_PLANNED: Final[str] = "ключ буде надіслано у форму"
FORM_MARK_FAILED: Final[str] = (
    "ключ у форму НЕ надіслано. {reason} Наступний запуск надішле його знову, "
    "а поки передайте ключ стримерові з keys.txt вручну"
)
FORM_FAILURE_UNKNOWN: Final[str] = "Форма ключів не підтвердила запис відповіді."
SUMMARY_BROADCASTS: Final[str] = (
    "Підсумок за ефірами (усього {total}): опубліковано {created}, виправлено {fixed}, уже стояло {matched}{kept}, "
    "не допущено {not_admitted}, помилок {errors}."
)
SUMMARY_BROADCASTS_DRY_RUN: Final[str] = (
    "Підсумок за ефірами (усього {total}): опублікуємо {created}, виправимо {fixed}, уже стояло {matched}{kept}, "
    "не допущено {not_admitted}, помилок {errors}."
)
SUMMARY_KEPT: Final[str] = ", тексти не оновлювалися {count}"
SUMMARY_BROADCASTS_STATUS: Final[str] = "Підсумок за ефірами (усього {total}): уже стояло {matched}, помилок {errors}."
SUMMARY_SLOTS_OUT: Final[str] = "Ефіри за планом поза роботою: {count} — {reasons}."
SUMMARY_SLOTS_REASON: Final[dict[str, str]] = {
    "past": "час старту вже минув",
    "too_late": "до старту менше {minutes} хвилин",
    "no_channel": "немає каналу для мови {language}",
}
SUMMARY_SLOTS_REASON_COUNTED: Final[str] = "{reason} {count}"
SUMMARY_EXIT_FAILED: Final[str] = "Код виходу {code} — не все виконано: {reasons}."
EXIT_REASON_TEXT: Final[dict[str, str]] = {
    "errors": "помилок за ефірами {count}",
    "failures": "помилок каналів і файлів програми {count}",
    "key_undelivered": "ключ не дійшов до стримера {count}",
    "packages": "пакетів не прочитано {count}",
}
CONSOLE_BLOCK_COUNTED: Final[str] = "{title} ({count})"
CONSOLE_TITLED_LINE: Final[str] = "{title} — {text}"
CONSOLE_BLOCK_ATTENTION: Final[str] = "УВАГА"
CONSOLE_BLOCK_CREATED: Final[str] = "ОПУБЛІКУВАЛИ"
CONSOLE_BLOCK_CREATED_DRY_RUN: Final[str] = "ОПУБЛІКУЄМО"
CONSOLE_BLOCK_FIXED: Final[str] = "ВИПРАВИЛИ"
CONSOLE_BLOCK_FIXED_DRY_RUN: Final[str] = "ВИПРАВИМО"
CONSOLE_BLOCK_KEYS: Final[str] = "КЛЮЧІ СТРИМЕРОВІ"
CONSOLE_BLOCK_MATCHED: Final[str] = "УЖЕ СТОЯЛО"
CONSOLE_BLOCK_KEPT: Final[str] = "ТЕКСТИ НЕ ОНОВЛЮВАЛИСЯ"
CONSOLE_BLOCK_SKIPPED: Final[str] = "НЕ ПУБЛІКУВАЛИ"
CONSOLE_CHANNEL_GROUP: Final[str] = "  {account_name} {handle} ({google_account})"
CONSOLE_BROADCAST_LINE: Final[str] = "    {date}  {time}  {language}  {title}"
CONSOLE_FIXED_LINE: Final[str] = "    {date}  {time}  {language}  {title} — оновлено: {what}"
CONSOLE_FIX_PLANNED_LINE: Final[str] = "    {date}  {time}  {language}  {title} — буде оновлено: {what}"
CONSOLE_KEY_LINE: Final[str] = "    {date}  {time}  {language}  {key}  {state}"
CONSOLE_SKIP_GROUP_TOO_LATE: Final[str] = "  до старту менше {minutes} хвилин"
CONSOLE_SKIP_GROUP_NO_CHANNEL: Final[str] = "  немає каналу для мови {language}"
CONSOLE_ATTENTION_ERROR: Final[str] = "  помилка: {text}"
CONSOLE_ATTENTION_NOT_DELIVERED: Final[str] = "  ключ не дійшов до стримера: {prefix} — {reason}"
CONSOLE_ATTENTION_TWO_KEYS: Final[str] = (
    "  {prefix}: попередній ефір на часі за планом не знайдено — поставлено новий; "
    "у формі на цю дату два ключі: чинний {new_key}, попередній {old_key}"
)
CONSOLE_ATTENTION_NOT_ADMITTED: Final[str] = "  не допущено: {text}"
CONSOLE_ATTENTION_NOT_ADMITTED_GROUP: Final[str] = "  не допущено ефірів — {count}: {text}"
CONSOLE_ATTENTION_REPEATED: Final[str] = "{text} (×{count})"
CONSOLE_ATTENTION_TEXT: Final[str] = "  {text}"
CONSOLE_ATTENTION_PACKAGE: Final[str] = "  пакет: {text}"
CONSOLE_ATTENTION_RESTORED: Final[str] = "  повернули до плану: {prefix} — {field}: було {before}, стало {after}"
CONSOLE_ATTENTION_RESTORED_UNKNOWN: Final[str] = "  повернули до плану: {prefix} — {field}: стало {after}"
CONSOLE_ATTENTION_RESTORE_PLANNED: Final[str] = (
    "  повернемо до плану: {prefix} — {field}: зараз {before}, буде {after}"
)
CONSOLE_ATTENTION_RESTORE_PLANNED_UNKNOWN: Final[str] = "  повернемо до плану: {prefix} — {field}: буде {after}"
CONSOLE_PATH: Final[str] = "  {label:<8}{path}"
CONSOLE_LABEL_KEYS: Final[str] = "ключі"
CONSOLE_LABEL_REPORT: Final[str] = "звіт"
CONSOLE_LABEL_LOG: Final[str] = "лог"
CONSOLE_TABLE_FILES: Final[str] = "Файли"
KEY_FORM_SENT_LEAD: Final[str] = "надіслано у форму"
KEY_FORM_CONFIRMED_LEAD: Final[str] = "передано у форму"
KEY_FORM_GIVEN_UP_LEAD: Final[str] = "двічі не дійшов до форми"
KEY_FORM_FAILED_LEAD: Final[str] = "НЕ надіслано"
KEY_FORM_NOT_ADMITTED_LEAD: Final[str] = KEY_FORM_FAILED_LEAD + ": не допущено"
KEY_FORM_UNKNOWN_LEAD: Final[str] = "немає підтвердження в пам'яті програми"
KEY_FORM_LINE_OFF_LEAD: Final[str] = "не надсилався"
CONSOLE_KEY_FAILED: Final[str] = KEY_FORM_FAILED_LEAD + " — {reason}"
KEYS_FILE_HEADER: Final[tuple[str, ...]] = (
    "# Ключі трансляцій. Згенеровано програмою {generated_at}.",
    "# Файл перезаписується на кожному запуску — не редагувати.",
    "# Рядок «форма»:",
    "#   «" + KEY_FORM_SENT_LEAD + "» — форма підтвердила ключ у цьому запуску;",
    "#   «" + KEY_FORM_CONFIRMED_LEAD + "» — форма підтвердила цей ключ раніше (пам'ять програми);",
    "#   «" + KEY_FORM_FAILED_LEAD + "» — ключ мав піти й не пішов: передайте його стримерові вручну;",
    "#   «" + KEY_FORM_NOT_ADMITTED_LEAD + "» — форма цей ефір не приймає (немає дати або варіанта) "
    "або канал не підтверджено: ефір стоїть, ключ стримерові не передано — передайте вручну;",
    "#   «" + KEY_FORM_LINE_OFF_LEAD + "» — лінію «Ключі у форму» вимкнено: передайте ключ стримерові вручну;",
    "#   «" + KEY_FORM_GIVEN_UP_LEAD + "» — "
    "ключ ішов у форму двічі — першого разу й повтором — і форма його не підтвердила; сам він більше не піде — " + KEYS_SEND_ALL_ACTION + ";",
    "#   «" + KEY_FORM_UNKNOWN_LEAD + "» — програма не знає, чи отримав стример цей ключ.",
)
KEYS_BLOCK_TITLE: Final[str] = "{date} {time}  {language}  {account_name} {handle}"
KEYS_BLOCK_KEY: Final[str] = "  ключ   {value}"
KEYS_BLOCK_STREAM: Final[str] = "  потік  {value}"
KEYS_BLOCK_BROADCAST: Final[str] = "  ефір   {value}"
KEYS_BLOCK_FORM: Final[str] = "  форма  {value}"
KEY_FORM_SENT: Final[str] = KEY_FORM_SENT_LEAD + " {sent_at}"
KEY_FORM_CONFIRMED: Final[str] = KEY_FORM_CONFIRMED_LEAD + " {confirmed_at}"
KEY_FORM_GIVEN_UP: Final[str] = KEY_FORM_GIVEN_UP_LEAD + " — " + KEYS_SEND_ALL_ACTION
KEY_FORM_FAILED: Final[str] = KEY_FORM_FAILED_LEAD + " — {reason} Передайте стримерові вручну."
KEY_FORM_NOT_ADMITTED: Final[str] = KEY_FORM_NOT_ADMITTED_LEAD + " — {reasons}"
KEY_FORM_UNKNOWN: Final[str] = KEY_FORM_UNKNOWN_LEAD
KEY_FORM_LINE_OFF: Final[str] = KEY_FORM_LINE_OFF_LEAD + ": лінію «{line}» вимкнено"

# --- прогон режима А (app\intake\intake.py)
INTAKE_TABLE_LINE: Final[str] = "Таблиця плану: рядків {rows}, допущено {admitted}, відсіяно {skipped}{reasons}."
INTAKE_TABLE_REASONS: Final[str] = " — {items}"
INTAKE_COUNT_ITEM: Final[str] = "{name}: {count}"
INTAKE_NO_FUTURE_ROWS: Final[str] = "Майбутніх ефірів у таблиці немає — пакет у цьому запуску не збирається."
INTAKE_SOURCES_LINE: Final[str] = "Відео: придатних {ready} з {total}, без прев’ю {no_preview}{no_description}{failures}."
INTAKE_SOURCES_NO_DESCRIPTION: Final[str] = ", без опису {count}"
INTAKE_SOURCE_REFUSED: Final[str] = "рядок {row}, {link}: {reason}"
INTAKE_SOURCES_FAILURES: Final[str] = "; не придатні — {items}"
PREVIEWS_LINE: Final[str] = (
    "Прев’ю: збережено в папці прев’ю — {saved}; на Google Диску — завантажено {uploaded}, уже було {kept}."
)
PREVIEWS_DRY_RUN_LINE: Final[str] = (
    "Прев’ю: збережено в папці прев’ю — {saved}; на Google Диск у пробному запуску нічого не завантажено."
)
PREVIEWS_LOCAL_LINE: Final[str] = "Прев’ю: збережено в папці прев’ю — {saved}."
PREVIEWS_DRIVE_LINE: Final[str] = "Прев’ю: на Google Диску — завантажено {uploaded}, уже було {kept}."
INTAKE_SHEET_WRITE_LINE: Final[str] = (
    "Таблиця плану: мов відео записано {languages}, уже стояли {languages_kept}; посилань на прев’ю записано {links}, "
    "уже стояли {links_kept}."
)
INTAKE_SHEET_WRITE_LANGUAGES_LINE: Final[str] = "Таблиця плану: мов відео записано {languages}, уже стояли {languages_kept}."
INTAKE_SHEET_WRITE_DRY_RUN_LINE: Final[str] = "Таблиця плану: пробний запуск — нічого не записано."
INTAKE_SHEET_WRITE_VIDEO_LINKS_LINE: Final[str] = "Таблиця плану: посилань на відео записано {written}, уже стояли {kept}."
INTAKE_SLOTS_LINE: Final[str] = "Ефіри за планом: {count}{languages}{refused}."
INTAKE_SLOTS_LANGUAGES: Final[str] = " ({items})"
INTAKE_SLOTS_REFUSED: Final[str] = ", відмовлено: {count} — причини в журналі"
INTAKE_NO_SLOTS: Final[str] = "Придатних ефірів немає — виведенню й YouTube нічого робити."
INTAKE_SLOT_NOT_FOR_YOUTUBE: Final[str] = (
    "Ефір {language} {time} {date}: нейромережа не об’єднала описи відео — тексти цього запуску на YouTube не "
    "йдуть; у документі й Telegram — описи за номерами."
)
PACKAGE_NO_YOUTUBE_SLOTS: Final[str] = "Ефірів для YouTube немає — пакет не записано."
INTAKE_MERGE_LINE: Final[str] = (
    "Нейромережа: ефірів {total}, тексти моделі {merged}, тексти відео {video}{reasons}{numbered}."
)
INTAKE_MERGE_NUMBERED: Final[str] = "; за номерами {count}{reasons}"
INTAKE_MERGE_REASONS: Final[str] = " — {items}"
INTAKE_MERGE_VIDEO_REASONS: Final[dict[str, str]] = {
    "few_descriptions": "менше двох описів у відео",
    "not_accepted": "відповідь моделі не прийнято",
    "publish_blocked": "не пройшли перевірку перед публікацією",
    "stopped": "нейромережу зупинено",
    "no_model": "модель не вибрано",
}
INTAKE_MERGE_COST: Final[str] = "Витрати нейромережі: запитів {requests}, ${cost}."
INTAKE_MERGE_COST_UNKNOWN: Final[str] = (
    "Витрати нейромережі: запитів {requests}, не менше за ${cost} — ціна частини відповідей невідома."
)
INTAKE_MERGE_STOPPED: Final[str] = (
    "Нейромережу зупинено до кінця запуску — решта ефірів, яким потрібне об’єднання описів, отримають "
    "описи за номерами. {failure}"
)

# --- пробник источников (app\tools\source_probe.py)
SOURCE_PROBE_TITLE: Final[str] = "Перевірка джерел через yt-dlp"
SOURCE_PROBE_USAGE: Final[str] = "Вкажіть одне або кілька посилань: python -m app.tools.source_probe <посилання> …"
SOURCE_PROBE_SOURCE: Final[str] = "Джерело {link}"
SOURCE_PROBE_BAD_LINK: Final[str] = "  у посиланні не знайдено відео YouTube: {raw}"
SOURCE_PROBE_ID: Final[str] = "  id: {value}"
SOURCE_PROBE_NAME: Final[str] = "  назва: {value}"
SOURCE_PROBE_DURATION: Final[str] = "  тривалість: {value}"
SOURCE_PROBE_LANGUAGE: Final[str] = "  мова відео: {video}; мова каналу: {channel}"
SOURCE_PROBE_AUDIO: Final[str] = "  мови аудіо: {value}"
SOURCE_PROBE_SUBTITLES: Final[str] = "  субтитри: {value}"
SOURCE_PROBE_AUTO_CAPTIONS: Final[str] = "  автосубтитри: {value}"
SOURCE_PROBE_SOURCE_LANGUAGE: Final[str] = "  мова джерела: {code} ({source})"
SOURCE_PROBE_SOURCE_LANGUAGE_NONE: Final[str] = "  мова джерела: не визначилася"
SOURCE_PROBE_MORE: Final[str] = "{shown} … і ще {more}"
SOURCE_PROBE_PREVIEW_OK: Final[str] = "  прев’ю: {width}×{height}, {kilobytes} КБ — годиться для YouTube"
SOURCE_PROBE_PREVIEW_BAD: Final[str] = "  прев’ю: не годиться — {reason}"
SOURCE_PROBE_PREVIEW_SKIPPED: Final[str] = (
    "  прев’ю: не завантажувалося — мову не визначено, у запуск таке джерело не йде"
)
SOURCE_PROBE_FAILED: Final[str] = "  відмова: {reason}"
SOURCE_PROBE_DETAIL: Final[str] = "  докладно: {detail}"
SOURCE_PROBE_SUMMARY: Final[str] = "Джерел: {total}, отримано: {ok}, відмов: {failed}."

# --- нейросеть (app\llm\)
LLM_BACKEND_TITLE: Final[dict[str, str]] = {
    "openai": "OpenAI",
}
LLM_REQUEST_FAILED: Final[str] = "Запит до нейромережі не вдався: {reason}."
LLM_REQUEST_FAILED_STATUS: Final[str] = "Запит до нейромережі не вдався: {reason} (код відповіді {status})."
LLM_ERROR_KIND_TEXT: Final[dict[str, str]] = {
    "timeout": "{provider} не відповів вчасно",
    "connection_error": "немає зв’язку з {provider} — перевірте інтернет",
    "quota_exhausted": "на рахунку {provider} закінчилися гроші або ліміт — поповніть баланс у кабінеті {provider}",
    "rate_limit": "{provider} перевантажений або перевищено ліміт запитів — запустіть пізніше",
    "server_error": "збій на боці {provider} — запустіть пізніше",
    "authentication_failed": "{provider} не прийняв ключ — перевірте ключ {provider} у налаштуваннях",
    "model_access_denied": "ключ {provider} не має доступу до цієї моделі",
    "model_not_found": "такої моделі немає або вона недоступна цьому ключу — перевірте назву моделі в налаштуваннях",
    "incompatible_request_shape": "модель не вміє відповідати за заданою схемою JSON",
    "unsupported_parameter": "модель не приймає один із параметрів запиту",
    "bad_request": "{provider} відхилив запит",
    "request_failed": "{provider} не виконав запит",
    "empty_output": "модель повернула порожню відповідь",
    "not_configured": "не задано ключ {provider} — задайте його на вкладці «Нейромережа» у налаштуваннях",
}
LLM_REQUEST_LABEL_TEXT: Final[dict[str, str]] = {
    "model_probe": "перевірка",
    "startup_ping": "проба",
}
LLM_CHOICE_REASON_TEXT: Final[dict[str, str]] = {
    "primary_confirmed": "основна, відповіла на перевірку",
    "primary_unchecked": "основна; перевірити не вдалося, працюємо на ній",
    "fallback_confirmed": "запасна: основна недоступна цьому ключу",
    "fallback_unchecked": "запасна: основна недоступна цьому ключу, запасну перевірити не вдалося",
    "refused": "відповідної моделі немає",
}
LLM_CHOICE_LINE: Final[str] = "Модель: {model} — {reason}."
LLM_CHOICE_REFUSED: Final[str] = "Модель не вибрано. {reason}"

# --- ответ модели на merge (app\llm\merges\)
MERGE_REJECT_TEXT: Final[dict[str, str]] = {
    "not_json_object": "модель відповіла не одним об’єктом JSON",
    "missing_keys": "у відповіді моделі немає назви або опису",
    "extra_keys": "у відповіді моделі є зайві поля, крім назви й опису",
    "invalid_title": "назва порожня або містить емодзі",
    "invalid_description": "опис порожній",
    "cta_as_first_paragraph": "опис починається із заклику підписатися або написати коментар",
    "duplicate_paragraph": "в описі повторюються абзаци або теза",
    "empty": "в описі не залишилося тексту після вилучення службових рядків",
    "paragraph_underflow": "в описі замало абзаців",
    "paragraph_overflow": "в описі забагато абзаців",
    "title_rules": "у назві числа, блюзнірство, негатив, питання, оклик, лапки, друга частина або великі літери",
    "opening_blasphemy": "у першій фразі опису блюзнірство",
    "unexpected_error": "модель повернула назву або опис не текстом",
    "per_source_enumeration": "опис переказує джерела по черзі, а не зводить їх",
    "hook_echo_in_body": "початок опису повторює тезу, і прибрати повтор не вдалося",
    "cta_in_hook": "перший абзац опису — заклик або службовий рядок, а не теза",
    "insufficient_bullet_coverage": "в описі замало пунктів для кількості джерел",
    "compact_bullet_overflow": "в описі більше семи пунктів за одного-двох джерел",
    "excessive_emoji_usage": "в описі більше десяти емодзі поза маркерами пунктів",
    "overloaded_bullet": "в описі кілька перевантажених пунктів",
    "numbered_title_dump": "назва перелічує теми під номерами",
    "semantic_gate": "опис не пройшов перевірку мови й абетки",
}
RESOURCE_PROBLEM_LINES: Final[str] = "потрібен непорожній список рядків"

# --- пробник нейросети (app\tools\llm_probe.py)
LLM_PROBE_TITLE: Final[str] = "Перевірка нейромережі OpenAI"
LLM_PROBE_SETTINGS: Final[str] = "Основна модель: {primary}; запасна: {fallback}; тариф: {tier}; міркування: {effort}."
LLM_PROBE_ANSWER: Final[str] = "Відповідь моделі: {text}"
LLM_PROBE_ANSWER_CUT: Final[str] = "{text}…"
LLM_PROBE_TOKENS: Final[str] = (
    "Токени: вхід {input} (з кешу {cached}), вихід {output} (з них міркування {thinking}), усього {total}."
)
LLM_PROBE_TOKENS_UNKNOWN: Final[str] = "Токени: нейромережа не повідомила витрати за частиною запитів."
LLM_PROBE_REQUESTS: Final[str] = "Запитів: {requests}; тарифи: {tiers}."
LLM_PROBE_TIER_ENTRY: Final[str] = "{label} — {tier}"
LLM_PROBE_COST: Final[str] = "Вартість: ${cost}."
LLM_PROBE_COST_UNKNOWN: Final[str] = "Вартість: не менше за ${cost} — цін частини моделей ({models}) у програмі немає."

# --- обрыв и падение запуска (app\main.py::Launch.run)
RUN_INTERRUPTED: Final[str] = (
    "Запуск перервано. Що вже зроблено на YouTube, знайде й урахує наступний запуск."
)
RUN_CRASHED: Final[str] = (
    "Livecraft аварійно зупинився — подробиці в журналі {log}. "
    "Що вже зроблено на YouTube, знайде й урахує наступний запуск; перешліть журнал операторові."
)

# --- замок эталона кода (app\tools\code_standard, §11)
CODE_STANDARD_DESCRIPTION: Final[str] = (
    "Замок еталона коду livecraft: звіт за правилами E1–E21 і реєстр боргів, який може лише скорочуватися."
)
CODE_STANDARD_HELP_INIT: Final[str] = (
    "створити реєстр боргів за поточним кодом, якщо його немає; в наявний реєстр — лише додати розділи "
    "правил, яких у ньому ще немає"
)
CODE_STANDARD_HELP_WRITE_DEBT: Final[str] = (
    "переписати реєстр за поточним кодом — лише якщо жоден борг не з’явився й не зріс"
)
CODE_STANDARD_HELP_COMPARE: Final[str] = (
    "порівняти реєстр із попередньою версією: git-посилання (HEAD, геш коміту) або шлях до файлу реєстру"
)
CODE_STANDARD_HELP_FILES: Final[str] = "показати борги реєстру в цих файлах або папках (шлях від кореня репозиторію)"
CODE_STANDARD_METAVAR_VERSION: Final[str] = "ВЕРСІЯ"
CODE_STANDARD_METAVAR_PATH: Final[str] = "ШЛЯХ"
CODE_STANDARD_RULE_LABELS: Final[dict[str, str]] = {
    "E1": "вільні функції",
    "E2": "статичні методи",
    "E3": "довжина визначення",
    "E4": "кількість параметрів",
    "E5": "літерали в тілах функцій",
    "E6": "кирилиця в коді",
    "E7": "текст у винятках",
    "E8": "одне значення — одне оголошення",
    "E9": "регулярні вирази",
    "E10": "логери",
    "E11": "структурні клони",
    "E12": "порожні обгортки",
    "E13": "кортежі-стани",
    "E14": "сирі дані",
    "E15": "захисні перетворення",
    "E16": "шари й кільця імпорту",
    "E17": "час",
    "E18": "розміри модулів і класів",
    "E19": "код у __init__.py",
    "E20": "тести",
    "E21": "ім’я визначено в модулі двічі",
}
CODE_STANDARD_SIGN_LABELS: Final[dict[str, str]] = {
    "names_app_class": "(а) в анотаціях клас app",
    "one_class_use": "(б) потрібна одному класу",
    "unused": "(в) ніхто не використовує",
    "forwarding": "(а) пересилання",
    "two_layers": "(б) два шари",
    "foreign_body": "(в) чуже тіло",
    "module": "модулів",
    "class": "класів",
    "number": "числа",
    "log": "журнал",
    "separator": "роздільники",
    "identifier": "ідентифікатори",
    "text": "текст",
    "text_constant": "рядки",
    "number_constant": "числа",
    "repeated_pattern": "повтори шаблону",
    "pattern_in_function": "шаблон у функції",
    "area_missing": "get_logger без LogArea",
    "raw_logger": "logging.getLogger поза пакетом журналів",
    "edge": "ребра",
    "ring": "кільця",
    "unmapped": "пакети поза картою",
    "test_import": "імпорт модуля тестів",
    "logger_name": "ім’я логера рядком",
    "private_patch": "підміна приватного імені",
    "global_patch": "підміна os / shutil",
    "dataclass_replace": "dataclasses.replace поза заготовками",
}
CODE_STANDARD_RING_KEY: Final[str] = "кільце: {modules}"
CODE_STANDARD_UNMAPPED_KEY: Final[str] = "поза картою: {package}"
CODE_STANDARD_REPORT_TITLE: Final[str] = "Еталон коду livecraft: порушення, борги реєстру й винятки"
CODE_STANDARD_REPORT_ROW: Final[str] = "{rule:<4} {label:<34} {now:>7} {ledger:>10} {exempt:>11} {goal:>5}"
CODE_STANDARD_REPORT_COLUMNS: Final[dict[str, str]] = {
    "rule": "код",
    "label": "правило",
    "now": "зараз",
    "ledger": "у реєстрі",
    "exempt": "винятків",
    "goal": "мета",
}
CODE_STANDARD_REPORT_NO_VALUE: Final[str] = "—"
CODE_STANDARD_REPORT_SIGNS: Final[str] = "     {signs}"
CODE_STANDARD_REPORT_SIGN: Final[str] = "{label}: {count}"
CODE_STANDARD_REPORT_STATE: Final[str] = (
    "Код проти реєстру: нових {new}, зрослих {grown}, зменшених {shrunk}, знятих {gone}."
)
CODE_STANDARD_REPORT_NO_LEDGER: Final[str] = (
    "Реєстру боргів немає — створіть його: python -m app.tools.code_standard --init"
)
CODE_STANDARD_CHANGE_LINES: Final[dict[str, str]] = {
    "new": "  {rule} {key} — нове: {after}",
    "grown": "  {rule} {key} — зросло: було {before}, стало {after}",
    "shrunk": "  {rule} {key} — зменшилося: було {before}, стало {after}",
    "gone": "  {rule} {key} — знято (було {before})",
    "same": "  {rule} {key} — без змін: {after}",
}
CODE_STANDARD_EXEMPTION_NO_REASON: Final[str] = "Виняток {rule} {key}: порожнє обґрунтування."
CODE_STANDARD_EXEMPTION_NOT_CAUGHT: Final[str] = (
    "Виняток {rule} {key}: правило його більше не ловить — приберіть його з exceptions.json."
)
CODE_STANDARD_STALE_ENTRIES: Final[str] = (
    "У реєстрі застарілі записи — борг знято або зменшено в коді. "
    "Оновіть реєстр: python -m app.tools.code_standard --write-debt"
)
CODE_STANDARD_GROWTH: Final[str] = (
    "З’явилися або зросли порушення еталона коду. Приберіть їх із коду — у реєстр нові борги не записуються:"
)
CODE_STANDARD_INIT_CREATED: Final[str] = "Реєстр боргів створено: {file}; записів: {count}."
CODE_STANDARD_INIT_EXTENDED: Final[str] = "До реєстру додано розділи правил {rules}; записів: {count}."
CODE_STANDARD_INIT_EXISTS: Final[str] = (
    "Реєстр {file} уже є й охоплює всі правила, що перевіряються, — переписати його може лише --write-debt."
)
CODE_STANDARD_NO_LEDGER: Final[str] = "Реєстру боргів немає — спочатку виконайте --init."
CODE_STANDARD_WRITE_REFUSED: Final[str] = (
    "Реєстр не переписано: борги з’явилися або зросли. Приберіть їх із коду:"
)
CODE_STANDARD_WRITE_DONE: Final[str] = "Реєстр {file} переписано за кодом; знятих і зменшених записів: {count}."
CODE_STANDARD_COMPARE_GROWN: Final[str] = "Проти {target} у реєстрі з’явилося або зросло:"
CODE_STANDARD_COMPARE_REDUCED: Final[str] = "Проти {target} з реєстру знято або зменшено:"
CODE_STANDARD_COMPARE_SAME: Final[str] = "Проти {target} реєстр не зріс."
CODE_STANDARD_FILES_TITLE: Final[str] = "Борги реєстру в {paths}:"
CODE_STANDARD_FILES_NONE: Final[str] = "Боргів реєстру в {paths} немає."
CODE_STANDARD_FILES_LINE: Final[str] = "  {rule} {key} — {value}{signs}"
CODE_STANDARD_FILES_SIGNS: Final[str] = "; {signs}"
CODE_STANDARD_FILE_PROBLEMS: Final[dict[str, str]] = {
    "unreadable": "Файл замка {file} не читається.",
    "not_json": "Файл замка {file} — не JSON.",
    "not_object": "У файлі замка {file} на місці «{key}» очікується об’єкт JSON.",
    "missing": "У файлі замка {file} немає ключа «{key}».",
    "not_integer": "У файлі замка {file} значення «{key}» — не ціле число.",
    "not_text": "У файлі замка {file} значення «{key}» — не рядок.",
    "not_text_list": "У файлі замка {file} значення «{key}» — не список рядків.",
    "not_integer_list": "У файлі замка {file} значення «{key}» — не список цілих чисел.",
    "not_object_list": "У файлі замка {file} значення «{key}» — не список об’єктів JSON.",
    "unknown_key": "У файлі замка {file} невідомий розділ «{key}».",
    "unknown_level": "У файлі замка {file} карта шарів посилається на невідомий рівень «{key}».",
    "git_failed": "git не віддав реєстр версії {file}: перевірте посилання або шлях до файлу реєстру.",
}
