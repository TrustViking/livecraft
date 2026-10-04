"""Тексты для людей на английском: консоль, отчёт, файл ключей, настройщик (CLAUDE.md §11, §14 решение 24).

Те же имена констант, ключи словарей и подстановки `{…}`, что в `app\\ui\\messages_ru.py`; зачем нужна каждая
строка, объясняют комментарии там. Каталог выбирает `app\\ui\\messages.py` по языку Windows.
"""
from __future__ import annotations

from typing import Final

# --- общий словарь
LIST_JOINER: Final[str] = ", "
ITEM_JOINER: Final[str] = "; "
NONE_TEXT: Final[str] = "none"

# --- командная строка (§10)
CLI_DESCRIPTION: Final[str] = (
    "Livecraft: stream plan from Google Sheets → broadcasts on YouTube → stream keys for the streamer."
)
HELP_SETUP: Final[str] = "open the setup window: keys and links, YouTube channels, run settings"
HELP_DRY_RUN: Final[str] = (
    "read the table, build the slots and compare them with YouTube; create nothing, "
    "send nothing to the form, leave keys.txt as it is"
)
HELP_CHECK: Final[str] = "check every channel: sign-in, handle and name, languages, number of scheduled broadcasts"
HELP_AUTH: Final[str] = (
    "sign in to a channel again (handle from channels.json, for example @MyChannel) or all — every channel"
)
HELP_STATUS: Final[str] = "compare livecraft broadcasts, keys.txt and the report — no table, no LLM"
HELP_PACKAGE_FILE: Final[str] = (
    "a .bcast package: copied into the package folder, then a normal run by the lines that are on"
)
CLI_PACKAGE_WITH_MODE: Final[str] = (
    "a .bcast package opens only in a normal run — without --setup, --check, --auth and --status"
)
HELP_DEBUG: Final[str] = "detailed log in the terminal"
HELP_VERSION: Final[str] = "show the version number and exit"
VERSION_TEXT: Final[str] = "Livecraft {version}"
CLI_METAVAR_HANDLE: Final[str] = "HANDLE"
CLI_METAVAR_PACKAGE: Final[str] = "PACKAGE"

# --- шапка запуска
CONSOLE_TITLE: Final[str] = "Livecraft {version} — {generated_at}"

# --- настройка программы (§8)
SETUP_REQUIRED: Final[str] = "Run .\\livecraft.bat --setup and fill in the settings."
SERVICE_NEED_BLOCKED: Final[str] = "Not ready: {gap}."
SETUP_OPENING: Final[str] = "Some settings are missing — opening the setup window."

# --- готовность частей режима (§10)
RUN_PART_LABELS: Final[dict[str, str]] = {
    "plan": "Plan table",
    "local_previews": "Previews on disk",
    "drive_previews": "Previews on Google Drive",
    "merge": "AI",
    "package": "Package",
    "doc": "Google document",
    "doc_copy": "Document copy",
    "announce": "Telegram",
    "packages_in": "Reading packages",
    "broadcast": "YouTube broadcasts",
    "keys": "Keys to the form",
}
RUN_NEED_BLOCKED: Final[str] = "Not ready — {parts}: {gap}."
LINES_NONE_WORKING: Final[str] = (
    "No line of work is on: turn the lines on in the setup window (.\\livecraft.bat --setup)."
)
LINES_NO_SUPPORT: Final[str] = "  not working without “{support}”: {lines}"
LINES_NO_SUPPORT_MERGE: Final[str] = (
    "  not working without “{support}”: {lines} — from the plan table they work only with the AI: numbered texts "
    "go neither to YouTube nor to the package"
)
READINESS_GAP_IN_SETUP: Final[str] = "{what} — “Livecraft — setup”, “{tab}” tab"
READINESS_GAP_SETTINGS: Final[str] = "advanced settings ({key} — {problem})"
READINESS_GAP_FORM: Final[str] = "link to the Google form for stream keys"
READINESS_GAP_TELEGRAM: Final[str] = "Telegram bot and chat for announcements"
READINESS_GAP_CHANNELS_MISSING: Final[str] = "no YouTube channels"
READINESS_GAP_CHANNELS: Final[str] = "YouTube channels ({key} — {problem})"
READINESS_GAP_VAULT_BROKEN: Final[str] = "keys and links cannot be read: {problem}. {advice}"
READINESS_GAP_CLIENT_SECRET: Final[str] = "no Google sign-in file client_secret.json — put it here: {path}"
DRIVE_FOLDER_MIGRATED: Final[str] = (
    "The Google Drive folder link is now kept hidden, like the plan table link — no need to enter it again."
)
DRIVE_FOLDER_MIGRATION_FAILED: Final[str] = (
    "WARNING: could not move the Google Drive folder link from the old settings ({reason}). "
    "Paste it on the “Previews” tab: .\\livecraft.bat --setup."
)
DRIVE_FOLDER_MIGRATION_LOCAL_UNREAD: Final[str] = (
    "the keys and links entered earlier were not read, and writing over them would erase them"
)

SETTINGS_FILE_CREATED: Final[str] = "Program settings created from the shipped template: {path}"
SETTINGS_SECTIONS_ADDED: Final[str] = "A new section from the shipped template was added to the program settings: {sections}"
RETENTION_REMOVED: Final[str] = "Old program files removed (older than {days} days): {count}."

# --- yt-dlp and deno in the tools folder update themselves, cookies are checked (app\runtime).
TOOL_UPDATED: Final[str] = "{tool} updated: {before} → {after}."
TOOL_DOWNLOADED: Final[str] = "{tool} {after} downloaded to the tools folder."
TOOL_MISSING: Final[str] = (
    "{tool}: the tools folder has no program file — the videos of the table will not be read. Install Livecraft over "
    "the current installation: the installer brings the file back, settings and data stay."
)
TOOL_NOT_CHECKED: Final[str] = (
    "{tool}: the new version is not checked — {reason}. The run goes on version {version}, the next run checks again."
)
TOOL_UNUSABLE: Final[str] = (
    "{tool}: the tools folder has no working file and downloading it failed — {reason}. YouTube videos may not be "
    "read; the next run tries again."
)
TOOL_PROBLEMS: Final[dict[str, str]] = {
    "no_answer": "no connection to GitHub",
    "refused": "GitHub refused to answer",
    "no_version": "GitHub did not name the latest version",
    "broken_download": "the downloaded file is damaged",
    "not_written": "the new file did not take the place of the previous one",
    "self_update_failed": "yt-dlp could not update itself",
}
COOKIES_BAD_FORMAT: Final[str] = (
    "The cookies file {path} has the wrong form: its first line must be \"{header}\". With such a file yt-dlp reads "
    "no video, so the plan table is not processed."
)
COOKIES_LOGIN_FAILED: Final[str] = "yt-dlp does not sign in to YouTube with the cookies: {reason}."
COOKIES_LOGIN_FAILURES: Final[dict[str, str]] = {
    "invalid": "the cookies are no longer valid (usually the browser renewed them after the export)",
    "no_auth": "the file has no YouTube sign-in cookies",
}
COOKIES_STALE: Final[str] = "The YouTube cookies were exported on {date} — {days} days ago, the limit is {limit} days."
COOKIES_REEXPORT: Final[str] = (
    "Export the cookies again: incognito window → sign in to YouTube → export the youtube.com cookies in Netscape "
    "format with a browser extension → close the window; put the file into {path}."
)

# --- готовность к запуску (§7.4)
READINESS_SUMMARY_TITLE: Final[str] = "Livecraft settings:"
READINESS_FIELD_LINE: Final[str] = "  {label}: {origin}"
READINESS_LINES_WORKING: Final[str] = "  lines of work: {lines}"
READINESS_LINES_OFF: Final[str] = "  off: {lines}"
FORM_URL_LABEL: Final[str] = "Google form for stream keys"
DOCS_CONTACTS_LABEL: Final[str] = "contacts for streamers in the announcement document"
READINESS_FORM_CONFIGURED: Final[str] = "set"
READINESS_FORM_NOT_CONFIGURED: Final[str] = "not set"
READINESS_CHANNELS_LINE: Final[str] = "  channels: {count}, stream languages: {languages}"
READINESS_CHANNELS_ABSENT: Final[str] = "  channels: not read"
# Сводка настроек запуска: откуда тексты эфиров — по линиям запуска (app\run\line_plan.py::RunTexts, §14 решение 50;
# ключи — значения RunTextSource), и повторная передача ключей — раздел broadcasts livecraft.json (решение 36).
READINESS_TEXTS_LABEL: Final[str] = "broadcast texts"
RUN_TEXT_SOURCES: Final[dict[str, str]] = {
    "llm": "from the AI",
    "videos": "video texts; a broadcast of several videos gets numbered texts, for people only",
    "packages": "from the packages",
}
READINESS_RESEND_KEYS_LABEL: Final[str] = "sending keys again"
READINESS_RESEND_KEYS_OFF: Final[str] = "off"
READINESS_RESEND_KEYS_ON: Final[str] = "on — the keys go out in this run"
READINESS_RESEND_KEYS_DRY_RUN: Final[str] = "on — the keys do not go out in a dry run"
VAULT_LOCAL_UNREADABLE: Final[str] = (
    "WARNING: own keys and links were not read ({fields}) — this happens after the program is moved to another "
    "computer or the Windows user changes. Enter the values again: .\\livecraft.bat --setup."
)
VAULT_TOKEN_UNREADABLE: Final[str] = (
    "WARNING: the values from the access token were not read — this happens after the program is moved to another "
    "computer or the Windows user changes. Load the token again: .\\livecraft.bat --setup, the “Tokens” tab."
)
VAULT_FORMAT_REASON_TEXT: Final[dict[str, str]] = {
    "file_unreadable": "the file does not open — another program holds it, there are no rights, or a folder is in its place",
    "not_text": "the file is damaged — it is not text",
    "damaged": "the file is damaged — its content is not what the program writes",
    "unsupported_version": "the file was written by another version of the program",
    "key_invalid": "the file key has the wrong length",
}
VAULT_FILE_PROBLEM: Final[str] = "{file} — {reason}"
VAULT_FILE_BROKEN: Final[str] = "Keys and links cannot be read: {problem}. {advice}."
VAULT_FILE_ADVICE_LOCAL: Final[str] = (
    "Open “Livecraft — setup” and enter the values again — saving replaces this file"
)
VAULT_FILE_ADVICE_TOKEN: Final[str] = "Load the token again: “Livecraft — setup”, the “Tokens” tab"
VAULT_DECRYPT_FAILED: Final[str] = "The value “{field}” cannot be decrypted: {reason}"
VAULT_DECRYPT_REASON_TEXT: Final[dict[str, str]] = {
    "tag_mismatch": "the file was changed or written with another key",
    "not_text": "the content is not text",
}
DPAPI_UNAVAILABLE: Final[str] = "Own keys and links cannot be saved on this computer: {reason}"
DPAPI_REASON_TEXT: Final[dict[str, str]] = {
    "not_loaded": "Windows data protection (DPAPI) did not load — Windows is required",
    "call_failed": "Windows data protection (DPAPI) failed",
}

# --- конфиги (§5)
CONFIG_ERROR: Final[str] = "Error in the config {path}: {key} — {problem}"
CONFIG_ROOT_KEY: Final[str] = "(file root)"
CONFIG_CHANNELS_FIELDS: Final[tuple[str, ...]] = (
    "  account_name — channel name as on YouTube: it goes to the form as “Channel name”;",
    "  handle — channel handle on YouTube, starts with @ (Studio -> avatar at the top right); "
    "the program keeps the handle and the name up to date itself;",
    "  google_account — email of the Google account that owns this channel;",
    "  languages — stream languages of this channel: {languages};",
    "  privacy — broadcast visibility: {privacy};",
    "  platform — {platform}.",
)
CONFIG_LANGUAGES_RULE: Final[str] = 'a non-empty list of two-letter ISO 639-1 codes without repeats, for example ["uk"]'
CONFIG_CHANNELS_TEMPLATE: Final[str] = """{
  "channels": [
    {"platform": "youtube", "account_name": "Channel name on YouTube", "handle": "@channel_handle", "google_account": "name@gmail.com",
     "languages": ["ru"], "privacy": "unlisted"}
  ]
}"""
CONFIG_PROBLEM_FILE_MISSING: Final[str] = "the file does not exist"
CONFIG_PROBLEM_JSON: Final[str] = "the file cannot be read as JSON: {error}"
CONFIG_PROBLEM_NOT_MAPPING: Final[str] = "a JSON object in curly braces is required"
CONFIG_PROBLEM_MISSING_KEY: Final[str] = "a required field is missing"
CONFIG_PROBLEM_UNKNOWN_KEY: Final[str] = "unknown field"
CONFIG_PROBLEM_DUPLICATE_KEY: Final[str] = "the field is given twice"
CONFIG_PROBLEM_NON_EMPTY_STRING: Final[str] = "a non-empty string in quotes is required"
CONFIG_PROBLEM_STRING: Final[str] = 'a string in quotes is required; an empty string "" means not set'
CONFIG_PROBLEM_FORM_URL: Final[str] = (
    "a Google form link is required: https://docs.google.com/forms/… or https://forms.gle/…, without spaces; "
    "an empty string means the form is not set"
)
CONFIG_PROBLEM_TEXT_OR_NULL: Final[str] = "a form question title in quotes is required, or null if the form has no such question"
CONFIG_PROBLEM_TEXT_MAPPING: Final[str] = (
    'a non-empty “code — option text” object is required, for example {"uk": "Ukrainian"}'
)
CONFIG_PROBLEM_INT_MIN: Final[str] = "a whole number not less than {minimum} is required"
CONFIG_PROBLEM_NUMBER_MIN: Final[str] = "a number not less than {minimum:g} is required, fractions allowed, for example 0.5"
CONFIG_PROBLEM_NUMBER_FINITE: Final[str] = "a regular number is required: NaN and infinity do not fit"
CONFIG_PROBLEM_BOOL: Final[str] = "true or false is required"
CONFIG_PROBLEM_CHOICE: Final[str] = "allowed: {allowed}"
CONFIG_PROBLEM_CHAT_ID: Final[str] = (
    "a Telegram chat id is required — a whole number, for example -1001234567890; an empty string means no chat"
)
CONFIG_PROBLEM_GROUP_CHAT_ID: Final[str] = "a Telegram group id is a negative number, for example -1001234567890"
CONFIG_PROBLEM_FORM_PLATFORM: Final[str] = "the platform options must include “{platform}”"
CONFIG_PROBLEM_FORM_DATE_FORMAT: Final[str] = "the date format must contain {required}; missing {absent}"
CONFIG_PROBLEM_IMAGE_TEMPLATE_PLACEHOLDERS: Final[str] = (
    "the preview folder template must contain {{date}} and {{language}}; missing: {absent}"
)
CONFIG_PROBLEM_IMAGE_TEMPLATE_ABSOLUTE: Final[str] = (
    "the preview folder template must be relative, for example {date}/{language}: the program sets the root itself"
)
CONFIG_PROBLEM_IMAGE_TEMPLATE_FORMAT: Final[str] = (
    "the preview folder template has a placeholder the program does not know; only {date} and {language} are allowed"
)
CONFIG_PROBLEM_TIMEZONE_UNKNOWN: Final[str] = (
    "time zone not recognized: a zone name from the IANA database is required, case matters, for example Europe/Kyiv"
)
CONFIG_PROBLEM_CHANNELS_EMPTY: Final[str] = "a non-empty list of channels is required"
CONFIG_PROBLEM_ACCOUNT_NAME_TOO_LONG: Final[str] = (
    "the channel name is longer than {maximum} characters (now {length}): YouTube has no such names"
)
CONFIG_PROBLEM_ACCOUNT_NAME_CONTROL: Final[str] = "the channel name has a control character (line break, tab)"
CONFIG_PROBLEM_ACCOUNT_NAME_SPACE_EDGE: Final[str] = (
    "the channel name starts or ends with a space: “{value}”; YouTube has no such names — remove the space"
)
CONFIG_PROBLEM_HANDLE_PREFIX: Final[str] = "the handle “{value}” must start with {prefix}, as on YouTube"
CONFIG_PROBLEM_HANDLE_LENGTH: Final[str] = (
    "the handle “{value}” needs {minimum} to {maximum} characters after @ (now {length})"
)
CONFIG_PROBLEM_HANDLE_CHAR: Final[str] = (
    "the handle “{value}” has a character that is not allowed: {char}; spaces, control characters and "
    "< > : \" / \\ | ? * never appear in a handle"
)
CONFIG_PROBLEM_HANDLE_DUPLICATE: Final[str] = (
    "the handle “{value}” already belongs to another channel (“{other}”); capital and small letters in a handle are the same"
)
CONFIG_PROBLEM_GOOGLE_ACCOUNT: Final[str] = (
    "“{value}” does not look like a Google account email: name@domain is required, exactly one @ and no spaces"
)
CONFIG_PROBLEM_PLATFORM_UNKNOWN: Final[str] = "unknown platform “{value}”; allowed: {allowed}"
CONFIG_PROBLEM_LANGUAGES: Final[str] = "required: " + CONFIG_LANGUAGES_RULE
CONFIG_PROBLEM_LANGUAGE_DUPLICATE: Final[str] = "the language “{value}” is given twice"
CONFIG_PROBLEM_LANGUAGE_UNKNOWN: Final[str] = (
    "“{value}” is not a language code: a two-letter ISO 639-1 code in small letters is required, for example uk, en, ru"
)

