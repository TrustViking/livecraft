"""Все тексты для оператора: консоль, отчёт, файл ключей, настройщик (CLAUDE.md §11).

В коде — только эти константы; английских текстов для человека в коде нет.
Здесь пока только то, что нужно скелету: строки командной строки, шапка запуска,
обрыв и падение, требование настройки. Остальное добавляют свои этапы (§13).
"""
from __future__ import annotations

from typing import Final

# --- командная строка (CLAUDE.md §10)
CLI_DESCRIPTION: Final[str] = (
    "Livecraft: план стримов из Google Sheets → эфиры на YouTube → ключи потоков стримеру."
)
HELP_SETUP: Final[str] = "открыть настройщик: ключи и ссылки, каналы YouTube, настройки запуска"
HELP_DRY_RUN: Final[str] = (
    "прочитать таблицу, собрать слоты и сверить их с YouTube; ничего не создавать, "
    "в форму не отправлять, keys.txt не менять"
)
HELP_NO_LLM: Final[str] = "не звать LLM: взять название и описание источника как есть"
HELP_EXPORT_SLOTS: Final[str] = "выгрузить слоты запуска JSON-ом в указанный файл (отладка)"
HELP_CHECK: Final[str] = "проверить каждый канал: вход, ник и название, языки, число запланированных эфиров"
HELP_AUTH: Final[str] = (
    "заново авторизовать канал (ник handle из channels.json, например @MyChannel) или all — все каналы"
)
HELP_STATUS: Final[str] = "сверка эфиров livecraft, keys.txt и отчёт — без таблицы и без LLM"
HELP_DEBUG: Final[str] = "подробный лог в терминал"
HELP_VERSION: Final[str] = "показать номер версии и выйти"
VERSION_TEXT: Final[str] = "Livecraft {version}"
# Подписи значений в справке argparse: их видит человек, поэтому они здесь, а не в main.py (§11).
CLI_METAVAR_PATH: Final[str] = "ПУТЬ"
CLI_METAVAR_HANDLE: Final[str] = "НИК"

# --- шапка запуска: первая строка любого запуска, время — то же, что в отчёте этого запуска
CONSOLE_TITLE: Final[str] = "Livecraft {version} — {generated_at}"

# --- настройка программы (CLAUDE.md §8): без сейфа и конфига обычный запуск не начинается
# Что именно не так, перечислено строками выше (сейф и конфиги называют свои причины сами) — здесь только что делать.
SETUP_REQUIRED: Final[str] = "Запустите livecraft.bat --setup и заполните настройки."

# --- готовность к запуску (app\setup\readiness.py): сводка без значений — только откуда что взялось (§7.4)
READINESS_SUMMARY_TITLE: Final[str] = "Настройки livecraft:"
READINESS_FIELD_LINE: Final[str] = "  {label}: {origin}"
READINESS_FIELD_ABSENT: Final[str] = "нет"
READINESS_CHANNELS_LINE: Final[str] = "  каналов: {count}, языки стримов: {languages}"
READINESS_CHANNELS_ABSENT: Final[str] = "  каналы: не прочитаны"
# Личный сейф есть, но не читается: молчаливый откат на поставку недопустим (§16) — иначе получатель
# незаметно работает на ключе OpenAI и таблице того, кто передал ему программу.
VAULT_LOCAL_UNREADABLE: Final[str] = (
    "ВНИМАНИЕ: ваши личные настройки из secrets\\vault.local.dat не прочитаны — программа работает на значениях, "
    "пришедших вместе с программой (ключ OpenAI, таблица плана, форма ключей). Так бывает после переноса папки "
    "на другой компьютер или смены пользователя Windows. Введите свои значения заново: livecraft.bat --setup."
)
VAULT_FILE_BROKEN: Final[str] = (
    "Файл сейфа не читается: {error}. Если это secrets\\vault.local.dat — введите свои значения заново через "
    "livecraft.bat --setup; если secrets\\vault.dat — переустановите программу."
)