# --- один экземпляр на машину (§6, инвариант 12)
LOCK_REJECTED: Final[str] = (
    "Livecraft is already running on this computer: process {pid}, started {started_at}. "
    "Wait until the first run ends or close its window."
)
LOCK_REJECTED_UNKNOWN_OWNER: Final[str] = (
    "Livecraft is already running on this computer, but it is not clear which process holds the run. "
    "Close the open Livecraft windows and start again."
)

# --- сейф (§7)
VAULT_FIELD_OPENAI_API_KEY: Final[str] = "OpenAI key"
VAULT_FIELD_SHEETS_ID: Final[str] = "Google content plan table"
VAULT_FIELD_TELEGRAM_BOT_TOKEN: Final[str] = "Telegram bot token"
VAULT_FIELD_DRIVE_FOLDER: Final[str] = "Google Drive folder for materials"
VAULT_FIELD_SUPPORT_BOT_TOKEN: Final[str] = "support bot token"
VAULT_MASK_FINGERPRINT: Final[str] = "{label} (…{fingerprint})"
VAULT_ORIGIN_TOKEN: Final[str] = "received with a token"
VAULT_ORIGIN_OWN: Final[str] = "entered in the setup window"

# --- настройщик, поля сейфа (§8.2)
SETUP_INPUT_EMPTY: Final[str] = "empty — enter a value"
SETUP_INPUT_EMPTY_RESET: Final[str] = "empty: to remove the own value, click “{button}”"
SETUP_INPUT_OPENAI_API_KEY: Final[str] = (
    "an OpenAI key starts with sk-, has no spaces or line breaks and is at least {minimum} characters long"
)
SETUP_INPUT_SHEETS_ID: Final[str] = (
    "a Google table link like https://docs.google.com/spreadsheets/d/<id>/edit or the id itself is required: "
    "Latin letters, digits, - and _, at least {minimum} characters"
)
SETUP_INPUT_TELEGRAM_BOT_TOKEN: Final[str] = (
    "a bot token from @BotFather is required: a number, a colon and at least {minimum} Latin letters, digits, "
    "_ and -, without spaces"
)
SETUP_INPUT_DRIVE_FOLDER: Final[str] = (
    "a Google Drive folder link like https://drive.google.com/drive/folders/… or the folder id itself is needed: "
    "Latin letters, digits, - and _"
)
SETUP_INPUT_OWN_UNAVAILABLE: Final[str] = (
    "keys and links cannot be saved on this computer: Windows does not let them be tied to the account"
)
SETUP_KEYS_NOTICE_PROTECTION: Final[str] = (
    "Values from the token are hidden from viewing and copying, but an expert can get them out. Own values work only "
    "on this computer under the same Windows account."
)
SETUP_KEYS_NOTICE_NO_OWN: Final[str] = (
    "Keys and links cannot be saved on this computer: Windows does not let them be tied to the account."
)
SETUP_KEYS_NOTICE_LOCAL_UNREADABLE: Final[str] = (
    "The values entered earlier were not read — this happens after the program is moved to another computer or the "
    "Windows user changes. The first save replaces them with new ones."
)
SETUP_KEYS_NOTICE_LOCAL_BROKEN: Final[str] = (
    "The file with the entered keys and links is damaged — enter the values again: saving replaces it."
)
SETUP_KEYS_NOTICE_TOKEN_UNREADABLE: Final[str] = (
    "The values from the token were not read — load the token again on the “Tokens” tab."
)

# --- настройщик, вкладка «Эфиры YouTube» (§8.2 п.4)
SETUP_CHANNELS_NOTICE_FILE_MISSING: Final[str] = (
    "There is no secrets\\channels.json file yet: add at least one channel and save."
)
SETUP_CHANNELS_NOTICE_UNREADABLE: Final[str] = (
    "The file secrets\\channels.json was not read: {key} — {problem}. Saving replaces it with the list on this tab, "
    "and the old file stays in secrets\\channels.previous.json."
)

# --- настройщик, вкладка «Дополнительно» (§8.2 п.6)
SETUP_SETTINGS_NOTICE_UNREADABLE: Final[str] = (
    "The file secrets\\livecraft.json was not read: {key} — {problem}. The window shows the program's shipped "
    "values; the file is written by the first save of the settings."
)

# --- окно настройщика (§8)
SETUP_WINDOW_TITLE: Final[str] = "Livecraft {version} — setup"
SETUP_WINDOW_FAILED: Final[str] = (
    "The setup window did not open ({error}). A Windows desktop and Python with the tcl/tk component are required."
)
SETUP_ACTION_FAILED: Final[str] = (
    "The window action failed because of a program error — details in the log {log}. The window keeps working; "
    "«Send logs» on the «Logs» tab passes the log to support."
)
SETUP_TAB_TITLES: Final[dict[str, str]] = {
    "home": "Home",
    "plan": "Plan table",
    "merge": "AI",
    "previews": "Previews",
    "doc": "Google document",
    "package": "Package",
    "telegram": "Telegram",
    "broadcasts": "YouTube broadcasts",
    "keys": "Form",
    "tokens": "Tokens",
    "logs": "Logs",
    "advanced": "Advanced",
}
SETUP_READY: Final[str] = "Ready to run."
SETUP_BUTTON_SAVE: Final[str] = "Save"
SETUP_PROBLEM_LINE: Final[str] = "{label}: {text}"
SETUP_SAVE_FAILED_TITLE: Final[str] = "Not saved"
SETUP_CLOSE_DIRTY_TITLE: Final[str] = "Unsaved changes"
SETUP_CLOSE_DIRTY_TEXT: Final[str] = "There are unsaved changes. Close without saving?"
SETUP_KEY_STATUS_OWN: Final[str] = "✓ set ({mask})"
SETUP_KEY_STATUS_TOKEN: Final[str] = "✓ received with a token ({mask})"
SETUP_LINK_STATUS_SET: Final[str] = "✓ set: {url}"
SETUP_STATUS_NOT_SET: Final[str] = "✗ not set"
CHECK_MARK_OK: Final[str] = "✓"
CHECK_MARK_PROBLEM: Final[str] = "✗"
CHECK_OK_LINE: Final[str] = "✓ {line}"
CHECK_PROBLEM_LINE: Final[str] = "✗ {line}"

# --- «Главная» (§14 решение 37)
SETUP_HOME_INTRO: Final[str] = (
    "Livecraft prepares broadcasts: it takes the plan from a Google table or from packages, writes the title and "
    "description of each broadcast with AI, prepares previews, the announcement document and the package, sends "
    "announcements to Telegram, creates broadcasts on YouTube channels and delivers the keys to the streamer."
)
SETUP_HOME_HOWTO: Final[str] = (
    "Each row below turns on and sets up one function of the application. A ✗ means that this function of the "
    "application needs setting up."
)
SETUP_HOME_GO: Final[str] = "Go"
SETUP_HOME_RUNS: Final[str] = "A run will do (broadcasts {source}): {lines}"
SETUP_HOME_RUNS_NOTHING: Final[str] = "A run will do nothing: no line of work is on."
SETUP_HOME_RUN_SOURCES: Final[dict[str, str]] = {
    "plan": "from the plan table",
    "packages_in": "from packages",
}
SETUP_HOME_RUNS_KEYS_ALL: Final[str] = "{line} — keys of all broadcasts of the run again"
SETUP_LINE_STAGES: Final[dict[str, str]] = {
    "input": "1. Input — where broadcasts come from",
    "processing": "2. Processing",
    "output": "3. Output",
    "broadcasts": "4. Broadcasts",
}
SETUP_HOME_INPUTS: Final[dict[str, str]] = {
    "plan": "Plan table",
    "packages_in": "Packages",
}
SETUP_LINE_DOES: Final[dict[str, str]] = {
    "plan": "reads the broadcast plan from a Google table",
    "merge": "writes one title and one description per broadcast",
    "local_previews": "saves video previews to a folder on this computer",
    "drive_previews": "copies previews to a Google Drive folder and puts links into the table",
    "doc": "creates an announcement document for each date",
    "doc_copy": "saves a .docx copy of the document on this computer",
    "package": "builds a package file for broadcasts on other computers",
    "announce": "sends announcements and the package to Telegram",
    "broadcast": "creates and updates broadcasts on YouTube channels",
    "keys": "delivers broadcast keys to the streamer through the Google form",
    "packages_in": "takes broadcasts from the packages in the packages folder — with their texts and key form",
}
SETUP_LINE_READY: Final[str] = "✓ ready"
SETUP_LINE_BLOCKED: Final[str] = "✗ missing: {gaps}"
SETUP_LINE_GAP_JOINER: Final[str] = "; "
SETUP_LINE_OFF: Final[str] = "off"
SETUP_LINE_WITH_SUPPORT: Final[str] = "not working without “{line}”"
SETUP_LINE_SUPPORT_REASONS: Final[dict[str, str]] = {
    "plan": "works only from the plan table",
    "merge": "from the plan table works only with the AI: numbered texts do not go to YouTube or into the package",
}
SETUP_LINE_TITLES: Final[dict[str, str]] = {
    "keys": "Deliver keys to the form",
}
SETUP_KEYS_CHOICES: Final[dict[str, str]] = {
    "new": "new",
    "all": "all",
}
SETUP_KEYS_HINTS: Final[dict[str, str]] = {
    "new": (
        "Keys go for the broadcasts the run puts on YouTube, plus one retry of a key the form did not confirm last "
        "time."
    ),
    "all": (
        "Keys of all broadcasts of the run go once more: the streamer gets repeated rows and takes the latest one. "
        "After a full run where the form confirmed every key, the choice returns to “new” by itself."
    ),
}
SETUP_KEYS_INACTIVE: Final[dict[str, str]] = {
    "off": "Key delivery is off — the “Deliver keys to the form” switch on the “Form” tab.",
    "no_broadcasts": "YouTube broadcasts are off — there is nothing to deliver.",
    "no_merge": "Broadcasts do not work: from the plan table they go only with the AI.",
    "no_form": "The key form link is not set — the “Form” tab.",
}
SETUP_FIELD_NEEDED_BY: Final[str] = "Needed by the lines: {lines}"
SETUP_FIELD_FROM_PACKAGES: Final[dict[str, str]] = {
    "form": "With the “Packages” input, each broadcast takes the key form from its package.",
    "sheets_vault": "With the “Packages” input, the plan table is not read.",
}

# --- вкладки линий (§8.2, §14 решение 37)
SETUP_KEY_FIELD_LABELS: Final[dict[str, str]] = {
    "openai_api_key": "OpenAI key",
    "sheets_id": "Google table with the stream plan",
    "drive_folder": "Google Drive folder for materials",
    "telegram_bot_token": "Bot token",
    "support_bot_token": "Support bot token",
}
SETUP_KEY_FIELD_HINTS: Final[dict[str, str]] = {
    "openai_api_key": "platform.openai.com → API keys → Create new secret key; the key starts with sk-",
    "sheets_id": "open the table in the browser and copy the link from the address bar",
    "drive_folder": (
        "a folder on Google Drive where the program puts announcement Google Docs and preview copies (it creates the "
        "preview subfolders itself): open the folder in the browser and copy a link like "
        "https://drive.google.com/drive/folders/…"
    ),
}
SETUP_TABLE_TITLE: Final[str] = "What the table should look like"
SETUP_TABLE_TEXT_BEFORE: Final[str] = (
    "The first row holds the column names. The program needs three columns — anywhere and in any order, it does "
    "not read the others. The program finds the sheet itself: the one whose first row has these three names."
)
SETUP_TABLE_SAMPLE_ROW: Final[dict[str, str]] = {
    "link": "https://www.youtube.com/watch?v=…",
    "date": "28.09.2026",
    "time": "19:00",
}
SETUP_TABLE_SAMPLE_BY_PROGRAM: Final[str] = "(filled in by the program)"
SETUP_TABLE_SAMPLE_CHIP_HEADER: Final[str] = "video (chip)"
SETUP_TABLE_SAMPLE_CHIP: Final[str] = "▶ Video title"
SETUP_TABLE_TEXT_AFTER: Final[str] = (
    "One row is one video. Videos for the same time and language are joined into one broadcast. Date — 28.09.2026, "
    "28-09-2026 or 2026-09-28; time — 19:00, in the program's time zone: {timezone}. Rows with a past date are "
    "skipped. Into the row of a video the program itself writes the language it detected from the video — into the “Lang” "
    "column, and the link to the preview copy — into the “Preview (Google Drive)” column; if there are no such "
    "columns, it adds them. The “video (chip)” column is for people; the rest of the table the program only reads."
)
SETUP_TABLE_BUTTON_CHECK: Final[str] = "Check table"
SETUP_TABLE_CHECKING: Final[str] = "Checking the table…"
SETUP_TABLE_LOGIN: Final[str] = (
    "A browser has opened — sign in with the Google account the plan table is shared with (not the YouTube "
    "channel account) and tick all permissions."
)
SETUP_TABLE_OK_NEAREST: Final[str] = (
    "✓ Sheet “{sheet}”: link — column {link}, date — {date}, time — {time}. Future broadcasts in the table: "
    "{count}, the nearest — {nearest}."
)
SETUP_TABLE_OK_NONE: Final[str] = (
    "✓ Sheet “{sheet}”: link — column {link}, date — {date}, time — {time}. No rows with future broadcasts yet."
)
SETUP_TABLE_FAILED: Final[str] = "✗ {problem}"
SETUP_TABLE_INTERRUPTED: Final[str] = "The check was interrupted — details are in the log."
SETUP_LINK_LABELS: Final[dict[str, str]] = {
    "form.url": "Google form for stream keys",
}
SETUP_LINK_HINTS: Final[dict[str, str]] = {
    "form.url": (
        "the form the program uses to pass stream keys to the streamer: a link like https://forms.gle/…"
    ),
}
SETUP_FOLDER_BUTTON_CHECK: Final[str] = "Check folder"
SETUP_FOLDER_CHECKING: Final[str] = "Checking the folder…"
SETUP_FOLDER_LOGIN: Final[str] = (
    "A browser opened — sign in to the Google account that has access to the folder and tick all permissions."
)
SETUP_FOLDER_OK: Final[str] = "✓ Folder “{name}”: the program can put files into it."
SETUP_FOLDER_FAILED: Final[str] = "✗ {problem}"
SETUP_FOLDER_NOT_FOLDER: Final[str] = "The link leads not to a folder but to the file “{name}” — a folder link is needed."
SETUP_FOLDER_READ_ONLY: Final[str] = (
    "Folder “{name}”: the program may not add files to it — give editor access to the Google account used for sign-in."
)
SETUP_LLM_KEY_BUTTON_CHECK: Final[str] = "Check key"
SETUP_LLM_KEY_CHECKING: Final[str] = "Checking the key…"
SETUP_LLM_KEY_OK: Final[str] = "✓ Key accepted. {choice}"
SETUP_LLM_KEY_UNCHECKED: Final[str] = "✗ The key could not be checked: {reason} {choice}"
SETUP_LLM_KEY_FAILED: Final[str] = "✗ {problem}"
SETUP_FORM_BUTTON_CHECK: Final[str] = "Check form"
SETUP_FORM_CHECKING: Final[str] = "Checking the form…"
SETUP_FORM_OK: Final[str] = "✓ Form “{form}”: questions in place — {questions}."
SETUP_FORM_QUESTIONS_MISSING: Final[str] = (
    "✗ Form “{form}” has no questions {questions} — question titles in livecraft.json (section form) must match the "
    "form."
)
SETUP_FORM_QUESTION: Final[str] = "“{title}”"
SETUP_FORM_DATES: Final[str] = "Dates of “{question}” from today: {dates}."
SETUP_FORM_NO_DATES: Final[str] = (
    "✗ “{question}” has no dates from today — broadcasts are not admitted until the form owner adds them."
)
SETUP_FORM_DATE_ANY: Final[str] = "“{question}”: the date is typed as text — any date fits."
SETUP_FORM_TABLE_EMPTY: Final[str] = "The plan table has no future broadcasts — there are no dates to cover."
SETUP_FORM_TABLE_UNREAD: Final[str] = "✗ Date coverage of the plan table was not checked: {problem}"
SETUP_FORM_FAILED: Final[str] = "✗ {problem}"
SETUP_FORM_NOT_SET: Final[str] = "No form link is set — enter it above and click “Save”."
SETUP_CHANNELS_BUTTON_LOGIN: Final[str] = "Sign in to the selected channel"
SETUP_CHANNELS_BUTTON_CHECK: Final[str] = "Check all channels"
SETUP_CHANNELS_CHECKING: Final[str] = "Checking the channels…"
SETUP_FOLDER_LABELS: Final[dict[str, str]] = {
    "folders.packages": "Package folder",
    "folders.docs": "Document copy folder",
    "folders.images": "Preview folder",
}
SETUP_FOLDER_HINTS: Final[dict[str, str]] = {
    "folders.packages": (
        "where the program puts plan_*.bcast packages; when the plan table is off, all lines take broadcasts from it"
    ),
    "folders.docs": "where the program saves .docx copies of announcement documents — a folder per date",
    "folders.images": "where the program saves video previews; subfolders follow the template below",
}
SETUP_FOLDER_STATUS: Final[str] = "✓ folder: {path}"
SETUP_FOLDER_BUTTON_CHOOSE: Final[str] = "Choose…"
SETUP_FOLDER_BUTTON_DEFAULT: Final[str] = "Default"
SETUP_KEYS_BUTTON_RESET_TO_TOKEN: Final[str] = "Restore the token's value"
SETUP_KEYS_BUTTON_DELETE_OWN: Final[str] = "Delete"
SETUP_TOKENS_INTRO: Final[str] = (
    "A token passes to another person the keys, links, Telegram bots and chats and the contacts of the announcement "
    "document set on this computer as own: the recipient works on them but does not see them. YouTube channels, "
    "Google sign-ins and values that came in someone else's token are not included."
)
SETUP_TOKENS_CREATE_TITLE: Final[str] = "New token"
SETUP_TOKENS_CREATE_TEXT: Final[str] = (
    "A token is one file (.lctoken) with the key to its values inside. It can be passed on by any route; anyone who "
    "gets it can load it, so it goes only to the person it is meant for."
)
SETUP_TOKENS_DAYS_LABEL: Final[str] = "Valid for, days:"
SETUP_TOKENS_DAYS_HINT: Final[str] = (
    "until the end of this period the token can be loaded; loaded values keep working after it"
)
SETUP_TOKENS_DAYS_PROBLEM: Final[str] = "the period is a whole number of days from 1 to {maximum}"
SETUP_TOKENS_CONTENTS: Final[str] = "The token will carry: {items}."
SETUP_TOKENS_NOTHING: Final[str] = (
    "Nothing to pass on: no own keys, links or chats are set yet — they are set on the line tabs."
)
SETUP_TOKENS_BUTTON_CREATE: Final[str] = "Create a token"
SETUP_TOKENS_CREATING: Final[str] = "Creating the token…"
SETUP_TOKENS_CREATED: Final[str] = "✓ Created the token {token}."
SETUP_TOKENS_VALID_UNTIL: Final[str] = "It can be loaded until {until}."
SETUP_TOKENS_INSIDE: Final[str] = "In the token: {items}."
SETUP_TOKENS_WRITE_FAILED: Final[str] = "the token file was not written: {reason}"
SETUP_TOKENS_LOAD_TITLE: Final[str] = "Received token"
SETUP_TOKENS_LOAD_TEXT: Final[str] = (
    "Press “Load a token…” and choose the token file (.lctoken). Values from the token replace the previous values "
    "from a token; own values stay first."
)
SETUP_TOKENS_BUTTON_LOAD: Final[str] = "Load a token…"
SETUP_TOKENS_LOADING: Final[str] = "Loading the token…"
SETUP_TOKENS_PICK_TOKEN: Final[str] = "Livecraft token file"
SETUP_TOKENS_LOADED: Final[str] = "✓ The token is loaded: {items}."
SETUP_TOKENS_LOADED_UNTIL: Final[str] = (
    "The token was valid until {until}; loaded values keep working after that."
)
SETUP_TOKENS_SAVE_FAILED: Final[str] = "the token values were not written: {reason}"
SETUP_TOKENS_SETTINGS_FAILED: Final[str] = "the settings from the token do not fit: {problem}"
SETUP_TOKENS_INTERRUPTED: Final[str] = "Work with the token was interrupted — details are in the log."
TOKEN_SETTING_LABELS: Final[dict[str, str]] = {
    "form.url": FORM_URL_LABEL,
    "telegram.target": "where announcements go",
    "telegram.group_chat_id": "group with the bot for announcements",
    "telegram.private_chat_id": "chat with the bot for announcements",
    "telegram.support_chat_id": "support chat",
    "docs.contacts": DOCS_CONTACTS_LABEL,
}
TOKEN_PROBLEM_TEXT: Final[dict[str, str]] = {
    "no_network": (
        "no connection to Google: the token's creation time and period come from Google's answer — connect to the "
        "internet and try again"
    ),
    "file_unreadable": "the file does not open — another program holds it, there are no rights or a folder is in its place",
    "not_token": "this is not a Livecraft token file (.lctoken)",
    "version": "the token is from another version of the program — create a new token in this version",
    "damaged": "the token file is damaged or changed",
    "expired": "the token has expired — a new token is needed",
}
SETUP_KEYS_BUTTON_REVEAL: Final[str] = "show"
SETUP_KEYS_BUTTON_HIDE: Final[str] = "hide"
SETUP_KEYS_SAVE_FAILED_OS: Final[str] = (
    "Could not write the file with the entered values. Check that no other program holds it (antivirus, sync) and "
    "click “Save” again."
)

# --- вкладка «Эфиры YouTube» (§8.2 п.4)
SETUP_CHANNELS_INTRO: Final[str] = (
    "YouTube channels where Livecraft creates broadcasts. On each channel the program schedules broadcasts in the "
    "language of its streams."
)
SETUP_CHANNEL_FIELD_LABELS: Final[dict[str, str]] = {
    "account_name": "Channel handle",
    "handle": "Channel handle",
    "google_account": "Google account email",
    "languages": "Stream language",
    "privacy": "Stream visibility on YouTube",
    "platform": "platform",
    "channels": "channel list",
}
SETUP_CHANNEL_FIELD_HINTS: Final[dict[str, str]] = {
    "handle": (
        "as on YouTube, with @, for example @Lena. Where to find it: YouTube → the avatar at the top right → the "
        "handle under the channel name"
    ),
    "google_account": (
        "the email of the Google account used to sign in to this channel, for example lena@gmail.com — sign-in opens "
        "the right account"
    ),
    "languages": "the language of the channel's broadcasts",
    "privacy": (
        "– stream visibility “public” — everyone sees the broadcast, subscribers get a notification;\n"
        "– stream visibility “unlisted” — only people with the link see the broadcast."
    ),
}
SETUP_CHANNEL_COLUMNS: Final[dict[str, str]] = {
    "handle": "handle",
    "google_account": "Google email",
    "languages": "stream language",
    "privacy": "visibility on YouTube",
}
SETUP_PRIVACY_LABELS: Final[dict[str, str]] = {
    "public": "public",
    "unlisted": "unlisted",
}
SETUP_CHANNELS_BUTTON_ADD: Final[str] = "Add"
SETUP_CHANNELS_BUTTON_UPDATE: Final[str] = "Change selected"
SETUP_CHANNELS_BUTTON_REMOVE: Final[str] = "Delete selected"
SETUP_CHANNELS_NOTHING_SELECTED: Final[str] = "First select a channel in the table."
SETUP_CHANNELS_SAVE_FAILED: Final[str] = "Could not write secrets\\channels.json: {error}"
SETUP_LANGUAGE_OPTION: Final[str] = "{name} ({code})"
SETUP_LANGUAGE_OPTION_IN_FORM: Final[str] = "{name} ({code}) — in the form"
SETUP_LANGUAGE_OPTION_NOT_ISO: Final[str] = "{code} (not an ISO 639-1 code)"
SETUP_LANGUAGE_OPTION_NOT_ISO_IN_FORM: Final[str] = "{code} (not an ISO 639-1 code) — in the form"
SETUP_LANGUAGE_PICK_FROM_LIST: Final[str] = "choose a language from the list"
SETUP_LANGUAGE_SEVERAL: Final[str] = "the channel has several languages — saving keeps {name}"
SETUP_LANGUAGE_NOT_IN_FORM: Final[str] = (
    "the language {names} is not among the Google form options — broadcasts in it will not be admitted"
)

# --- настройки livecraft.json на вкладках линий и «Дополнительно» (§8.2 п.6)
SETUP_ADVANCED_INTRO: Final[str] = (
    "The program time zone and how long old files are kept matter for any lines of work; the other settings are on "
    "the tabs of the lines. The default values fit — change them only for a known reason."
)
SETUP_SETTINGS_FIELD_LABELS: Final[dict[str, str]] = {
    "min_lead_minutes": "minimum time before a broadcast starts (minutes)",
    "keep_days": "keep old program files (days)",
    "auto_start": "the broadcast starts by itself when the video stream begins",
    "set_thumbnail": "set the broadcast thumbnail",
    "category_id": "video category on YouTube",
    "youtube_pause_seconds": "pause between YouTube requests (seconds)",
    "image_dir_template": "preview subfolder template",
    "timezone": "time zone",
    "llm.model": "OpenAI model",
    "llm.fallback_model": "fallback OpenAI model",
    "llm.reasoning_effort": "model reasoning depth",
    "llm.service_tier": "OpenAI service tier",
    "llm.timeout_sec": "how long to wait for the model's answer (seconds)",
    "llm.max_output_tokens": "longest model answer (tokens)",
    "drive.preview_path_template": "preview subfolder template on Google Drive",
    "docs.access": "link access to the announcement document",
    "docs.contacts": DOCS_CONTACTS_LABEL,
}
SETUP_SETTINGS_FIELD_HINTS: Final[dict[str, str]] = {
    "category_id": (
        "YouTube category number: 22 — “People & Blogs”, 24 — “Entertainment”, 25 — “News & Politics”, "
        "27 — “Education”"
    ),
    "image_dir_template": (
        "template of a subfolder inside the preview folder: the program puts the broadcast date in place of {date} "
        "and the language in place of {language}. {date}/{language} "
        "gives image\\23-09-2026\\uk"
    ),
    "youtube_pause_seconds": "how long to wait between YouTube requests; 0.5 is usually enough",
    "llm.model": "OpenAI model for broadcast texts, for example gpt-5.6-sol",
    "llm.fallback_model": "if the main model is not available, for example gpt-5.4",
    "llm.service_tier": "flex — cheaper and slower, default — regular",
    "timezone": "Europe/Kyiv — Kyiv time",
    "drive.preview_path_template": (
        "template of a preview subfolder inside the materials folder on Google Drive: the program puts the "
        "broadcast date in place of {date} and the language in place of {language}. "
        "preview/{date}/{language} gives preview\\28-09-2026\\uk"
    ),
    "docs.access": "who can open the announcement document with its link",
    "docs.contacts": (
        "the “Contact:” line in the header of the announcement document, for example @nick or an email "
        "address; empty — no contacts block"
    ),
}
SETUP_DOC_ACCESS_LABELS: Final[dict[str, str]] = {
    "private": "only people the document is shared with on Drive",
    "reader": "anyone with the link — view only",
    "commenter": "anyone with the link — comment",
    "writer": "anyone with the link — edit",
}
SETUP_SETTINGS_SAVE_FAILED: Final[str] = "Could not write secrets\\livecraft.json: {error}"