# --- конфиги (CLAUDE.md §5): два JSON, все поля обязательные, умолчаний и копирования примеров нет
CONFIG_ERROR: Final[str] = "Ошибка в конфиге {path}: {key} — {problem}"
CONFIG_ROOT_KEY: Final[str] = "(корень файла)"
CONFIG_CHANNELS_HINT: Final[str] = "Создайте файл {path} с таким содержимым и впишите свои значения:"
# Что вписать в каждое поле: печатается между CONFIG_CHANNELS_HINT и шаблоном.
# {languages} — CONFIG_LANGUAGES_RULE, {privacy} и {platform} — допустимые значения из config\loader.py.
CONFIG_CHANNELS_FIELDS: Final[tuple[str, ...]] = (
    "  account_name — название канала как на YouTube: оно уходит в форму как «Название канала»;",
    "  handle — ник канала на YouTube, начинается с @ (Студия -> аватар вверху справа); "
    "ник и название программа потом выравнивает сама;",
    "  google_account — почта аккаунта Google, в котором этот канал;",
    "  languages — языки стримов этого канала: {languages};",
    "  privacy — видимость эфиров: {privacy};",
    "  platform — {platform}.",
)
CONFIG_LANGUAGES_RULE: Final[str] = 'непустой список кодов строчными буквами без повторов, например ["uk"] или ["uk", "ru"]'
CONFIG_SETTINGS_HINT: Final[str] = "Восстановите файл {path} с таким содержимым и впишите свои значения:"
# Точные шаблоны файлов для консоли: печатаются, когда файла или поля нет. В код как умолчания не идут.
# Шаблон настроек совпадает с поставочным secrets\livecraft.json — это проверяет тест.
CONFIG_CHANNELS_TEMPLATE: Final[str] = """{
  "channels": [
    {"platform": "youtube", "account_name": "Название канала на YouTube", "handle": "@ник_канала", "google_account": "you@gmail.com",
     "languages": ["ru"], "privacy": "unlisted"}
  ]
}"""
CONFIG_SETTINGS_TEMPLATE: Final[str] = """{
  "min_lead_minutes": 60,
  "keep_days": 30,
  "auto_start": true,
  "set_thumbnail": true,
  "category_id": "22",
  "youtube_pause_seconds": 0.5,
  "image_dir_template": "{date}/{language}",
  "timezone": "Europe/Kyiv",
  "llm": {
    "model": "gpt-5.2",
    "fallback_model": "gpt-5.2",
    "reasoning_effort": "medium",
    "service_tier": "default",
    "timeout_sec": 120,
    "max_output_tokens": 6000
  },
  "form": {
    "fields": {
      "language": "Язык стрима ( Language of stream)",
      "account_name": "Название канала ( Channel name)",
      "date": "Время стрима ( Stream time )",
      "platform": "Платформа (Platform)",
      "stream_key": "You Tube Stream Key",
      "stream_url": "Stream-URL (YT)",
      "time": null,
      "broadcast_url": null,
      "slot_id": null
    },
    "values": {
      "language": {
        "uk": "Украинский ( Ukranian)",
        "ru": "Русский ( Russian)",
        "en": "Английский ( English)",
        "hu": "Венгерский (Hungarian, Magyar)"
      },
      "platform": {
        "youtube": "You Tube",
        "facebook": "Facebook",
        "rumble": "Rumble"
      }
    },
    "date_format": "%d.%m.%Y"
  }
}"""
CONFIG_PROBLEM_FILE_MISSING: Final[str] = "файла нет"
CONFIG_PROBLEM_JSON: Final[str] = "файл не читается как JSON: {error}"
CONFIG_PROBLEM_NOT_MAPPING: Final[str] = "нужен объект JSON в фигурных скобках"
CONFIG_PROBLEM_MISSING_KEY: Final[str] = "обязательное поле отсутствует"
CONFIG_PROBLEM_UNKNOWN_KEY: Final[str] = "неизвестное поле"
CONFIG_PROBLEM_DUPLICATE_KEY: Final[str] = "поле указано дважды"
CONFIG_PROBLEM_NON_EMPTY_STRING: Final[str] = "нужна непустая строка в кавычках"
CONFIG_PROBLEM_TEXT_OR_NULL: Final[str] = "нужно название вопроса формы в кавычках или null, если такого вопроса в форме нет"
CONFIG_PROBLEM_TEXT_MAPPING: Final[str] = (
    'нужен непустой объект «код — текст варианта», например {"uk": "Украинский ( Ukranian)"}'
)
CONFIG_PROBLEM_INT_MIN: Final[str] = "нужно целое число не меньше {minimum}"
CONFIG_PROBLEM_NUMBER_MIN: Final[str] = "нужно число не меньше {minimum:g}, можно дробное, например 0.5"
CONFIG_PROBLEM_NUMBER_FINITE: Final[str] = "нужно обычное число: NaN и бесконечность не годятся"
CONFIG_PROBLEM_BOOL: Final[str] = "нужно true или false"
CONFIG_PROBLEM_CHOICE: Final[str] = "допустимо: {allowed}"
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
VAULT_FIELD_SHEETS_ID: Final[str] = "таблица плана"
VAULT_FIELD_SHEETS_RANGE: Final[str] = "диапазон таблицы"
VAULT_FIELD_KEY_FORM_URL: Final[str] = "форма ключей"
# Маска по отпечатку: название поля и четыре знака sha256 — различить два значения можно, восстановить нет.
VAULT_MASK_FINGERPRINT: Final[str] = "{label} (…{fingerprint})"
# Происхождение поля: пришло со сборкой или его вписал сам пользователь (§7.3).
VAULT_ORIGIN_SUPPLIED: Final[str] = "поставка"
VAULT_ORIGIN_OWN: Final[str] = "своё"
# Сейф заполнен не до конца — запускаться не с чем; перечень недостающих полей строит сам сейф.
# Что делать, говорит SETUP_REQUIRED, который main печатает следом, — здесь только чего не хватает.
VAULT_NOT_READY: Final[str] = "Сейф заполнен не до конца: не хватает {fields}."