# --- вкладка «Логи» (§8.2 п.11, §14 решения 20, 43)
SETUP_LOGS_INTRO: Final[str] = (
    "Something went wrong — one click sends the Livecraft logs to the support chat, where they show what happened, "
    "with no back-and-forth and no hunting for files."
)
SETUP_LOGS_BOT_TITLE: Final[str] = "Support bot"
SETUP_LOGS_BOT_TEXT: Final[str] = (
    "The logs are brought by the support bot — separate from the announcement bot: the logs reach support whichever "
    "bot sends the announcements. The support bot usually comes with an access token. An own bot — at @BotFather: "
    "/newbot; paste the token here and press «Save»."
)
SETUP_LOGS_CHAT_TITLE: Final[str] = "Support chat"
SETUP_LOGS_CHAT_TEXT: Final[str] = (
    "Open the support bot in Telegram and press «Start» (or add it to the support group and send /start@bot_name "
    "there), then press «Connect support chat»."
)
SETUP_LOGS_SEND_TITLE: Final[str] = "Send logs"
SETUP_LOGS_SEND_TEXT: Final[str] = (
    "The archive goes into the logs folder: the files of that folder, newest first, up to {limit} MB, and "
    "diagnostics.txt — program version, system and line readiness, without keys or links. Never sent: secrets, "
    "keystreams, tokens."
)
SETUP_LOGS_BUTTON_SEND: Final[str] = "Send logs"
SETUP_LOGS_BUTTON_SAVE: Final[str] = "Save the log archive"
SETUP_LOGS_BUTTON_CONNECT: Final[str] = "Connect support chat"
SETUP_LOGS_BUTTON_RECONNECT: Final[str] = "Connect another support chat"
SETUP_LOGS_NO_SUPPORT_BOT: Final[str] = "No support bot set — the log archive stays in the logs folder."
SETUP_LOGS_ROUTE_SEND: Final[str] = (
    "The archive goes into the logs folder and then by the support bot to the support chat."
)
SETUP_LOGS_WORKING: Final[str] = "Packing the log archive…"
SETUP_LOGS_INTERRUPTED: Final[str] = "Sending the logs was interrupted — details in the log."
SETUP_LOGS_CAPTION: Final[str] = "🛠 Livecraft {version} logs as of {moment} — files: {files}"
SETUP_LOGS_SENT: Final[str] = "Logs sent to the support chat: {files} files, {megabytes:.1f} MB."
SETUP_LOGS_SAVED: Final[str] = "Log archive saved: {path} ({files} files, {megabytes:.1f} MB)."
SETUP_LOGS_NOT_SENT: Final[str] = "Logs not sent: {reason}"
SETUP_LOGS_NOT_SAVED: Final[str] = "The log archive was not saved to the logs folder: {reason}"
SETUP_LOGS_SKIPPED: Final[str] = "Older log files did not fit into the archive — limit {limit} MB: {count}."
SETUP_LOGS_CHAT_NOT_CONNECTED: Final[str] = (
    "No support chat connected yet — the log archive is saved to the logs folder."
)
SETUP_LOGS_CHAT_CONNECTED: Final[str] = (
    "Done: the logs will arrive in {destination}. The test message is already there — take a look in Telegram."
)
SETUP_LOGS_CHAT_CHOOSE: Final[str] = "The bot sees several chats — click the one to send the logs to in the list."
SETUP_LOGS_CHAT_NO_CHATS: Final[str] = (
    "Support bot @{username} does not see any chat yet: open it in Telegram and press «Start» (for a group — add "
    "the bot to the group and send /start@{username} there), then press «{button}» again."
)
SETUP_LOGS_BOT_FIRST: Final[str] = "The support bot first: paste its token above and press «Save»."
SETUP_LOGS_CHAT_CONNECT_TEXT: Final[str] = "Livecraft: chat connected. Livecraft logs will arrive here."

# --- вкладка «Telegram» (§8.2 п.3, §14 решения 19, 20)
SETUP_TELEGRAM_INTRO: Final[str] = (
    "Before broadcasts Livecraft sends announcements — title, description, previews and broadcast time — to Telegram "
    "on behalf of a bot: to the chat with the bot or to a group with the bot. Setup takes three steps."
)
SETUP_TELEGRAM_STEP_1_TITLE: Final[str] = "Step 1. Bot"
SETUP_TELEGRAM_STEP_1_TEXT: Final[str] = (
    "No Telegram bot yet — create one: find @BotFather, send it /newbot and choose a name — BotFather replies with a "
    "token. Paste the bot token here and click “Save”."
)
SETUP_TELEGRAM_STEP_2_TITLE: Final[str] = "Step 2. Chat"
SETUP_TELEGRAM_STEP_2_TEXT: Final[str] = (
    "Chat with the bot: open the bot in Telegram and tap “Start” (or send /start). Group with the bot: add the bot to "
    "the group and send /start@bot_name there — the bot does not see ordinary group messages."
)
SETUP_TELEGRAM_STEP_3_TITLE: Final[str] = "Step 3. Connection"
SETUP_TELEGRAM_STEP_3_TEXT: Final[str] = (
    "Click the connect button of the chat with the bot or of the group with the bot — the program finds the chat, "
    "remembers it and sends a test message there. Announcements go to one chat — the choice is below."
)
SETUP_TELEGRAM_BUTTON_OPEN_BOT: Final[str] = "Open bot in Telegram"
SETUP_TELEGRAM_BOT_READY: Final[str] = "✓ bot “{name}” @{username}"
SETUP_TELEGRAM_TARGET_TITLES: Final[dict[str, str]] = {
    "private": "Chat with the bot",
    "group": "Group with the bot",
}
SETUP_TELEGRAM_TARGET_CONNECT: Final[dict[str, str]] = {
    "private": "Connect chat with the bot",
    "group": "Connect group with the bot",
}
SETUP_TELEGRAM_TARGET_RECONNECT: Final[dict[str, str]] = {
    "private": "Connect another chat with the bot",
    "group": "Connect another (new) group with the bot",
}
SETUP_TELEGRAM_TARGET_HINTS: Final[dict[str, str]] = {
    "group": (
        "First add the bot @{username} to the group and send /start@{username} there, then click “Connect group with "
        "the bot”."
    ),
}
SETUP_TELEGRAM_TARGET_HINTS_UNNAMED: Final[dict[str, str]] = {
    "group": "First add the bot to the group and send /start@bot_name there, then click “Connect group with the bot”.",
}
SETUP_TELEGRAM_TARGET_CHOOSE: Final[dict[str, str]] = {
    "private": "The bot sees several chats with it — click the right one in the list.",
    "group": "The bot sees several groups — click the right one in the list.",
}
SETUP_TELEGRAM_TARGET_NO_CHATS: Final[dict[str, str]] = {
    "private": (
        "The bot @{username} does not see any chat with it yet: open it in Telegram (the “Open bot in Telegram” "
        "button), tap “Start”, then click “{button}” once more."
    ),
    "group": (
        "The bot @{username} does not see any group yet: add it to a group, send /start@{username} there, then click "
        "“{button}” once more."
    ),
}
SETUP_TELEGRAM_CHAT_CONNECTED: Final[str] = "connected: {chat}"
SETUP_TELEGRAM_CHAT_NOT_CONNECTED: Final[str] = "not connected"
SETUP_TELEGRAM_CHAT_BY_ID: Final[str] = "id {chat_id}"
SETUP_TELEGRAM_TARGET_CHOICE: Final[str] = "Send announcements to:"
SETUP_TELEGRAM_TARGET_LABELS: Final[dict[str, str]] = {
    "private": "the chat with the bot",
    "group": "the group with the bot",
}
SETUP_TELEGRAM_TARGETS_INTO: Final[dict[str, str]] = {
    "private": "the chat with the bot",
    "group": "the group with the bot",
}
SETUP_TELEGRAM_DESTINATION_NOW: Final[str] = "Announcements now go to {destination}."
SETUP_TELEGRAM_DESTINATION_NONE: Final[str] = (
    "Announcements have nowhere to go yet: connect the chat with the bot or a group with the bot."
)
SETUP_TELEGRAM_DESTINATION_BY_ID: Final[str] = "{into} (id {chat_id})"
SETUP_TELEGRAM_DESTINATION_BY_TITLE: Final[str] = "{into} “{title}”"
SETUP_TELEGRAM_CONNECTED: Final[str] = (
    "Done: announcements will come to {destination}. The test message is already there — take a look in Telegram."
)
SETUP_TELEGRAM_STEP_1_FIRST: Final[str] = "Step 1 first: paste the bot token and click “Save”."
SETUP_TELEGRAM_CHAT_OPTION: Final[str] = "{kind}: {title} (id {chat_id})"
TELEGRAM_CHAT_KINDS: Final[dict[str, str]] = {
    "private": "private chat",
    "group": "group",
    "supergroup": "supergroup",
    "channel": "channel",
}
SETUP_TELEGRAM_CONNECT_TEXT: Final[str] = "Livecraft: chat connected. Broadcast announcements will come here."
TELEGRAM_CHAT_MIGRATED: Final[str] = "The group became a supergroup: its new id {new_chat_id} is saved instead of {old_chat_id}."
SETUP_TELEGRAM_NOTICE_UNREADABLE: Final[str] = (
    "The file secrets\\livecraft.json was not read: {key} — {problem}. Connecting a chat writes it again, and the "
    "other settings in it will get the program's default values."
)

# --- Telegram (app\publish\telegram_bot.py)
TELEGRAM_PROBLEMS: Final[dict[str, str]] = {
    "bad_token": (
        "Telegram did not accept the bot token: check the token — the announcement bot on the “Telegram” tab, the "
        "support bot on the “Logs” tab."
    ),
    "chat_not_found": (
        "Telegram does not know this chat: write to the bot in this chat and connect the chat again — the "
        "announcement chat on the “Telegram” tab, the support chat on the “Logs” tab."
    ),
    "forbidden": "The bot may not write to this chat: it was removed from the group or blocked in private chat — bring it back.",
    "other_poller": "Another program polls the bot (for example, restreamer) — stop it and try again.",
    "webhook": (
        "The bot has a webhook: another program takes the bot's messages, so chats are not visible. Remove the "
        "webhook (deleteWebhook) or stop that program, then try again."
    ),
    "rate_limited": "Telegram asks to wait: too many messages in a row. Try again in a minute.",
    "network": "No connection to Telegram: check the internet and try again.",
    "server": "The Telegram server does not answer right now — try again later.",
    "rejected": "Telegram refused: {description}",
}

# --- план из таблицы (app\sheets\)
SHEET_ROW_SKIP_REASONS: Final[dict[str, str]] = {
    "empty_link": "no video link",
    "missing_date_time": "date or time is empty",
    "bad_date_time": "date or time could not be read",
    "nonexistent_time": "this time does not exist: the clocks go forward to summer time that night",
    "in_past": "the broadcast time has already passed",
    "bad_link": "no YouTube video found in the link",
    "duplicate": "repeat: the same link for the same time is already higher in the table",
}
SHEET_PLAN_COLUMN_NAMES: Final[dict[str, str]] = {
    "link": "link",
    "date": "date",
    "time": "time",
}
SHEET_PLAN_EMPTY: Final[str] = "The sheet “{sheet}” has no rows under the column names."
SHEET_PLAN_HEADER_UNKNOWN: Final[str] = (
    "No sheet of the table has all three columns in its first row: link, date, time. The closest is the sheet "
    "“{sheet}” — missing: {missing}. Its headers: {headers}."
)
SHEET_PLAN_HEADER_NONE: Final[str] = "none at all"

# --- вход в Google (app\google\auth.py)
AUTH_OPEN_LINK: Final[str] = "If the browser did not open, open this link: {url}"
AUTH_BROWSER_DONE: Final[str] = "Signed in. Go back to the Livecraft window."
AUTH_REASON_TEXT: Final[dict[str, str]] = {
    "client_secret_missing": "no client_secret.json file next to the program",
    "token_unreadable": "the Google sign-in file cannot be read; delete it and sign in again",
    "token_unwritable": (
        "the Google sign-in file cannot be written or deleted — check that the program folder is writable "
        "and no other program holds the file"
    ),
    "flow_failed": "the browser did not return permission",
    "refresh_failed": "could not renew the sign-in (no connection to Google)",
    "login_required": "Google sign-in is required: there was none yet or it was revoked",
    "login_timeout": (
        "sign-in was not finished in {minutes} minutes — the browser was closed or no account was chosen; "
        "the program offers sign-in again on the next run"
    ),
    "scopes_not_granted": (
        "not all permissions the program asks for were ticked in the Google sign-in window — sign-in is not "
        "accepted without them; sign in again and tick all permissions"
    ),
}

# --- чтение таблицы плана (app\sheets\client.py)
SHEETS_READ_FAILED: Final[str] = "The plan table {label} was not read: {reason}."
SHEETS_READ_FAILED_STATUS: Final[str] = "The plan table {label} was not read: {reason} (response code {status})."
SHEETS_WRITE_FAILED: Final[str] = (
    "The plan table {label}: video languages and preview links were not written: {reason}."
)
SHEETS_WRITE_FAILED_STATUS: Final[str] = (
    "The plan table {label}: video languages and preview links were not written: {reason} (response code {status})."
)
GOOGLE_NO_NETWORK_TEXT: Final[str] = (
    "the computer cannot find the Google servers — no internet or an unstable connection; run again when the "
    "connection is back"
)
SHEETS_READ_REASON_TEXT: Final[dict[str, str]] = {
    "not_configured": "no table link — “Livecraft — setup”, “Plan table” tab",
    "auth": "could not sign in to Google — {detail}",
    "no_access": "no access — share the table with the Google account used for sign-in",
    "account_refused": (
        "the table is not shared with the account {detail} — sign in with the account it is shared with, or ask "
        "the table owner to share it with this account"
    ),
    "not_found": "there is no such table — check the table link in the settings",
    "bad_range": "Google did not accept the table request — check the table link",
    "rejected": "Google refused to read",
    "unavailable": "Google did not answer even after retries — check the connection and run again",
    "no_network": GOOGLE_NO_NETWORK_TEXT,
}

SHEETS_LOGIN_BROWSER: Final[str] = (
    "Google sign-in is needed for the plan table and Google Drive — a browser opens now. Sign in with the Google "
    "account the plan table is shared with (not the YouTube channel account) and tick all permissions."
)
OPERATOR_LOGGED_IN: Final[str] = "Google sign-in: {account}"
OPERATOR_ACCESS_REFUSED: Final[str] = (
    "The plan table is not shared with the Google account {account} — sign-in with the account it is shared "
    "with is needed."
)
OPERATOR_ACCOUNT_UNKNOWN: Final[str] = "(email not known)"

DRIVE_FAILED: Final[str] = "Google Drive: {reason}."
DRIVE_FAILED_STATUS: Final[str] = "Google Drive: {reason} (response code {status})."
DRIVE_REASON_TEXT: Final[dict[str, str]] = {
    "auth": "could not sign in to Google — {detail}",
    "no_access": "no access to the folder — share it with editor access to the Google account used for sign-in",
    "not_found": (
        "there is no such folder or the Google account used for sign-in cannot see it — check the folder link in the "
        "settings"
    ),
    "bad_request": "Google did not accept the request — check the folder link in the settings",
    "rejected": "Google refused",
    "unavailable": "Google did not answer even after retries — check the connection and run again",
    "unknown": (
        "Google did not say whether the action was done — a retry could duplicate it; nothing unfinished goes "
        "anywhere, just run again"
    ),
    "not_configured": "the materials folder is not set — paste its link above and click “Save”",
    "no_network": GOOGLE_NO_NETWORK_TEXT,
}

DOCS_FAILED: Final[str] = "Google Docs: {reason}{status}."
DOCS_FAILED_STATUS: Final[str] = " (response code {status})"
DOCS_REASON_TEXT: Final[dict[str, str]] = {
    "auth": "could not sign in to Google — {detail}",
    "no_access": "no access to the document — sign in with the Google account the materials folder is shared with",
    "not_found": "the document was not found",
    "bad_request": "Google Docs did not accept the request — details in the log",
    "rejected": "Google Docs refused",
    "unavailable": "Google Docs did not answer even after retries — check the connection and run again",
    "unknown": (
        "Google Docs did not say whether the edit was done — a retry could duplicate the text; an unfinished "
        "document goes nowhere, just run again"
    ),
    "no_network": GOOGLE_NO_NETWORK_TEXT,
}
DOC_LINE: Final[str] = "Announcement document for {date}: {url} — previews {placed} of {total}."
DOC_DRY_RUN_LINE: Final[str] = "Announcement document: dry run — no document is created."
DOC_FAILED_LINE: Final[str] = "Announcement document for {date} is not ready — {reason}"
DOC_SKIPPED_LINE: Final[str] = "Documents for the following dates ({count}) were not created."
DOC_COPY_SAVED: Final[str] = " Copy .docx: {path}."
DOC_COPY_NOT_SAVED: Final[str] = " Copy .docx not saved — {reason}"
DOC_COPY_WRITE_FAILED: Final[str] = "the file was not written: {reason}."

ANNOUNCE_DAY_LINE: Final[str] = "Announcements for {date} sent to Telegram: slots {slots}, previews {previews}."
ANNOUNCE_PACKAGE_LINE: Final[str] = "Package {name} sent to Telegram."
ANNOUNCE_FAILED_LINE: Final[str] = "Announcements for {date} are not sent in full — {reason}"
ANNOUNCE_PACKAGE_FAILED_LINE: Final[str] = "The package is not sent to Telegram — {reason}"
ANNOUNCE_SKIPPED_LINE: Final[str] = "Announcements for the following dates ({count}) were not sent."
ANNOUNCE_DRY_RUN_LINE: Final[str] = "Telegram announcements: dry run — nothing is sent."

# --- пробник чтения таблицы (app\tools\sheets_probe.py)
SHEETS_PROBE_TITLE: Final[str] = "Plan table read check"
SHEETS_PROBE_LOGIN: Final[str] = SHEETS_LOGIN_BROWSER
SHEETS_PROBE_COLUMNS: Final[str] = "Sheet “{sheet}”. Columns: link — {link}, date — {date}, time — {time}."
SHEETS_PROBE_COLUMN: Final[str] = "“{name}” (column {letters})"
SHEETS_PROBE_ROWS: Final[str] = "Rows read: {rows}, admitted: {admitted}, skipped: {skipped}."
SHEETS_PROBE_SKIP_LINE: Final[str] = "  {name}: {count}"
SHEETS_PROBE_RELOGIN_HELP: Final[str] = "sign in to Google again in the browser and choose another account"
SHEETS_PROBE_RELOGIN_HINT: Final[str] = (
    "Signed in with the wrong account? Run with --relogin and choose the account that has access to the table."
)

# --- источники (app\sources\)
SOURCE_FAILURE_REASONS: Final[dict[str, str]] = {
    "tool_missing": "no yt-dlp.exe in the tools folder — video data cannot be read without it",
    "private": "the video is private or needs sign-in: the cookies did not fit or there are none",
    "unavailable": "the video is not available: deleted or blocked",
    "timeout": "yt-dlp did not answer in time",
    "bad_output": "yt-dlp returned an answer that cannot be read",
    "no_title": "the video has no title",
    "failed": "yt-dlp could not get the video data — details are in the log",
    "no_language": "the video language was not found either from YouTube data or from the title and description",
}
PREVIEW_PROBLEMS: Final[dict[str, str]] = {
    "no_url": "the source gave no preview address",
    "not_found": "there is no preview at the address",
    "rejected": "the preview server refused the download",
    "unavailable": "the preview did not download even after retries",
    "not_image": "the downloaded file is not a picture",
    "too_large": "the preview is larger than 2 MB even after compression",
}

# --- слоты (app\slots\)
SLOT_PROBLEMS: Final[dict[str, str]] = {
    "empty_title": "The broadcast title is empty after fitting it to YouTube rules — the slot goes no further.",
}

# --- пакет plan_*.bcast (app\packages\)
PACKAGE_PROBLEMS: Final[dict[str, str]] = {
    "no_slots": "the run has no usable slots — nothing to write",
    "form_not_configured": (
        "no key form link — set the form link in the setup window, "
        "“Form” tab"
    ),
}
PACKAGE_WRITTEN: Final[str] = "Package written: {path} (slots: {slots}, previews: {previews})."
PACKAGE_NOT_WRITTEN: Final[str] = "Package not written: {reason}."
# Чтение пакетов bcast\ — режим Б (app\packages\package_file.py, package_shelf.py, package_drop.py).
PACKAGE_REASON_WITH_DETAIL: Final[str] = "{reason} ({detail})"
PACKAGE_LINE_TEMPLATES: Final[dict[str, str]] = {
    "accepted": "{file} — accepted, slots {total}, in channel languages {mine}",
    "damaged": "{file} — the package is damaged: {detail}; the file is left untouched",
    "unsupported_schema": (
        "{file} — package version {detail} is not supported (needed {supported}); the file is left untouched"
    ),
    "all_past": "{file} — all slots are in the past, nothing is planned from it",
}
PACKAGE_REASON_TEXT: Final[dict[str, str]] = {
    "not_zip": "not a ZIP archive",
    "no_manifest": "no manifest.json",
    "bad_json": "manifest.json cannot be read",
    "unsupported_schema": "unknown package version",
    "missing_key": "a required field is missing from the manifest",
    "bad_value": "a wrong value in the manifest",
    "duplicate_slot": "slot_id repeats",
    "preview_missing": "the preview file is missing from the archive",
    "preview_not_image": "the preview file in the archive is not an image",
}
SHELF_PACKAGE_ACCEPTED: Final[str] = "{file} — accepted, future slots {slots}"
SHELF_SUMMARY: Final[str] = "Packages in {path}: files {packages}, future slots {slots} (the list is in the report)."
BCAST_EMPTY: Final[str] = "{path} has no *.bcast packages — save the operator's package there and run again."
BCAST_NO_FUTURE_SLOTS: Final[str] = (
    "The packages in {path} have no future slots — save a fresh package from the operator "
    "there and run again."
)
PACKAGE_DROP_COPIED: Final[str] = "Package copied: {path}."
PACKAGE_DROP_IN_PLACE: Final[str] = "Package is already in place: {path}."
PACKAGE_DROP_NO_SETTINGS: Final[str] = (
    "Package {file} is not copied: the program settings are not read — the package folder is unknown."
)
PACKAGE_DROP_PROBLEMS: Final[dict[str, str]] = {
    "not_package": "{path} is not a .bcast package: only *.bcast packages can be opened.",
    "missing": "{path} does not exist — the package is not opened.",
}

# --- форма ключей (app\form\)
FORM_PROBLEMS: Final[dict[str, str]] = {
    "structure_unreadable": "The key form “{form}” was not read: no form questions were found on the page{detail}.",
    "missing_option": (
        "The key form “{form}” has no option for the needed answer{detail} — ask the form owner to add it."
    ),
    "required_missing": "The key form “{form}” still has required questions without an answer{detail}.",
    "transport_failed": "The key form “{form}” is unavailable{detail}.",
    "not_confirmed": "The key form “{form}” did not confirm that the answer was recorded{detail}.",
}
FORM_PROBLEM_DETAIL: Final[str] = " ({detail})"
FORM_STATUS_DETAIL: Final[str] = "response code {status}"
FORM_DATES_OK: Final[str] = (
    "Key form “{form}”: every date of the run is in it — {wanted} needed, the form accepts {accepted}."
)
FORM_DATES_ANY: Final[str] = "Key form “{form}”: the date is typed as text — any date fits."
FORM_DATES_MISSING: Final[str] = (
    "Key form “{form}”: dates {dates} are missing — broadcasts on these dates are not created, keys will not reach "
    "the streamer."
)

# --- память программы (app\records\)
RECORDS_BROKEN: Final[str] = (
    "Program memory {path} could not be read — the file was renamed to {renamed} and a new one was created; "
    "broadcasts with the program mark are recorded as already delivered to the streamer."
)
RECORDS_BROKEN_READ_ONLY: Final[str] = (
    "Program memory {path} cannot be read — in this mode the program works without it; a regular run will create "
    "a new one."
)
RECORDS_WRITE_FAILED: Final[str] = (
    "Program memory {path} cannot be written ({error}) — work continues, but the next run will not see this run's "
    "confirmations and may send keys again."
)

# --- YouTube platform (app\platforms\)
_YOUTUBE_RATE_LIMIT_TEXT: Final[str] = (
    "YouTube rejected too frequent requests and retries did not help — run the program later "
    "or increase the pause between YouTube requests on the “YouTube broadcasts” tab of the setup window"
)
_YOUTUBE_ACCESS_TEXT: Final[str] = (
    "access to the channel was revoked or is insufficient — sign in to the channel again: "
    ".\\livecraft.bat --auth \"@channel handle\""
)
_YOUTUBE_CLOSED_TEXT: Final[str] = "the channel or account is closed on YouTube"
_YOUTUBE_SUSPENDED_TEXT: Final[str] = "the channel or account is suspended by YouTube"
YOUTUBE_REASON_TEXT: Final[dict[str, str]] = {
    "quotaExceeded": (
        "the daily YouTube API quota is used up (one per Google project — for all channels); no other YouTube "
        "requests were made in this run; the quota resets around 10:00 Kyiv time — run the program after that"
    ),
    "rateLimitExceeded": _YOUTUBE_RATE_LIMIT_TEXT,
    "userRateLimitExceeded": _YOUTUBE_RATE_LIMIT_TEXT,
    "userRequestsExceedRateLimit": _YOUTUBE_RATE_LIMIT_TEXT,
    "liveStreamingNotEnabled": (
        "live streaming is not enabled on the channel — enable it in the Studio (YouTube takes up to 24 hours)"
    ),
    "livePermissionBlocked": "YouTube blocked live streaming on the channel — the reason is shown in the Studio",
    "insufficientLivePermissions": "the account cannot create live streams on this channel",
    "userBroadcastsExceedLimit": (
        "the channel has too many scheduled broadcasts and YouTube refuses new ones — delete extra ones in the Studio"
    ),
    "authError": _YOUTUBE_ACCESS_TEXT,
    "insufficientPermissions": _YOUTUBE_ACCESS_TEXT,
    "channelClosed": _YOUTUBE_CLOSED_TEXT,
    "authenticatedUserAccountClosed": _YOUTUBE_CLOSED_TEXT,
    "channelSuspended": _YOUTUBE_SUSPENDED_TEXT,
    "authenticatedUserAccountSuspended": _YOUTUBE_SUSPENDED_TEXT,
    "authenticatedUserNotChannel": "the account has no YouTube channel — choose a channel when signing in",
    "channelNotFound": "the account has no YouTube channel — choose a channel when signing in",
    "videoNotFound": "the broadcast was not found on YouTube — it may have been deleted during the run",
    "notListed": (
        "YouTube did not return the broadcast or stream by its id even after retries — the platform sometimes lags "
        "after a write; the next run will read it again"
    ),
    "invalidScheduledStartTime": "YouTube did not accept the broadcast start time",
    "transportFailed": (
        "YouTube is unavailable (network or a YouTube-side failure) and retries did not help — run the program later"
    ),
    "authFailed": "signing in to the channel failed — sign in again: .\\livecraft.bat --auth \"@channel handle\"",
    "loginRequired": (
        "the channel needs a sign-in in the browser — sign in: .\\livecraft.bat --auth \"@channel handle\""
    ),
    "badResponse": "YouTube sent an answer the program could not read; the next run will ask again",
    "unexpectedStreamKeyFormat": (
        "YouTube issued a stream key of an unusual shape — the broadcast is not counted and the key did not go to "
        "the streamer; the next run will create the stream again"
    ),
    "unknown": "YouTube refused without a reason; the next run will ask again",
}
YOUTUBE_REASON_UNKNOWN: Final[str] = "YouTube refused ({code}); the next run will ask again"
STREAM_DESCRIPTION: Final[str] = (
    "Livecraft key: channel “{account_name}” {handle}, broadcast {date} {time}, language {language}; "
    "written by the program {written_at}"
)
STREAM_DESCRIPTION_PLACEHOLDER: Final[str] = "; cover placeholder {token}"

# --- YouTube channels (app\platforms\channel*.py, verified.py): channel sign-in, handle → id → title check,
# alignment by the YouTube id and the channel passport (§6 invariant 5, §14 decision 25).
AUTH_STARTING: Final[str] = (
    "Channel «{account_name}» {handle}: Google sign-in is needed — {reason}. A browser opens now."
)
# Почему каналу нужен вход — по значениям LoginNeed (app\platforms\channel.py).
AUTH_LOGIN_NEEDS: Final[dict[str, str]] = {
    "no_token": "there is no channel token yet — first sign-in",
    "token_revoked": "Google no longer accepts the channel token",
    "foreign_token": "the old token led to another channel and was removed",
    "forced": "signing in again by --auth",
}
AUTH_CHOOSE_ACCOUNT: Final[str] = (
    "Sign in to the Google account {google_account} — the account of the channel «{account_name}» {handle}."
)
AUTH_CHOOSE_RIGHT_CHANNEL: Final[str] = (
    "If this account has several channels, choose the channel with the handle {handle} («{account_name}»)."
)
AUTH_UNVERIFIED_APP_WARNING: Final[str] = (
    "Google shows the warning «Google hasn't verified this app» — this is expected: the app has not passed the "
    "Google review yet. Click Advanced, then the link Go to ... (unsafe), then Continue. On the consent screen tick "
    "the item about managing the YouTube account and confirm."
)
AUTH_OK: Final[str] = (
    "Channel «{account_name}» {handle}: signed in — «{title}» {youtube_handle} (id {youtube_channel_id})."
)
AUTH_WRONG_CHANNEL_RETRY: Final[str] = (
    "Channel «{account_name}» {handle}: the browser chose the channel «{youtube_title}» {youtube_handle} — "
    "«{account_name}» {handle} is needed; signing in once more."
)
AUTH_WRONG_CHANNEL_GIVE_UP: Final[str] = (
    "Channel «{account_name}» {handle}: the browser again chose the channel «{youtube_title}» {youtube_handle} — "
    "«{account_name}» {handle} is needed; no sign-in attempts left, the channel is skipped in this run."
)
AUTH_NEXT_RUN_HINT: Final[str] = (
    "the program offers sign-in again on the next run; if the channel handle changed on YouTube — "
    "enter the new handle on the «YouTube broadcasts» tab of the setup window"
)
# Channel check refusals: the value from the channel list and what YouTube sent.
AUTH_CHANNEL_HANDLE_MISSING: Final[str] = (
    "channel «{account_name}» {handle}: the YouTube channel «{youtube_title}» (id {youtube_channel_id}) has no "
    "handle; the channel is skipped. Give the channel a handle in YouTube Studio and enter it on the "
    "«YouTube broadcasts» tab of the setup window; if the wrong channel was chosen — " + AUTH_NEXT_RUN_HINT
)
AUTH_CHANNEL_HANDLE_MISMATCH: Final[str] = (
    "channel «{account_name}» {handle}: signed in to the YouTube channel «{youtube_title}» {youtube_handle} "
    "(id {youtube_channel_id}), while the channel list has the handle {handle}, and the channel passport does not "
    "confirm it is the same channel; the channel is skipped; " + AUTH_NEXT_RUN_HINT
)
AUTH_CHANNEL_ID_MISMATCH: Final[str] = (
    "channel «{account_name}» {handle}: the channel passport has id {passport_channel_id} for the handle {handle}, "
    "while YouTube sent the channel «{youtube_title}» {youtube_handle} with id {youtube_channel_id}; "
    "the channel is skipped; " + AUTH_NEXT_RUN_HINT
)
AUTH_YOUTUBE_HANDLE_MISSING: Final[str] = "no handle"
AUTH_FAILED: Final[str] = "Channel «{account_name}» {handle}: sign-in failed — {reason}."
AUTH_SCOPE_HINT: Final[str] = (
    "If the consent screen had no item about managing the YouTube account — the youtube permission is not added "
    "in the app access settings in Google Cloud."
)
WARNING_CHANNEL_ALIGNED: Final[str] = (
    "channel aligned with YouTube (id {youtube_channel_id}): «{title_before}» {handle_before} -> "
    "«{title_after}» {handle_after}; the channel list, the sign-in file and the channel passport are updated, "
    "no new sign-in is needed; the previous channel list is secrets\\channels.previous.json"
)
WARNING_TOKEN_RENAME_SKIPPED: Final[str] = (
    "channel «{account_name}» {handle}: YouTube confirmed the channel (id {youtube_channel_id}) with the handle "
    "{handle_after}, but the file {target} already exists — the files are untouched; if the channel list has no "
    "channel with the handle {handle_after}, delete this file — the next run aligns the channel by itself"
)
WARNING_CHANNEL_ALIGN_FAILED: Final[str] = (
    "channel «{account_name}» {handle}: YouTube confirmed the channel (id {youtube_channel_id}), "
    "but the files could not be aligned — {reason}; the files are untouched, the next run tries again"
)
CHANNEL_ALIGN_TITLE_EMPTY: Final[str] = "YouTube sent an empty channel title"
WARNING_TOKEN_REJECTED: Final[str] = (
    "the sign-in of the channel «{account_name}» {handle} led to the channel «{youtube_title}» {youtube_handle} "
    "(id {youtube_channel_id}) — the sign-in file is deleted, the program offers sign-in to «{account_name}» {handle}"
)
WARNING_TOKEN_SAVE_FAILED: Final[str] = (
    "channel «{account_name}» {handle}: signed in, but the sign-in file is not written ({error}) — "
    "the channel works in this run, the program offers sign-in again on the next run"
)
WARNING_PASSPORT_UNREADABLE: Final[str] = (
    "the channel passport {path} is unreadable — it will be written anew; "
    "a channel with a new handle is not recognised by the old passport until its first check"
)
WARNING_PASSPORT_WRITE_FAILED: Final[str] = (
    "the channel passport {path} is not written ({error}); the run goes on, the next run writes the passport"
)