# --- настройщик, вкладка «Ключи и ссылки» (CLAUDE.md §8.2, п.1): что не так с введённым значением.
# Само введённое значение в строки не подставляется: это секрет, и он не должен попасть ни в один вывод (§7.4).
SETUP_INPUT_EMPTY: Final[str] = "пусто: чтобы убрать своё значение, нажмите «Сбросить к поставке»"
SETUP_INPUT_OPENAI_API_KEY: Final[str] = (
    "ключ OpenAI начинается с sk-, пишется без пробелов и переводов строк и длиной не меньше {minimum} символов"
)
SETUP_INPUT_SHEETS_ID: Final[str] = (
    "нужна ссылка на Google-таблицу вида https://docs.google.com/spreadsheets/d/<id>/edit или сам id: "
    "латинские буквы, цифры, - и _, не меньше {minimum} символов"
)
SETUP_INPUT_SHEETS_RANGE: Final[str] = (
    "нужен диапазон вида A:F, A1:F200, План!A:F или 'План стримов'!A2:F: "
    "колонки — от 1 до 3 латинских букв, номер строки — по желанию"
)
SETUP_INPUT_KEY_FORM_URL: Final[str] = (
    "нужна ссылка на Google-форму: https://docs.google.com/forms/… или https://forms.gle/…, без пробелов"
)
SETUP_INPUT_OWN_UNAVAILABLE: Final[str] = (
    "своё значение на этой машине сохранить нельзя: защита Windows (DPAPI) недоступна"
)
# Оговорка §7.2 и §14 решения 6: вкладка показывает её всегда, без неё шифрование выглядело бы защитой от всех.
SETUP_KEYS_NOTICE_PROTECTION: Final[str] = (
    "Значения, пришедшие вместе с программой, зашифрованы от копирования и чтения глазами, но не от специалиста: "
    "ключ к ним лежит внутри программы. Свои значения шифруются ключом вашей учётной записи Windows — "
    "на другом компьютере или под другим пользователем файл с ними бесполезен."
)
SETUP_KEYS_NOTICE_NO_OWN: Final[str] = (
    "На этой машине недоступна защита Windows (DPAPI), поэтому своих значений здесь не будет: "
    "программа работает на значениях, пришедших вместе с программой."
)
SETUP_KEYS_NOTICE_LOCAL_UNREADABLE: Final[str] = (
    "Прежний файл ваших значений (secrets\\vault.local.dat) не прочитался — так бывает после переноса папки на другой "
    "компьютер или смены пользователя Windows. Первое сохранение заменит его тем, что вы введёте сейчас."
)

# --- настройщик, вкладка «Каналы YouTube» (CLAUDE.md §8.2, п.2). {key} и {problem} — из ConfigError загрузчика.
SETUP_CHANNELS_NOTICE_FILE_MISSING: Final[str] = (
    "Файла secrets\\channels.json ещё нет: добавьте хотя бы один канал и сохраните."
)
SETUP_CHANNELS_NOTICE_UNREADABLE: Final[str] = (
    "Файл secrets\\channels.json не прочитался: {key} — {problem}. Сохранение заменит его списком этой вкладки, "
    "а прежний файл останется в secrets\\channels.previous.json."
)

# --- настройщик, вкладка «Настройки запуска» (CLAUDE.md §8.2, п.3). {key} и {problem} — из ConfigError загрузчика.
SETUP_SETTINGS_NOTICE_UNREADABLE: Final[str] = (
    "Файл secrets\\livecraft.json не прочитался: {key} — {problem}. Вкладка открыта на поставочных значениях "
    "программы; файл будет записан только по кнопке «Сохранить»."
)