# --- план и сверка эфиров (app\pipeline\)
ADMISSION_CHANNEL_TEXT: Final[dict[str, str]] = {
    "refused": "wrong channel",
    "failed": "the platform did not answer",
    "needs_login": "not signed in",
}
PROGRESS_CHANNELS_CHECK: Final[str] = "Checking the YouTube channels by saved sign-ins: {count}."
PROGRESS_CHANNEL_CHECK_STARTED: Final[str] = "Channel «{account_name}» {handle}: checking by the saved sign-in."
PROGRESS_CHANNEL_READ_STARTED: Final[str] = "Channel «{account_name}» {handle}: reading the scheduled broadcasts."
PROGRESS_CHANNEL_READ_DONE: Final[str] = "Channel «{account_name}» {handle}: scheduled broadcasts — {count}."
PROGRESS_BROADCAST_CREATE: Final[str] = "Channel «{account_name}» {handle}: creating broadcast {date} {time} {language}."
PROGRESS_BROADCAST_FIX: Final[str] = "Channel «{account_name}» {handle}: fixing broadcast {date} {time} {language}."
PROGRESS_KEY_SEND: Final[str] = (
    "Channel «{account_name}» {handle}: sending the key to the form — broadcast {date} {time} {language}."
)
PROGRESS_REPORT: Final[str] = "Writing the report."
PROGRESS_PACKAGES_READ: Final[str] = (
    "Packages read: {packages}; slots — {slots_total}, in channel languages — "
    "{slots_mine}."
)
PROGRESS_SHEETS_RETRY: Final[str] = "Google did not answer — retry {place} of {total}."
PROGRESS_VIDEO: Final[str] = "Reading video {place} of {total}: {link}"
PROGRESS_DRIVE_PREVIEW: Final[str] = "Preview copy to Google Drive: {place} of {total}."
PROGRESS_MERGE_SLOT: Final[str] = "AI: slot {place} of {total} — {date} {time} {language}."
PROGRESS_DOC: Final[str] = "Creating announcement document {place} of {total}: {date}."
PROGRESS_ANNOUNCE: Final[str] = "Sending announcements to Telegram {place} of {total}: {date}."
PROGRESS_ANNOUNCE_PACKAGE: Final[str] = "Sending the package to Telegram: {name}."
YOUTUBE_USAGE_LINE: Final[str] = "YouTube: {calls} calls, quota ≈ {units} units."
BROADCASTS_NO_SLOTS: Final[str] = "Broadcasts: no slots for YouTube — the program did not contact YouTube."
# Ключ, который форма не подтвердила ни в первый раз, ни повтором (§14 решение 49): что сделать человеку.
KEYS_SEND_ALL_ACTION: Final[str] = (
    "to send it, choose «all» (the «new | all» choice in the «Keys to the form» row on the «Home» tab of the setup "
    "window)"
)
KEYS_GIVEN_UP: Final[str] = (
    "{prefix}: the key did not reach the form twice and will not go by itself any more — " + KEYS_SEND_ALL_ACTION
)
# Повторная передача ключей после полного запуска (app\broadcasts\key_resend.py, §14 решение 36).
KEYS_RESEND_SWITCHED_OFF: Final[str] = "Broadcast keys sent again: {sent}. Sending keys again is now off."
KEYS_RESEND_KEPT: Final[str] = (
    "Broadcast keys sent again: {sent}, not delivered {undelivered} — sending keys again stays on."
)
KEYS_RESEND_WRITE_FAILED: Final[str] = (
    "Broadcast keys sent again: {sent}, but sending keys again was not switched off — the settings file was not "
    "written: {reason}. Set the key choice back to “new” — the “Keys to the form” row on Home: .\\livecraft.bat --setup."
)
# --check и --auth (app\broadcasts\service.py; поведение planers main.py).
CHECK_HEADER: Final[str] = "Channel check by {path}:"
CHECK_CHANNEL_OK: Final[str] = (
    "- «{account_name}» {handle}: «{title}» {youtube_handle} (id {youtube_channel_id}), "
    "channel language on YouTube: {channel_language}; "
    "stream languages from channels.json: {languages}; scheduled broadcasts: {upcoming}"
)
CHECK_CHANNEL_LANGUAGE_UNSET: Final[str] = "not set"
CHECK_CHANNEL_LANGUAGE_NOTE: Final[str] = (
    "The channel language on YouTube is for reference only and does not affect the program decisions: "
    "the operator sets the stream language in channels.json."
)
CHECK_CHANNEL_FAILED: Final[str] = "- «{account_name}» {handle}: {reason}"
CHECK_CHANNEL_REFUSED: Final[str] = "- {message}"
CHANNEL_LISTED: Final[str] = "{handle} «{account_name}»"
CHECK_ALL_OK: Final[str] = "All channels are in place, live streaming is enabled."
CHECK_HAS_PROBLEMS: Final[str] = "Some channels failed the check — see the lines above."
AUTH_UNKNOWN_CHANNEL: Final[str] = "{path} has no channel with the handle {handle}. Channels in the file: {known}."
# Причина недопуска словами человека (AdmissionReason.wording) — см. messages_ru.
ADMISSION_CHANNEL_PROBLEM: Final[dict[str, str]] = {
    "refused": "The channel is not confirmed: another channel was chosen at sign-in (details in the channel error line).",
    "failed": "The channel is not checked: YouTube did not answer (details in the channel error line).",
    "needs_login": "Sign-in to the channel was not done.",
}
ADMISSION_CHANNEL_ACTION: Final[dict[str, str]] = {
    "refused": "At sign-in, choose the right channel in the browser.",
    "failed": "If the failure repeats, forward the report to the operator.",
    "needs_login": "Sign in to the channel when the program opens the browser.",
}
ADMISSION_MISSING_OPTION: Final[str] = "The form «{form}» has no option «{value}» in the question «{question}»."
ADMISSION_ACTION_MISSING_OPTION: Final[str] = "Add the option to the form."
ADMISSION_MISSING_SETTINGS_TEXT: Final[str] = (
    "The form settings have no answer text for the question «{question}» of the form «{form}»."
)
ADMISSION_ACTION_MISSING_SETTINGS_TEXT: Final[str] = (
    "Operator: enter the option text in the form section of secrets\\livecraft.json; broadcasts from a package get it "
    "with the next package."
)
ADMISSION_REQUIRED_MISSING: Final[str] = (
    "The form «{form}» has a required question «{question}» the program has no answer to."
)
ADMISSION_ACTION_REQUIRED_MISSING: Final[str] = "Make this question optional in the form or tell the operator."
ADMISSION_ACTION_FORM_UNREADABLE: Final[str] = "Check that the key form opens by its link."

# --- вывод контура B (app\output\) — см. messages_ru.
CHANNEL_LABEL: Final[str] = "{account_name} {handle}"
SKIP_PAST: Final[str] = "{date} {time} {language} — already past"
SKIP_TOO_LATE: Final[str] = "{date} {time} {language} — less than {minutes} minutes before the start"
SKIP_NO_CHANNEL: Final[str] = "{date} {time} {language} — no channel for the language {language}"
OUTCOME_SLOT_PREFIX: Final[str] = "{date} {time} {language} -> {channel}"
OUTCOME_CREATED: Final[str] = "{prefix} — broadcast created, {form}"
OUTCOME_CREATE_PLANNED: Final[str] = "{prefix} — no broadcast, will be created"
OUTCOME_FIXED: Final[str] = "{prefix} — differed on YouTube: {what}; fixed, the key and link are the same{form}"
OUTCOME_FIXED_FORM: Final[str] = ", {mark}"
OUTCOME_FIX_PLANNED: Final[str] = "{prefix} — differs on YouTube: {what}; will be fixed, the key will go to the form"
OUTCOME_MATCHED: Final[str] = "{prefix} — {url}"
OUTCOME_MATCHED_FORM: Final[str] = "; {mark}"
UNFIXED_FIELD_TEXT: Final[dict[str, str]] = {"thumbnail": "broadcast thumbnail not set"}
OUTCOME_UNFIXED: Final[str] = "; {what}"
OUTCOME_NO_STREAM: Final[str] = (
    "{prefix} — the broadcast is on the channel ({url}), but no stream is bound to it: there is no key to take. "
    "Bind a stream in YouTube Studio or delete the broadcast — the program will create it again"
)
OUTCOME_STREAM_ATTACHED: Final[str] = "{prefix} — the broadcast had no stream, a stream is bound, {form}"
OUTCOME_AMBIGUOUS: Final[str] = (
    "{prefix} — the channel has several broadcasts at this minute without the program marker, cannot tell them "
    "apart — sort it out by hand"
)
OUTCOME_ERROR: Final[str] = "{prefix} — {text}"
OUTCOME_DRY_RUN_SUFFIX: Final[str] = " — not done (dry-run)"
RUN_FAILURE_LINE: Final[str] = "{subject} — {text}"
KEYS_WRITE_FAILED: Final[str] = "the key file is not written: {detail}"
WARNING_LINE: Final[str] = "{prefix}: {step} — {code} ({message})"
WARNING_REASON_LINE: Final[str] = "{prefix}: {step} — {reason}"
WARNING_STEP_TEXT: Final[dict[str, str]] = {
    "thumbnail": "broadcast thumbnail not set; the broadcast and key stand",
    "language": "broadcast language not written; the broadcast and key stand",
    "audience": (
        "the broadcast audience was «made for kids» (a channel setting) — the program removed it; "
        "check the channel settings"
    ),
    "settings": "the broadcast settings (language, category, audience) failed to apply; the broadcast and key stand",
    "age_restricted": (
        "the broadcast has an 18+ age restriction; the API does not remove it — remove it by hand in Studio"
    ),
    "facts": "the broadcast could not be re-read after scheduling; this does not affect the broadcast itself",
}
THUMBNAIL_REASON_TEXT: Final[dict[str, str]] = {
    "uploadRateLimitExceeded": (
        "YouTube temporarily limited broadcast thumbnail uploads on this channel without saying for how long; the "
        "other broadcast thumbnails of the channel were not set in this run — the next run delivers them itself, run "
        "it in a few hours"
    ),
    "forbidden": (
        "YouTube does not allow custom broadcast thumbnails on this channel — verify the channel by phone in Studio "
        "(advanced features)"
    ),
    "invalidImage": "YouTube did not accept the preview picture from the plan",
}
WARNING_REPORTED_FIELD: Final[str] = (
    "cannot fix: {prefix} — {field}: {wanted} is needed, the platform has {actual}; the API does not fix this "
    "(monitorStream is needed) — correct it in Studio; the broadcast and key stand"
)
WARNING_AMBIGUOUS: Final[str] = (
    "cannot choose a broadcast: {prefix} — the channel has several broadcasts without the program mark at this "
    "minute; the program neither chooses nor deletes — leave one: {urls}"
)
WARNING_FORM_DIAGNOSTIC: Final[str] = "the form answer is saved for analysis: {path}"
WARNING_KEPT_KEY: Final[str] = (
    "the form already confirmed the key of the matching broadcast earlier (program memory) — it is not sent again. "
    "If the streamer did not get the key, pass it from keys.txt by hand or delete the broadcast on YouTube: "
    "the program will create it again with a new key and send it"
)
WARNING_LIVE_CHAT: Final[str] = (
    "YouTube broadcasts always have the live chat on. The API does not turn it off: if the chat is not needed, "
    "turn it off once in Studio for the whole channel (Settings -> Community)"
)
NOTE_UNDATED_BROADCAST: Final[str] = (
    "the channel {channel} has a platform service broadcast without a date and time — «{title}». YouTube creates "
    "such a broadcast itself when the channel live dashboard is opened; the program neither checks it against "
    "slots nor touches it, and it is not shown in the Studio broadcast list"
)
MISMATCH_LINE: Final[str] = "{prefix}: {field} — wanted: {wanted}; on the platform: {actual}"
MISMATCH_FIELD_START: Final[str] = "start time"
MISMATCH_FIELD_LANGUAGE: Final[str] = "language"
MISMATCH_FIELD_AUDIENCE: Final[str] = "audience"
MISMATCH_DESCRIPTION: Final[str] = "{length} characters, beginning «{head}»"
AUDIENCE_NOT_FOR_KIDS: Final[str] = "not made for kids"
AUDIENCE_FOR_KIDS: Final[str] = "made for kids"
SPEC_VALUE_TRUE: Final[str] = "yes"
SPEC_VALUE_FALSE: Final[str] = "no"
THUMBNAIL_BEFORE: Final[str] = "channel placeholder"
THUMBNAIL_AFTER: Final[str] = "from the plan"
CHANGED_FIELD_TEXT: Final[dict[str, str]] = {
    "title": "title",
    "description": "description",
    "category": "category",
    "privacy": "visibility",
    "marker": "stream marker",
    "thumbnail": "broadcast thumbnail",
    "auto_start": "auto start",
    "auto_stop": "auto stop",
    "latency": "broadcast latency",
}
ORPHAN_LINE: Final[str] = "{date} {time} {language} -> {channel} — {url} — the broadcast is not deleted"
ORPHAN_MOVED_LINE: Final[str] = (
    "{date} {time} {language} -> {channel} — {url} — stands at {actual}: the owner changed the broadcast time, "
    "the program does not touch it"
)
REPORT_TITLE: Final[str] = "# Livecraft {version} — report {generated_at}"
REPORT_TITLE_DRY_RUN: Final[str] = " (dry-run)"
REPORT_ITEM: Final[str] = "- {text}"
REPORT_SECTION_CREATED: Final[str] = "### Created ({count})"
REPORT_SECTION_FIXED: Final[str] = "### Fixed ({count})"
REPORT_SECTION_MATCHED: Final[str] = "### Already scheduled, matches ({count})"
REPORT_SECTION_ORPHANS: Final[str] = "### Moved or cancelled? ({count})"
REPORT_SECTION_SCHEDULED: Final[str] = "### Scheduled on the channels ({count})"
REPORT_SECTION_SKIPPED: Final[str] = "### Skipped"
REPORT_SECTION_PACKAGES: Final[str] = "### Packages"
REPORT_SECTION_WARNINGS: Final[str] = "### Warnings"
REPORT_SECTION_MISMATCHES: Final[str] = "### Differences with the platform"
REPORT_SECTION_ERRORS: Final[str] = "### Errors"
REPORT_SECTION_NOT_DELIVERED: Final[str] = "### The key did not reach the streamer"
REPORT_SECTION_TWO_KEYS: Final[str] = "### Two keys for one slot in the form ({count})"
REPORT_SECTION_NOT_ADMITTED: Final[str] = "### Not admitted to publication ({count})"
REPORT_SECTION_NOTES: Final[str] = "### Platform features — this is how the platform works, not about this run"
REPORT_TOTAL_KEYS_FILE: Final[str] = "Key file: {path}"
REPORT_PART: Final[str] = "## {title}"
REPORT_PART_RUN: Final[str] = "Run"
REPORT_PART_INTAKE: Final[str] = "Plan table and texts"
REPORT_PART_SHELF: Final[str] = "Packages"
REPORT_PART_PREVIEWS: Final[str] = "Previews"
REPORT_SECTION_SKIPPED_ROWS: Final[str] = "### Table rows left out ({count})"
REPORT_SECTION_VIDEOS: Final[str] = "### Videos ({count})"
REPORT_SECTION_SLOTS: Final[str] = "### Slots ({count})"
REPORT_ROW_LINE: Final[str] = "row {row}: {link} — {text}"
REPORT_VIDEO_READY: Final[str] = "language {language}, {preview}"
REPORT_VIDEO_PREVIEW: Final[str] = "preview present"
REPORT_VIDEO_NO_PREVIEW: Final[str] = "no preview"
REPORT_SLOT: Final[str] = "{date} {time} {language} — videos: {videos}, texts: {origin} — “{title}”"
REPORT_SLOT_REFUSED: Final[str] = "{date} {time} {language} — videos: {videos} — {problem}"
REPORT_TEXT_ORIGINS: Final[dict[str, str]] = {
    "source_single": "video texts",
    "source_composed": "video texts",
    "merged": "from the neural network",
    "numbered": "numbered — does not go to YouTube",
    "package": "from the package",
}
TWO_KEYS_LINE: Final[str] = (
    "{prefix} — the previous broadcast {old_url} is not found at the slot time (deleted or moved), a new one is set "
    "{new_url}. The current key is {new_key}; the previous {old_key} was also passed to the form for this date — "
    "it no longer works for this slot"
)
NOT_DELIVERED_LINE: Final[str] = (
    "{prefix} — {reason} The broadcast is on the channel — pass the key to the streamer from keys.txt by hand"
)
NOT_ADMITTED_LINE: Final[str] = "{prefix} — {problems} {consequence}. {actions} {next_run}."
NOT_ADMITTED_CONSEQUENCE_NO_BROADCAST: Final[str] = "The broadcast is not created, the key is not passed to the streamer"
NOT_ADMITTED_CONSEQUENCE_BROADCAST: Final[str] = (
    "The broadcast is on the channel ({url}) but was not fixed, the key is not passed to the streamer"
)
NOT_ADMITTED_CONSEQUENCE_CHANNEL: Final[str] = (
    "The channel broadcasts were not checked, the key is not passed to the streamer"
)
NOT_ADMITTED_NEXT_NO_BROADCAST: Final[str] = "The program will create the broadcast on the next run"
NOT_ADMITTED_NEXT_BROADCAST: Final[str] = "The program will pass the key on the next run"
NOT_ADMITTED_NEXT_CHANNEL: Final[str] = "The program will check the channel on the next run"
FORM_MARK_SENT: Final[str] = "key sent to the form"
FORM_MARK_PLANNED: Final[str] = "the key will be sent to the form"
FORM_MARK_FAILED: Final[str] = (
    "the key is NOT sent to the form. {reason} The next run sends it again; "
    "meanwhile pass the key to the streamer from keys.txt by hand"
)
FORM_FAILURE_UNKNOWN: Final[str] = "The key form did not confirm the answer."
SUMMARY_BROADCASTS: Final[str] = (
    "Broadcast totals ({total} in all): published {created}, fixed {fixed}, already there {matched}, "
    "not admitted {not_admitted}, errors {errors}."
)
SUMMARY_BROADCASTS_DRY_RUN: Final[str] = (
    "Broadcast totals ({total} in all): to publish {created}, to fix {fixed}, already there {matched}, "
    "not admitted {not_admitted}, errors {errors}."
)
SUMMARY_BROADCASTS_STATUS: Final[str] = "Broadcast totals ({total} in all): already there {matched}, errors {errors}."
SUMMARY_SLOTS_OUT: Final[str] = "Slots out of work: {count} — {reasons}."
SUMMARY_SLOTS_REASON: Final[dict[str, str]] = {
    "past": "the start time has passed",
    "too_late": "less than {minutes} minutes before the start",
    "no_channel": "no channel for the language {language}",
}
SUMMARY_SLOTS_REASON_COUNTED: Final[str] = "{reason} {count}"
SUMMARY_EXIT_FAILED: Final[str] = "Exit code {code} — not everything is done: {reasons}."
EXIT_REASON_TEXT: Final[dict[str, str]] = {
    "errors": "broadcast errors {count}",
    "failures": "channel and program file errors {count}",
    "key_undelivered": "key did not reach the streamer {count}",
    "packages": "packages not read {count}",
}
CONSOLE_RULE_CHAR: Final[str] = "="
CONSOLE_RULE_TITLE: Final[str] = " {title} "
CONSOLE_BLOCK_COUNTED: Final[str] = "{title} ({count})"
CONSOLE_BLOCK_ATTENTION: Final[str] = "ATTENTION"
CONSOLE_BLOCK_CREATED: Final[str] = "PUBLISHED"
CONSOLE_BLOCK_CREATED_DRY_RUN: Final[str] = "TO PUBLISH"
CONSOLE_BLOCK_FIXED: Final[str] = "FIXED"
CONSOLE_BLOCK_FIXED_DRY_RUN: Final[str] = "TO FIX"
CONSOLE_BLOCK_KEYS: Final[str] = "KEYS FOR THE STREAMER"
CONSOLE_BLOCK_MATCHED: Final[str] = "ALREADY THERE"
CONSOLE_BLOCK_SKIPPED: Final[str] = "NOT PUBLISHED"
CONSOLE_CHANNEL_GROUP: Final[str] = "  {account_name} {handle} ({google_account})"
CONSOLE_BROADCAST_LINE: Final[str] = "    {date}  {time}  {language}  {title}"
CONSOLE_FIXED_LINE: Final[str] = "    {date}  {time}  {language}  {title} — updated: {what}"
CONSOLE_FIX_PLANNED_LINE: Final[str] = "    {date}  {time}  {language}  {title} — will be updated: {what}"
CONSOLE_KEY_LINE: Final[str] = "    {date}  {time}  {language}  {key}  {state}"
CONSOLE_SKIP_GROUP_TOO_LATE: Final[str] = "  less than {minutes} minutes before the start"
CONSOLE_SKIP_GROUP_NO_CHANNEL: Final[str] = "  no channel for the language {language}"
CONSOLE_ATTENTION_ERROR: Final[str] = "  error: {text}"
CONSOLE_ATTENTION_NOT_DELIVERED: Final[str] = "  the key did not reach the streamer: {prefix} — {reason}"
CONSOLE_ATTENTION_TWO_KEYS: Final[str] = (
    "  {prefix}: the previous broadcast is not found at the slot time — a new one is set; "
    "the form has two keys for this date: current {new_key}, previous {old_key}"
)
CONSOLE_ATTENTION_NOT_ADMITTED: Final[str] = "  not admitted: {text}"
CONSOLE_ATTENTION_TEXT: Final[str] = "  {text}"
CONSOLE_ATTENTION_PACKAGE: Final[str] = "  package: {text}"
CONSOLE_ATTENTION_RESTORED: Final[str] = "  returned to the plan: {prefix} — {field}: was {before}, now {after}"
CONSOLE_ATTENTION_RESTORED_UNKNOWN: Final[str] = "  returned to the plan: {prefix} — {field}: now {after}"
CONSOLE_ATTENTION_RESTORE_PLANNED: Final[str] = (
    "  will return to the plan: {prefix} — {field}: now {before}, will be {after}"
)
CONSOLE_ATTENTION_RESTORE_PLANNED_UNKNOWN: Final[str] = "  will return to the plan: {prefix} — {field}: will be {after}"
CONSOLE_PATH: Final[str] = "  {label:<8}{path}"
CONSOLE_LABEL_KEYS: Final[str] = "keys"
CONSOLE_LABEL_REPORT: Final[str] = "report"
CONSOLE_LABEL_LOG: Final[str] = "log"
KEY_FORM_SENT_LEAD: Final[str] = "sent to the form"
KEY_FORM_CONFIRMED_LEAD: Final[str] = "passed to the form"
KEY_FORM_GIVEN_UP_LEAD: Final[str] = "did not reach the form twice"
KEY_FORM_FAILED_LEAD: Final[str] = "NOT sent"
KEY_FORM_NOT_ADMITTED_LEAD: Final[str] = KEY_FORM_FAILED_LEAD + ": not admitted"
KEY_FORM_UNKNOWN_LEAD: Final[str] = "no confirmation in the program memory"
KEY_FORM_LINE_OFF_LEAD: Final[str] = "not sent to the form"
CONSOLE_KEY_FAILED: Final[str] = KEY_FORM_FAILED_LEAD + " — {reason}"
KEYS_FILE_HEADER: Final[tuple[str, ...]] = (
    "# Broadcast keys. Generated by the program {generated_at}.",
    "# The file is rewritten on every run — do not edit.",
    "# The «form» line:",
    "#   «" + KEY_FORM_SENT_LEAD + "» — the form confirmed the key in this run;",
    "#   «" + KEY_FORM_CONFIRMED_LEAD + "» — the form confirmed this key earlier (program memory);",
    "#   «" + KEY_FORM_FAILED_LEAD + "» — the key had to go and did not: pass it to the streamer by hand;",
    "#   «" + KEY_FORM_NOT_ADMITTED_LEAD + "» — the form does not accept this broadcast (no date or option) "
    "or the channel is not confirmed: the broadcast stands, the key is not passed to the streamer — pass it by hand;",
    "#   «" + KEY_FORM_LINE_OFF_LEAD + "» — the «Keys to the form» line is off: pass the key to the streamer by hand;",
    "#   «" + KEY_FORM_GIVEN_UP_LEAD + "» — "
    "the key went to the form twice — the first time and once again — and the form did not confirm it; it will "
    "not go by itself any more: " + KEYS_SEND_ALL_ACTION + ";",
    "#   «" + KEY_FORM_UNKNOWN_LEAD + "» — the program does not know whether the streamer got this key.",
)
KEYS_BLOCK_TITLE: Final[str] = "{date} {time}  {language}  {account_name} {handle}"
KEYS_BLOCK_KEY: Final[str] = "  key    {value}"
KEYS_BLOCK_STREAM: Final[str] = "  stream {value}"
KEYS_BLOCK_BROADCAST: Final[str] = "  live   {value}"
KEYS_BLOCK_FORM: Final[str] = "  form   {value}"
KEY_FORM_SENT: Final[str] = KEY_FORM_SENT_LEAD + " {sent_at}"
KEY_FORM_CONFIRMED: Final[str] = KEY_FORM_CONFIRMED_LEAD + " {confirmed_at}"
KEY_FORM_GIVEN_UP: Final[str] = KEY_FORM_GIVEN_UP_LEAD + " — " + KEYS_SEND_ALL_ACTION
KEY_FORM_FAILED: Final[str] = KEY_FORM_FAILED_LEAD + " — {reason} Pass it to the streamer by hand."
KEY_FORM_NOT_ADMITTED: Final[str] = KEY_FORM_NOT_ADMITTED_LEAD + " — {reasons}"
KEY_FORM_UNKNOWN: Final[str] = KEY_FORM_UNKNOWN_LEAD
KEY_FORM_LINE_OFF: Final[str] = KEY_FORM_LINE_OFF_LEAD + ": the «{line}» line is off"

# --- прогон режима А (app\intake\intake.py)
INTAKE_TABLE_LINE: Final[str] = "Plan table: rows {rows}, admitted {admitted}, skipped {skipped}{reasons}."
INTAKE_TABLE_REASONS: Final[str] = " — {items}"
INTAKE_COUNT_ITEM: Final[str] = "{name}: {count}"
INTAKE_NO_FUTURE_ROWS: Final[str] = "No future broadcasts in the table — no slots and no package in this run."
INTAKE_SOURCES_LINE: Final[str] = "Videos: usable {ready} of {total}, without preview {no_preview}{failures}."
INTAKE_SOURCES_FAILURES: Final[str] = "; not usable — {items}"
PREVIEWS_LINE: Final[str] = (
    "Previews: saved to the preview folder — {saved}; on Google Drive — uploaded {uploaded}, already there {kept}."
)
PREVIEWS_DRY_RUN_LINE: Final[str] = (
    "Previews: saved to the preview folder — {saved}; nothing is uploaded to Google Drive in a dry run."
)
PREVIEWS_LOCAL_LINE: Final[str] = "Previews: saved to the preview folder — {saved}."
PREVIEWS_DRIVE_LINE: Final[str] = "Previews: on Google Drive — uploaded {uploaded}, already there {kept}."
INTAKE_SHEET_WRITE_LINE: Final[str] = (
    "The plan table: video languages written {languages}, already there {languages_kept}; preview links written "
    "{links}, already there {links_kept}."
)
INTAKE_SHEET_WRITE_LANGUAGES_LINE: Final[str] = (
    "The plan table: video languages written {languages}, already there {languages_kept}."
)
INTAKE_SHEET_WRITE_DRY_RUN_LINE: Final[str] = "The plan table: dry run — nothing is written."
INTAKE_SLOTS_LINE: Final[str] = "Broadcast slots: {count}{languages}{refused}."
INTAKE_SLOTS_LANGUAGES: Final[str] = " ({items})"
INTAKE_SLOTS_REFUSED: Final[str] = ", refused: {count} — reasons in the log"
INTAKE_NO_SLOTS: Final[str] = "No usable slots — nothing for the output and the broadcasts."
INTAKE_SLOT_NOT_FOR_YOUTUBE: Final[str] = (
    "Stream {language} {time} {date} will not go to YouTube — the AI did not merge the video descriptions; the "
    "document and Telegram get the numbered descriptions."
)
PACKAGE_NO_YOUTUBE_SLOTS: Final[str] = "No slots for YouTube — package not written."
INTAKE_MERGE_LINE: Final[str] = "AI: slots {total}, model texts {merged}, video texts {video}{reasons}."
INTAKE_MERGE_REASONS: Final[str] = " — {items}"
INTAKE_MERGE_VIDEO_REASONS: Final[dict[str, str]] = {
    "few_descriptions": "fewer than two video descriptions",
    "not_accepted": "the model answer was not accepted",
    "publish_blocked": "did not pass the pre-publishing check",
    "stopped": "the AI was stopped",
    "no_model": "no model chosen",
}
INTAKE_MERGE_COST: Final[str] = "AI usage: requests {requests}, ${cost}."
INTAKE_MERGE_COST_UNKNOWN: Final[str] = (
    "AI usage: requests {requests}, at least ${cost} — the price of some answers is unknown."
)
INTAKE_MERGE_STOPPED: Final[str] = (
    "The AI is stopped until the end of the run — the other slots that need their descriptions combined get "
    "numbered descriptions. {failure}"
)