# --- окно настройщика (CLAUDE.md §8, app\setup\app.py и app\setup\tabs\): подписи, кнопки, диалоги.
# Значения сейфа сюда не подставляются никогда: окно показывает только маски из модели вкладки (§7.4).
SETUP_WINDOW_TITLE: Final[str] = "Livecraft {version} — настройка"
SETUP_WINDOW_FAILED: Final[str] = (
    "Окно настройщика не открылось ({error}). Нужен рабочий стол Windows и Python с компонентом tcl/tk."
)
SETUP_TAB_KEYS: Final[str] = "Ключи и ссылки"
SETUP_TAB_CHANNELS: Final[str] = "Каналы YouTube"
SETUP_TAB_SETTINGS: Final[str] = "Настройки запуска"
SETUP_READY: Final[str] = "Готово к запуску."
SETUP_BUTTON_SAVE: Final[str] = "Сохранить"
SETUP_PROBLEM_LINE: Final[str] = "{label}: {text}"
SETUP_SAVE_FAILED_TITLE: Final[str] = "Не сохранено"
SETUP_CLOSE_DIRTY_TITLE: Final[str] = "Несохранённые изменения"
SETUP_CLOSE_DIRTY_TEXT: Final[str] = "Есть несохранённые изменения. Закрыть без сохранения?"
# Вкладка «Ключи и ссылки»: заголовки колонок, кнопки строки, отказы записи — без значения и без пути к сейфу.
SETUP_KEYS_HEADER_FIELD: Final[str] = "Поле"
SETUP_KEYS_HEADER_ORIGIN: Final[str] = "Откуда"
SETUP_KEYS_HEADER_VALUE: Final[str] = "Значение"
SETUP_KEYS_HEADER_INPUT: Final[str] = "Своё значение"
SETUP_KEYS_BUTTON_ACCEPT: Final[str] = "Сохранить значение"
SETUP_KEYS_BUTTON_RESET: Final[str] = "Сбросить к поставке"
# «Показать своё» (§14 решение 11): только значение, которое пользователь ввёл сам, только на экран.
SETUP_KEYS_BUTTON_REVEAL: Final[str] = "показать"
SETUP_KEYS_BUTTON_HIDE: Final[str] = "скрыть"
SETUP_KEYS_SAVE_FAILED_OS: Final[str] = (
    "Не удалось записать файл ваших значений. Проверьте, не занят ли он другой программой "
    "(антивирус, синхронизация), и нажмите «Сохранить» ещё раз."
)
# Вкладка «Каналы YouTube»: подписи по ключам SettingProblem (имя поля строки канала) и по полям ChannelDraft.
SETUP_CHANNEL_FIELD_LABELS: Final[dict[str, str]] = {
    "account_name": "название канала",
    "handle": "ник",
    "google_account": "аккаунт Google",
    "languages": "языки",
    "privacy": "видимость",
    "platform": "площадка",
    "channels": "список каналов",
}
SETUP_CHANNELS_BUTTON_ADD: Final[str] = "Добавить"
SETUP_CHANNELS_BUTTON_UPDATE: Final[str] = "Изменить выбранный"
SETUP_CHANNELS_BUTTON_REMOVE: Final[str] = "Удалить выбранный"
SETUP_CHANNELS_NOTHING_SELECTED: Final[str] = "Сначала выберите канал в таблице."
SETUP_CHANNELS_SAVE_FAILED: Final[str] = "Не удалось записать secrets\\channels.json: {error}"
# Вкладка «Настройки запуска»: подписи по ключам SettingProblem (путь поля в livecraft.json).
SETUP_SETTINGS_FIELD_LABELS: Final[dict[str, str]] = {
    "min_lead_minutes": "минимальный запас до старта (минут)",
    "keep_days": "хранить старые файлы (дней)",
    "auto_start": "автостарт эфира",
    "set_thumbnail": "ставить обложку",
    "category_id": "категория YouTube (номер)",
    "youtube_pause_seconds": "пауза между обращениями к YouTube (секунд)",
    "image_dir_template": "папка превью (шаблон)",
    "timezone": "часовой пояс",
    "llm.model": "модель LLM",
    "llm.fallback_model": "запасная модель LLM",
    "llm.reasoning_effort": "уровень рассуждений",
    "llm.service_tier": "тариф OpenAI",
    "llm.timeout_sec": "таймаут запроса к LLM (секунд)",
    "llm.max_output_tokens": "предел ответа LLM (токенов)",
}
SETUP_SETTINGS_SAVE_FAILED: Final[str] = "Не удалось записать secrets\\livecraft.json: {error}"

# --- обрыв и падение запуска (app\main.py::run_cli)
RUN_INTERRUPTED: Final[str] = (
    "Запуск прерван. Что уже сделано на YouTube, найдёт и учтёт следующий запуск."
)
RUN_CRASHED: Final[str] = (
    "Livecraft аварийно остановился — подробности в логе {log}. "
    "Что уже сделано на YouTube, найдёт и учтёт следующий запуск; перешлите лог оператору."
)