# --- пробник источников (app\tools\source_probe.py)
SOURCE_PROBE_TITLE: Final[str] = "Source check through yt-dlp"
SOURCE_PROBE_USAGE: Final[str] = "Give one or more links: python -m app.tools.source_probe <link> …"
SOURCE_PROBE_SOURCE: Final[str] = "Source {link}"
SOURCE_PROBE_BAD_LINK: Final[str] = "  no YouTube video found in the link: {raw}"
SOURCE_PROBE_ID: Final[str] = "  id: {value}"
SOURCE_PROBE_NAME: Final[str] = "  title: {value}"
SOURCE_PROBE_DURATION: Final[str] = "  duration: {value}"
SOURCE_PROBE_LANGUAGE: Final[str] = "  video language: {video}; channel language: {channel}"
SOURCE_PROBE_AUDIO: Final[str] = "  audio languages: {value}"
SOURCE_PROBE_SUBTITLES: Final[str] = "  subtitles: {value}"
SOURCE_PROBE_AUTO_CAPTIONS: Final[str] = "  automatic subtitles: {value}"
SOURCE_PROBE_SOURCE_LANGUAGE: Final[str] = "  source language: {code} ({source})"
SOURCE_PROBE_SOURCE_LANGUAGE_NONE: Final[str] = "  source language: not found"
SOURCE_PROBE_MORE: Final[str] = "{shown} … and {more} more"
SOURCE_PROBE_PREVIEW_OK: Final[str] = "  preview: {width}×{height}, {kilobytes} KB — fits YouTube"
SOURCE_PROBE_PREVIEW_BAD: Final[str] = "  preview: does not fit — {reason}"
SOURCE_PROBE_PREVIEW_SKIPPED: Final[str] = (
    "  preview: not downloaded — the language was not found, such a source does not go into a run"
)
SOURCE_PROBE_FAILED: Final[str] = "  refused: {reason}"
SOURCE_PROBE_DETAIL: Final[str] = "  details: {detail}"
SOURCE_PROBE_SUMMARY: Final[str] = "Sources: {total}, received: {ok}, refused: {failed}."

# --- нейросеть (app\llm\)
LLM_BACKEND_TITLE: Final[dict[str, str]] = {
    "openai": "OpenAI",
}
LLM_REQUEST_FAILED: Final[str] = "The AI request failed: {reason}."
LLM_REQUEST_FAILED_STATUS: Final[str] = "The AI request failed: {reason} (response code {status})."
LLM_ERROR_KIND_TEXT: Final[dict[str, str]] = {
    "timeout": "{provider} did not answer in time",
    "connection_error": "no connection to {provider} — check the internet",
    "quota_exhausted": (
        "the {provider} account is out of money or over its limit — top up the balance of the {provider} account"
    ),
    "rate_limit": "{provider} is overloaded or the request limit is exceeded — run later",
    "server_error": "a failure on the {provider} side — run later",
    "authentication_failed": "{provider} did not accept the key — check the {provider} key in the settings",
    "model_access_denied": "the {provider} key has no access to this model",
    "model_not_found": "there is no such model or this key cannot use it — check the model name in the settings",
    "incompatible_request_shape": "the model cannot answer in the given JSON schema",
    "unsupported_parameter": "the model does not accept one of the request parameters",
    "bad_request": "{provider} rejected the request",
    "request_failed": "{provider} did not carry out the request",
    "empty_output": "the model returned an empty answer",
    "not_configured": "no {provider} key — set it on the “AI” tab of the setup window",
}
LLM_REQUEST_LABEL_TEXT: Final[dict[str, str]] = {
    "model_probe": "check",
    "startup_ping": "test",
}
LLM_CHOICE_REASON_TEXT: Final[dict[str, str]] = {
    "primary_confirmed": "main, answered the check",
    "primary_unchecked": "main; the check failed, working on it",
    "fallback_confirmed": "fallback: the main one is not available to this key",
    "fallback_unchecked": "fallback: the main one is not available to this key, the fallback could not be checked",
    "refused": "no suitable model",
}
LLM_CHOICE_LINE: Final[str] = "Model: {model} — {reason}."
LLM_CHOICE_REFUSED: Final[str] = "No model chosen. {reason}"

# --- ответ модели на merge (app\llm\merges\)
MERGE_REJECT_TEXT: Final[dict[str, str]] = {
    "not_json_object": "the model did not answer with a single JSON object",
    "missing_keys": "the model answer has no title or description",
    "extra_keys": "the model answer has extra fields besides the title and description",
    "invalid_title": "the title is empty or has emoji",
    "invalid_description": "the description is empty",
    "cta_as_first_paragraph": "the description starts with a call to subscribe or comment",
    "duplicate_paragraph": "the description repeats paragraphs or the main point",
    "empty": "no text is left in the description after removing service lines",
    "paragraph_underflow": "the description has too few paragraphs",
    "paragraph_overflow": "the description has too many paragraphs",
    "unexpected_error": "the model returned the title or description not as text",
    "per_source_enumeration": "the description retells the sources one by one instead of joining them",
    "hook_echo_in_body": "the start of the description repeats the main point, and the repeat could not be removed",
    "cta_in_hook": "the first paragraph of the description is a call or a service line, not the main point",
    "insufficient_bullet_coverage": "the description has too few points for the number of sources",
    "compact_bullet_overflow": "the description has more than seven points for one or two sources",
    "excessive_emoji_usage": "the description has more than ten emoji outside the point markers",
    "overloaded_bullet": "the description has several overloaded points",
    "numbered_title_dump": "the title lists topics by number",
    "semantic_gate": "the description did not pass the language and alphabet check",
}
RESOURCE_PROBLEM_LINES: Final[str] = "a non-empty list of strings is required"

# --- пробник нейросети (app\tools\llm_probe.py)
LLM_PROBE_TITLE: Final[str] = "OpenAI AI check"
LLM_PROBE_SETTINGS: Final[str] = "Main model: {primary}; fallback: {fallback}; tier: {tier}; reasoning: {effort}."
LLM_PROBE_ANSWER: Final[str] = "Model answer: {text}"
LLM_PROBE_ANSWER_CUT: Final[str] = "{text}…"
LLM_PROBE_TOKENS: Final[str] = (
    "Tokens: input {input} (from cache {cached}), output {output} (of it reasoning {thinking}), total {total}."
)
LLM_PROBE_TOKENS_UNKNOWN: Final[str] = "Tokens: the AI did not report usage for some requests."
LLM_PROBE_REQUESTS: Final[str] = "Requests: {requests}; tiers: {tiers}."
LLM_PROBE_TIER_ENTRY: Final[str] = "{label} — {tier}"
LLM_PROBE_COST: Final[str] = "Cost: ${cost}."
LLM_PROBE_COST_UNKNOWN: Final[str] = "Cost: at least ${cost} — the program has no prices for some models ({models})."

# --- обрыв и падение запуска (app\main.py::Launch.run)
RUN_INTERRUPTED: Final[str] = (
    "The run was interrupted. The next run finds and takes into account what is already done on YouTube."
)
RUN_CRASHED: Final[str] = (
    "Livecraft stopped with a failure — details are in the log {log}. "
    "The next run finds and takes into account what is already done on YouTube; send the log to the operator."
)

# --- замок эталона кода (app\tools\code_standard, §11)
CODE_STANDARD_DESCRIPTION: Final[str] = (
    "Livecraft code standard lock: report on rules E1–E21 and a debt registry that can only shrink."
)
CODE_STANDARD_HELP_INIT: Final[str] = (
    "create the debt registry from the current code if there is none; to an existing registry — only add the "
    "sections of rules it does not have yet"
)
CODE_STANDARD_HELP_WRITE_DEBT: Final[str] = (
    "rewrite the registry from the current code — only if no debt appeared or grew"
)
CODE_STANDARD_HELP_COMPARE: Final[str] = (
    "compare the registry with an earlier version: a git reference (HEAD, commit hash) or a path to a registry file"
)
CODE_STANDARD_HELP_FILES: Final[str] = "show registry debts in these files or folders (path from the repository root)"
CODE_STANDARD_METAVAR_VERSION: Final[str] = "VERSION"
CODE_STANDARD_METAVAR_PATH: Final[str] = "PATH"
CODE_STANDARD_RULE_LABELS: Final[dict[str, str]] = {
    "E1": "free functions",
    "E2": "static methods",
    "E3": "definition length",
    "E4": "number of parameters",
    "E5": "literals in function bodies",
    "E6": "Cyrillic in code",
    "E7": "text in exceptions",
    "E8": "one value — one declaration",
    "E9": "regular expressions",
    "E10": "loggers",
    "E11": "structural clones",
    "E12": "empty wrappers",
    "E13": "state tuples",
    "E14": "raw data",
    "E15": "defensive conversions",
    "E16": "layers and import rings",
    "E17": "time",
    "E18": "module and class sizes",
    "E19": "code in __init__.py",
    "E20": "tests",
    "E21": "a name defined twice in a module",
}
CODE_STANDARD_SIGN_LABELS: Final[dict[str, str]] = {
    "names_app_class": "(a) an app class in annotations",
    "one_class_use": "(b) needed by one class",
    "unused": "(c) nobody uses it",
    "forwarding": "(a) forwarding",
    "two_layers": "(b) two layers",
    "foreign_body": "(c) foreign body",
    "module": "modules",
    "class": "classes",
    "number": "numbers",
    "log": "log",
    "separator": "separators",
    "identifier": "identifiers",
    "text": "text",
    "text_constant": "strings",
    "number_constant": "numbers",
    "repeated_pattern": "pattern repeats",
    "pattern_in_function": "pattern in a function",
    "area_missing": "get_logger without LogArea",
    "raw_logger": "logging.getLogger outside the log package",
    "edge": "edges",
    "ring": "rings",
    "unmapped": "packages outside the map",
    "test_import": "test module import",
    "logger_name": "logger name as a string",
    "private_patch": "private name patch",
    "global_patch": "os / shutil patch",
    "dataclass_replace": "dataclasses.replace outside fixtures",
}
CODE_STANDARD_RING_KEY: Final[str] = "ring: {modules}"
CODE_STANDARD_UNMAPPED_KEY: Final[str] = "outside the map: {package}"
CODE_STANDARD_REPORT_TITLE: Final[str] = "Livecraft code standard: violations, registry debts and exceptions"
CODE_STANDARD_REPORT_ROW: Final[str] = "{rule:<4} {label:<34} {now:>7} {ledger:>10} {exempt:>11} {goal:>5}"
CODE_STANDARD_REPORT_COLUMNS: Final[dict[str, str]] = {
    "rule": "code",
    "label": "rule",
    "now": "now",
    "ledger": "registry",
    "exempt": "exceptions",
    "goal": "goal",
}
CODE_STANDARD_REPORT_NO_VALUE: Final[str] = "—"
CODE_STANDARD_REPORT_SIGNS: Final[str] = "     {signs}"
CODE_STANDARD_REPORT_SIGN: Final[str] = "{label}: {count}"
CODE_STANDARD_REPORT_STATE: Final[str] = (
    "Code against the registry: new {new}, grown {grown}, shrunk {shrunk}, removed {gone}."
)
CODE_STANDARD_REPORT_NO_LEDGER: Final[str] = (
    "There is no debt registry — create it: python -m app.tools.code_standard --init"
)
CODE_STANDARD_CHANGE_LINES: Final[dict[str, str]] = {
    "new": "  {rule} {key} — new: {after}",
    "grown": "  {rule} {key} — grown: was {before}, now {after}",
    "shrunk": "  {rule} {key} — shrunk: was {before}, now {after}",
    "gone": "  {rule} {key} — removed (was {before})",
    "same": "  {rule} {key} — no change: {after}",
}
CODE_STANDARD_EXEMPTION_NO_REASON: Final[str] = "Exception {rule} {key}: empty justification."
CODE_STANDARD_EXEMPTION_NOT_CAUGHT: Final[str] = (
    "Exception {rule} {key}: the rule no longer catches it — remove it from exceptions.json."
)
CODE_STANDARD_STALE_ENTRIES: Final[str] = (
    "The registry has stale entries — a debt was removed or shrank in the code. "
    "Update the registry: python -m app.tools.code_standard --write-debt"
)
CODE_STANDARD_GROWTH: Final[str] = (
    "Code standard violations appeared or grew. Remove them from the code — new debts are not written to the registry:"
)
CODE_STANDARD_INIT_CREATED: Final[str] = "Debt registry created: {file}; entries: {count}."
CODE_STANDARD_INIT_EXTENDED: Final[str] = "Rule sections {rules} added to the registry; entries: {count}."
CODE_STANDARD_INIT_EXISTS: Final[str] = (
    "The registry {file} already exists and covers all checked rules — only --write-debt can rewrite it."
)
CODE_STANDARD_NO_LEDGER: Final[str] = "There is no debt registry — run --init first."
CODE_STANDARD_WRITE_REFUSED: Final[str] = (
    "The registry was not rewritten: debts appeared or grew. Remove them from the code:"
)
CODE_STANDARD_WRITE_DONE: Final[str] = "The registry {file} was rewritten from the code; removed and shrunk entries: {count}."
CODE_STANDARD_COMPARE_GROWN: Final[str] = "Against {target} the registry got new or grown entries:"
CODE_STANDARD_COMPARE_REDUCED: Final[str] = "Against {target} entries were removed from the registry or shrank:"
CODE_STANDARD_COMPARE_SAME: Final[str] = "Against {target} the registry did not grow."
CODE_STANDARD_FILES_TITLE: Final[str] = "Registry debts in {paths}:"
CODE_STANDARD_FILES_NONE: Final[str] = "No registry debts in {paths}."
CODE_STANDARD_FILES_LINE: Final[str] = "  {rule} {key} — {value}{signs}"
CODE_STANDARD_FILES_SIGNS: Final[str] = "; {signs}"
CODE_STANDARD_FILE_PROBLEMS: Final[dict[str, str]] = {
    "unreadable": "The lock file {file} cannot be read.",
    "not_json": "The lock file {file} is not JSON.",
    "not_object": "In the lock file {file} a JSON object is expected at “{key}”.",
    "missing": "The lock file {file} has no key “{key}”.",
    "not_integer": "In the lock file {file} the value “{key}” is not a whole number.",
    "not_text": "In the lock file {file} the value “{key}” is not a string.",
    "not_text_list": "In the lock file {file} the value “{key}” is not a list of strings.",
    "not_integer_list": "In the lock file {file} the value “{key}” is not a list of whole numbers.",
    "not_object_list": "In the lock file {file} the value “{key}” is not a list of JSON objects.",
    "unknown_key": "The lock file {file} has an unknown section “{key}”.",
    "unknown_level": "In the lock file {file} the layer map refers to an unknown level “{key}”.",
    "git_failed": "git did not return the registry of version {file}: check the reference or the registry file path.",
}
